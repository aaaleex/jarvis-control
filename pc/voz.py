"""
Voz de Jarvis: micrófono, palabra de activación, reconocimiento (Whisper) y síntesis (edge-tts / Piper).

Funcionamiento:
  - Un hilo lee el micrófono sin parar en trozos de 80 ms.
  - En reposo, openWakeWord busca "Jarvis". También se puede activar con un atajo de teclado.
  - Al activarse, graba hasta que dejas de hablar (detector de voz Silero) y Whisper lo transcribe.
  - La respuesta del modelo se divide en frases que se sintetizan y reproducen en cuanto están listas.
  - Si dices "Jarvis" mientras habla, se calla y te escucha (así funciona "Jarvis, para").
"""
import asyncio
import os
import queue
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd

from nucleo import RAIZ, cfg, emitir, log

FRECUENCIA = 16000          # Whisper, openWakeWord y Silero trabajan a 16 kHz
TROZO = 1280                # 80 ms: tamaño que espera openWakeWord
PALABRAS_PARAR = ("para", "parar", "para ya", "calla", "cállate", "silencio", "stop", "basta", "déjalo", "cancela")


def _preparar_dlls_cuda():
    """Las librerías CUDA de Whisper vienen como paquetes pip (nvidia-*). Windows necesita saber dónde están."""
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn", "cuda_nvrtc"):
        carpeta = base / sub / "bin"
        if carpeta.is_dir():
            os.add_dll_directory(str(carpeta))
            os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ["PATH"]


# ==================================================================
#  DETECTOR DE VOZ (Silero VAD, el que trae faster-whisper)
# ==================================================================
class DetectorVoz:
    def __init__(self):
        import onnxruntime
        import faster_whisper

        ruta = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        opciones = onnxruntime.SessionOptions()
        opciones.inter_op_num_threads = 1
        opciones.intra_op_num_threads = 1
        opciones.log_severity_level = 4
        self.sesion = onnxruntime.InferenceSession(str(ruta), sess_options=opciones, providers=["CPUExecutionProvider"])
        self.reiniciar()

    def reiniciar(self):
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.contexto = np.zeros((1, 64), dtype=np.float32)
        self.resto = np.zeros(0, dtype=np.float32)

    def probabilidad(self, audio_int16: np.ndarray) -> float:
        """Devuelve la probabilidad máxima de voz en el trozo (ventanas de 512 muestras + 64 de contexto)."""
        audio = np.concatenate([self.resto, audio_int16.astype(np.float32) / 32768.0])
        maximo = 0.0
        while len(audio) >= 512:
            ventana, audio = audio[:512], audio[512:]
            x = np.concatenate([self.contexto, ventana[None, :]], axis=1).astype(np.float32)
            salida, self.h, self.c = self.sesion.run(None, {"input": x, "h": self.h, "c": self.c})
            self.contexto = x[:, -64:]
            maximo = max(maximo, float(np.ravel(salida)[0]))
        self.resto = audio
        return maximo


