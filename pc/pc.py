"""
HERRAMIENTAS DEL PC (bloque 3): archivos, sistema, apps abiertas, portapapeles, texto en pantalla (OCR),
capturas, recordatorios persistentes, rutinas programadas y red.

Todas se registran para el modelo con @herramienta (categorías en cerebro.py) y las órdenes comunes tienen
camino rápido en intenciones.py. Todo lo que hacen queda en datos/jarvis.log (línea HERRAMIENTA o RÁPIDO).

Límites (a propósito):
  · Nada se borra. Mover un archivo y cerrar un proceso piden confirmación (voz «sí/no» o Intro/Esc).
  · Ejecutar un programa (.exe, .msi, .bat…) desde «abre el archivo» también pide confirmación.
  · No se tocan procesos del sistema ni de otros usuarios, ni el propio Jarvis.
  · Sin permisos de administrador, sin abrir puertos, sin leer contraseñas.
"""
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import time
import typing
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from herramientas import herramienta
from nucleo import DATOS, cfg, confirmar, log

_SIN_VENTANA = 0x08000000


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


# ==================================================================
#  ARCHIVOS
# ==================================================================
_CARPETAS_CONOCIDAS = {  # nombre que dices -> carpeta conocida de Windows (GUID de SHGetKnownFolderPath)
    "escritorio": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "documentos": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "descargas": "{374DE290-123F-4565-9164-39C4925E467B}", "imagenes": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "fotos": "{33E28130-4E1E-4676-835A-98395C3BC3BB}", "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "musica": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}
_TIPOS = {
    "pdf": {".pdf"}, "imagen": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm"}, "audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "documento": {".docx", ".doc", ".odt", ".txt", ".md", ".rtf", ".pdf"}, "word": {".docx", ".doc"},
    "excel": {".xlsx", ".xls", ".csv", ".ods"}, "presentacion": {".pptx", ".ppt", ".odp"},
    "comprimido": {".zip", ".rar", ".7z", ".tar", ".gz"}, "instalador": {".exe", ".msi"},
    "codigo": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".html", ".css", ".json", ".sql"},
}
_SINONIMOS_TIPO = {"foto": "imagen", "fotos": "imagen", "imagenes": "imagen", "captura": "imagen", "capturas": "imagen",
                   "videos": "video", "cancion": "audio", "canciones": "audio", "musica": "audio", "pdfs": "pdf",
                   "documentos": "documento", "texto": "documento", "hoja de calculo": "excel", "excels": "excel",
                   "zip": "comprimido", "zips": "comprimido", "programa": "instalador", "instaladores": "instalador",
                   "presentaciones": "presentacion", "powerpoint": "presentacion"}
_SALTAR = {"appdata", "node_modules", ".git", ".venv", "venv", "__pycache__", "$recycle.bin", ".cache", ".obsidian"}
_EJECUTABLES = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar", ".scr", ".com", ".reg"}
_ULTIMOS: list = []  # resultados de la última búsqueda (para «abre el segundo»)


def carpeta_conocida(nombre: str):
    """'descargas' -> Path real (aunque esté en OneDrive o en otra unidad)."""
    clave = _norm(nombre).strip()
    clave = {"imágenes": "imagenes", "música": "musica", "vídeos": "videos", "mis documentos": "documentos"}.get(clave, clave)
    guid = _CARPETAS_CONOCIDAS.get(clave)
    if not guid:
        return None
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(g))
    ruta = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ruta)) != 0:
        return None
    try:
        return Path(ruta.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ruta)


def _carpetas_busqueda(carpeta: str = ""):
    if carpeta:
        c = carpeta_conocida(carpeta)
        if c:
            return [c]
        p = Path(carpeta).expanduser()
        return [p] if p.is_dir() else []
    vistas, salida = set(), []
    for nombre in ("escritorio", "documentos", "descargas", "imagenes", "videos", "musica"):
        c = carpeta_conocida(nombre)
        if c and c.exists() and str(c).lower() not in vistas:
            vistas.add(str(c).lower())
            salida.append(c)
    return salida


