"""
Herramientas de Jarvis: funciones Python normales que el modelo puede decidir usar.

Para añadir una herramienta nueva:
  1. Escribe una función con tipos en los parámetros y un docstring (descripción + Args).
  2. Ponle encima @herramienta()  (o @herramienta(peligrosa=True, confirmacion="¿...?")).
Listo: el modelo la verá automáticamente.
"""
import ctypes
import difflib
import inspect
import json
import re
import subprocess
import threading
import time
import typing
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import psutil
import pyperclip
import requests

from nucleo import DATOS, avisar, cfg, confirmar, emitir, log, memoria_añadir, memoria_guardar, memoria_leer

# ==================================================================
#  REGISTRO DE HERRAMIENTAS
# ==================================================================
HERRAMIENTAS = {}  # nombre -> {"funcion", "peligrosa", "confirmacion", "esquema"}
_TIPOS = {str: "string", int: "integer", float: "number", bool: "boolean"}


def herramienta(peligrosa: bool = False, confirmacion: str = ""):
    """Decorador que registra una función como herramienta del modelo."""

    def decorar(funcion):
        HERRAMIENTAS[funcion.__name__] = {
            "funcion": funcion,
            "peligrosa": peligrosa,
            "confirmacion": confirmacion,
            "esquema": _esquema(funcion),
        }
        return funcion

    return decorar


def _esquema(funcion) -> dict:
    """Construye el esquema JSON de la herramienta a partir de la firma y el docstring."""
    doc = inspect.getdoc(funcion) or ""
    descripcion, _, seccion_args = doc.partition("Args:")
    descripciones = {}
    for linea in seccion_args.splitlines():
        m = re.match(r"\s*(\w+)\s*:\s*(.+)", linea)
        if m:
            descripciones[m.group(1)] = m.group(2).strip()

    propiedades, requeridos = {}, []
    pistas = typing.get_type_hints(funcion)
    for nombre, parametro in inspect.signature(funcion).parameters.items():
        tipo = pistas.get(nombre, str)
        if typing.get_origin(tipo) is typing.Literal:
            propiedad = {"type": "string", "enum": list(typing.get_args(tipo))}
        else:
            propiedad = {"type": _TIPOS.get(tipo, "string")}
        propiedad["description"] = descripciones.get(nombre, nombre)
        propiedades[nombre] = propiedad
        if parametro.default is inspect.Parameter.empty:
            requeridos.append(nombre)

    return {
        "name": funcion.__name__,
        "description": " ".join(descripcion.split()),
        "parameters": {"type": "object", "properties": propiedades, "required": requeridos},
    }


def _convertir(valor, tipo):
    """Los modelos pequeños a veces mandan '50' en vez de 50: lo corregimos."""
    try:
        if tipo is int:
            return int(float(valor))
        if tipo is float:
            return float(valor)
        if tipo is bool and isinstance(valor, str):
            return valor.strip().lower() in ("true", "1", "si", "sí", "yes")
    except (TypeError, ValueError):
        pass
    return valor


def ejecutar(nombre: str, argumentos: dict) -> str:
    """Ejecuta una herramienta por nombre. Siempre devuelve un texto (nunca lanza excepciones)."""
    info = HERRAMIENTAS.get(nombre)
    if not info:
        return f"Error: no existe la herramienta '{nombre}'."
    argumentos = dict(argumentos or {})
    pistas = typing.get_type_hints(info["funcion"])
    firma = inspect.signature(info["funcion"]).parameters
    argumentos = {k: _convertir(v, pistas.get(k, str)) for k, v in argumentos.items() if k in firma}

    texto_args = ", ".join(f"{k}={v!r}" for k, v in argumentos.items())
    emitir("herramienta_inicio", nombre=nombre, argumentos=argumentos)

    if info["peligrosa"]:
        try:
            pregunta = info["confirmacion"].format(**argumentos) if info["confirmacion"] else f"¿Ejecuto {nombre}({texto_args})?"
        except (KeyError, IndexError):
            pregunta = f"¿Ejecuto {nombre}({texto_args})?"
        if not confirmar(pregunta):
            log.info(f"CANCELADA  {nombre}({texto_args})")
            emitir("herramienta_fin", nombre=nombre, resultado="Cancelada por el usuario", ok=False)
            return "El usuario NO ha confirmado la acción. No se ha hecho nada."

    inicio = time.time()
    try:
        resultado = str(info["funcion"](**argumentos))
        ok = not resultado.startswith("Error")
    except Exception as e:
        resultado, ok = f"Error al ejecutar {nombre}: {e}", False
    log.info(f"HERRAMIENTA  {nombre}({texto_args}) -> {resultado[:300]!r} [{time.time() - inicio:.1f}s]")
    emitir("herramienta_fin", nombre=nombre, resultado=resultado[:500], ok=ok)
    return resultado


