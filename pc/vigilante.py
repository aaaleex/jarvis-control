"""
VIGILANTE DE JARVIS — proceso ligero que arranca con Windows.

Qué hace (y nada más, para gastar muy poco):
  · Icono en la bandeja del sistema con su menú.
  · Escucha la palabra «Jarvis» con Vosk (modelo pequeño en español y vocabulario cerrado).
  · Atajo de teclado global (RegisterHotKey de Windows: sin ganchos de teclado, no afecta a los juegos).
  · Cuando lo llamas: pitido + aviso «despertando», abre Jarvis y le pasa el audio de tu frase,
    así «Jarvis, abre YouTube» se ejecuta sin repetirlo.
  · Modo juego: si hay un juego a pantalla completa, apaga el micrófono y solo atiende al atajo.
  · Mientras Jarvis está abierto, el vigilante deja de escuchar (Jarvis usa su propio oído).

Se arranca con:  .venv\\Scripts\\pythonw.exe vigilante.py   (o iniciar_jarvis.bat)
"""
import ctypes
import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from collections import deque
from ctypes import wintypes
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
(RAIZ / "datos").mkdir(exist_ok=True)
if sys.stdout is None or sys.stderr is None:  # pythonw no tiene consola
    _salida = open(RAIZ / "datos" / "salida_vigilante.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _salida
    sys.stderr = sys.stderr or _salida

import math
from array import array

import nucleo  # (sin numpy a propósito: el vigilante debe ocupar lo mínimo)
from nucleo import cfg

log = logging.getLogger("vigilante")
if not log.handlers:
    log.setLevel(logging.INFO)
    _m = logging.FileHandler(RAIZ / "datos" / "vigilante.log", encoding="utf-8")
    _m.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(_m)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE

FRECUENCIA = 16000
TROZO = 1600  # 100 ms
# Palabras "señuelo": dan al reconocedor alternativas a «jarvis» para que no confunda Javier, jardín,
# "has visto"... con el nombre. Medido: 97 % de aciertos y 0 falsas activaciones en 128 frases de prueba.
PALABRAS = ["jarvis", "travis", "javier", "jardín", "jarra", "harry", "jarabe", "chavales", "garbanzos",
            "has", "visto", "vista", "vas", "es", "harto", "carlos", "marcos", "dar", "bis", "jamás", "barbie",
            "parís", "jabón", "garaje", "hace", "ya", "vale", "oye", "hola", "abre", "pon", "que", "sí", "no",
            "más", "jugar", "partido", "ayer", "chicos", "harvard", "javi", "[unk]"]


def _url():
    return f"http://127.0.0.1:{int(cfg('interfaz.puerto', 8765))}"


def llamar_jarvis(ruta: str, datos: bytes = b"", espera: float = 2.0, metodo: str = "POST"):
    """Habla con el Jarvis abierto por HTTP local. Devuelve el JSON o None si no responde."""
    try:
        peticion = urllib.request.Request(_url() + ruta, data=datos if metodo == "POST" else None, method=metodo)
        with urllib.request.urlopen(peticion, timeout=espera) as r:
            return json.loads(r.read() or b"{}")
    except Exception:
        return None


def jarvis_abierto() -> bool:
    """¿Hay un proceso de Jarvis escuchando en su puerto? (despierto o dormido)"""
    import socket
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", int(cfg("interfaz.puerto", 8765)))) == 0


def estado_jarvis():
    """None si no hay Jarvis; si lo hay, su estado ({"dormido": True/False, "visible": ...})."""
    if not jarvis_abierto():
        return None
    # Si no contesta a tiempo (está arrancando), lo tratamos como dormido: el vigilante sigue escuchando
    return llamar_jarvis("/api/estado", metodo="GET", espera=0.8) or {"dormido": True, "sin_respuesta": True}


def jarvis_despierto() -> bool:
    e = estado_jarvis()
    return bool(e) and not e.get("dormido")


_ultimo_precalentado = [0.0]


def precalentar_modelo():
    """Al oír «Jarvis» mandamos a Ollama la misma petición con la que Jarvis prepara el modelo
    (la guarda Jarvis en datos/precalentar.json). Así el modelo carga y lee sus instrucciones MIENTRAS
    aún hablas y Jarvis arranca. Si era una falsa alarma, Ollama lo suelta solo a los 5 minutos."""
    if time.time() - _ultimo_precalentado[0] < 60:
        return
    ruta = RAIZ / "datos" / "precalentar.json"
    if not ruta.exists() or cfg("cerebro.proveedor", "ollama") != "ollama":
        return
    _ultimo_precalentado[0] = time.time()

    def mandar():
        inicio = time.time()
        try:
            url = str(cfg("cerebro.ollama.url", "http://localhost:11434")).rstrip("/") + "/api/chat"
            peticion = urllib.request.Request(url, data=ruta.read_bytes(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(peticion, timeout=180) as r:
                r.read()
            log.info(f"OLLAMA  precalentado desde el vigilante en {time.time() - inicio:.1f}s")
        except Exception as e:
            log.warning(f"OLLAMA  no pude precalentar: {e}")
    threading.Thread(target=mandar, daemon=True, name="precalentar").start()


def a_wav(audio: bytes) -> bytes:
    """Audio PCM 16 bits mono -> archivo WAV en memoria."""
    bufer = io.BytesIO()
    with wave.open(bufer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FRECUENCIA)
        w.writeframes(audio)
    return bufer.getvalue()


def energia(datos: bytes) -> float:
    """Volumen (RMS) de un trozo de audio."""
    muestras = array("h")
    muestras.frombytes(datos)
    return math.sqrt(sum(x * x for x in muestras) / max(1, len(muestras)))


# ==================================================================
#  MODELO DE VOSK "LIGERO": solo lo necesario para reconocer nuestra gramática cerrada.
#  Sin el modelo de lenguaje general (Gr.fst) y con 45 palabras en vez de 100.000:
#  pasa de 99 MB a 52 MB de RAM con la misma precisión (medido).
# ==================================================================
MODELO_ORIGINAL = RAIZ / "modelos" / "vosk" / "vosk-model-small-es-0.42"
MODELO_LIGERO = RAIZ / "modelos" / "vosk" / "jarvis-ligero"


def _tabla_palabras_de_fst(ruta) -> list:
    """Lee la tabla de palabras guardada dentro de un Gr.fst (formato binario de OpenFst)."""
    import struct

    def cadena(f):
        return f.read(struct.unpack("<i", f.read(4))[0]).decode("utf-8")

    def tabla(f):
        assert struct.unpack("<i", f.read(4))[0] == 2125658996
        cadena(f)
        f.read(8)
        return [(cadena(f), struct.unpack("<q", f.read(8))[0]) for _ in range(struct.unpack("<q", f.read(8))[0])]

    with open(ruta, "rb") as f:
        assert struct.unpack("<i", f.read(4))[0] == 2125659606, "Gr.fst no válido"
        cadena(f)
        cadena(f)
        _, banderas = struct.unpack("<ii", f.read(8))
        f.read(32)
        entrada = tabla(f) if banderas & 1 else None
        salida = tabla(f) if banderas & 2 else None
    return salida or entrada


def preparar_modelo_ligero() -> Path:
    import shutil

    firma = ",".join(PALABRAS)
    marca = MODELO_LIGERO / "palabras.txt"
    if marca.exists() and marca.read_text(encoding="utf-8") == firma:
        return MODELO_LIGERO
    if not MODELO_ORIGINAL.exists():
        raise FileNotFoundError(f"falta el modelo de Vosk en {MODELO_ORIGINAL} (ejecuta instalar.bat)")
    log.info("VOSK  preparando el modelo ligero (solo la primera vez)")
    shutil.rmtree(MODELO_LIGERO, ignore_errors=True)
    shutil.copytree(MODELO_ORIGINAL, MODELO_LIGERO, ignore=shutil.ignore_patterns("Gr.fst", "README"))
    utiles = set(PALABRAS) | {"<eps>", "!SIL", "#0", "<s>", "</s>"}
    lineas = [f"{p} {c}" for p, c in _tabla_palabras_de_fst(MODELO_ORIGINAL / "graph" / "Gr.fst") if p in utiles]
    (MODELO_LIGERO / "graph" / "words.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    marca.write_text(firma, encoding="utf-8")
    return MODELO_LIGERO


# ==================================================================
#  SONIDO DE CONFIRMACIÓN (se genera una vez)
# ==================================================================
RUTA_PITIDO = RAIZ / "datos" / "despertar.wav"


def _crear_pitido():
    if RUTA_PITIDO.exists():
        return
    onda = array("h")
    for i in range(int(FRECUENCIA * 0.22)):
        t = i / FRECUENCIA
        nota = 880 if t < 0.09 else 1320                        # dos notas ascendentes
        envolvente = min(1.0, t * 80) * math.exp(-((t % 0.11) * 18))
        onda.append(int(math.sin(2 * math.pi * nota * t) * envolvente * 9000))
    RUTA_PITIDO.write_bytes(a_wav(onda.tobytes()))


def pitido():
    if cfg("vigilante.sonido_activacion", True):
        import winsound
        try:
            winsound.PlaySound(str(RUTA_PITIDO), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass


# ==================================================================
#  AVISO «DESPERTANDO» (ventanita sin foco; tkinter se carga solo la primera vez)
# ==================================================================
class AvisoDespertar:
    def __init__(self):
        self.cola = queue.Queue()
        self.hilo = None

    def preparar(self):
        """Crea la ventanita oculta de antemano (tkinter tarda ~1 s en arrancar la primera vez)."""
        if self.hilo is None:
            self.hilo = threading.Thread(target=self._bucle, daemon=True, name="aviso")
            self.hilo.start()

    def mostrar(self, texto="DESPERTANDO"):
        self.preparar()
        self.cola.put(("mostrar", texto))

    def ocultar(self):
        if self.hilo:
            self.cola.put(("ocultar", None))

    def _bucle(self):
        import math
        import tkinter as tk

        raiz = tk.Tk()
        raiz.withdraw()
        raiz.overrideredirect(True)
        raiz.attributes("-topmost", True)
        transparente = "#010203"
        raiz.configure(bg=transparente)
        raiz.attributes("-transparentcolor", transparente)
        lado = 190
        zona = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(zona), 0)  # zona útil de la pantalla principal
        raiz.geometry(f"{lado}x{lado + 30}+{zona.right - lado - 24}+{zona.bottom - lado - 54}")
        lienzo = tk.Canvas(raiz, width=lado, height=lado + 30, bg=transparente, highlightthickness=0)
        lienzo.pack()
        raiz.update_idletasks()
        # Que nunca robe el foco ni salga en la barra de tareas
        hwnd = user32.GetParent(raiz.winfo_id())
        estilo = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, estilo | 0x08000000 | 0x00000080)  # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        estado = {"visible": False, "texto": "", "t": 0.0, "inicio": 0.0}

        def dibujar():
            try:
                while True:
                    orden, texto = self.cola.get_nowait()
                    if orden == "mostrar":
                        estado.update(visible=True, texto=texto, inicio=time.time())
                        # en el centro de la pantalla del ratón: donde aparecerá el orbe de verdad
                        p = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(p))

                        class MONITORINFO(ctypes.Structure):
                            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                                        ("dwFlags", wintypes.DWORD)]
                        info = MONITORINFO()
                        info.cbSize = ctypes.sizeof(MONITORINFO)
                        user32.GetMonitorInfoW(user32.MonitorFromPoint(p, 2), ctypes.byref(info))
                        w = info.rcWork
                        user32.SetWindowPos(hwnd, None, (w.left + w.right - lado) // 2, (w.top + w.bottom - lado) // 2 - 15,
                                            0, 0, 0x0001 | 0x0004 | 0x0010)
                        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                        user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # encima, sin activar
                    else:
                        estado["visible"] = False
                        user32.ShowWindow(hwnd, 0)
            except queue.Empty:
                pass
            if estado["visible"]:
                if time.time() - estado["inicio"] > 45:  # por si Jarvis no llega a abrirse
                    estado["visible"] = False
                    user32.ShowWindow(hwnd, 0)
                # Mismo lenguaje que el orbe 3D (por si aún no está precargado): anillos finos de un solo acento,
                # núcleo blanco que respira y una palabra discreta. Sin morados ni mayúsculas.
                estado["t"] += 0.05
                t, c = estado["t"], lado / 2
                lienzo.delete("all")
                entrada = min(1.0, (time.time() - estado["inicio"]) / 0.2)
                r = 58 * (0.85 + 0.15 * entrada) * (1 + 0.025 * math.sin(t * 2.2))
                fondo = r * 1.5  # velo oscuro detrás, como el del orbe 3D (contraste sobre fondos claros o con texto)
                lienzo.create_oval(c - fondo, c - fondo, c + fondo, c + fondo, fill="#05080d", outline="")
                lienzo.create_rectangle(c - 46, lado + 4, c + 46, lado + 24, fill="#05080d", outline="")
                for radio, color, ancho in ((r * 1.32, "#0c2a3a", 1), (r * 1.18, "#123f57", 1), (r * 1.0, "#3fc8ff", 2)):
                    lienzo.create_oval(c - radio, c - radio, c + radio, c + radio, outline=color, width=ancho)
                inicio = math.degrees(t * 1.6)
                lienzo.create_arc(c - r * 1.18, c - r * 1.18, c + r * 1.18, c + r * 1.18, start=inicio, extent=60,
                                  style="arc", outline="#9feaff", width=2)
                for radio, color in ((r * 0.34, "#1a6dff"), (r * 0.22, "#4fd8ff"), (r * 0.12, "#ffffff")):
                    radio *= 1 + 0.08 * math.sin(t * 3)
                    lienzo.create_oval(c - radio, c - radio, c + radio, c + radio, fill=color, outline="")
                lienzo.create_text(c, lado + 14, text=estado["texto"].capitalize() + "…", fill="#a9b6c2", font=("Segoe UI Light", 10))
            raiz.after(33, dibujar)

        dibujar()
        raiz.mainloop()


# ==================================================================
#  MICRÓFONO (se reconecta solo si lo desenchufas)
# ==================================================================
class Microfono:
    def __init__(self, cola):
        self.cola = cola
        self.stream = None
        self.ultimo_audio = 0.0
        self.nombre = ""

    @property
    def abierto(self):
        return self.stream is not None

    def abrir(self) -> bool:
        import sounddevice as sd
        self.cerrar()
        try:
            # PortAudio solo ve los dispositivos que había al iniciarse: lo reiniciamos para detectar el G733 reconectado
            sd._terminate()
            sd._initialize()
            dispositivo = cfg("voz.microfono", None)
            if dispositivo is not None and not isinstance(dispositivo, int):
                candidatos = [i for i, d in enumerate(sd.query_devices())
                              if str(dispositivo).lower() in d["name"].lower() and d["max_input_channels"] > 0
                              and sd.query_hostapis(d["hostapi"])["name"] == "MME"]
                dispositivo = candidatos[0] if candidatos else None
            self.nombre = sd.query_devices(dispositivo, "input")["name"]

            def recibir(datos, _frames, _tiempo, _estado):
                self.ultimo_audio = time.time()
                self.cola.put(bytes(datos))

            self.stream = sd.RawInputStream(samplerate=FRECUENCIA, channels=1, dtype="int16", blocksize=TROZO,
                                            device=dispositivo, callback=recibir)
            self.stream.start()
            self.ultimo_audio = time.time()
            return True
        except Exception as e:
            log.warning(f"No pude abrir el micrófono: {e}")
            self.stream = None
            return False

    def cerrar(self):
        if self.stream is not None:
            try:
                self.stream.abort()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def colgado(self) -> bool:
        """Si el micro deja de mandar audio (desenchufado), hay que reabrirlo."""
        return self.abierto and time.time() - self.ultimo_audio > 2.5


# ==================================================================
#  INICIO CON WINDOWS (acceso directo en la carpeta Inicio del usuario: sin permisos de administrador)
# ==================================================================
RUTA_INICIO = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Jarvis.lnk"


def inicio_con_windows() -> bool:
    return RUTA_INICIO.exists()


def configurar_inicio_con_windows(activar: bool):
    if activar:
        import win32com.client
        acceso = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(RUTA_INICIO))
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        acceso.TargetPath = str(pythonw if pythonw.exists() else sys.executable)
        acceso.Arguments = f'"{RAIZ / "vigilante.py"}"'
        acceso.WorkingDirectory = str(RAIZ)
        acceso.Description = "Vigilante de J.A.R.V.I.S."
        acceso.Save()
    elif RUTA_INICIO.exists():
        RUTA_INICIO.unlink()
    log.info(f"INICIO CON WINDOWS  {'activado' if activar else 'desactivado'}")