def _cuando(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    hoy = datetime.now().date()
    if d.date() == hoy:
        return f"hoy {d:%H:%M}"
    if d.date() == hoy - timedelta(days=1):
        return f"ayer {d:%H:%M}"
    return f"{d:%d/%m/%Y}"


def _tamano(n: int) -> str:
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            return f"{n:.0f} {unidad}" if unidad == "B" else f"{n:.1f} {unidad}"
        n /= 1024


def _describir(lista, cuantos=8) -> str:
    lineas = []
    for i, p in enumerate(lista[:cuantos], 1):
        try:
            st = p.stat()
            extra = "carpeta" if p.is_dir() else _tamano(st.st_size)
            lineas.append(f"{i}. {p.name} ({extra}, {_cuando(st.st_mtime)}, en {p.parent.name})")
        except OSError:
            lineas.append(f"{i}. {p.name}")
    return "\n".join(lineas)


@herramienta()
def buscar_archivos(texto: str = "", tipo: str = "", dias: int = 0, carpeta: str = "") -> str:
    """Busca archivos y carpetas del usuario por nombre, tipo y fecha (escritorio, documentos, descargas, imágenes,
    vídeos y música). Después se puede abrir uno con abrir_archivo("1").

    Args:
        texto: palabras del nombre (vacío = cualquiera)
        tipo: pdf, imagen, video, audio, documento, word, excel, presentacion, comprimido, instalador, codigo (vacío = todos)
        dias: solo los modificados en los últimos N días (0 = sin límite)
        carpeta: escritorio, documentos, descargas, imagenes, videos, musica o una ruta (vacío = todas)
    """
    global _ULTIMOS
    tipo = _SINONIMOS_TIPO.get(_norm(tipo).strip(), _norm(tipo).strip())
    extensiones = _TIPOS.get(tipo)
    if tipo and not extensiones:
        extensiones = {"." + tipo.lstrip(".")}
    palabras = [w for w in re.split(r"[\s_\-.]+", _norm(texto)) if w and w not in ("el", "la", "los", "las", "de", "del", "un", "una", "mi")]
    limite_fecha = time.time() - dias * 86400 if dias else 0
    raices = _carpetas_busqueda(carpeta)
    if not raices:
        return f"No encuentro la carpeta «{carpeta}»."
    encontrados, inicio, mirados = [], time.time(), 0
    for raiz in raices:
        pila = [(raiz, 0)]
        while pila and time.time() - inicio < 6:
            actual, nivel = pila.pop()
            try:
                entradas = list(os.scandir(actual))
            except OSError:
                continue
            for e in entradas:
                mirados += 1
                nombre = _norm(e.name)
                if e.name.startswith((".", "~$")):
                    continue
                try:
                    es_dir = e.is_dir(follow_symlinks=False)
                    if es_dir:
                        if nombre in _SALTAR:
                            continue
                        if nivel < 7:
                            pila.append((e.path, nivel + 1))
                        if extensiones or not palabras:
                            continue
                    elif extensiones and os.path.splitext(nombre)[1] not in extensiones:
                        continue
                    if palabras and not all(w in nombre for w in palabras):
                        continue
                    mtime = e.stat(follow_symlinks=False).st_mtime
                    if limite_fecha and mtime < limite_fecha:
                        continue
                    encontrados.append((mtime, Path(e.path)))
                except OSError:
                    continue
    encontrados.sort(key=lambda x: x[0], reverse=True)
    _ULTIMOS = [p for _, p in encontrados[:20]]
    log.info(f"ARCHIVOS  búsqueda texto={texto!r} tipo={tipo!r} dias={dias} -> {len(encontrados)} ({mirados} entradas, {time.time() - inicio:.1f}s)")
    if not encontrados:
        return "No he encontrado nada con eso."
    total = f"He encontrado {len(encontrados)}" + (" (te digo los más recientes)" if len(encontrados) > 8 else "") + ":\n"
    return total + _describir(_ULTIMOS) + "\nDime «abre el 1», «abre la carpeta del 2»…"


_ORDINALES = {"primero": 1, "primer": 1, "1": 1, "uno": 1, "segundo": 2, "2": 2, "dos": 2, "tercero": 3, "tercer": 3,
              "3": 3, "tres": 3, "cuarto": 4, "4": 4, "cuatro": 4, "quinto": 5, "5": 5, "cinco": 5, "sexto": 6, "6": 6,
              "seis": 6, "septimo": 7, "7": 7, "siete": 7, "octavo": 8, "8": 8, "ocho": 8}


def _elegir(cual: str):
    """'1', 'el segundo', 'el último' o un nombre -> Path (de la última búsqueda, o buscando por nombre)."""
    c = _norm(cual).strip()
    c = re.sub(r"^(?:el|la|numero|n)\s+", "", c).strip()
    if c in ("ultimo", "ultima") and _ULTIMOS:
        return _ULTIMOS[0]  # el más reciente
    if c in _ORDINALES:
        i = _ORDINALES[c] - 1
        return _ULTIMOS[i] if i < len(_ULTIMOS) else None
    if not c:
        return None
    p = Path(cual).expanduser()
    if p.exists():
        return p
    buscar_archivos(cual)
    return _ULTIMOS[0] if _ULTIMOS else None


@herramienta()
def abrir_archivo(cual: str) -> str:
    """Abre un archivo con su programa: el número de la última búsqueda ("1", "segundo", "último") o un nombre.

    Args:
        cual: número de la lista de la última búsqueda o nombre del archivo
    """
    p = _elegir(cual)
    if not p:
        return "No sé qué archivo abrir. Búscalo antes («busca el pdf de la factura»)."
    if p.suffix.lower() in _EJECUTABLES and not confirmar(f"«{p.name}» es un programa. ¿Lo ejecuto?"):
        return "Vale, no lo ejecuto."
    os.startfile(str(p))
    log.info(f"ARCHIVOS  abierto {p}")
    return f"Abro {p.name}."


@herramienta()
def abrir_carpeta(cual: str) -> str:
    """Abre una carpeta en el Explorador: descargas, documentos, escritorio, imagenes, videos, musica, la de un
    resultado de la última búsqueda ("del 2") o una ruta.

    Args:
        cual: nombre de la carpeta, número de un resultado o ruta
    """
    c = carpeta_conocida(cual)
    if c:
        os.startfile(str(c))
        return f"Abro {c.name}."
    p = _elegir(cual)
    if not p:
        return "No sé qué carpeta abrir."
    if p.is_dir():
        os.startfile(str(p))
    else:
        subprocess.Popen(["explorer", "/select,", str(p)])  # la carpeta con el archivo seleccionado
    return f"Abro la carpeta de {p.name}."


@herramienta()
def descargas_recientes(cuantos: int = 5) -> str:
    """Lista lo último que has descargado (carpeta Descargas), lo más nuevo primero.

    Args:
        cuantos: cuántos archivos decir (1-15)
    """
    global _ULTIMOS
    d = carpeta_conocida("descargas")
    if not d or not d.exists():
        return "No encuentro tu carpeta de Descargas."
    archivos = sorted((p for p in d.iterdir() if not p.name.startswith((".", "~$")) and not p.name.endswith((".crdownload", ".part", ".tmp"))),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    _ULTIMOS = archivos[:20]
    if not archivos:
        return "La carpeta de Descargas está vacía."
    return "Lo último descargado:\n" + _describir(_ULTIMOS, max(1, min(15, int(cuantos))))


def _destino(destino: str):
    c = carpeta_conocida(destino)
    if c:
        return c
    p = Path(destino).expanduser()
    if p.is_dir():
        return p
    # «a la carpeta proyectos»: una carpeta con ese nombre dentro de las del usuario (la más reciente)
    buscar_archivos(destino)
    carpetas = [x for x in _ULTIMOS if x.is_dir()]
    return carpetas[0] if carpetas else None


def _copiar_o_mover(cual: str, destino: str, mover: bool) -> str:
    origen = _elegir(cual)
    if not origen or not origen.exists():
        return "No sé qué archivo es. Búscalo antes («busca el pdf de la factura»)."
    carpeta = _destino(destino)
    if not carpeta:
        return f"No encuentro la carpeta «{destino}». No he tocado nada."
    final = carpeta / origen.name
    if final.resolve() == origen.resolve():
        return f"{origen.name} ya está en {carpeta.name}."
    verbo = "Muevo" if mover else "Copio"
    if final.exists():
        if not confirmar(f"Ya hay un «{origen.name}» en {carpeta.name}. ¿Lo sobrescribo?"):
            return "Vale, no he tocado nada."
    elif mover and not confirmar(f"¿{verbo} «{origen.name}» a {carpeta}?"):
        return "Vale, no lo muevo."
    if mover:
        shutil.move(str(origen), str(final))
    elif origen.is_dir():
        shutil.copytree(str(origen), str(final), dirs_exist_ok=True)
    else:
        shutil.copy2(str(origen), str(final))
    log.info(f"ARCHIVOS  {verbo.lower()} {origen} -> {final}")
    return f"{'Movido' if mover else 'Copiado'}: {origen.name} a {carpeta.name}."


@herramienta()
def copiar_archivo(cual: str, destino: str) -> str:
    """Copia un archivo (o carpeta) a otra carpeta. Si ya existe allí, pregunta antes de sobrescribir.

    Args:
        cual: número de la última búsqueda ("1", "segundo") o nombre del archivo
        destino: descargas, documentos, escritorio, imagenes... o el nombre/ruta de una carpeta
    """
    return _copiar_o_mover(cual, destino, mover=False)


@herramienta()
def mover_archivo(cual: str, destino: str) -> str:
    """Mueve un archivo a otra carpeta (siempre pide confirmación; nunca borra).

    Args:
        cual: número de la última búsqueda ("1", "segundo") o nombre del archivo
        destino: descargas, documentos, escritorio, imagenes... o el nombre/ruta de una carpeta
    """
    return _copiar_o_mover(cual, destino, mover=True)


# ==================================================================
#  SISTEMA
# ==================================================================
@herramienta()
def discos() -> str:
    """Espacio libre de cada disco."""
    partes = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        partes.append(f"{p.device.rstrip(chr(92))} {u.free / 2**30:.0f} GB libres de {u.total / 2**30:.0f} ({u.percent:.0f}% lleno)")
    return "Discos: " + "; ".join(partes) + "." if partes else "No veo ningún disco."


@herramienta()
def bateria() -> str:
    """Nivel de batería y si está cargando."""
    b = psutil.sensors_battery()
    if b is None:
        return "Este PC no tiene batería (es un sobremesa o no la detecto)."
    estado = "cargando" if b.power_plugged else "sin cargador"
    resto = "" if b.power_plugged or b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else \
        f", quedan unas {b.secsleft // 3600} h {b.secsleft % 3600 // 60} min"
    return f"Batería al {b.percent:.0f}%, {estado}{resto}."


# Procesos que nunca se tocan (Windows se cuelga o se reinicia) y el propio Jarvis
_PROTEGIDOS = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
               "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe",
               "sihost.exe", "ctfmon.exe", "audiodg.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
               "spoolsv.exe", "memory compression", "secure system", "taskhostw.exe", "runtimebroker.exe",
               "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
               "conhost.exe", "dllhost.exe", "wudfhost.exe", "ollama.exe", "ollama app.exe"}


def _es_jarvis(p) -> bool:
    try:
        return p.pid == os.getpid() or any(x in " ".join(p.cmdline()).lower() for x in ("jarvis.py", "vigilante.py"))
    except Exception:
        return False


@herramienta()
def procesos_que_mas_consumen(por: typing.Literal["cpu", "ram"] = "cpu", cuantos: int = 5) -> str:
    """Los programas que más CPU o RAM están usando ahora (sumando todos sus procesos).

    Args:
        por: cpu o ram
        cuantos: cuántos decir (1-10)
    """
    grupos = {}
    procesos = list(psutil.process_iter(["name", "memory_info"]))
    if por == "cpu":
        for p in procesos:
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        time.sleep(0.8)
    nucleos = psutil.cpu_count() or 1
    for p in procesos:
        try:
            nombre = p.info["name"] or "?"
            if nombre.lower() in ("system idle process", "idle"):
                continue
            valor = p.cpu_percent(None) / nucleos if por == "cpu" else p.info["memory_info"].rss / 2**20
        except Exception:
            continue
        grupos[nombre] = grupos.get(nombre, 0) + valor
    top = sorted(grupos.items(), key=lambda x: x[1], reverse=True)[:max(1, min(10, int(cuantos)))]
    if por == "cpu":
        partes = [f"{n.removesuffix('.exe')} {v:.0f}%" for n, v in top]
        return f"Más CPU ahora mismo (total {psutil.cpu_percent():.0f}%): " + ", ".join(partes) + "."
    partes = [f"{n.removesuffix('.exe')} {v / 1024:.1f} GB" if v >= 1024 else f"{n.removesuffix('.exe')} {v:.0f} MB" for n, v in top]
    return f"Más RAM (en uso {psutil.virtual_memory().percent:.0f}%): " + ", ".join(partes) + "."


@herramienta()
def cerrar_proceso(nombre: str) -> str:
    """Cierra a la fuerza un programa por su nombre de proceso (p. ej. "chrome", "notepad"). Pide confirmación;
    nunca toca procesos del sistema ni el propio Jarvis. Para cerrar una app con normalidad usa cerrar_aplicacion.

    Args:
        nombre: nombre del proceso o del programa
    """
    buscado = _norm(nombre).strip().removesuffix(".exe")
    candidatos = []
    usuario = psutil.Process().username()
    for p in psutil.process_iter(["name", "username"]):
        try:
            n = (p.info["name"] or "").lower()
            if buscado and buscado in _norm(n).removesuffix(".exe") and p.info["username"] == usuario:
                candidatos.append(p)
        except Exception:
            continue
    if not candidatos:
        return f"No hay ningún proceso que se llame «{nombre}»."
    protegidos = {p.info["name"] for p in candidatos if (p.info["name"] or "").lower() in _PROTEGIDOS}
    candidatos = [p for p in candidatos if (p.info["name"] or "").lower() not in _PROTEGIDOS and not _es_jarvis(p)]
    if not candidatos:
        return f"{', '.join(protegidos) or nombre} es parte de Windows o de Jarvis: no lo cierro."
    nombres = sorted({p.info["name"] for p in candidatos})
    if not confirmar(f"¿Cierro a la fuerza {len(candidatos)} proceso{'s' if len(candidatos) > 1 else ''} de "
                     f"{', '.join(nombres)}? Lo que no esté guardado se pierde."):
        return "Vale, no lo cierro."
    for p in candidatos:
        try:
            p.terminate()
        except Exception:
            pass
    vivos = psutil.wait_procs(candidatos, timeout=3)[1]
    for p in vivos:
        try:
            p.kill()
        except Exception:
            pass
    log.info(f"PROCESOS  cerrados {len(candidatos)} de {nombres}")
    return f"Cerrado: {', '.join(n.removesuffix('.exe') for n in nombres)}."


def _sesiones_audio():
    import comtypes
    from pycaw.pycaw import AudioUtilities
    comtypes.CoInitialize()
    return [s for s in AudioUtilities.GetAllSessions() if s.Process]


@herramienta()
def volumen_app(app: str, accion: typing.Literal["fijar", "subir", "bajar", "silenciar", "quitar_silencio", "consultar"] = "consultar",
                cantidad: int = 50) -> str:
    """Volumen de UNA aplicación (Spotify, Discord, Chrome…) sin tocar el general.

    Args:
        app: nombre de la aplicación
        accion: fijar, subir, bajar, silenciar, quitar_silencio o consultar
        cantidad: porcentaje (fijar) o puntos (subir/bajar)
    """
    buscado = _norm(app).strip().replace(" ", "")
    sesiones = [s for s in _sesiones_audio() if buscado in _norm(s.Process.name()).replace(" ", "")]
    if not sesiones:
        activas = sorted({s.Process.name().removesuffix(".exe") for s in _sesiones_audio()})
        return f"{app} no está usando el sonido ahora." + (f" Suenan: {', '.join(activas)}." if activas else "")
    vol = sesiones[0].SimpleAudioVolume
    actual = round(vol.GetMasterVolume() * 100)
    if accion == "consultar":
        return f"{app.capitalize()} está al {actual}%" + (" (silenciado)" if vol.GetMute() else "") + "."
    for s in sesiones:
        v = s.SimpleAudioVolume
        if accion == "silenciar":
            v.SetMute(1, None)
        elif accion == "quitar_silencio":
            v.SetMute(0, None)
        else:
            nuevo = {"subir": actual + cantidad, "bajar": actual - cantidad}.get(accion, cantidad)
            v.SetMute(0, None)
            v.SetMasterVolume(max(0, min(100, nuevo)) / 100, None)
    if accion == "silenciar":
        return f"{app.capitalize()} silenciado."
    if accion == "quitar_silencio":
        return f"{app.capitalize()} vuelve a sonar."
    nuevo = max(0, min(100, {"subir": actual + cantidad, "bajar": actual - cantidad}.get(accion, cantidad)))
    return f"{app.capitalize()} al {nuevo}%."


def _volumen_micro():
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    comtypes.CoInitialize()
    dispositivo = AudioUtilities.GetMicrophone()
    interfaz = dispositivo.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    # QueryInterface (y no ctypes.cast): cast crea una segunda referencia sin AddRef y el objeto COM se libera
    # dos veces -> «COM method call without VTable» y, más tarde, un cierre del proceso (visto en las pruebas)
    return interfaz.QueryInterface(IAudioEndpointVolume)


@herramienta()
def microfono(accion: typing.Literal["silenciar", "activar", "consultar"] = "consultar") -> str:
    """Silencia o activa el micrófono de Windows (mientras esté silenciado, Jarvis solo te atiende con el atajo).

    Args:
        accion: silenciar, activar o consultar
    """
    m = _volumen_micro()
    if accion == "consultar":
        return "El micrófono está silenciado." if m.GetMute() else "El micrófono está activo."
    m.SetMute(1 if accion == "silenciar" else 0, None)
    if accion == "silenciar":
        return "Micrófono silenciado. Para volver a oírte usa el atajo de teclado y escribe, o dime «activa el micro» tras el atajo."
    return "Micrófono activo."


@herramienta()
def brillo(accion: typing.Literal["consultar", "fijar", "subir", "bajar"] = "consultar", cantidad: int = 10) -> str:
    """Brillo de las pantallas (DDC/CI en monitores externos; el monitor debe tenerlo activado en su menú).

    Args:
        accion: consultar, fijar (porcentaje), subir o bajar (puntos)
        cantidad: porcentaje o puntos
    """
    from ctypes import wintypes
    dxva2, user32 = ctypes.windll.dxva2, ctypes.windll.user32

    class FISICO(ctypes.Structure):
        _fields_ = [("h", wintypes.HANDLE), ("desc", wintypes.WCHAR * 128)]
    monitores = []

    import ventanas
    numeros = {p["hmonitor"]: p["numero"] for p in ventanas.pantallas()}  # la numeración de Windows (pantalla 1, 2, 3)

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def cada(hmon, _dc, _r, _):
        monitores.append(hmon)
        return True
    user32.EnumDisplayMonitors(None, None, cada, 0)
    resultados, cambiados = [], 0
    for hmon in monitores:
        i = numeros.get(hmon, "?")
        n = wintypes.DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(n)) or not n.value:
            continue
        fisicos = (FISICO * n.value)()
        if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, n.value, fisicos):
            continue
        try:
            for f in fisicos:
                minimo, actual, maximo = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
                if not dxva2.GetMonitorBrightness(f.h, ctypes.byref(minimo), ctypes.byref(actual), ctypes.byref(maximo)):
                    continue
                rango = max(1, maximo.value - minimo.value)
                pct = round((actual.value - minimo.value) * 100 / rango)
                if accion != "consultar":
                    nuevo = max(0, min(100, {"subir": pct + cantidad, "bajar": pct - cantidad}.get(accion, cantidad)))
                    if dxva2.SetMonitorBrightness(f.h, minimo.value + round(nuevo * rango / 100)):
                        pct, cambiados = nuevo, cambiados + 1
                resultados.append(f"pantalla {i} al {pct}%")
        finally:
            dxva2.DestroyPhysicalMonitors(n.value, fisicos)
    if not resultados:
        return "Tus pantallas no dejan cambiar el brillo desde Windows (activa DDC/CI en el menú del monitor)."
    return ("Brillo: " if accion == "consultar" or cambiados else "No he podido cambiarlo. Brillo: ") + ", ".join(resultados) + "."