def esquemas_ollama() -> list:
    return [{"type": "function", "function": h["esquema"]} for h in HERRAMIENTAS.values()]


def esquemas_claude() -> list:
    return [{"name": h["esquema"]["name"], "description": h["esquema"]["description"],
             "input_schema": h["esquema"]["parameters"]} for h in HERRAMIENTAS.values()]


# ==================================================================
#  APLICACIONES Y WEBS
# ==================================================================
_apps_inicio = {}  # nombre en minúsculas -> AppID del menú Inicio
_SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW: que no parpadee una consola negra


def cargar_apps_inicio():
    """Lee todas las apps del menú Inicio (incluidas las de la Microsoft Store)."""
    global _apps_inicio
    cache = DATOS / "apps_inicio.json"
    try:
        salida = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=30, creationflags=_SIN_VENTANA,
        ).stdout
        lista = json.loads(salida)
        _apps_inicio = {a["Name"].lower(): a["AppID"] for a in lista}
        cache.write_text(json.dumps(_apps_inicio, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning(f"No pude leer las apps del menú Inicio: {e}")
        if cache.exists():
            _apps_inicio = json.loads(cache.read_text(encoding="utf-8"))


threading.Thread(target=cargar_apps_inicio, daemon=True).start()


def _buscar_app(nombre: str):
    """Devuelve (nombre_real, appid) de la app del menú Inicio que mejor encaja."""
    nombre = nombre.lower().strip()
    if not _apps_inicio:
        cargar_apps_inicio()
    if nombre in _apps_inicio:
        return nombre, _apps_inicio[nombre]
    candidatas = [n for n in _apps_inicio if n.startswith(nombre)] or [n for n in _apps_inicio if nombre in n]
    if candidatas:
        mejor = min(candidatas, key=len)
        return mejor, _apps_inicio[mejor]
    parecidas = difflib.get_close_matches(nombre, list(_apps_inicio), n=1, cutoff=0.6)
    if parecidas:
        return parecidas[0], _apps_inicio[parecidas[0]]
    return None, None


@herramienta()
def abrir_aplicacion(nombre: str, pantalla: str = "", tamano: str = "") -> str:
    """Abre una aplicación instalada (Spotify, VS Code, Discord...), opcionalmente en una pantalla concreta.

    Args:
        nombre: nombre de la aplicación, p. ej. "spotify"
        pantalla: "" (da igual), "1", "2", "3", "principal", "izquierda", "centro" o "derecha"
        tamano: "" , maximizar, mitad_izquierda, mitad_derecha o centrar
    """
    if pantalla or tamano:
        import ventanas
        return ventanas.abrir_en(nombre, pantalla or None, tamano or "maximizar", esperar=False)["texto"]
    import ventanas
    _, info = ventanas.resolver_app(nombre)
    if info and ventanas.esta_instalada(info):
        if ventanas.ventanas_de(info):
            return ventanas.traer(nombre)["texto"]
        if ventanas.lanzar(info):
            return f"Abriendo {info['nombre']}."
    alias = {k.lower(): v for k, v in (cfg("apps", {}) or {}).items()}
    objetivo = alias.get(nombre.lower().strip(), nombre)

    real, appid = _buscar_app(objetivo)
    if appid:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"])
        return f"Abriendo {real}."
    # Último recurso: comando o ruta directa (notepad, calc, C:\...\app.exe)
    if re.search(r'[&|<>^"%]', objetivo):
        return f"Error: nombre de aplicación no válido: {objetivo}"
    try:
        subprocess.Popen(f'start "" "{objetivo}"', shell=True, creationflags=_SIN_VENTANA)
        return f"Intentando abrir {objetivo}."
    except Exception:
        return f"Error: no encuentro ninguna aplicación llamada '{nombre}'."


def _ventanas_de(nombre: str) -> list:
    """Ventanas visibles cuyo título o proceso coincide con el nombre."""
    import win32gui
    import win32process

    nombre = nombre.lower().replace(".exe", "").strip()
    alias = {k.lower(): v for k, v in (cfg("apps", {}) or {}).items()}
    claves = {nombre, str(alias.get(nombre, nombre)).lower()}
    if nombre in ("vscode", "vs code", "visual studio code"):
        claves.add("code")
    encontradas = []

    def revisar(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return
        titulo = win32gui.GetWindowText(hwnd).lower()
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proceso = psutil.Process(pid).name().lower().replace(".exe", "")
        except Exception:
            proceso = ""
        if any(c == proceso or (len(c) > 3 and c in titulo) for c in claves):
            encontradas.append((hwnd, titulo, proceso))

    win32gui.EnumWindows(revisar, None)
    return encontradas


@herramienta()
def cerrar_aplicacion(nombre: str, forzar: bool = False) -> str:
    """Cierra una aplicación abierta de forma normal (como pulsar la X; si hay algo sin guardar, la app preguntará).

    Args:
        nombre: nombre de la aplicación o del proceso, por ejemplo "chrome", "spotify", "Code"
        forzar: true solo si el usuario pide cerrarla a la fuerza (puede perder datos sin guardar)
    """
    import win32con
    import win32gui

    if forzar:
        procesos = [p for p in psutil.process_iter(["name"]) if nombre.lower() in (p.info["name"] or "").lower()]
        if not procesos:
            return f"No encuentro ningún proceso llamado '{nombre}'."
        if not confirmar(f"¿Cierro a la fuerza {len(procesos)} proceso(s) de '{nombre}'? Puedes perder lo no guardado."):
            return "El usuario NO ha confirmado. No se ha cerrado nada."
        for p in procesos:
            p.kill()
        return f"He cerrado a la fuerza {nombre}."

    ventanas = _ventanas_de(nombre)
    if not ventanas:
        return f"No veo ninguna ventana abierta de '{nombre}'."
    for hwnd, _, _ in ventanas:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return f"He pedido cerrar {len(ventanas)} ventana(s) de {nombre}."


@herramienta()
def abrir_web(destino: str, pantalla: str = "") -> str:
    """Abre una web (youtube, gmail... o una URL) en el navegador, opcionalmente en una pantalla concreta.

    Args:
        destino: nombre del sitio (p. ej. "youtube") o URL
        pantalla: "" (da igual), "1", "2", "3", "principal", "izquierda", "centro" o "derecha"
    """
    webs = {k.lower(): v for k, v in (cfg("webs", {}) or {}).items()}
    clave = destino.lower().strip()
    url = webs.get(clave) or webs.get(clave.replace(".com", ""))
    if not url:
        url = destino if destino.startswith("http") else (f"https://{destino}" if "." in destino else f"https://www.{clave}.com")
    if pantalla:
        import ventanas
        return ventanas.abrir_web_en(url, pantalla, "maximizar", esperar=False)["texto"]
    webbrowser.open(url)
    return f"Abierta {url}"


@herramienta()
def buscar_en_google(consulta: str) -> str:
    """Abre en el navegador una búsqueda de Google para que el usuario vea los resultados.

    Args:
        consulta: lo que hay que buscar
    """
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(consulta)}")
    return f"Búsqueda de Google abierta: {consulta}"


@herramienta()
def buscar_en_youtube(consulta: str) -> str:
    """Abre en el navegador una búsqueda en YouTube (canciones, vídeos, tutoriales).

    Args:
        consulta: lo que hay que buscar en YouTube
    """
    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(consulta)}")
    return f"Búsqueda de YouTube abierta: {consulta}"


@herramienta()
def buscar_web(consulta: str) -> str:
    """Busca en internet y DEVUELVE los resultados (título, enlace y resumen) para que tú los leas.
    Úsala para responder preguntas de actualidad o investigar algo.

    Args:
        consulta: lo que hay que buscar
    """
    from ddgs import DDGS

    try:
        resultados = DDGS().text(consulta, region="es-es", max_results=5)
    except Exception as e:
        return f"Error: la búsqueda falló ({e})."
    if not resultados:
        return "Sin resultados."
    return "\n".join(f"{i}. {r['title']} — {r['href']}\n   {r['body']}" for i, r in enumerate(resultados, 1))


@herramienta()
def leer_pagina_web(url: str) -> str:
    """Descarga una página web y devuelve su texto (para resumirla o investigar).

    Args:
        url: dirección completa de la página
    """
    from lxml import html as lxml_html

    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
    except Exception as e:
        return f"Error: no pude descargar la página ({e})."
    arbol = lxml_html.fromstring(r.content)
    for basura in arbol.xpath("//script|//style|//nav|//footer|//header|//noscript"):
        basura.drop_tree()
    texto = re.sub(r"\s+", " ", arbol.text_content()).strip()
    return texto[:6000] + ("…" if len(texto) > 6000 else "")


# ==================================================================
#  HORA, FECHA, TEMPORIZADORES Y ALARMAS
# ==================================================================
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_bonita(d: datetime = None) -> str:
    d = d or datetime.now()
    return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]} de {d.year}"