# ==================================================================
#  ATAJO DE TECLADO GLOBAL
# ==================================================================
_MODIFICADORES = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "mayus": 0x4, "win": 0x8}
_TECLAS = {"space": 0x20, "espacio": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "insert": 0x2D, "home": 0x24,
           "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "pause": 0x13, "scrolllock": 0x91}


def interpretar_atajo(texto: str):
    """'ctrl+alt+j' -> (modificadores, código de tecla)."""
    mods, tecla = 0, None
    for parte in texto.lower().replace(" ", "").split("+"):
        if parte in _MODIFICADORES:
            mods |= _MODIFICADORES[parte]
        elif len(parte) == 1 and parte.isalnum():
            tecla = ord(parte.upper())
        elif parte.startswith("f") and parte[1:].isdigit() and 1 <= int(parte[1:]) <= 24:
            tecla = 0x6F + int(parte[1:])
        elif parte in _TECLAS:
            tecla = _TECLAS[parte]
    if tecla is None or mods == 0:
        raise ValueError(f"atajo no válido: '{texto}' (ejemplo válido: ctrl+alt+j)")
    return mods, tecla


# ==================================================================
#  EL VIGILANTE
# ==================================================================
class Vigilante:
    def __init__(self):
        self.cola_audio = queue.Queue()
        self.microfono = Microfono(self.cola_audio)
        self.aviso = AvisoDespertar()
        self.icono = None
        self.pausado = False
        self.juego_auto = False          # detectado automáticamente
        self.juego_forzado = None        # True/False si lo has cambiado desde el menú
        self._negativos_juego = 0
        self.captura = None              # frase que se está grabando tras oír «Jarvis» o pulsar el atajo
        self.reconocedor = None
        self._muestras = 0
        self._aviso_parcial = False      # ya dimos el aviso rápido por un resultado parcial
        self.proceso_jarvis = None
        self.proceso_dormido = None      # Jarvis precargado (ventana oculta, sin modelos)
        self._cerrojo_lanzar = threading.Lock()
        self._ultimo_dormido = 0.0
        self._fallos_dormido = 0
        self._desperte_dormido = False   # desperté al dormido por un «Jarvis» parcial (por si era falsa alarma)
        self.estado = None               # último estado conocido de Jarvis (None = cerrado)
        self._oyendo_hasta = 0.0         # tras un «Jarvis» parcial, seguimos con el micro abierto hasta tener la frase
        self._avisado_micro = False
        self._ultima_config = 0.0
        self.salir_evento = threading.Event()

    # ---------------- estado ----------------
    @property
    def modo_juego(self) -> bool:
        return self.juego_forzado if self.juego_forzado is not None else self.juego_auto

    def notificar(self, texto: str):
        log.info(f"NOTIFICACIÓN  {texto}")
        try:
            self.icono.notify(texto, "J.A.R.V.I.S.")
        except Exception:
            pass

    def actualizar_icono(self):
        if not self.icono:
            return
        color = "#5a6b78" if self.pausado else "#ffb547" if self.modo_juego else "#00e5ff"
        self.icono.icon = dibujar_icono(color, bool(self.estado) and not self.estado.get("dormido"))
        estado = "en pausa" if self.pausado else "modo juego (solo atajo)" if self.modo_juego else "escuchando «Jarvis»"
        self.icono.title = f"Jarvis — {estado}\nAtajo: {cfg('vigilante.atajo', 'ctrl+alt+j')}"
        self.icono.update_menu()

    # ---------------- abrir Jarvis ----------------
    def _python(self):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        return str(pythonw if pythonw.exists() else sys.executable)

    def lanzar_jarvis(self, *argumentos, activar=True):
        with self._cerrojo_lanzar:  # voz parcial + frase final + atajo pueden llegar a la vez: de uno en uno
            self._lanzar_jarvis(*argumentos, activar=activar)

    def _lanzar_jarvis(self, *argumentos, activar=True):
        estado = estado_jarvis()
        # El Jarvis dormido aún arrancando (proceso vivo pero sin responder): antes se lanzaba OTRO Jarvis
        # en paralelo (parte del bug de duplicados). Ahora se espera a que responda y se le despierta.
        if not estado and self.proceso_dormido and self.proceso_dormido.poll() is None:
            limite = time.time() + 15
            while time.time() < limite and self.proceso_dormido.poll() is None:
                estado = estado_jarvis()
                if estado:
                    break
                time.sleep(0.1)
        if estado and estado.get("dormido"):
            # Ya hay una ventana precargada: solo hay que despertarla (aparece en décimas de segundo)
            llamar_jarvis("/api/despertar", json.dumps({"mostrar": True, "activar": activar}).encode())
            if "--briefing" in argumentos:
                llamar_jarvis("/api/orden", json.dumps({"texto": "Buenos días. Dame el briefing de hoy."}).encode())
            log.info("JARVIS  despertado (estaba precargado)")
            self.aviso.ocultar()
            return
        if estado or (self.proceso_jarvis and self.proceso_jarvis.poll() is None):
            return
        self.proceso_jarvis = subprocess.Popen(
            [self._python(), str(RAIZ / "jarvis.py"), "--vigilante", *argumentos],
            cwd=str(RAIZ), creationflags=0x08000000)  # sin consola
        log.info(f"JARVIS  lanzado {argumentos}")
        threading.Thread(target=self._esperar_ventana, daemon=True).start()

    def _gestionar_precarga(self):
        """Mantiene un Jarvis dormido (ventana oculta y sin modelos) listo para aparecer al instante.
        En modo juego no: se cierra para no ocupar nada."""
        quiere = bool(cfg("interfaz.precargar", True)) and not self.modo_juego
        if self.estado is not None:
            self._fallos_dormido = 0  # hay Jarvis respondiendo: la precarga funciona
            self._dormido_respondio = True
        if self.estado is None:
            if not quiere or self._fallos_dormido >= 3 or time.time() - self._ultimo_dormido < 10:
                return
            if self.proceso_jarvis and self.proceso_jarvis.poll() is None:
                return  # hay un Jarvis arrancando
            if self.proceso_dormido and self.proceso_dormido.poll() is None:
                return
            if self.proceso_dormido is not None and not getattr(self, "_dormido_respondio", True):
                self._fallos_dormido += 1  # el anterior murió sin llegar a responder: algo falla
                log.warning(f"PRECARGA  el Jarvis dormido no llegó a arrancar ({self._fallos_dormido}/3)")
            self._dormido_respondio = False
            self._ultimo_dormido = time.time()
            self.proceso_dormido = subprocess.Popen([self._python(), str(RAIZ / "jarvis.py"), "--vigilante", "--dormido"],
                                                    cwd=str(RAIZ), creationflags=0x08000000)
            log.info(f"PRECARGA  Jarvis dormido lanzado (pid {self.proceso_dormido.pid})")
        elif self.estado.get("dormido") and not quiere:
            log.info("PRECARGA  cierro el Jarvis dormido (modo juego o precarga desactivada)")
            llamar_jarvis("/api/cerrar")
            self._ultimo_dormido = time.time()

    def _esperar_ventana(self):
        """Oculta el aviso «despertando» en cuanto la ventana de Jarvis está a la vista."""
        limite = time.time() + 60
        while time.time() < limite:
            estado = llamar_jarvis("/api/estado", metodo="GET", espera=0.5)
            if estado and estado.get("visible"):
                break
            if self.proceso_jarvis and self.proceso_jarvis.poll() is not None:
                self.notificar("Jarvis no ha podido arrancar. Mira datos\\jarvis.log para más detalles.")
                break
            time.sleep(0.25)
        time.sleep(0.4)
        self.aviso.ocultar()

    def avisar_que_te_oigo(self, desde_atajo=False):
        """Respuesta instantánea al oír «Jarvis» (< 0,5 s): pitido + Jarvis a la vista sin robar el foco.
        Si hay un Jarvis precargado, se muestra su ventana directamente; si no, el orbe «despertando»."""
        pitido()
        precalentar_modelo()  # el modelo empieza a cargar ya, mientras sigues hablando
        estado = estado_jarvis()
        if estado and estado.get("dormido"):
            if desde_atajo:
                user32.AllowSetForegroundWindow(-1)
            llamar_jarvis("/api/despertar", json.dumps({"mostrar": True, "activar": desde_atajo}).encode())
            self._desperte_dormido = not desde_atajo
            log.info("JARVIS  despertado (estaba precargado)")
        elif not self.modo_juego:
            self.aviso.mostrar("DESPERTANDO" if not estado else "TE ESCUCHO")

    def despertar(self, desde_atajo=False, ya_avisado=False):
        """Feedback instantáneo (si no se dio ya) y arranque de Jarvis si no estaba abierto."""
        if not ya_avisado:
            self.avisar_que_te_oigo(desde_atajo)
        self._desperte_dormido = False  # confirmado: ya no es una falsa alarma
        self.lanzar_jarvis(activar=desde_atajo)

    def abrir_desde_menu(self, *_):
        if jarvis_abierto():
            user32.AllowSetForegroundWindow(-1)
            llamar_jarvis("/api/mostrar", json.dumps({"escuchar": False}).encode())
        else:
            self.despertar(desde_atajo=True)

    def abrir_panel(self, *_):
        """Menú › Ajustes, escenas y pantallas: el panel aparte (sin enseñar el orbe)."""
        user32.AllowSetForegroundWindow(-1)
        if not jarvis_abierto():
            self.lanzar_jarvis(activar=False)
            limite = time.time() + 20
            while time.time() < limite and not estado_jarvis():
                time.sleep(0.2)
        llamar_jarvis("/api/panel", b"{}")

    def al_atajo(self):
        log.info("ATAJO  pulsado")
        if jarvis_despierto():
            user32.AllowSetForegroundWindow(-1)  # deja que Jarvis pase al frente (si no, Windows lo bloquea)
            llamar_jarvis("/api/alternar")
            return
        self.despertar(desde_atajo=True)
        # Graba lo que digas a continuación (aunque estés en modo juego) para pasárselo a Jarvis
        self.captura = {"audio": [], "silencio": 0.0, "fin": 1.0, "conf": 1.0, "forzar": True, "voz": False, "inicio": time.time()}
        if not self.microfono.abierto:
            self.microfono.abrir()

    def _enviar_frase(self, captura):
        audio = b"".join(captura["audio"])
        if captura["forzar"] and not captura["voz"]:
            audio = b""  # pulsaste el atajo pero no dijiste nada: Jarvis solo se abre y escucha
        log.info(f"FRASE  {len(audio) / 2 / FRECUENCIA:.1f}s de audio para Jarvis (confianza {captura['conf']:.2f})")
        datos = a_wav(audio)

        def entregar():
            limite = time.time() + 120  # la primera vez Jarvis tarda en cargar Whisper
            while time.time() < limite:
                r = llamar_jarvis(f"/api/audio?conf={captura['conf']:.2f}&forzar={int(captura['forzar'])}", datos, espera=3)
                if r is not None:
                    return
                time.sleep(0.5)
            log.warning("Jarvis no respondió a tiempo para recibir la frase")
        threading.Thread(target=entregar, daemon=True).start()

    # ---------------- escucha ----------------
    def _nuevo_reconocedor(self):
        import vosk
        if not hasattr(self, "_modelo_vosk"):
            vosk.SetLogLevel(-1)
            self._modelo_vosk = vosk.Model(str(preparar_modelo_ligero()))
        self.reconocedor = vosk.KaldiRecognizer(self._modelo_vosk, FRECUENCIA, json.dumps(PALABRAS, ensure_ascii=False))
        self.reconocedor.SetWords(True)
        self._muestras = 0

    def _liberar_reconocedor(self):
        import gc
        self.reconocedor = None
        if hasattr(self, "_modelo_vosk"):
            del self._modelo_vosk
        gc.collect()

    def _hilo_audio(self):
        historial = deque(maxlen=150)  # últimos 15 s de audio (para recuperar la frase desde «Jarvis»)
        ruido = 300.0
        while not self.salir_evento.is_set():
            try:
                datos = self.cola_audio.get(timeout=1)
            except queue.Empty:
                continue
            try:
                trozo = datos
                posicion = self._muestras
                self._muestras += len(trozo) // 2
                volumen = energia(trozo)
                historial.append((posicion, trozo, volumen))
                umbral_voz = max(ruido * 2.5, 350)
                if volumen < umbral_voz:
                    ruido = ruido * 0.98 + volumen * 0.02  # el ruido de fondo se adapta poco a poco

                # --- Grabando la frase para Jarvis ---
                if self.captura is not None:
                    c = self.captura
                    c["audio"].append(trozo)
                    if volumen >= umbral_voz:
                        c["voz"], c["silencio"] = True, 0.0
                    else:
                        c["silencio"] += 0.1
                    duracion = len(c["audio"]) * 0.1
                    sin_voz_al_principio = not c["voz"] and duracion > 6
                    if (c["voz"] and c["silencio"] >= c["fin"]) or sin_voz_al_principio or duracion > 15:
                        self.captura = None
                        self._enviar_frase(c)
                        if self.reconocedor is not None:
                            self._nuevo_reconocedor()  # reinicia el reconocedor (el modelo ya está cargado)
                        historial.clear()
                    continue

                if self.reconocedor is None:
                    continue
                if self.reconocedor.AcceptWaveform(datos):
                    palabras = json.loads(self.reconocedor.Result()).get("result", [])
                    umbral = float(cfg("vigilante.umbral_confianza", 0.6))
                    nombre = [p for p in palabras if p["word"] == "jarvis" and p["conf"] >= umbral]
                    avisado, self._aviso_parcial = self._aviso_parcial, False
                    if nombre:
                        # La frase empieza tras el último silencio real (≥ 0,8 s) antes del nombre:
                        # así en «Cierra Chrome, Jarvis» la orden que va ANTES del nombre también llega a Jarvis
                        inicio = int((min(p["start"] for p in palabras) - 0.35) * FRECUENCIA)
                        trozos = list(historial)
                        k = next((i for i, (p, _, _) in enumerate(trozos) if p + len(trozos[i][1]) // 2 > inicio), len(trozos))
                        callado = 0
                        while k > 0 and callado < 8:
                            k -= 1
                            callado = callado + 1 if trozos[k][2] < max(ruido * 2.5, 350) else 0
                        previo = [t for _, t, _ in trozos[k:]]
                        hay_mas = any(p["start"] > nombre[0]["end"] for p in palabras)
                        log.info(f"ACTIVACIÓN  «Jarvis» (confianza {nombre[0]['conf']:.2f})")
                        self.despertar(ya_avisado=avisado)
                        # Seguimos grabando hasta que termines de hablar: «Jarvis… abre YouTube»
                        self.captura = {"audio": previo, "silencio": 0.0, "fin": 0.25 if hay_mas else 1.3,
                                        "conf": nombre[0]["conf"], "forzar": False, "voz": True, "inicio": time.time()}
                    elif avisado:
                        self.aviso.ocultar()  # el aviso rápido fue una falsa alarma: lo quitamos sin hacer nada más
                        if self._desperte_dormido:
                            self._desperte_dormido = False
                            log.info("FALSA ALARMA  devuelvo a Jarvis a dormir")
                            llamar_jarvis("/api/falsa_alarma")
                elif not self._aviso_parcial:
                    # Resultado parcial: en cuanto aparece «jarvis» damos señal (pitido + orbe), sin esperar al final
                    if "jarvis" in json.loads(self.reconocedor.PartialResult()).get("partial", "").split():
                        self._aviso_parcial = True
                        self._oyendo_hasta = time.time() + 12  # el micro del vigilante sigue abierto hasta entregar la frase
                        threading.Thread(target=self.avisar_que_te_oigo, daemon=True).start()
            except Exception:
                log.exception("Error procesando audio")

    # ---------------- detección de juegos ----------------
    def _proceso_en_primer_plano(self, hwnd) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            bufer = ctypes.create_unicode_buffer(520)
            tam = wintypes.DWORD(520)
            if kernel32.QueryFullProcessImageNameW(h, 0, bufer, ctypes.byref(tam)):
                return Path(bufer.value).name.lower()
            return ""
        finally:
            kernel32.CloseHandle(h)

    def hay_juego(self) -> bool:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        proceso = self._proceso_en_primer_plano(hwnd)
        excluidos = {p.lower() for p in (cfg("modo_juego.excluir", []) or [])} | {"python.exe", "pythonw.exe", "explorer.exe"}
        if proceso in excluidos:
            return False
        if proceso in {p.lower() for p in (cfg("modo_juego.procesos", []) or [])}:
            return True
        estado = ctypes.c_int(0)
        shell32.SHQueryUserNotificationState(ctypes.byref(estado))
        if estado.value == 3:  # QUNS_RUNNING_D3D_FULL_SCREEN: juego en pantalla completa exclusiva
            return True
        # Ventana sin bordes que ocupa todo el monitor (juegos en "pantalla completa sin bordes")
        clase = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, clase, 64)
        if clase.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        ventana = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(ventana))
        monitor = user32.MonitorFromWindow(hwnd, 2)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(monitor, ctypes.byref(info))
        m = info.rcMonitor
        return (estado.value == 2 and ventana.left <= m.left and ventana.top <= m.top
                and ventana.right >= m.right and ventana.bottom >= m.bottom)

    # ---------------- bucle de mantenimiento (1 vez por segundo) ----------------
    def _hilo_control(self):
        vuelta = 0
        abierto_antes = False
        while not self.salir_evento.is_set():
            try:
                vuelta += 1
                if self.salir_evento.wait(1.0):
                    break
                # Recargar config.yaml si lo has cambiado
                try:
                    cambio = nucleo.RUTA_CONFIG.stat().st_mtime
                    if cambio != self._ultima_config:
                        if self._ultima_config:
                            nucleo.CONFIG.clear()
                            nucleo.CONFIG.update(nucleo._cargar_config())
                            log.info("CONFIG  recargada")
                        self._ultima_config = cambio
                except Exception as e:
                    log.warning(f"config.yaml no válido: {e}")

                # «Abrir» pedido por otra instancia (doble clic en iniciar_jarvis.bat)
                if kernel32.WaitForSingleObject(self.evento_abrir, 0) == 0:
                    self.abrir_desde_menu()

                # Modo juego (cada 3 s), con margen para no parpadear al hacer alt+tab un momento
                if vuelta % 3 == 0:
                    juego = self.hay_juego() if cfg("modo_juego.automatico", True) else False
                    antes = self.modo_juego
                    if juego:
                        self._negativos_juego = 0
                        self.juego_auto = True
                    else:
                        self._negativos_juego += 1
                        if self._negativos_juego >= 3:
                            self.juego_auto = False
                            if self.juego_forzado is False:
                                self.juego_forzado = None  # se acabó el juego que habías "ignorado"
                    if self.modo_juego != antes:
                        self._cambio_modo_juego()

                # Modo juego pedido por voz a Jarvis («activa el modo juego»)
                if kernel32.WaitForSingleObject(self.evento_juego_on, 0) == 0 and not self.modo_juego:
                    self.juego_forzado = True
                    self._cambio_modo_juego(manual=True)
                if kernel32.WaitForSingleObject(self.evento_juego_off, 0) == 0 and self.modo_juego:
                    self.juego_forzado = False
                    self._cambio_modo_juego(manual=True)

                # Estado de Jarvis: cerrado (None), dormido (precargado, sin modelos) o despierto
                self.estado = estado_jarvis()
                abierto = bool(self.estado) and not self.estado.get("dormido")
                if abierto != abierto_antes:
                    abierto_antes = abierto
                    self.actualizar_icono()
                    if not abierto:
                        log.info("JARVIS  cerrado o dormido; vuelvo a vigilar")
                self._gestionar_precarga()

                # ¿Debe estar abierto el micrófono del vigilante?
                quiere_micro = self.captura is not None or time.time() < self._oyendo_hasta or \
                    (not abierto and not self.pausado and not self.modo_juego)
                if quiere_micro and not self.microfono.abierto:
                    if self.microfono.abrir():
                        self._nuevo_reconocedor()
                        log.info(f"MICRÓFONO  abierto: {self.microfono.nombre}")
                        if self._avisado_micro:
                            self.notificar(f"Micrófono reconectado ({self.microfono.nombre}). Vuelvo a escucharte.")
                            self._avisado_micro = False
                    elif not self._avisado_micro:
                        self._avisado_micro = True
                        self.notificar("No encuentro el micrófono. Conéctalo y volveré a escuchar solo; "
                                       f"mientras, usa {cfg('vigilante.atajo', 'ctrl+alt+j')}.")
                elif not quiere_micro and self.microfono.abierto:
                    self.microfono.cerrar()
                    self._liberar_reconocedor()  # en modo juego o con Jarvis abierto, ni el modelo ocupa memoria
                elif self.microfono.colgado():
                    log.warning("MICRÓFONO  sin audio (¿desenchufado?); reintentando")
                    self.microfono.cerrar()
                    if not self._avisado_micro:
                        self._avisado_micro = True
                        self.notificar("He perdido el micrófono. En cuanto vuelva, seguiré escuchando.")

                # Si la captura del atajo lleva demasiado (sin audio), la entregamos igualmente
                if self.captura and time.time() - self.captura["inicio"] > 20:
                    c, self.captura = self.captura, None
                    self._enviar_frase(c)

                # Briefing de la mañana (una vez al día)
                if vuelta % 60 == 5:
                    self._revisar_briefing()

                # Recordatorios guardados y rutinas programadas (cada 15 s)
                if vuelta % 15 == 7:
                    self._revisar_recordatorios()
            except Exception:
                log.exception("Error en el bucle de control")

    def _revisar_recordatorios(self):
        """Los dispara aunque Jarvis esté cerrado. En modo juego no te interrumpe la voz: aviso de Windows."""
        import recordatorios
        avisos, ordenes = recordatorios.pendientes_ahora()
        for texto in avisos:
            log.info(f"RECORDATORIO  {texto}")
            if self.modo_juego:
                self.notificar(f"Recordatorio: {texto}")
                continue
            self._asegurar_jarvis()
            llamar_jarvis("/api/aviso", json.dumps({"texto": f"Recordatorio: {texto}"}).encode(), espera=5)
        for orden in ordenes:
            if self.modo_juego:
                log.info(f"PROGRAMADA  «{orden}» no se hace: estás jugando")
                self.notificar(f"No he hecho «{orden}» porque estabas jugando.")
                continue
            log.info(f"PROGRAMADA  «{orden}»")
            self._asegurar_jarvis()
            llamar_jarvis("/api/orden", json.dumps({"texto": orden, "mostrar": True}).encode(), espera=5)

    def _asegurar_jarvis(self):
        """Que haya un Jarvis respondiendo (el dormido sirve: se despierta solo al recibir la orden)."""
        if estado_jarvis():
            return
        self.lanzar_jarvis(activar=False)
        limite = time.time() + 40
        while time.time() < limite and not estado_jarvis():
            time.sleep(0.5)

    def _cambio_modo_juego(self, manual: bool = False):
        activo = self.modo_juego
        log.info(f"MODO JUEGO  {'activado' if activo else 'desactivado'}{' (desde el menú)' if manual else ''}")
        llamar_jarvis("/api/escucha", json.dumps({"activa": not activo and not self.pausado}).encode())
        self.actualizar_icono()  # el icono se pone ámbar: así no hace falta molestarte con avisos en mitad de la partida
        if manual or cfg("modo_juego.notificar", False):
            self.notificar("Modo juego: dejo de escuchar. Llámame con el atajo de teclado." if activo
                           else "Modo juego desactivado: vuelvo a escuchar «Jarvis».")

    def _revisar_briefing(self):
        from datetime import datetime
        if not cfg("briefing.automatico", False) or self.modo_juego or self.pausado:
            return
        ahora = datetime.now()
        h, m = map(int, str(cfg("briefing.hora", "08:00")).split(":"))
        ruta = RAIZ / "datos" / "estado.json"
        try:
            estado = json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            estado = {}
        hoy = ahora.strftime("%Y-%m-%d")
        if (ahora.hour, ahora.minute) >= (h, m) and ahora.hour < 12 and estado.get("ultimo_briefing") != hoy:
            ruta.write_text(json.dumps({**estado, "ultimo_briefing": hoy}), encoding="utf-8")
            log.info("BRIEFING  automático")
            if jarvis_abierto():
                llamar_jarvis("/api/orden", json.dumps({"texto": "Buenos días. Dame el briefing de hoy."}).encode())
            else:
                self.lanzar_jarvis("--briefing")

    # ---------------- atajo (hilo con su propio bucle de mensajes de Windows) ----------------
    def _hilo_atajo(self):
        texto = cfg("vigilante.atajo", "ctrl+alt+j")
        try:
            mods, tecla = interpretar_atajo(texto)
        except ValueError as e:
            self.notificar(f"El atajo de config.yaml no es válido ({e}).")
            return
        if not user32.RegisterHotKey(None, 1, mods | 0x4000, tecla):  # MOD_NOREPEAT
            self.notificar(f"El atajo {texto} ya lo usa otra aplicación. Cámbialo en config.yaml (vigilante.atajo) "
                           "y reinicia el vigilante desde el icono de la bandeja.")
            return
        log.info(f"ATAJO  registrado: {texto}")
        mensaje = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0) > 0:
            if mensaje.message == 0x0312:  # WM_HOTKEY
                threading.Thread(target=self.al_atajo, daemon=True).start()
        user32.UnregisterHotKey(None, 1)

    # ---------------- menú de la bandeja ----------------
    def alternar_pausa(self, *_):
        self.pausado = not self.pausado
        log.info(f"PAUSA  {self.pausado}")
        llamar_jarvis("/api/escucha", json.dumps({"activa": not self.pausado and not self.modo_juego}).encode())
        self.actualizar_icono()

    def alternar_juego(self, *_):
        self.juego_forzado = not self.modo_juego
        self._cambio_modo_juego(manual=True)

    def alternar_inicio(self, *_):
        try:
            configurar_inicio_con_windows(not inicio_con_windows())
        except Exception as e:
            self.notificar(f"No pude cambiar el inicio con Windows: {e}")
        self.actualizar_icono()

    def reiniciar(self, *_):
        log.info("REINICIO  pedido desde el menú")
        llamar_jarvis("/api/cerrar")
        kernel32.CloseHandle(self.mutex)
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), str(RAIZ / "vigilante.py")],
                         cwd=str(RAIZ), creationflags=0x08000000)
        self.salir(cerrar_jarvis=False)

    def salir(self, *_, cerrar_jarvis=True):
        log.info("SALIR")
        if cerrar_jarvis:
            llamar_jarvis("/api/cerrar")
        self.salir_evento.set()
        self.microfono.cerrar()
        if self.icono:
            self.icono.stop()
        os._exit(0)

    # ---------------- arranque ----------------
    def ejecutar(self, abrir_al_iniciar=False):
        import pystray

        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)  # prioridad baja: nunca molesta a un juego
        _crear_pitido()
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Jarvis", self.abrir_desde_menu, default=True),
            pystray.MenuItem("Ajustes, escenas y pantallas", self.abrir_panel),
            pystray.MenuItem("Pausar escucha", self.alternar_pausa, checked=lambda _: self.pausado),
            pystray.MenuItem("Modo juego", self.alternar_juego, checked=lambda _: self.modo_juego),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Iniciar con Windows", self.alternar_inicio, checked=lambda _: inicio_con_windows()),
            pystray.MenuItem("Reiniciar", self.reiniciar),
            pystray.MenuItem("Salir", self.salir),
        )
        self.icono = pystray.Icon("jarvis", dibujar_icono("#00e5ff", False), "Jarvis", menu)

        def preparar(icono):
            icono.visible = True
            self.actualizar_icono()
            self.aviso.preparar()
            threading.Thread(target=self._hilo_audio, daemon=True, name="audio").start()
            threading.Thread(target=self._hilo_control, daemon=True, name="control").start()
            threading.Thread(target=self._hilo_atajo, daemon=True, name="atajo").start()
            log.info(f"VIGILANTE  en marcha (pid {os.getpid()})")
            if abrir_al_iniciar:
                self.abrir_desde_menu()

        self.icono.run(setup=preparar)