_PLANES = {"ahorro": "a1841308-3541-4fab-bc81-f71556f20b4a", "equilibrado": "381b4222-f694-41f0-9685-ff5bb260df2e",
           "alto_rendimiento": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"}


@herramienta()
def plan_energia(plan: typing.Literal["consultar", "ahorro", "equilibrado", "alto_rendimiento"] = "consultar") -> str:
    """Plan de energía de Windows (modo ahorro de energía, equilibrado o alto rendimiento).

    Args:
        plan: consultar, ahorro, equilibrado o alto_rendimiento
    """
    salida = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, creationflags=_SIN_VENTANA).stdout
    disponibles = {m.group(1).lower(): m.group(2) for m in re.finditer(r"([0-9a-f-]{36})\s+\(([^)]+)\)", salida)}
    activo = next((nombre for guid, nombre in disponibles.items() if guid in re.findall(r"([0-9a-f-]{36})[^\n]*\*", salida)), None)
    if plan == "consultar":
        return f"Plan de energía: {activo or 'desconocido'}. Disponibles: {', '.join(disponibles.values())}."
    guid = _PLANES[plan]
    if guid not in disponibles:
        return f"Ese plan no está disponible en tu PC. Tienes: {', '.join(disponibles.values())}."
    r = subprocess.run(["powercfg", "/setactive", guid], capture_output=True, text=True, creationflags=_SIN_VENTANA)
    if r.returncode:
        return f"Windows no me deja cambiar el plan: {r.stderr.strip() or r.stdout.strip()}"
    return f"Plan de energía: {disponibles[guid]}."