@herramienta()
def hora_y_fecha() -> str:
    """Devuelve la hora y la fecha actuales."""
    ahora = datetime.now()
    return f"Son las {ahora:%H:%M} del {fecha_bonita(ahora)}."


_temporizadores = {}  # id -> {"fin": datetime, "etiqueta": str, "timer": Timer}
_contador_temporizadores = 0


def _programar(segundos: float, mensaje: str, etiqueta: str) -> int:
    global _contador_temporizadores
    _contador_temporizadores += 1
    ident = _contador_temporizadores

    def sonar():
        _temporizadores.pop(ident, None)
        try:
            import winsound
            for _ in range(3):
                winsound.Beep(880, 250)
                time.sleep(0.1)
        except Exception:
            pass
        avisar(mensaje)

    t = threading.Timer(segundos, sonar)
    t.daemon = True
    t.start()
    _temporizadores[ident] = {"fin": datetime.now() + timedelta(seconds=segundos), "etiqueta": etiqueta, "timer": t}
    emitir("temporizadores", lista=listar_temporizadores())
    return ident


@herramienta()
def poner_temporizador(minutos: float, etiqueta: str = "") -> str:
    """Pone un temporizador. Cuando termine, Jarvis avisará en voz alta.

    Args:
        minutos: duración en minutos (puede tener decimales: 0.5 = 30 segundos)
        etiqueta: para qué es, por ejemplo "pasta" (opcional)
    """
    if minutos <= 0:
        return "Error: la duración debe ser mayor que cero."
    texto = f"temporizador de {etiqueta}" if etiqueta else "temporizador"
    ident = _programar(minutos * 60, f"Tu {texto} ha terminado.", etiqueta or "temporizador")
    return f"Temporizador {ident} de {minutos:g} minutos en marcha."


