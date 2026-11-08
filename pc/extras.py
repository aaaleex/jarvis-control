"""
Fase 5 — Inteligencia extra:
  1. Briefing de la mañana (y automático a la hora que digas)
  2. Ver la pantalla con un modelo de visión
  3. Rutinas personalizadas (modo estudio, modo descanso...)
  4. Control del PC: escribir texto, atajos de teclado, mover ventanas
  5. Control desde el móvil por Telegram (opcional)
"""
import base64
import io
import json
import re
import threading
import time
import typing
from datetime import datetime

import requests

import herramientas
from herramientas import herramienta
from nucleo import DATOS, cfg, emitir, log


# ==================================================================
#  1. BRIEFING
# ==================================================================
@herramienta()
def briefing_del_dia() -> str:
    """Reúne todo para el briefing de la mañana o para "¿qué tengo hoy?": fecha, tiempo, nota diaria,
    tareas pendientes, Inbox y alarmas. Resúmelo de forma natural y breve, como un mayordomo."""
    partes = [herramientas.hora_y_fecha(), herramientas.clima("", 2)]
    try:
        import obsidian
        partes.append(obsidian.leer_nota_diaria("hoy"))
        partes.append(obsidian.tareas_pendientes())
    except Exception as e:
        partes.append(f"(Obsidian no disponible: {e})")
    partes.append(herramientas.listar_temporizadores())
    return "\n\n".join(partes)


# ==================================================================
#  2. VER LA PANTALLA
# ==================================================================
def _imagen_pantalla_base64(ancho_max: int = 1280) -> str:
    from PIL import Image

    ruta = herramientas.hacer_captura()
    if herramientas.captura_es_negra(ruta):
        raise ValueError("la captura ha salido negra. Suele pasar con juegos a pantalla completa o vídeos "
                         "protegidos: pon la ventana en modo ventana o sin bordes y vuelve a intentarlo")
    imagen = Image.open(ruta)
    if imagen.width > ancho_max:
        imagen = imagen.resize((ancho_max, int(imagen.height * ancho_max / imagen.width)))
    bufer = io.BytesIO()
    imagen.convert("RGB").save(bufer, format="JPEG", quality=85)
    return base64.b64encode(bufer.getvalue()).decode()


@herramienta()
def mirar_pantalla(pregunta: str = "Describe qué hay en la pantalla") -> str:
    """Hace una captura de la pantalla y la analiza con un modelo de visión. Úsala cuando el usuario diga
    "mira mi pantalla", "¿qué ves?", "ayúdame con este error", "¿qué pone aquí?".

    Args:
        pregunta: qué quiere saber el usuario sobre lo que hay en pantalla
    """
    try:
        imagen = _imagen_pantalla_base64()
    except ValueError as e:
        return f"Error: {e}."
    instruccion = (f"{pregunta}\nResponde en español, de forma concreta. Si hay un error o código, "
                   "explica qué pasa y cómo arreglarlo.")
    if cfg("cerebro.proveedor") == "claude" and (cfg("cerebro.claude.api_key") or __import__("os").environ.get("ANTHROPIC_API_KEY")):
        import anthropic
        cliente = anthropic.Anthropic(api_key=cfg("cerebro.claude.api_key") or None)
        r = cliente.messages.create(
            model=cfg("cerebro.claude.modelo", "claude-opus-5-5"), max_tokens=2000,
            output_config={"effort": cfg("cerebro.claude.esfuerzo", "low")},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": imagen}},
                {"type": "text", "text": instruccion}]}])
        return "Lo que veo en tu pantalla: " + "".join(b.text for b in r.content if b.type == "text")

    import ollama
    modelo = cfg("cerebro.ollama.modelo_vision", "qwen2.5vl:3b")
    try:
        r = ollama.Client(host=cfg("cerebro.ollama.url")).chat(
            model=modelo, messages=[{"role": "user", "content": instruccion, "images": [imagen]}],
            options={"num_ctx": 4096, "num_predict": 400}, keep_alive="2m")
    except Exception as e:
        if "not found" in str(e).lower():
            return f"Error: falta el modelo de visión. Ejecuta: ollama pull {modelo}"
        return f"Error: el modelo de visión falló ({e})."
    finally:
        emitir("recalentar")  # el modelo de visión desplaza al de chat en la VRAM: lo volvemos a dejar listo
    return "Lo que veo en tu pantalla: " + r.message.content.strip()