# ==================================================================
#  APPS ABIERTAS
# ==================================================================
@herramienta()
def apps_abiertas() -> str:
    """Lista las aplicaciones con ventana abierta y en qué pantalla está cada una."""
    import ventanas
    lista = ventanas.ventanas_visibles()
    if not lista:
        return "No hay ninguna app con ventana abierta."
    monitores = ventanas.pantallas()
    bonitos = {"windowsterminal": "Terminal", "msedge": "Edge", "chrome": "Chrome", "code": "VS Code", "explorer": "Explorador",
               "epicgameslauncher": "Epic Games", "notepad": "Bloc de notas", "calculatorapp": "Calculadora"}
    por_app = {}
    for v in lista:
        nombre = (v.get("proceso") or "?").removesuffix(".exe")
        if nombre.lower() in ("pythonw", "python", "applicationframehost", "textinputhost", "shellexperiencehost"):
            continue
        nombre = bonitos.get(nombre.lower(), nombre[:1].upper() + nombre[1:])
        p = ventanas.pantalla_de_ventana(v["hwnd"], monitores)
        por_app.setdefault(nombre, set()).add(p["numero"] if p else None)
    partes = [f"{n} (pantalla {', '.join(str(p) for p in sorted(x for x in ps if x))})" if any(ps) else n for n, ps in por_app.items()]
    return f"Tienes abiertas {len(partes)} apps: " + ", ".join(partes) + "."