@herramienta()
def poner_alarma(hora: str, etiqueta: str = "") -> str:
    """Pone una alarma a una hora concreta de hoy (o de mañana si esa hora ya pasó).

    Args:
        hora: hora en formato HH:MM de 24 horas, por ejemplo "07:30" o "18:00"
        etiqueta: motivo de la alarma (opcional)
    """
    m = re.match(r"^\s*(\d{1,2})[:.h]?(\d{2})?\s*$", hora)
    if not m:
        return "Error: indica la hora en formato HH:MM."
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return "Error: hora no válida."
    ahora = datetime.now()
    objetivo = ahora.replace(hour=h, minute=mi, second=0, microsecond=0)
    if objetivo <= ahora:
        objetivo += timedelta(days=1)
    mensaje = f"Son las {h:02d}:{mi:02d}. " + (f"Alarma: {etiqueta}." if etiqueta else "Tu alarma.")
    ident = _programar((objetivo - ahora).total_seconds(), mensaje, etiqueta or f"alarma {h:02d}:{mi:02d}")
    cuando = "mañana" if objetivo.date() > ahora.date() else "hoy"
    return f"Alarma {ident} puesta para {cuando} a las {h:02d}:{mi:02d}."


@herramienta()
def listar_temporizadores() -> str:
    """Lista los temporizadores y alarmas activos con el tiempo que les queda."""
    if not _temporizadores:
        return "No hay temporizadores ni alarmas activos."
    lineas = []
    for ident, t in sorted(_temporizadores.items()):
        quedan = int((t["fin"] - datetime.now()).total_seconds())
        lineas.append(f"{ident}: {t['etiqueta']} — quedan {quedan // 60} min {quedan % 60} s (a las {t['fin']:%H:%M})")
    return "\n".join(lineas)


