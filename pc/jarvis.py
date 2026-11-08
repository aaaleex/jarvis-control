"""
JARVIS — punto de entrada.
  python jarvis.py            -> Jarvis completo (interfaz + voz)
  python jarvis.py --voz      -> solo voz, sin interfaz (en la terminal)
  python jarvis.py --consola  -> chat por texto en la terminal (sin voz)
"""
import sys
import threading

# Con doble clic (pythonw) no hay consola: sys.stdout es None y algunas librerías fallan.
# Mandamos esa salida a un archivo para que todo funcione igual.
if sys.stdout is None or sys.stderr is None:
    from pathlib import Path
    (Path(__file__).resolve().parent / "datos").mkdir(exist_ok=True)
    _salida = open(Path(__file__).resolve().parent / "datos" / "salida_consola.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _salida
    sys.stderr = sys.stderr or _salida
    import faulthandler
    faulthandler.enable(file=_salida)  # si algo nativo revienta, queda la traza en datos/salida_consola.log

import nucleo
from nucleo import ErrorJarvis, emitir, log


class Asistente:
    """Une el cerebro, la voz y la interfaz. Todas las órdenes (voz, chat, móvil) pasan por procesar()."""

    def __init__(self, con_voz: bool = True):
        from cerebro import Cerebro

        self.cerebro = Cerebro()
        self.voz = None
        self._cerrojo = threading.Lock()
        self._confirmacion = None
        if con_voz:
            from voz import Voz

            self.voz = Voz(al_oir_orden=lambda texto: self.procesar(texto, origen="voz"))
            nucleo.confirmador = self.confirmar
        nucleo.suscribir(self._al_evento)
        self.precalentado = threading.Event()

        def precalentar():
            self.cerebro.precalentar()
            self.precalentado.set()
        threading.Thread(target=precalentar, daemon=True, name="precalentar").start()

    def iniciar_voz(self):
        if self.voz:
            return self.voz.iniciar()
        return False

    def iniciar_extras(self, con_briefing: bool = True):
        """Briefing automático, índice de Obsidian en segundo plano y Telegram (si está configurado).
        Si Jarvis lo abre el vigilante, el briefing lo programa el vigilante (con_briefing=False)."""
        import extras
        if con_briefing:
            extras.vigilar_briefing(self)
        try:
            import obsidian
            obsidian.vigilar_cambios()
        except Exception as e:
            log.warning(f"Obsidian no disponible: {e}")
        if extras.Telegram(self).iniciar():
            emitir("aviso_ui", texto="Telegram conectado: ya puedes darme órdenes desde el móvil.")

    # --------------------------------------------------------------
    def procesar(self, texto: str, origen: str = "texto") -> str:
        """Procesa una orden venga de donde venga. Si había otra en marcha, la corta."""
        texto = texto.strip()
        if not texto:
            return ""
        if self._cerrojo.locked():
            self.cerebro.cancelado = True
        if self.voz:
            self.voz.interrumpir()
        emitir("usuario", texto=texto, origen=origen)
        with self._cerrojo:
            hablar = self.voz is not None and self.voz.activa and \
                (origen == "voz" or nucleo.cfg("voz.responder_texto_en_voz", True))

            # 1) CAMINO RÁPIDO: órdenes comunes sin pasar por el modelo
            rapida = self._camino_rapido(texto)
            if rapida is not None:
                if hablar:
                    self.voz.decir(rapida)
                else:
                    emitir("estado", estado="reposo")
                return rapida

            # 2) El modelo, para lo ambiguo o conversacional
            def al_texto(trozo):
                emitir("texto_parcial", texto=trozo)   # la interfaz lo va escribiendo
                if hablar:
                    self.voz.decir_trozo(trozo)        # y la voz lo va diciendo frase a frase

            respuesta = self.cerebro.pensar(texto, al_texto=al_texto)
            if hablar:
                self.voz.terminar_respuesta()
            elif self.voz is None or not self.voz._hablando.is_set():
                emitir("estado", estado="reposo")
        return respuesta

    def _camino_rapido(self, texto: str):
        """Si la orden es simple (abrir, volumen, hora, escena...), la ejecuta con reglas y devuelve la respuesta.
        Si no está clara, devuelve None y la orden va al modelo."""
        import time
        import intenciones
        try:
            lista = intenciones.entender(texto)
        except Exception:
            log.exception("Fallo entendiendo la orden en el camino rápido")
            return None
        if not lista:
            return None
        inicio = time.time()
        textos = []
        for intencion in lista:
            emitir("herramienta_inicio", nombre=intencion.accion, argumentos=intencion.argumentos, rapido=True)
            t0 = time.time()
            try:
                resultado = intencion.ejecutar()
            except Exception as e:
                log.exception(f"Fallo en el camino rápido: {intencion}")
                resultado = None if not textos else f"No he podido con lo último: {e}"
            if resultado is None:  # p. ej. el clima sin internet: que lo intente el modelo
                emitir("herramienta_fin", nombre=intencion.accion, resultado="(paso al modelo)", ok=False)
                if not textos:
                    return None
                break
            emitir("herramienta_fin", nombre=intencion.accion, resultado=resultado, ok=True, rapido=True)
            log.info(f"RÁPIDO  {intencion} -> {resultado!r} [{(time.time() - t0) * 1000:.0f} ms]")
            textos.append(resultado)
        respuesta = " ".join(textos)
        log.info(f"USUARIO  {texto}")
        log.info(f"JARVIS  {respuesta}  (camino rápido, {(time.time() - inicio) * 1000:.0f} ms)")
        emitir("respuesta", texto=respuesta, rapido=True)
        self.cerebro.anotar(texto, respuesta)
        return respuesta

    def procesar_audio(self, audio, conf: float, forzar: bool):
        """Frase grabada por el vigilante. forzar=True si vino del atajo (no hace falta decir «Jarvis»)."""
        from voz import NOMBRE_JARVIS, PALABRAS_PARAR, limpiar_orden

        if not self.voz or not self.voz.whisper:
            emitir("error", texto="No puedo transcribir tu voz (el reconocimiento no está cargado). Escríbeme por el chat.")
            return
        texto = self.voz.transcribir(audio) if len(audio) > 1600 else ""
        if not texto:
            if forzar:
                self.voz.activar_manual()     # pulsaste el atajo y no dijiste nada: te escucho ahora
            return
        tiene_nombre = bool(NOMBRE_JARVIS.search(texto))
        if not (tiene_nombre or forzar or conf >= 0.9):
            # Vosk creyó oír «Jarvis» pero Whisper no lo confirma: no ejecuto nada raro
            log.info(f"ACTIVACIÓN DESCARTADA  {texto!r} (confianza {conf:.2f})")
            emitir("estado", estado="reposo")
            return
        orden = limpiar_orden(texto) if tiene_nombre else texto.strip()
        if not orden:
            self.voz.activar_manual()         # solo dijo «Jarvis»: ahora escucho la orden
        elif orden.lower().strip(" .,!¡¿?") not in PALABRAS_PARAR:
            self.procesar(orden, origen="voz")

    def decir(self, texto: str):
        emitir("respuesta", texto=texto)
        if self.voz:
            self.voz.decir(texto)

    # --------------------------------------------------------------
    #  Confirmaciones: por voz ("sí"/"no") o con los botones de la interfaz, lo que llegue antes
    # --------------------------------------------------------------
    def confirmar(self, pregunta: str) -> bool:
        self._confirmacion = {"evento": threading.Event(), "respuesta": False}
        emitir("confirmar", pregunta=pregunta)
        if self.voz and self.voz.activa:
            self.voz.decir(pregunta)
            threading.Thread(target=self._confirmar_por_voz, args=(self._confirmacion,), daemon=True).start()
        respondida = self._confirmacion["evento"].wait(30)
        emitir("confirmar_fin")
        return respondida and self._confirmacion["respuesta"]

    def _confirmar_por_voz(self, confirmacion):
        from voz import es_afirmativo

        texto = self.voz.escuchar_respuesta()
        if not confirmacion["evento"].is_set():
            confirmacion["respuesta"] = es_afirmativo(texto)
            confirmacion["evento"].set()

    def responder_confirmacion(self, si: bool):
        if self._confirmacion and not self._confirmacion["evento"].is_set():
            self._confirmacion["respuesta"] = si
            self._confirmacion["evento"].set()

    # --------------------------------------------------------------
    def _al_evento(self, tipo, datos):
        if tipo == "aviso":           # temporizadores, alarmas, recordatorios: los dice en alto
            if self.voz:
                self.voz.decir(datos["texto"])
        elif tipo == "decir":         # paso "decir" de una rutina
            self.decir(datos["texto"])
        elif tipo in ("memoria", "recalentar"):  # rehacemos la caché del modelo sin que tengas que esperar
            threading.Timer(3, self.cerebro.precalentar).start()
        elif tipo == "error" and self.voz is None:
            print(f"[!] {datos['texto']}")


# ==================================================================
#  MODOS DE ARRANQUE
# ==================================================================
def modo_consola():
    asistente = Asistente(con_voz=False)
    print("JARVIS en modo consola. Escribe 'salir' para terminar.\n")
    while True:
        try:
            texto = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texto.lower() in ("salir", "exit"):
            break
        if texto:
            print("Jarvis: ", end="", flush=True)
            asistente.cerebro.pensar(texto, al_texto=lambda t: print(t, end="", flush=True))
            print("\n")


def modo_voz():
    asistente = Asistente(con_voz=True)

    def mostrar(tipo, datos):
        if tipo == "usuario":
            print(f"\nTú: {datos['texto']}")
        elif tipo == "respuesta":
            print(f"Jarvis: {datos['texto']}")
        elif tipo in ("error", "cargando"):
            print(f"[{tipo}] {datos['texto']}")
        elif tipo == "estado":
            print(f"  ({datos['estado']})")
        elif tipo == "herramienta_inicio":
            print(f"  ⚙ {datos['nombre']} {datos['argumentos']}")

    nucleo.suscribir(mostrar)
    if not asistente.iniciar_voz():
        print("La voz no está disponible. Prueba: python jarvis.py --consola")
        return
    asistente.iniciar_extras()
    print("\nJARVIS escuchando. Di \"Jarvis\". Ctrl+C para salir.\n")
    asistente.decir("Sistemas en línea. A tu servicio.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        asistente.cerebro.liberar()


def mostrar_error(texto: str):
    """Muestra un error en una ventanita de Windows (funciona aunque no haya consola)."""
    log.error(texto)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, texto, "J.A.R.V.I.S.", 0x30)
    except Exception:
        print(f"[!] {texto}")


if __name__ == "__main__":
    try:
        if "--consola" in sys.argv:
            modo_consola()
        elif "--voz" in sys.argv:
            modo_voz()
        else:
            from interfaz import arrancar_interfaz
            arrancar_interfaz(Asistente)
    except ErrorJarvis as e:
        mostrar_error(str(e))
    except ModuleNotFoundError as e:
        mostrar_error(f"Falta una librería ({e.name}). Ejecuta instalar.bat para reinstalar las dependencias.")
    except Exception as e:
        log.exception("Error fatal")
        mostrar_error(f"Jarvis se ha detenido por un error inesperado:\n{e}\n\nTienes los detalles en datos\\jarvis.log")