# ==================================================================
#  PORTAPAPELES (resumir, traducir, guardar en Obsidian) Y DICTADO
# ==================================================================
def _texto_portapapeles() -> str:
    import pyperclip
    try:
        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


def preguntar_al_modelo(instruccion: str, texto: str, max_tokens: int = 400) -> str:
    """Una pregunta suelta al modelo (sin herramientas ni historial): resumir, traducir…"""
    texto = texto[:12000]
    if cfg("cerebro.proveedor", "ollama") == "claude":
        import anthropic
        cliente = anthropic.Anthropic(api_key=cfg("cerebro.claude.api_key") or None)
        r = cliente.messages.create(model=cfg("cerebro.claude.modelo", "claude-haiku-5-5"), max_tokens=max_tokens,
                                    messages=[{"role": "user", "content": f"{instruccion}\n\n---\n{texto}"}])
        return "".join(b.text for b in r.content if b.type == "text").strip()
    import ollama
    r = ollama.Client(host=cfg("cerebro.ollama.url", "http://localhost:11434")).chat(
        model=cfg("cerebro.ollama.modelo"), keep_alive="30m" if cfg("cerebro.ollama.mantener_cargado", True) else None,
        messages=[{"role": "system", "content": "Respondes en español, directo y sin adornos."},
                  {"role": "user", "content": f"{instruccion}\n\n---\n{texto}"}],
        options={"num_ctx": int(cfg("cerebro.ollama.contexto", 8192)), "num_predict": max_tokens})
    return r["message"]["content"].strip()