@herramienta()
def cancelar_temporizador(ident: int = 0) -> str:
    """Cancela un temporizador o alarma. Sin número, cancela todos.

    Args:
        ident: número del temporizador (0 = todos)
    """
    ids = list(_temporizadores) if ident == 0 else [ident]
    cancelados = 0
    for i in ids:
        t = _temporizadores.pop(i, None)
        if t:
            t["timer"].cancel()
            cancelados += 1
    emitir("temporizadores", lista=listar_temporizadores())
    return f"Cancelados {cancelados}." if cancelados else "No había nada que cancelar."


# ==================================================================
#  VOLUMEN Y MÚSICA
# ==================================================================
def _volumen_sistema():
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()  # necesario si se llama desde otro hilo
    return AudioUtilities.GetSpeakers().EndpointVolume


@herramienta()
def volumen(accion: typing.Literal["subir", "bajar", "fijar", "silenciar", "quitar_silencio", "consultar"],
            cantidad: int = 15) -> str:
    """Controla el volumen general del PC.

    Args:
        accion: subir, bajar, fijar (a un porcentaje exacto), silenciar, quitar_silencio o consultar
        cantidad: puntos a subir/bajar, o el porcentaje exacto si la acción es fijar (0-100)
    """
    vol = _volumen_sistema()
    actual = round(vol.GetMasterVolumeLevelScalar() * 100)
    if accion == "consultar":
        return f"El volumen está al {actual}%" + (" (silenciado)" if vol.GetMute() else "") + "."
    if accion == "silenciar":
        vol.SetMute(1, None)
        return "Sonido silenciado."
    if accion == "quitar_silencio":
        vol.SetMute(0, None)
        return f"Sonido activado, al {actual}%."
    nuevo = {"subir": actual + cantidad, "bajar": actual - cantidad}.get(accion, cantidad)
    nuevo = max(0, min(100, nuevo))
    vol.SetMute(0, None)
    vol.SetMasterVolumeLevelScalar(nuevo / 100, None)
    return f"Volumen del {actual}% al {nuevo}%."