# ==================================================================
#  SÍNTESIS DE VOZ
# ==================================================================
def preparar_para_voz(texto: str) -> str:
    texto = re.sub(r"https?://\S+", "el enlace", texto)
    texto = re.sub(r"[A-Za-z]:\\\S+", "la carpeta de Jarvis", texto)
    texto = (texto.replace("°C", " grados").replace("ºC", " grados").replace("°", " grados")
             .replace("%", " por ciento").replace("km/h", " kilómetros por hora").replace("–", " a "))
    texto = re.sub(r"[*_#`>\[\]{}|]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


class Sintetizador:
    """Convierte texto en audio (array int16 + frecuencia). Motores: edge, piper y SAPI de Windows como último recurso."""

    def __init__(self):
        self._piper = None

    def sintetizar(self, texto: str):
        motor = cfg("voz.motor_tts", "edge")
        if motor == "edge":
            try:
                return self._edge(texto)
            except Exception as e:
                log.warning(f"edge-tts falló ({e}); paso a Piper")
                emitir("error", texto="La voz online no responde (¿sin internet?). Uso la voz local.")
        try:
            return self._piper_sintetizar(texto)
        except Exception as e:
            log.warning(f"Piper falló ({e})")
            return None

    def _edge(self, texto: str):
        # Caché de frases cortas ("Abro Spotify.", "Volumen al 40."): se dicen al instante, sin ir a internet
        import hashlib
        voz, velocidad = cfg("voz.voz_edge", "es-ES-AlvaroNeural"), cfg("voz.velocidad_edge", "+0%")
        cache = RAIZ / "datos" / "cache_voz"
        ruta = cache / (hashlib.sha1(f"{voz}|{velocidad}|{texto}".encode()).hexdigest()[:20] + ".pcm")
        if len(texto) <= 90 and ruta.exists():
            return np.frombuffer(ruta.read_bytes(), dtype=np.int16), 24000
        audio, frecuencia = self._edge_descargar(texto, voz, velocidad)
        if len(texto) <= 90:
            try:
                cache.mkdir(exist_ok=True)
                ruta.write_bytes(audio.tobytes())
                archivos = sorted(cache.glob("*.pcm"), key=lambda p: p.stat().st_mtime)
                for viejo in archivos[:-400]:  # como mucho 400 frases (~20 MB)
                    viejo.unlink()
            except Exception:
                pass
        return audio, frecuencia

    def _edge_descargar(self, texto: str, voz: str, velocidad: str):
        import edge_tts
        import miniaudio

        async def descargar():
            comunicador = edge_tts.Communicate(texto, voz, rate=velocidad)
            datos = bytearray()
            async for trozo in comunicador.stream():
                if trozo["type"] == "audio":
                    datos.extend(trozo["data"])
            return bytes(datos)

        mp3 = asyncio.run(descargar())
        if not mp3:
            raise RuntimeError("edge-tts no devolvió audio")
        sonido = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
        return np.frombuffer(sonido.samples, dtype=np.int16), 24000

    def _piper_sintetizar(self, texto: str):
        if self._piper is None:
            from piper import PiperVoice

            ruta = Path(cfg("voz.piper_modelo", "modelos/piper/es_ES-davefx-medium.onnx"))
            if not ruta.is_absolute():
                ruta = RAIZ / ruta
            if not ruta.exists():
                raise FileNotFoundError(f"No encuentro la voz de Piper en {ruta}")
            self._piper = PiperVoice.load(str(ruta))
        trozos = list(self._piper.synthesize(texto))
        if not trozos:
            return None
        return np.concatenate([t.audio_int16_array for t in trozos]), trozos[0].sample_rate


WHISPER_PRECARGADO = None  # modelo cargado por el Jarvis dormido (interfaz.precargar_oido)
WAKEWORD_PRECARGADO = None  # openWakeWord ya creado por el Jarvis dormido
PRECARGANDO = threading.Event()  # se está precargando ahora mismo (para no cargarlo dos veces a la vez)


_VENTANAS_FFT = {}


def espectro(trozo: np.ndarray, frecuencia: int, bandas: int = 16) -> list:
    """16 bandas (90 Hz-7,6 kHz, escala logarítmica) entre 0 y 1 para el orbe: la onda sigue a la voz de verdad.
    Calibrado con voz sintética: una voz normal llega a 0,6-0,9 en sus formantes; el silencio de una habitación, 0."""
    x = trozo.astype(np.float32) / 32768
    n = 512 if len(x) >= 512 else 256
    if len(x) < n:
        return [0.0] * bandas
    if n not in _VENTANAS_FFT:
        _VENTANAS_FFT[n] = np.hanning(n).astype(np.float32)
    magnitud = np.abs(np.fft.rfft(x[-n:] * _VENTANAS_FFT[n]))
    frecuencias = np.fft.rfftfreq(n, 1 / frecuencia)
    bordes = np.geomspace(90, min(7600, frecuencia / 2 - 1), bandas + 1)
    salida = []
    for i, (a, b) in enumerate(zip(bordes[:-1], bordes[1:])):
        sel = magnitud[(frecuencias >= a) & (frecuencias < b)]
        v = float(sel.mean()) if len(sel) else float(magnitud[int(np.argmin(np.abs(frecuencias - (a + b) / 2)))])
        db = 20 * np.log10(v + 1e-9) + i * 1.4   # la voz tiene poca energía en agudos: se compensa (preénfasis)
        salida.append(round(float(np.clip((db + 8) / 38, 0, 1)), 2))
    return salida


def cargar_modelo_whisper():
    """Carga Whisper (GPU si se puede). Se usa al despertar o, con interfaz.precargar_oido, ya en modo dormido."""
    from faster_whisper import WhisperModel

    _preparar_dlls_cuda()
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    modelo = cfg("voz.whisper_modelo", "small")
    dispositivo = cfg("voz.whisper_dispositivo", "auto")
    # int8_float16 en la GPU: medido con small, carga en 1,6 s (antes 2,9) y transcribe en 0,4 s (antes 1,0),
    # con el mismo texto resultante. Si la GPU no lo admite, se prueba float16 y luego la CPU.
    intentos = [("cuda", "int8_float16"), ("cuda", "float16"), ("cpu", "int8")] if dispositivo == "auto" else \
               [(dispositivo, "int8_float16" if dispositivo == "cuda" else "int8")]
    for disp, tipo in intentos:
        try:
            emitir("cargando", texto=f"Cargando reconocimiento de voz ({modelo}, {disp})…")
            whisper = WhisperModel(modelo, device=disp, compute_type=tipo, download_root=str(RAIZ / "modelos" / "whisper"))
            # Prueba real: si CUDA no funciona de verdad, falla aquí y no en mitad de una orden
            list(whisper.transcribe(np.zeros(FRECUENCIA, dtype=np.float32), language="es")[0])
            log.info(f"WHISPER  {modelo} en {disp} ({tipo})")
            return whisper
        except Exception as e:
            log.warning(f"Whisper no arrancó en {disp}: {e}")
    raise RuntimeError("no se pudo cargar el reconocimiento de voz (Whisper)")


# ==================================================================
#  VOZ: escucha + habla
# ==================================================================
class Voz:
    def __init__(self, al_oir_orden):
        """al_oir_orden(texto) se llama (en otro hilo) cada vez que el usuario da una orden por voz."""
        self.al_oir_orden = al_oir_orden
        self.activa = False
        self.estado = "reposo"            # reposo | escuchando | pensando | hablando
        self._hablando = threading.Event()
        self._cerrojo = threading.Lock()
        self._pendientes = 0              # frases que faltan por decir
        self._parar_habla = threading.Event()
        self._cola_frases = queue.Queue()
        self._cola_audio = queue.Queue(maxsize=3)
        self._cola_mic = queue.Queue()
        self._respuestas = queue.Queue()  # transcripciones pedidas con escuchar_respuesta()
        self._esperando_respuesta = False
        self._activacion_manual = threading.Event()
        self._buffer_frase = ""
        self.sintetizador = Sintetizador()
        self.whisper = None
        self.wakeword = None
        self.vad = None
        self.microfono_ok = False
        self.pausada = False              # True en modo juego: no detecta «Jarvis» (sí el atajo y el botón)
        threading.Thread(target=self._hilo_sintesis, daemon=True, name="sintesis").start()
        threading.Thread(target=self._hilo_reproduccion, daemon=True, name="reproduccion").start()

    # --------------------------------------------------------------
    #  ARRANQUE
    # --------------------------------------------------------------
    def iniciar(self):
        """Carga modelos y abre el micrófono. Si algo falla, lo explica y sigue (solo texto)."""
        try:
            self._cargar_whisper()
            self.vad = DetectorVoz()
            self._abrir_microfono()
            if cfg("voz.modo_activacion", "hibrido") in ("hibrido", "wakeword"):
                # "Hey Jarvis" instantáneo: se carga en segundo plano (tarda ~2 s y no hace falta para empezar)
                threading.Thread(target=self._cargar_wakeword_seguro, daemon=True, name="wakeword").start()
        except Exception as e:
            log.exception("No se pudo iniciar la escucha")
            emitir("error", texto=f"No puedo escucharte: {e}. Puedes escribirme en el chat.")
            return False
        # El atajo de teclado lo gestiona el vigilante (RegisterHotKey, sin ganchos de teclado)
        self.activa = True
        threading.Thread(target=self._hilo_escucha, daemon=True, name="escucha").start()
        return True

    def _cargar_whisper(self):
        global WHISPER_PRECARGADO
        limite = time.time() + 20
        while PRECARGANDO.is_set() and time.time() < limite:  # a medio precargar: esperamos a ese
            time.sleep(0.05)
        if WHISPER_PRECARGADO is not None:  # lo dejó cargado el Jarvis dormido: no hay que esperar
            self.whisper, WHISPER_PRECARGADO = WHISPER_PRECARGADO, None
            log.info("WHISPER  ya estaba precargado")
            return
        self.whisper = cargar_modelo_whisper()


    def _cargar_wakeword_seguro(self):
        try:
            self._cargar_wakeword()
        except Exception as e:
            log.warning(f"openWakeWord no disponible ({e}); sigo con la detección por Whisper")

    def _cargar_wakeword(self):
        global WAKEWORD_PRECARGADO
        if WAKEWORD_PRECARGADO is not None:
            self.wakeword, WAKEWORD_PRECARGADO = WAKEWORD_PRECARGADO, None
            log.info("WAKEWORD  ya estaba precargado")
            return
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        nombre = cfg("voz.palabra_activacion", "hey_jarvis")
        download_models([nombre])
        self.wakeword = Model(wakeword_models=[nombre], inference_framework="onnx")
        log.info(f"WAKEWORD  {nombre} umbral={cfg('voz.umbral_activacion', 0.35)}")

    def _abrir_microfono(self):
        dispositivo = cfg("voz.microfono", None)
        if dispositivo is not None and not isinstance(dispositivo, int):
            candidatos = [i for i, d in enumerate(sd.query_devices())
                          if str(dispositivo).lower() in d["name"].lower() and d["max_input_channels"] > 0]
            dispositivo = candidatos[0] if candidatos else None
        try:
            info = sd.query_devices(dispositivo, "input")
        except Exception:
            raise RuntimeError("no encuentro ningún micrófono conectado")
        self._nombre_mic = info["name"]

        def recibir(datos, _frames, _tiempo, estado):
            self._cola_mic.put(datos[:, 0].copy())

        self._stream_mic = sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="int16", blocksize=TROZO,
                                          device=dispositivo, callback=recibir)
        self._stream_mic.start()
        self.microfono_ok = True
        log.info(f"MICRÓFONO  {self._nombre_mic}")

    # --------------------------------------------------------------
    #  ESCUCHA
    # --------------------------------------------------------------
    def pausar(self, pausar: bool = True):
        self.pausada = pausar
        log.info(f"ESCUCHA  {'en pausa' if pausar else 'activa'}")

    def activar_manual(self):
        """Pulsar para hablar (atajo de teclado o botón del micro en la interfaz)."""
        self._activacion_manual.set()

    def _cambiar_estado(self, estado):
        self.estado = estado
        emitir("estado", estado=estado)

    def _hilo_escucha(self):
        """Mantiene vivo el bucle de escucha aunque ocurra un error puntual."""
        while self.activa:
            try:
                self._bucle_escucha()
            except Exception:
                log.exception("Error en la escucha; la reinicio")
                self._cambiar_estado("reposo")
                time.sleep(1)

    def _bucle_escucha(self):
        """Bucle principal del micrófono. Dos formas de activarse (modo 'hibrido'):
          1. openWakeWord detecta "Hey Jarvis" al instante y empieza a grabar la orden.
          2. El detector de voz recorta cada frase que dices; Whisper la transcribe y si contiene
             "Jarvis" (al principio, en medio o al final) el resto de la frase es la orden.
        """
        modo = cfg("voz.modo_activacion", "hibrido")
        usar_whisper = modo in ("hibrido", "whisper")
        vad_reposo = DetectorVoz() if usar_whisper else None
        segundos_trozo = TROZO / FRECUENCIA
        previo = deque(maxlen=8)          # ~0,6 s de audio anterior a la activación
        grabando, audio, voz_detectada, silencio = False, [], False, 0.0
        segmento, silencio_seg = None, 0.0
        ultimo_nivel = 0.0

        def empezar_grabacion(con_previo: bool):
            nonlocal grabando, audio, voz_detectada, silencio, segmento
            self._activacion_manual.clear()
            if self._hablando.is_set() or self.estado == "pensando":
                self.interrumpir()        # "Jarvis, para": se calla al momento
            grabando, voz_detectada, silencio, segmento = True, False, 0.0, None
            audio = list(previo) if con_previo else []
            self.vad.reiniciar()
            self._cambiar_estado("escuchando")
            emitir("activado")

        while self.activa:
            try:
                trozo = self._cola_mic.get(timeout=0.5)
            except queue.Empty:
                continue
            ahora = time.time()
            if ahora - ultimo_nivel > 0.05:
                emitir("nivel_mic", nivel=float(np.sqrt(np.mean((trozo.astype(np.float32) / 32768) ** 2))),
                       espectro=espectro(trozo, FRECUENCIA) if self.estado == "escuchando" else None)
                ultimo_nivel = ahora

            # ---------------- Grabando una orden ----------------
            if grabando:
                audio.append(trozo)
                if self.vad.probabilidad(trozo) > 0.5:
                    voz_detectada, silencio = True, 0.0
                else:
                    silencio += segundos_trozo
                duracion = len(audio) * segundos_trozo
                fin_frase = voz_detectada and silencio >= float(cfg("voz.silencio_fin_frase", 0.7))
                if fin_frase or (not voz_detectada and duracion > 6) or duracion > 20:
                    grabando = False
                    texto = self.transcribir(np.concatenate(audio)) if voz_detectada else ""
                    self._entregar(texto)
                    self._tras_transcribir(previo, vad_reposo)
                continue

            # ---------------- En reposo (o hablando / pensando) ----------------
            previo.append(trozo)
            if self._activacion_manual.is_set() or self._esperando_respuesta:
                empezar_grabacion(con_previo=False)
                continue
            if self.pausada:
                continue  # modo juego / pausa: solo atiendo al atajo o al botón del micro
            if self.wakeword is not None:
                puntuacion = max(self.wakeword.predict(trozo).values())
                if puntuacion >= float(cfg("voz.umbral_activacion", 0.35)):
                    log.info(f"ACTIVACIÓN  'hey jarvis' (puntuación {puntuacion:.2f})")
                    empezar_grabacion(con_previo=True)
                    continue
            if not usar_whisper:
                continue
            hay_voz = vad_reposo.probabilidad(trozo) > 0.5
            if segmento is None:
                if hay_voz:
                    segmento, silencio_seg = list(previo), 0.0
                continue
            segmento.append(trozo)
            silencio_seg = 0.0 if hay_voz else silencio_seg + segundos_trozo
            if silencio_seg >= float(cfg("voz.silencio_fin_frase", 0.9)) or len(segmento) * segundos_trozo > 15:
                frase, segmento = np.concatenate(segmento), None
                if len(frase) < FRECUENCIA * 0.5:
                    continue
                texto = self.transcribir(frase, registrar=False)
                if NOMBRE_JARVIS.search(texto):
                    log.info(f"ACTIVACIÓN  nombre en la frase: {texto!r}")
                    if self._hablando.is_set() or self.estado == "pensando":
                        self.interrumpir()
                    if limpiar_orden(texto):
                        emitir("activado")
                        self._entregar(texto)
                    else:
                        empezar_grabacion(con_previo=False)   # solo dijo "Jarvis": ahora escucho la orden
                        continue
                self._tras_transcribir(previo, vad_reposo)

    def _tras_transcribir(self, previo, vad_reposo):
        """Descarta el audio acumulado mientras transcribíamos (para no oírnos con retraso) y reinicia detectores."""
        while not self._cola_mic.empty():
            try:
                self._cola_mic.get_nowait()
            except queue.Empty:
                break
        previo.clear()
        if self.wakeword is not None:
            self.wakeword.reset()
        if vad_reposo is not None:
            vad_reposo.reiniciar()

    def transcribir(self, audio_int16: np.ndarray, registrar: bool = True) -> str:
        segmentos, _ = self.whisper.transcribe(
            audio_int16.astype(np.float32) / 32768.0, language="es", beam_size=1, vad_filter=False,
            initial_prompt="Jarvis, abre YouTube. Apunta en Obsidian. Spotify, VS Code, Mockito, Java.")
        segmentos = [s for s in segmentos if s.no_speech_prob < 0.6]
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        if registrar or NOMBRE_JARVIS.search(texto):
            log.info(f"OÍDO  {texto!r}")
        return texto

    def _entregar(self, texto: str):
        if self._esperando_respuesta:
            self._respuestas.put(texto)
            return
        orden = limpiar_orden(texto)
        if not orden:
            self._cambiar_estado("reposo")
            return
        if orden.lower().strip(" .,!¡¿?") in PALABRAS_PARAR:
            log.info("PARADA  por voz")
            self._cambiar_estado("reposo")
            return
        self._cambiar_estado("pensando")
        threading.Thread(target=self.al_oir_orden, args=(orden,), daemon=True, name="orden").start()

    def escuchar_respuesta(self, espera: float = 12.0) -> str:
        """Escucha una frase sin palabra de activación (para confirmaciones). Devuelve '' si no hay respuesta."""
        if not self.activa:
            return ""
        self.esperar_fin_habla()
        while not self._respuestas.empty():
            self._respuestas.get_nowait()
        self._esperando_respuesta = True
        try:
            return self._respuestas.get(timeout=espera)
        except queue.Empty:
            return ""
        finally:
            self._esperando_respuesta = False

    # --------------------------------------------------------------
    #  HABLA (streaming por frases)
    # --------------------------------------------------------------
    def decir_trozo(self, delta: str):
        """Recibe la respuesta a trozos y manda a sintetizar cada frase completa en cuanto llega."""
        self._buffer_frase += delta
        while True:
            m = re.search(r"[.!?…:;]\s", self._buffer_frase[15:])
            if not m:
                break
            corte = 15 + m.end()
            frase, self._buffer_frase = self._buffer_frase[:corte], self._buffer_frase[corte:]
            self._encolar(frase)

    def terminar_respuesta(self):
        if self._buffer_frase.strip():
            self._encolar(self._buffer_frase)
        self._buffer_frase = ""

    def decir(self, texto: str):
        """Dice un texto completo (avisos, saludos...)."""
        self._buffer_frase = ""
        self._encolar(texto)

    def _encolar(self, texto: str):
        from cerebro import CORTESIA
        if CORTESIA.match(texto.strip()):
            return  # no decimos "¿Necesitas algo más?" y similares
        texto = preparar_para_voz(texto)
        if texto and cfg("voz.activada", True):
            self._parar_habla.clear()
            with self._cerrojo:
                self._pendientes += 1
                self._hablando.set()
            self._cola_frases.put(texto)

    def _frase_terminada(self):
        """Lleva la cuenta de frases pendientes; cuando no queda ninguna, Jarvis ha terminado de hablar."""
        with self._cerrojo:
            self._pendientes = max(0, self._pendientes - 1)
            if self._pendientes == 0:
                self._hablando.clear()
                if self.estado == "hablando":
                    self._cambiar_estado("reposo")

    def interrumpir(self):
        """Corta la voz al instante y vacía lo pendiente."""
        self._parar_habla.set()
        self._buffer_frase = ""
        for cola in (self._cola_frases, self._cola_audio):
            while not cola.empty():
                try:
                    cola.get_nowait()
                except queue.Empty:
                    break
        with self._cerrojo:
            self._pendientes = 0
            self._hablando.clear()
        emitir("interrumpido")

    def esperar_fin_habla(self, maximo: float = 60):
        limite = time.time() + maximo
        while self._hablando.is_set() and time.time() < limite:
            time.sleep(0.05)

    def _hilo_sintesis(self):
        while True:
            texto = self._cola_frases.get()
            if self._parar_habla.is_set():
                continue
            try:
                resultado = self.sintetizador.sintetizar(texto)
            except Exception as e:
                log.warning(f"Error sintetizando: {e}")
                resultado = None
            if resultado is not None and not self._parar_habla.is_set():
                self._cola_audio.put(resultado)
            else:
                self._frase_terminada()

    def _hilo_reproduccion(self):
        while True:
            audio, frecuencia = self._cola_audio.get()
            if not self._parar_habla.is_set():
                self._reproducir(audio, frecuencia)
            self._frase_terminada()

    def _reproducir(self, audio: np.ndarray, frecuencia: int):
        if self.estado != "escuchando":
            self._cambiar_estado("hablando")
        volumen = max(0, min(100, int(cfg("voz.volumen_voz", 100)))) / 100
        if volumen != 1:
            audio = (audio.astype(np.float32) * volumen).astype(np.int16)
        bloque = frecuencia // 20  # 50 ms
        try:
            with sd.OutputStream(samplerate=frecuencia, channels=1, dtype="int16") as salida:
                for i in range(0, len(audio), bloque):
                    if self._parar_habla.is_set():
                        break
                    trozo = audio[i:i + bloque]
                    emitir("nivel_voz", nivel=float(np.sqrt(np.mean((trozo.astype(np.float32) / 32768) ** 2))),
                           espectro=espectro(trozo, frecuencia))
                    salida.write(trozo)
        except Exception as e:
            log.warning(f"No pude reproducir audio: {e}")
            emitir("error", texto="No puedo reproducir sonido. Revisa los altavoces o auriculares.")
        emitir("nivel_voz", nivel=0.0)