# ==================================================================
#  3. RUTINAS
# ==================================================================
@herramienta()
def decir(texto: str) -> str:
    """Dice un texto en voz alta tal cual (útil dentro de rutinas).

    Args:
        texto: lo que hay que decir
    """
    emitir("decir", texto=texto)
    return "Dicho."


@herramienta()
def ejecutar_rutina(nombre: str) -> str:
    """Ejecuta una rutina guardada en config.yaml (por ejemplo "estudio" o "descanso"): una lista de acciones seguidas.
    Úsala para "modo estudio", "activa la rutina X", "modo descanso".

    Args:
        nombre: nombre de la rutina, por ejemplo "estudio"
    """
    rutinas = {str(k).lower(): v for k, v in (cfg("rutinas", {}) or {}).items()}
    clave = nombre.lower().replace("modo ", "").replace("rutina ", "").strip()
    if clave not in rutinas:
        return f"No existe la rutina '{nombre}'. Rutinas disponibles: {', '.join(rutinas) or 'ninguna'}."
    resultados = []
    for paso in rutinas[clave] or []:
        for herramienta_paso, argumentos in dict(paso).items():
            resultados.append(f"{herramienta_paso}: {herramientas.ejecutar(herramienta_paso, dict(argumentos or {}))}")
            time.sleep(0.6)  # da tiempo a que cada app abra
    log.info(f"RUTINA  {clave} ({len(resultados)} pasos)")
    return f"Rutina '{clave}' completada:\n" + "\n".join(resultados)


# ==================================================================
#  4. CONTROL DEL PC: teclado y ventanas
# ==================================================================
@herramienta()
def escribir_texto(texto: str) -> str:
    """Escribe un texto en la aplicación que esté activa, como si lo tecleara el usuario (en el campo donde esté el cursor).

    Args:
        texto: el texto a escribir
    """
    import keyboard
    time.sleep(0.4)
    keyboard.write(texto, delay=0.005)
    return "Texto escrito."


@herramienta()
def pulsar_teclas(combinacion: str) -> str:
    """Pulsa una tecla o combinación en la aplicación activa, por ejemplo "ctrl+s", "alt+tab", "enter", "ctrl+shift+t".

    Args:
        combinacion: teclas en inglés unidas con +, por ejemplo "ctrl+c"
    """
    import keyboard
    prohibidas = {"ctrl+alt+delete", "ctrl+alt+supr"}
    if combinacion.lower().replace(" ", "") in prohibidas:
        return "Error: esa combinación no está permitida."
    keyboard.send(combinacion)
    return f"Pulsado {combinacion}."


# (Las ventanas y pantallas están ahora en ventanas.py: herramienta «ventana», abrir en pantalla, etc.)


# ==================================================================
#  5. PROACTIVIDAD: briefing automático por la mañana
# ==================================================================
RUTA_ESTADO = DATOS / "estado.json"