def dibujar_icono(color: str, jarvis_activo: bool):
    """Icono de la bandeja: hexágono con núcleo (cian = escuchando, ámbar = modo juego, gris = pausa)."""
    from PIL import Image, ImageDraw
    import math

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    puntos = [(32 + 28 * math.cos(math.radians(a)), 32 + 28 * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
    d.polygon(puntos, fill=(2, 10, 20, 255), outline=color, width=5)
    r = 12 if jarvis_activo else 9
    d.ellipse((32 - r, 32 - r, 32 + r, 32 + r), fill=color)
    return img


def main():
    vigilante = Vigilante()
    # Una sola instancia: si ya hay un vigilante, le pedimos que abra Jarvis y salimos
    vigilante.mutex = kernel32.CreateMutexW(None, False, "Local\\JarvisVigilante")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        evento = kernel32.OpenEventW(0x0002, False, "Local\\JarvisVigilanteAbrir")
        if evento and "--abrir" in sys.argv:
            kernel32.SetEvent(evento)
        return
    vigilante.evento_abrir = kernel32.CreateEventW(None, False, False, "Local\\JarvisVigilanteAbrir")
    # Jarvis nos pide entrar/salir del modo juego («activa el modo juego») con estos eventos de Windows
    vigilante.evento_juego_on = kernel32.CreateEventW(None, False, False, "Local\\JarvisModoJuegoOn")
    vigilante.evento_juego_off = kernel32.CreateEventW(None, False, False, "Local\\JarvisModoJuegoOff")
    vigilante.ejecutar(abrir_al_iniciar="--abrir" in sys.argv)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Error fatal del vigilante")
        ctypes.windll.user32.MessageBoxW(0, f"El vigilante de Jarvis se ha detenido:\n{e}\n\nDetalles en datos\\vigilante.log",
                                         "J.A.R.V.I.S.", 0x30)