# Whisper escribe el nombre de muchas formas: Jarvis, Yarbis, Yardis, Giarbis, Yaris, Arbis, Harvis...
# Patrón fonético medido: reconoce todas esas variantes y no confunde París, Harvard, crisis, Travis, varias...
NOMBRE_JARVIS = re.compile(r"\b(?:g?[jyhc]h?|gi)?[aeiy]?[ae]r[bdv]{0,2}[iy]s\b", re.I)


def limpiar_orden(texto: str) -> str:
    """Quita el 'Jarvis' (esté donde esté) y la basura típica que Whisper inventa con silencio."""
    texto = texto.strip()
    if re.fullmatch(r"[\W_]*(gracias\.?|subtítulos.*|amara\.org.*)?[\W_]*", texto, flags=re.I):
        return ""
    texto = re.sub(r"\b(oye|hey|hei|ey|eh|vale)?[\s,]*" + NOMBRE_JARVIS.pattern + r"[\s,.:;!¡?¿]*", " ", texto, flags=re.I)
    texto = re.sub(r"\s+", " ", texto).strip(" ,.;:")
    return texto[0].upper() + texto[1:] if texto else ""


def es_afirmativo(texto: str) -> bool:
    texto = texto.lower()
    return bool(re.search(r"\b(s[ií]|vale|claro|adelante|hazlo|confirmo|correcto|ok|okay|por supuesto|venga)\b", texto)) \
        and not re.search(r"\bno\b", texto)