_TECLAS_MULTIMEDIA = {"play_pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1, "parar": 0xB2}


@herramienta()
def controlar_musica(accion: typing.Literal["play_pausa", "siguiente", "anterior", "parar"]) -> str:
    """Controla la música o el vídeo que esté sonando (Spotify, YouTube...) con las teclas multimedia.

    Args:
        accion: play_pausa (reanudar o pausar), siguiente, anterior o parar
    """
    tecla = _TECLAS_MULTIMEDIA[accion]
    ctypes.windll.user32.keybd_event(tecla, 0, 1, 0)      # pulsar
    ctypes.windll.user32.keybd_event(tecla, 0, 1 | 2, 0)  # soltar
    return {"play_pausa": "Hecho: play/pausa.", "siguiente": "Siguiente pista.",
            "anterior": "Pista anterior.", "parar": "Música parada."}[accion]


# ==================================================================
#  PANTALLA Y PORTAPAPELES
# ==================================================================
def carpeta_permitida() -> Path:
    base = Path(cfg("seguridad.carpeta_permitida", str(Path.home() / "Documents" / "Jarvis"))).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def hacer_captura() -> Path:
    import mss
    import mss.tools

    carpeta = carpeta_permitida() / "capturas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"captura_{datetime.now():%Y%m%d_%H%M%S}.png"
    with mss.mss() as sct:
        imagen = sct.grab(_monitor_activo(sct.monitors))
        mss.tools.to_png(imagen.rgb, imagen.size, output=str(ruta))
    return ruta


def _monitor_activo(monitores: list) -> dict:
    """La pantalla donde está la ventana que estás usando (si tienes varias)."""
    try:
        import win32gui
        izq, arr, der, aba = win32gui.GetWindowRect(win32gui.GetForegroundWindow())
        cx, cy = (izq + der) // 2, (arr + aba) // 2
        for m in monitores[1:]:
            if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
                return m
    except Exception:
        pass
    return monitores[1]  # pantalla principal


def captura_es_negra(ruta: Path) -> bool:
    from PIL import Image
    return Image.open(ruta).convert("L").getextrema()[1] < 8


@herramienta()
def captura_de_pantalla() -> str:
    """Hace una captura de la pantalla principal y la guarda en la carpeta de Jarvis."""
    return f"Captura guardada en {hacer_captura()}"


@herramienta()
def leer_portapapeles() -> str:
    """Devuelve el texto que hay copiado en el portapapeles."""
    texto = pyperclip.paste()
    return texto[:4000] if texto else "El portapapeles está vacío (o no contiene texto)."


@herramienta()
def copiar_al_portapapeles(texto: str) -> str:
    """Copia un texto al portapapeles para que el usuario pueda pegarlo con Ctrl+V.

    Args:
        texto: el texto a copiar
    """
    pyperclip.copy(texto)
    return "Copiado al portapapeles."


# ==================================================================
#  ARCHIVOS (solo dentro de la carpeta permitida)
# ==================================================================
def ruta_segura(nombre: str) -> Path:
    """Convierte un nombre en ruta y comprueba que NO se sale de la carpeta permitida."""
    base = carpeta_permitida()
    ruta = (base / nombre.strip().strip("/\\")).resolve()
    if ruta != base and base not in ruta.parents:
        raise PermissionError(f"'{nombre}' está fuera de la carpeta permitida ({base}).")
    return ruta


@herramienta()
def listar_archivos(subcarpeta: str = "") -> str:
    """Lista los archivos y carpetas dentro de la carpeta de trabajo de Jarvis.

    Args:
        subcarpeta: subcarpeta a listar ("" = la carpeta principal)
    """
    ruta = ruta_segura(subcarpeta)
    if not ruta.is_dir():
        return f"Error: no existe la carpeta '{subcarpeta}'."
    elementos = sorted(ruta.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    if not elementos:
        return f"La carpeta {ruta} está vacía."
    return f"Contenido de {ruta}:\n" + "\n".join(
        f"[carpeta] {p.name}" if p.is_dir() else f"{p.name} ({p.stat().st_size} bytes)" for p in elementos[:100])


@herramienta()
def leer_archivo(nombre: str) -> str:
    """Lee un archivo de texto de la carpeta de trabajo de Jarvis.

    Args:
        nombre: nombre o ruta relativa del archivo, por ejemplo "apuntes.txt"
    """
    ruta = ruta_segura(nombre)
    if not ruta.is_file():
        return f"Error: no existe el archivo '{nombre}'."
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    return texto[:8000] + ("\n…(recortado)" if len(texto) > 8000 else "")


@herramienta()
def crear_archivo(nombre: str, contenido: str, al_final: bool = False) -> str:
    """Crea un archivo de texto en la carpeta de trabajo de Jarvis (o añade texto al final de uno existente).

    Args:
        nombre: nombre del archivo, por ejemplo "lista_compra.txt"
        contenido: texto que se guardará
        al_final: true para añadir al final de un archivo existente en vez de crearlo
    """
    ruta = ruta_segura(nombre)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if al_final:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(("\n" if ruta.exists() and ruta.stat().st_size else "") + contenido)
        return f"Texto añadido a {ruta}"
    if ruta.exists() and not confirmar(f"El archivo '{nombre}' ya existe. ¿Lo sobrescribo?"):
        return "El usuario NO quiere sobrescribirlo. No se ha cambiado nada."
    ruta.write_text(contenido, encoding="utf-8")
    return f"Archivo guardado en {ruta}"


@herramienta(peligrosa=True, confirmacion="¿Borro el archivo '{nombre}'? No se puede deshacer.")
def borrar_archivo(nombre: str) -> str:
    """Borra un archivo de la carpeta de trabajo de Jarvis (pide confirmación).

    Args:
        nombre: nombre o ruta relativa del archivo
    """
    ruta = ruta_segura(nombre)
    if not ruta.is_file():
        return f"Error: no existe el archivo '{nombre}'."
    ruta.unlink()
    return f"Archivo {nombre} borrado."


# ==================================================================
#  CLIMA (Open-Meteo: gratis y sin clave)
# ==================================================================
_CODIGOS_CLIMA = {
    0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado", 45: "niebla", 48: "niebla helada",
    51: "llovizna débil", 53: "llovizna", 55: "llovizna intensa", 61: "lluvia débil", 63: "lluvia", 65: "lluvia fuerte",
    66: "lluvia helada", 67: "lluvia helada fuerte", 71: "nieve débil", 73: "nieve", 75: "nieve fuerte", 77: "granizo fino",
    80: "chubascos débiles", 81: "chubascos", 82: "chubascos fuertes", 85: "chubascos de nieve", 86: "nevadas fuertes",
    95: "tormenta", 96: "tormenta con granizo", 99: "tormenta fuerte con granizo",
}


def datos_clima(ciudad: str = "", dias: int = 1) -> dict:
    ciudad = ciudad or cfg("usuario.ciudad", "Madrid")
    geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": ciudad, "count": 1, "language": "es"}, timeout=10).json()
    if not geo.get("results"):
        raise ValueError(f"No encuentro la ciudad '{ciudad}'")
    lugar = geo["results"][0]
    datos = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lugar["latitude"], "longitude": lugar["longitude"], "timezone": "auto",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": max(1, min(7, dias)),
    }, timeout=10).json()
    datos["lugar"] = lugar["name"]
    return datos