@herramienta()
def resumir_portapapeles() -> str:
    """Resume en 2-4 frases el texto que el usuario ha copiado (Ctrl+C)."""
    texto = _texto_portapapeles()
    if len(texto) < 40:
        return "No hay texto copiado que resumir (o es muy corto)." if not texto else f"Lo copiado es corto: «{texto}»."
    return preguntar_al_modelo("Resume este texto en 2 a 4 frases, en español:", texto, 300)


@herramienta()
def traducir_portapapeles(idioma: str = "español") -> str:
    """Traduce el texto copiado (Ctrl+C) al idioma que se pida y deja la traducción en el portapapeles.

    Args:
        idioma: idioma de destino (español, inglés, francés…)
    """
    import pyperclip
    texto = _texto_portapapeles()
    if not texto:
        return "No hay texto copiado que traducir."
    traduccion = preguntar_al_modelo(f"Traduce al {idioma} este texto. Devuelve SOLO la traducción:", texto, 800)
    try:
        pyperclip.copy(traduccion)
    except Exception:
        pass
    return traduccion + "\n(Te la he dejado copiada.)"


@herramienta()
def portapapeles_a_obsidian() -> str:
    """Guarda en el Inbox de Obsidian lo que el usuario ha copiado (Ctrl+C)."""
    texto = _texto_portapapeles()
    if not texto:
        return "No hay nada copiado que guardar."
    import obsidian
    r = obsidian.captura_rapida(texto[:4000])
    return "Guardado en tu Inbox." if not str(r).startswith("Error") else r