def _estado() -> dict:
    try:
        return json.loads(RUTA_ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def vigilar_briefing(asistente):
    """Si briefing.automatico está activo, da el briefing una vez al día a partir de la hora indicada
    (si a esa hora el PC estaba apagado, lo da en cuanto arrancas Jarvis, antes de mediodía)."""
    def bucle():
        while True:
            try:
                if cfg("briefing.automatico", False):
                    ahora = datetime.now()
                    h, m = map(int, str(cfg("briefing.hora", "08:00")).split(":"))
                    hoy = ahora.strftime("%Y-%m-%d")
                    hora_ok = (ahora.hour, ahora.minute) >= (h, m) and ahora.hour < 12
                    if hora_ok and _estado().get("ultimo_briefing") != hoy:
                        RUTA_ESTADO.write_text(json.dumps({**_estado(), "ultimo_briefing": hoy}), encoding="utf-8")
                        log.info("BRIEFING  automático")
                        asistente.procesar("Buenos días. Dame el briefing de hoy.", origen="sistema")
            except Exception as e:
                log.warning(f"Fallo en el briefing automático: {e}")
            time.sleep(60)
    threading.Thread(target=bucle, daemon=True, name="briefing").start()


# ==================================================================
#  6. TELEGRAM: controla Jarvis desde el móvil
# ==================================================================
class Telegram:
    """Bot de Telegram por 'long polling' (no hace falta abrir puertos). Solo obedece a los IDs permitidos."""

    def __init__(self, asistente):
        self.asistente = asistente
        self.token = str(cfg("telegram.token", "") or "").strip()
        self.permitidos = {int(u) for u in (cfg("telegram.usuarios_permitidos", []) or [])}
        self.url = f"https://api.telegram.org/bot{self.token}"
        self.chat_activo = None
        self.esperando_confirmacion = False

    def iniciar(self) -> bool:
        if not self.token:
            return False
        try:
            r = requests.get(f"{self.url}/getMe", timeout=10).json()
        except Exception as e:
            emitir("error", texto=f"No puedo conectar con Telegram: {e}")
            return False
        if not r.get("ok"):
            emitir("error", texto="El token de Telegram no es válido. Revisa telegram.token en config.yaml.")
            return False
        log.info(f"TELEGRAM  conectado como @{r['result']['username']}")
        from nucleo import suscribir
        suscribir(self._al_evento)
        threading.Thread(target=self._bucle, daemon=True, name="telegram").start()
        return True

    def enviar(self, chat_id, texto: str):
        try:
            requests.post(f"{self.url}/sendMessage", json={"chat_id": chat_id, "text": texto[:4000]}, timeout=15)
        except Exception as e:
            log.warning(f"Telegram: no pude enviar mensaje: {e}")

    def _al_evento(self, tipo, datos):
        # Si Jarvis pide confirmación mientras atiende una orden del móvil, la pregunta también llega al móvil
        if tipo == "confirmar" and self.chat_activo:
            self.esperando_confirmacion = True
            self.enviar(self.chat_activo, f"⚠️ {datos['pregunta']}\nResponde «sí» o «no».")
        elif tipo == "confirmar_fin":
            self.esperando_confirmacion = False

    def _bucle(self):
        desplazamiento = 0
        while True:
            try:
                r = requests.get(f"{self.url}/getUpdates", params={"timeout": 50, "offset": desplazamiento}, timeout=60).json()
                for actualizacion in r.get("result", []):
                    desplazamiento = actualizacion["update_id"] + 1
                    mensaje = actualizacion.get("message") or {}
                    texto = (mensaje.get("text") or "").strip()
                    usuario = mensaje.get("from", {}).get("id")
                    chat = mensaje.get("chat", {}).get("id")
                    if not texto or not chat:
                        continue
                    if usuario not in self.permitidos:
                        log.warning(f"TELEGRAM  mensaje rechazado del usuario {usuario}")
                        self.enviar(chat, f"No estás autorizado. Tu ID es {usuario}: añádelo a telegram.usuarios_permitidos en config.yaml.")
                        continue
                    if self.esperando_confirmacion:
                        from voz import es_afirmativo
                        self.asistente.responder_confirmacion(es_afirmativo(texto))
                        continue
                    if texto == "/start":
                        self.enviar(chat, "A tu servicio. Escríbeme lo que necesites y lo haré en tu PC.")
                        continue
                    threading.Thread(target=self._atender, args=(chat, texto), daemon=True).start()
            except Exception as e:
                log.warning(f"Telegram: {e}")
                time.sleep(10)

    def _atender(self, chat, texto):
        self.chat_activo = chat
        try:
            respuesta = self.asistente.procesar(texto, origen="telegram")
            self.enviar(chat, respuesta or "Hecho.")
        finally:
            self.chat_activo = None