@herramienta()
def clima(ciudad: str = "", dias: int = 1) -> str:
    """Da el tiempo actual y la previsión. Sin ciudad, usa la del usuario.
    IMPORTANTE: para saber el tiempo de mañana pide dias=2; para el fin de semana o la semana, dias=7.

    Args:
        ciudad: ciudad a consultar ("" = la ciudad del usuario)
        dias: días de previsión contando hoy, de 1 a 7 (1 = solo hoy, 2 = hoy y mañana)
    """
    try:
        d = datos_clima(ciudad, dias)
    except Exception as e:
        return f"Error: no pude consultar el clima ({e})."
    a = d["current"]
    texto = (f"En {d['lugar']} ahora: {_CODIGOS_CLIMA.get(a['weather_code'], 'variable')}, {a['temperature_2m']:.0f} °C "
             f"(sensación {a['apparent_temperature']:.0f} °C), humedad {a['relative_humidity_2m']}%, "
             f"viento {a['wind_speed_10m']:.0f} km/h.")
    dd = d["daily"]
    for i, fecha in enumerate(dd["time"]):
        dia = "Hoy" if i == 0 else fecha_bonita(datetime.fromisoformat(fecha)).rsplit(" de ", 1)[0]
        texto += (f"\n{dia}: {_CODIGOS_CLIMA.get(dd['weather_code'][i], 'variable')}, "
                  f"{dd['temperature_2m_min'][i]:.0f}–{dd['temperature_2m_max'][i]:.0f} °C, "
                  f"probabilidad de lluvia {dd['precipitation_probability_max'][i]}%.")
    return texto