# ==================================================================
#  PANTALLA: LEER TEXTO (OCR de Windows, local) Y CAPTURAS
# ==================================================================
_OCR_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Esperar($op, $tipo) { $t = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$archivo = Esperar ([Windows.Storage.StorageFile]::GetFileFromPathAsync($args[0])) ([Windows.Storage.StorageFile])
$flujo = Esperar ($archivo.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Esperar ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($flujo)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Esperar ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$motor = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($args[1]))
if (-not $motor) { $motor = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
$res = Esperar ($motor.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$res.Lines | ForEach-Object { $_.Text }
"""


def ocr_imagen(ruta: Path, idioma: str = "es-ES") -> str:
    """Texto de una imagen con el OCR que trae Windows (sin instalar nada, sin internet)."""
    script = DATOS / "ocr.ps1"
    if not script.exists() or script.read_text(encoding="utf-8") != _OCR_PS:
        script.write_text(_OCR_PS, encoding="utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(ruta), idioma],
                       capture_output=True, timeout=40, creationflags=_SIN_VENTANA)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[:300])
    return r.stdout.decode("utf-8", "replace").strip()


@herramienta()
def leer_texto_pantalla(zona: typing.Literal["ventana", "pantalla"] = "ventana") -> str:
    """Lee el texto que se ve en la ventana activa o en toda la pantalla (OCR local de Windows).

    Args:
        zona: ventana (la que estás usando) o pantalla (la pantalla entera donde está)
    """
    import mss
    import mss.tools
    import win32gui
    import herramientas
    ruta = DATOS / "ocr_captura.png"
    with mss.mss() as s:
        if zona == "ventana":
            hwnd = win32gui.GetForegroundWindow()
            # si la ventana activa es el orbe o el panel de Jarvis, la de debajo
            titulo = win32gui.GetWindowText(hwnd)
            if titulo in ("J.A.R.V.I.S.", "Jarvis · Panel"):
                hwnd = win32gui.GetWindow(hwnd, 2)  # GW_HWNDNEXT
                while hwnd and not (win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd)):
                    hwnd = win32gui.GetWindow(hwnd, 2)
            izq, arr, der, aba = win32gui.GetWindowRect(hwnd)
            zona_px = {"left": izq, "top": arr, "width": max(1, der - izq), "height": max(1, aba - arr)}
        else:
            zona_px = herramientas._monitor_activo(s.monitors)
        img = s.grab(zona_px)
        mss.tools.to_png(img.rgb, img.size, output=str(ruta))
    try:
        texto = ocr_imagen(ruta)
    except Exception as e:
        log.warning(f"OCR  falló: {e}")
        return "No he podido leer la pantalla (el OCR de Windows ha fallado)."
    finally:
        ruta.unlink(missing_ok=True)  # no guardo lo que hay en tu pantalla
    texto = re.sub(r"\n{2,}", "\n", texto).strip()
    if not texto:
        return "No veo texto ahí."
    log.info(f"OCR  {len(texto)} caracteres leídos de la {zona}")
    return texto if len(texto) < 1500 else texto[:1500] + "… (sigue)"


def _capturas_recientes():
    import herramientas
    carpetas = [herramientas.carpeta_permitida() / "capturas"]
    imagenes = carpeta_conocida("imagenes")
    if imagenes:
        carpetas += [imagenes / "Screenshots", imagenes / "Capturas de pantalla"]
    archivos = []
    for c in carpetas:
        if c.exists():
            archivos += [p for p in c.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    return sorted(archivos, key=lambda p: p.stat().st_mtime, reverse=True)


@herramienta()
def abrir_ultima_captura() -> str:
    """Abre la última captura de pantalla (las de Jarvis y las de Windows)."""
    lista = _capturas_recientes()
    if not lista:
        return "No encuentro ninguna captura."
    os.startfile(str(lista[0]))
    return f"Abro la última captura ({_cuando(lista[0].stat().st_mtime)})."


# ==================================================================
#  RECORDATORIOS PERSISTENTES Y RUTINAS PROGRAMADAS
#  Se guardan en datos/ y los dispara el VIGILANTE (siempre en marcha), así que funcionan aunque Jarvis esté
#  cerrado o hayas reiniciado el PC (si vuelve a arrancar con Windows).
# ==================================================================
from recordatorios import DIAS as _DIAS, PROGRAMADAS, RECORDATORIOS  # noqa: E402
from recordatorios import escribir as _escribir, leer as _leer  # noqa: E402


def fecha_de_texto(cuando: str):
    """'mañana a las 10', 'el viernes a las 9:30', 'hoy a las 18', 'a las 7', '2026-11-05 10:00' -> datetime."""
    import intenciones
    t = _norm(cuando).strip()
    ahora = datetime.now()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ t](\d{1,2}:\d{2})", t)
    if m:
        return datetime.fromisoformat(f"{m.group(1)} {m.group(2).zfill(5)}")
    dia = None
    m = re.match(r"(?:el\s+)?(pasado\s+manana|manana|hoy|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s*(?:que\s+viene\s*)?", t)
    if m:
        palabra = m.group(1)
        t = t[m.end():].strip()
        if palabra == "hoy":
            dia = ahora.date()
        elif palabra == "manana":
            dia = (ahora + timedelta(days=1)).date()
        elif palabra.startswith("pasado"):
            dia = (ahora + timedelta(days=2)).date()
        else:
            dif = (_DIAS.index(palabra) - ahora.weekday()) % 7 or 7
            dia = (ahora + timedelta(days=dif)).date()
    m = re.match(r"(?:a\s+)?(?:las?\s+)?(.+)", t)
    hora = intenciones.hora_reloj(m.group(1)) if m and t else None
    if not hora:
        if dia and not t:
            hora = "09:00"  # «recuérdame mañana X» sin hora: a las 9
        else:
            return None
    h, mi = map(int, hora.split(":"))
    if dia is None:
        momento = ahora.replace(hour=h, minute=mi, second=0, microsecond=0)
        if momento <= ahora:
            momento += timedelta(days=1)
        return momento
    return datetime(dia.year, dia.month, dia.day, h, mi)


@herramienta()
def crear_recordatorio(texto: str, cuando: str) -> str:
    """Recordatorio que se guarda (sobrevive a cerrar Jarvis y a reiniciar): «recuérdame mañana a las 10 llamar al médico».

    Args:
        texto: qué hay que recordar
        cuando: "mañana a las 10", "el viernes a las 9:30", "hoy a las 18:00", "a las 7" o "AAAA-MM-DD HH:MM"
    """
    momento = fecha_de_texto(cuando)
    if not momento:
        return f"No entiendo cuándo es «{cuando}». Dime algo como «mañana a las 10»."
    lista = _leer(RECORDATORIOS)
    lista.append({"id": int(time.time() * 1000), "texto": texto.strip(), "cuando": momento.isoformat(timespec="minutes")})
    _escribir(RECORDATORIOS, lista)
    dias = (momento.date() - datetime.now().date()).days
    cuando_txt = {0: "hoy", 1: "mañana"}.get(dias, _DIAS[momento.weekday()] + f" {momento.day}")
    return f"Te lo recordaré {cuando_txt} a las {momento:%H:%M}: {texto.strip()}."


@herramienta()
def listar_recordatorios() -> str:
    """Recordatorios guardados que aún no han saltado."""
    lista = sorted(_leer(RECORDATORIOS), key=lambda r: r["cuando"])
    if not lista:
        return "No tienes recordatorios pendientes."
    return "Recordatorios: " + "; ".join(f"{datetime.fromisoformat(r['cuando']):%d/%m %H:%M} {r['texto']}" for r in lista) + "."


@herramienta()
def borrar_recordatorio(texto: str = "") -> str:
    """Quita un recordatorio pendiente (el que contenga ese texto; vacío = el próximo).

    Args:
        texto: parte del texto del recordatorio
    """
    lista = sorted(_leer(RECORDATORIOS), key=lambda r: r["cuando"])
    t = _norm(texto)
    quitar = next((r for r in lista if t in _norm(r["texto"])), None) if t else (lista[0] if lista else None)
    if not quitar:
        return "No encuentro ese recordatorio."
    _escribir(RECORDATORIOS, [r for r in lista if r["id"] != quitar["id"]])
    return f"Quitado el recordatorio: {quitar['texto']}."


def _dias_de_texto(texto: str) -> str:
    t = _norm(texto)
    if re.search(r"laborable|entre semana|de lunes a viernes", t):
        return "laborables"
    if re.search(r"fin(?:es)? de semana", t):
        return "fines_de_semana"
    dias = [d for d in _DIAS if re.search(r"\b" + d[:-1], t)]
    return ",".join(dias) if dias and not re.search(r"cada dia|todos los dias|diario", t) else "diario"


@herramienta()
def programar_rutina(orden: str, hora: str, dias: str = "diario") -> str:
    """Programa una orden para que Jarvis la haga sola a una hora: «cada día a las 9 lee mi agenda».

    Args:
        orden: lo que tiene que hacer, como se lo dirías («lee mi agenda», «dime el tiempo»)
        hora: HH:MM
        dias: diario, laborables, fines_de_semana o días separados por comas (lunes,miercoles)
    """
    import intenciones
    h = intenciones.hora_reloj(_norm(hora)) or (hora if re.fullmatch(r"\d{2}:\d{2}", hora) else None)
    if not h:
        return f"No entiendo la hora «{hora}»."
    dias = _dias_de_texto(dias) if dias not in ("diario", "laborables", "fines_de_semana") else dias
    lista = _leer(PROGRAMADAS)
    lista.append({"id": int(time.time() * 1000), "orden": orden.strip(), "hora": h, "dias": dias, "ultima": ""})
    _escribir(PROGRAMADAS, lista)
    texto_dias = {"diario": "cada día", "laborables": "de lunes a viernes", "fines_de_semana": "los fines de semana"}.get(
        dias, "los " + dias.replace(",", ", "))
    return f"Hecho: {texto_dias} a las {h} haré «{orden.strip()}»."


@herramienta()
def listar_rutinas_programadas() -> str:
    """Las órdenes programadas (rutinas con hora)."""
    lista = _leer(PROGRAMADAS)
    if not lista:
        return "No tienes rutinas programadas."
    return "Programadas: " + "; ".join(f"{r['hora']} ({r['dias'].replace('_', ' ')}) «{r['orden']}»" for r in lista) + "."


@herramienta()
def borrar_rutina_programada(texto: str = "") -> str:
    """Quita una rutina programada (la que contenga ese texto o esa hora).

    Args:
        texto: parte de la orden o la hora (HH:MM)
    """
    import intenciones
    lista = _leer(PROGRAMADAS)
    t = _norm(texto).strip()
    hora = intenciones.hora_reloj(t) if t else None
    quitar = next((r for r in lista if (hora and r["hora"] == hora) or (t and t in _norm(r["orden"]))), None)
    if not quitar:
        return "No encuentro esa rutina programada."
    _escribir(PROGRAMADAS, [r for r in lista if r["id"] != quitar["id"]])
    return f"Quitada: «{quitar['orden']}» a las {quitar['hora']}."


# ==================================================================
#  RED
# ==================================================================
def _ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # no envía nada: solo pregunta qué interfaz usaría
            return s.getsockname()[0]
    except OSError:
        return "?"


def _latencia(host="1.1.1.1", puerto=443):
    t0 = time.time()
    try:
        with socket.create_connection((host, puerto), timeout=3):
            return (time.time() - t0) * 1000
    except OSError:
        return None


@herramienta()
def estado_red() -> str:
    """Conexión a internet, IP local, red Wi-Fi y latencia."""
    lat = _latencia()
    try:
        socket.gethostbyname("www.google.com")
        dns = True
    except OSError:
        dns = False
    wifi = ""
    try:
        salida = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=5,
                                creationflags=_SIN_VENTANA).stdout.decode("cp850", "replace")
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", salida, re.M)
        if m:
            wifi = f", Wi-Fi «{m.group(1).strip()}»"
    except Exception:
        pass
    if lat is None:
        return f"Sin internet ahora mismo (IP local {_ip_local()}{wifi})." + ("" if dns else " Tampoco resuelve nombres (DNS).")
    return f"Internet bien: {lat:.0f} ms de latencia. IP local {_ip_local()}{wifi or ', por cable'}."


@herramienta()
def velocidad_internet() -> str:
    """Mide la velocidad de bajada aproximada (descarga 25 MB de Cloudflare, ~3 s) y la latencia."""
    import requests
    lat = _latencia()
    if lat is None:
        return "No hay conexión a internet."
    t0, bytes_ = time.time(), 0
    try:
        with requests.get("https://speed.cloudflare.com/__down?bytes=25000000", stream=True, timeout=15) as r:
            for trozo in r.iter_content(256 * 1024):
                bytes_ += len(trozo)
                if time.time() - t0 > 8:
                    break
    except Exception as e:
        return f"No he podido medirla ({e.__class__.__name__}). Latencia {lat:.0f} ms."
    mbps = bytes_ * 8 / (time.time() - t0) / 1e6
    return f"Bajada aproximada: {mbps:.0f} Mbps. Latencia {lat:.0f} ms."


@herramienta()
def vpn(accion: typing.Literal["listar", "conectar", "desconectar"] = "listar", nombre: str = "") -> str:
    """VPN de Windows ya configuradas: listar, conectar o desconectar (no crea ni configura ninguna).

    Args:
        accion: listar, conectar o desconectar
        nombre: nombre de la VPN (vacío = la única que haya)
    """
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-VpnConnection | Select Name, ConnectionStatus | ConvertTo-Json"],
                       capture_output=True, text=True, timeout=15, creationflags=_SIN_VENTANA)
    try:
        datos = json.loads(r.stdout or "[]")
        datos = [datos] if isinstance(datos, dict) else datos
    except json.JSONDecodeError:
        datos = []
    if not datos:
        return "No tienes ninguna VPN configurada en Windows."
    if accion == "listar":
        return "VPN: " + ", ".join(f"{d['Name']} ({d['ConnectionStatus']})" for d in datos) + "."
    elegida = next((d for d in datos if _norm(nombre) in _norm(d["Name"])), None) if nombre else (datos[0] if len(datos) == 1 else None)
    if not elegida:
        return "¿Cuál? Tienes: " + ", ".join(d["Name"] for d in datos) + "."
    args = ["rasdial", elegida["Name"]] + (["/disconnect"] if accion == "desconectar" else [])
    r = subprocess.run(args, capture_output=True, timeout=60, creationflags=_SIN_VENTANA)
    salida = r.stdout.decode("cp850", "replace").strip()
    return f"VPN {elegida['Name']} {'desconectada' if accion == 'desconectar' else 'conectada'}." if r.returncode == 0 else \
        f"No he podido: {salida[-200:]}"
