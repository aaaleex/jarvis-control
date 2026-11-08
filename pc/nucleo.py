"""
Núcleo de Jarvis: configuración, log, eventos, memoria y confirmaciones.
Lo usan todos los demás módulos.
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from ruamel.yaml import YAML

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
DATOS.mkdir(exist_ok=True)

# ------------------------------------------------------------------
# Log legible: todo lo que hace Jarvis queda en datos/jarvis.log
# ------------------------------------------------------------------
log = logging.getLogger("jarvis")
if not log.handlers:
    log.setLevel(logging.INFO)
    _manejador = logging.FileHandler(DATOS / "jarvis.log", encoding="utf-8")
    _manejador.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(_manejador)


class ErrorJarvis(Exception):
    """Error con un mensaje en español pensado para mostrárselo al usuario."""


# ------------------------------------------------------------------
# Configuración (config.yaml). ruamel conserva los comentarios al guardar.
# ------------------------------------------------------------------
_yaml = YAML()
_yaml.preserve_quotes = True
RUTA_CONFIG = RAIZ / "config.yaml"


def _cargar_config():
    if not RUTA_CONFIG.exists():
        raise ErrorJarvis(f"No encuentro el archivo de configuración: {RUTA_CONFIG}")
    try:
        with open(RUTA_CONFIG, encoding="utf-8") as f:
            return _yaml.load(f) or {}
    except Exception as e:
        raise ErrorJarvis(f"El archivo config.yaml tiene un error de formato: {e}")


CONFIG = _cargar_config()


def cfg(ruta: str, defecto=None):
    """Lee un valor de la config con notación de puntos: cfg('voz.motor_tts')."""
    actual = CONFIG
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return defecto
        actual = actual[parte]
    return actual if actual is not None else defecto


def cambiar_cfg(ruta: str, valor):
    """Cambia un valor de la config y lo guarda en config.yaml (manteniendo comentarios)."""
    partes = ruta.split(".")
    actual = CONFIG
    for parte in partes[:-1]:
        actual = actual.setdefault(parte, {})
    actual[partes[-1]] = valor
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        _yaml.dump(CONFIG, f)
    log.info(f"CONFIG  {ruta} = {valor!r}")


# ------------------------------------------------------------------
# Eventos: la interfaz y la voz se suscriben para enterarse de todo
# (texto del usuario, respuestas, herramientas, estados...).
# ------------------------------------------------------------------
_suscriptores = []


def suscribir(funcion):
    _suscriptores.append(funcion)


def emitir(tipo: str, **datos):
    for funcion in list(_suscriptores):
        try:
            funcion(tipo, datos)
        except Exception as e:
            log.warning(f"Fallo en suscriptor de eventos ({tipo}): {e}")


# ------------------------------------------------------------------
# Confirmaciones de acciones peligrosas.
# Por defecto pregunta en la consola; la voz y la interfaz lo sustituyen.
# ------------------------------------------------------------------
def _confirmar_consola(pregunta: str) -> bool:
    try:
        return input(f"\n⚠  {pregunta} (s/n): ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except EOFError:
        return False


confirmador = _confirmar_consola


def confirmar(pregunta: str) -> bool:
    if not cfg("seguridad.pedir_confirmacion", True):
        return True
    respuesta = bool(confirmador(pregunta))
    log.info(f"CONFIRMACIÓN  '{pregunta}' -> {'SÍ' if respuesta else 'NO'}")
    return respuesta


def avisar(texto: str):
    """Aviso proactivo (temporizador, alarma, recordatorio). La voz lo dirá en alto."""
    log.info(f"AVISO  {texto}")
    emitir("aviso", texto=texto)


# ------------------------------------------------------------------
# Memoria a largo plazo: datos que le pides que recuerde.
# ------------------------------------------------------------------
RUTA_MEMORIA = DATOS / "memoria.json"
_cerrojo_memoria = threading.Lock()


def memoria_leer() -> list:
    if not RUTA_MEMORIA.exists():
        return []
    try:
        return json.loads(RUTA_MEMORIA.read_text(encoding="utf-8"))
    except Exception:
        log.warning("memoria.json estaba dañado; empiezo una memoria nueva")
        return []


def memoria_guardar(datos: list):
    with _cerrojo_memoria:
        RUTA_MEMORIA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def memoria_añadir(texto: str):
    datos = memoria_leer()
    datos.append({"dato": texto.strip(), "fecha": datetime.now().strftime("%Y-%m-%d")})
    memoria_guardar(datos)