# ==================================================================
#  MEMORIA
# ==================================================================
@herramienta()
def recordar(dato: str) -> str:
    """Guarda en la memoria permanente un dato o preferencia del usuario para tenerlo en cuenta siempre.
    Úsala cuando el usuario diga "recuerda que...", o cuente algo personal importante.

    Args:
        dato: el dato en una frase clara, por ejemplo "Su comida favorita es la paella"
    """
    memoria_añadir(dato)
    emitir("memoria")
    return f"Guardado en memoria: {dato}"


@herramienta()
def olvidar(dato: str) -> str:
    """Borra de la memoria permanente los datos que coincidan con el texto indicado.

    Args:
        dato: palabra o frase del dato a olvidar
    """
    memoria = memoria_leer()
    quedan = [m for m in memoria if dato.lower() not in m["dato"].lower()]
    if len(quedan) == len(memoria):
        return f"No tenía nada guardado sobre '{dato}'."
    memoria_guardar(quedan)
    emitir("memoria")
    return f"Olvidado ({len(memoria) - len(quedan)} dato(s))."


# ==================================================================
#  SISTEMA (peligrosas: siempre piden confirmación)
# ==================================================================
@herramienta(peligrosa=True, confirmacion="¿Ejecuto este comando en PowerShell?: {comando}")
def ejecutar_comando(comando: str) -> str:
    """Ejecuta un comando de PowerShell en el PC y devuelve su salida. Úsala solo si ninguna otra herramienta sirve.

    Args:
        comando: el comando de PowerShell
    """
    r = subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, creationflags=_SIN_VENTANA)
    salida = (r.stdout + r.stderr).strip() or "(sin salida)"
    return salida[:3000]


@herramienta(peligrosa=True, confirmacion="¿Seguro que quieres {accion} el equipo?")
def energia_equipo(accion: typing.Literal["apagar", "reiniciar", "suspender", "cerrar_sesion"]) -> str:
    """Apaga, reinicia, suspende el PC o cierra la sesión (pide confirmación).

    Args:
        accion: apagar, reiniciar, suspender o cerrar_sesion
    """
    if accion == "apagar":
        subprocess.run(["shutdown", "/s", "/t", "30"], creationflags=_SIN_VENTANA)
        return "El equipo se apagará en 30 segundos (para cancelarlo: shutdown /a)."
    if accion == "reiniciar":
        subprocess.run(["shutdown", "/r", "/t", "30"], creationflags=_SIN_VENTANA)
        return "El equipo se reiniciará en 30 segundos (para cancelarlo: shutdown /a)."
    if accion == "suspender":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Suspendiendo."
    subprocess.run(["shutdown", "/l"], creationflags=_SIN_VENTANA)
    return "Cerrando sesión."


@herramienta()
def bloquear_equipo() -> str:
    """Bloquea la sesión de Windows (pantalla de bloqueo)."""
    ctypes.windll.user32.LockWorkStation()
    return "Equipo bloqueado."


@herramienta()
def estado_del_sistema() -> str:
    """Devuelve el uso de CPU, RAM, disco, batería y GPU del PC."""
    texto = (f"CPU {psutil.cpu_percent(interval=0.5):.0f}%, RAM {psutil.virtual_memory().percent:.0f}% "
             f"({psutil.virtual_memory().used / 2**30:.1f} de {psutil.virtual_memory().total / 2**30:.1f} GB), "
             f"disco C: {psutil.disk_usage('C:/').percent:.0f}% lleno.")
    gpu = datos_gpu()
    if gpu:
        texto += f" GPU {gpu['uso']}%, VRAM {gpu['vram_usada']:.1f} de {gpu['vram_total']:.1f} GB, {gpu['temp']} °C."
    return texto


def datos_gpu():
    """Uso de la GPU NVIDIA (None si no hay)."""
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8, creationflags=_SIN_VENTANA,
        ).stdout.strip().split(",")
        n = [float(x) for x in salida]  # algunos drivers dan decimales ("67.10")
        return {"uso": round(n[0]), "vram_usada": n[1] / 1024, "vram_total": n[2] / 1024, "temp": round(n[3])}
    except Exception:
        return None
