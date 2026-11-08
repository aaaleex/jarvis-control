"""
Pantallas y ventanas: detecta tus monitores, abre apps/webs en la pantalla que digas, trae ventanas al frente,
las mueve, maximiza, minimiza, pone en mitad de pantalla...

Nombres de pantalla que entiende:
  · "pantalla 1/2/3" (o "primera/segunda/tercera") = el número que les da Windows (\\\\.\\DISPLAY1, 2, 3).
  · "principal" = la pantalla principal de Windows.
  · "izquierda / centro / derecha" = según su posición física.
  · Los nombres que les pongas en config.yaml (pantallas.nombres) o desde la interfaz.

Todo el proceso es "DPI-aware" (por monitor): las coordenadas son píxeles reales aunque cada pantalla tenga
una escala de Windows distinta.
"""
import ctypes
import os
import re
import subprocess
import threading
import time
import unicodedata
from ctypes import wintypes
from pathlib import Path

import psutil

from nucleo import cfg, log

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindow.restype = wintypes.HWND


# ==================================================================
#  DPI: hay que activarlo ANTES de crear ninguna ventana del proceso
# ==================================================================
def hacer_dpi_aware():
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").strip()


# ==================================================================
#  PANTALLAS
# ==================================================================
class _MONITORINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def pantallas() -> list:
    """Lista de monitores (se lee de nuevo cada vez: si conectas o desconectas uno, se entera al momento).
    Cada uno: numero, dispositivo, x, y, ancho, alto, zona (x, y, ancho, alto sin barra de tareas),
    principal, escala (%), posicion (izquierda/centro/derecha), nombre."""
    encontrados = []

    @ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def recoger(hmon, _hdc, _rect, _dato):
        info = _MONITORINFOEX()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        dpi_x, dpi_y = ctypes.c_uint(96), ctypes.c_uint(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        except Exception:
            pass
        m, w = info.rcMonitor, info.rcWork
        encontrados.append({
            "hmonitor": hmon, "dispositivo": info.szDevice,
            "x": m.left, "y": m.top, "ancho": m.right - m.left, "alto": m.bottom - m.top,
            "zona": (w.left, w.top, w.right - w.left, w.bottom - w.top),
            "principal": bool(info.dwFlags & 1), "escala": round(dpi_x.value * 100 / 96),
        })
        return 1

    user32.EnumDisplayMonitors(None, None, recoger, 0)
    # Número "de Windows": el de \\.\DISPLAYn, ordenado (1, 2, 3...)
    def num_dispositivo(p):
        m = re.search(r"(\d+)$", p["dispositivo"])
        return int(m.group(1)) if m else 99
    for i, p in enumerate(sorted(encontrados, key=num_dispositivo), 1):
        p["numero"] = i
    # Posición física de izquierda a derecha
    por_x = sorted(encontrados, key=lambda p: (p["x"], p["y"]))
    for i, p in enumerate(por_x):
        if len(por_x) == 1:
            p["posicion"] = "unica"
        elif i == 0:
            p["posicion"] = "izquierda"
        elif i == len(por_x) - 1:
            p["posicion"] = "derecha"
        else:
            p["posicion"] = "centro" if len(por_x) == 3 else f"centro {i}"
    nombres = {str(k): str(v) for k, v in (cfg("pantallas.nombres", {}) or {}).items()}
    for p in encontrados:
        p["nombre"] = nombres.get(str(p["numero"]), "")
    return sorted(encontrados, key=lambda p: p["numero"])


_ORDINALES = {"1": 1, "uno": 1, "una": 1, "primera": 1, "primer": 1, "primero": 1,
              "2": 2, "dos": 2, "segunda": 2, "segundo": 2,
              "3": 3, "tres": 3, "tercera": 3, "tercer": 3, "tercero": 3,
              "4": 4, "cuatro": 4, "cuarta": 4, "cuarto": 4}


def resolver_pantalla(texto, lista=None):
    """'2', 'la segunda', 'principal', 'izquierda', 'la del medio', 'tele' (nombre propio)... -> pantalla o None."""
    lista = lista or pantallas()
    if texto is None or texto == "" or texto == 0:
        return None
    if isinstance(texto, int):
        return next((p for p in lista if p["numero"] == texto), None)
    t = _normalizar(texto)
    t = re.sub(r"\b(la|el|en|de|pantalla|monitor|escritorio|pantallas)\b", " ", t).strip()
    t = re.sub(r"\s+", " ", t)
    for p in lista:  # nombres propios primero
        if p["nombre"] and _normalizar(p["nombre"]) == t:
            return p
    if t in ("principal", "main", "primaria", "grande"):
        return next((p for p in lista if p["principal"]), lista[0])
    if t in ("izquierda", "izquierdo", "izq"):
        return next((p for p in lista if p["posicion"] == "izquierda"), None)
    if t in ("derecha", "derecho", "der"):
        return next((p for p in lista if p["posicion"] == "derecha"), None)
    if t in ("centro", "central", "medio", "del medio", "centrar"):
        return next((p for p in lista if p["posicion"].startswith("centro")), None)
    if t in ("esta", "actual", "este"):
        return pantalla_de_ventana(user32.GetForegroundWindow(), lista)
    if t in _ORDINALES:
        return next((p for p in lista if p["numero"] == _ORDINALES[t]), None)
    return None


def describir_pantalla(p) -> str:
    if not p:
        return ""
    extra = p["nombre"] or ("principal" if p["principal"] else p["posicion"])
    return f"pantalla {p['numero']}" + (f" ({extra})" if extra and extra != "unica" else "")


def pantalla_de_ventana(hwnd, lista=None):
    lista = lista or pantallas()
    hmon = user32.MonitorFromWindow(hwnd, 2)
    return next((p for p in lista if p["hmonitor"] == hmon), lista[0] if lista else None)


# ==================================================================
#  APLICACIONES CONOCIDAS (proceso de sus ventanas y cómo lanzarlas)
# ==================================================================
LOCAL = os.environ.get("LOCALAPPDATA", "")
APPS = {
    "spotify": {"nombre": "Spotify", "procesos": ["spotify.exe"], "lanzar": ["spotify:"]},
    "discord": {"nombre": "Discord", "procesos": ["discord.exe"], "minimo": (500, 400),
                "lanzar": [[rf"{LOCAL}\Discord\Update.exe", "--processStart", "Discord.exe"]]},
    "epic": {"nombre": "Epic Games", "procesos": ["epicgameslauncher.exe"], "espera": 60,
             "lanzar": [r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
                        r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
                        "com.epicgames.launcher://"]},
    "chrome": {"nombre": "Chrome", "procesos": ["chrome.exe"], "navegador": True,
               "lanzar": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]},
    "edge": {"nombre": "Edge", "procesos": ["msedge.exe"], "navegador": True, "lanzar": ["msedge"]},
    "firefox": {"nombre": "Firefox", "procesos": ["firefox.exe"], "navegador": True, "lanzar": ["firefox"]},
    "vscode": {"nombre": "VS Code", "procesos": ["code.exe"],
               "lanzar": [rf"{LOCAL}\Programs\Microsoft VS Code\Code.exe", r"C:\Program Files\Microsoft VS Code\Code.exe"]},
    "obsidian": {"nombre": "Obsidian", "procesos": ["obsidian.exe"], "lanzar": [rf"{LOCAL}\Programs\Obsidian\Obsidian.exe"]},
    "steam": {"nombre": "Steam", "procesos": ["steamwebhelper.exe", "steam.exe"], "minimo": (500, 400)},
    "whatsapp": {"nombre": "WhatsApp", "procesos": ["whatsapp.exe", "whatsapp.root.exe"]},
    "explorador": {"nombre": "Explorador", "procesos": ["explorer.exe"], "clase": "CabinetWClass", "lanzar": ["explorer"]},
    "bloc de notas": {"nombre": "Bloc de notas", "procesos": ["notepad.exe"], "lanzar": ["notepad"]},
    "calculadora": {"nombre": "Calculadora", "procesos": ["calculatorapp.exe"], "titulo": "calculadora", "lanzar": ["calc"]},
    "word": {"nombre": "Word", "procesos": ["winword.exe"]},
    "excel": {"nombre": "Excel", "procesos": ["excel.exe"]},
    "powerpoint": {"nombre": "PowerPoint", "procesos": ["powerpnt.exe"]},
    "terminal": {"nombre": "Terminal", "procesos": ["windowsterminal.exe"], "lanzar": ["wt"]},
    "administrador de tareas": {"nombre": "Administrador de tareas", "procesos": ["taskmgr.exe"], "lanzar": ["taskmgr"]},
    "configuracion": {"nombre": "Configuración", "titulo": "configuracion", "procesos": ["systemsettings.exe"],
                      "lanzar": ["ms-settings:"]},
}
SINONIMOS = {
    "epic games": "epic", "epic games launcher": "epic", "el epic": "epic", "la epic": "epic", "epic launcher": "epic",
    "visual studio code": "vscode", "vs code": "vscode", "visual code": "vscode", "code": "vscode", "el code": "vscode",
    "google chrome": "chrome", "el chrome": "chrome", "navegador": "chrome", "el navegador": "chrome", "google": "chrome",
    "microsoft edge": "edge", "el edge": "edge", "notepad": "bloc de notas", "notas de windows": "bloc de notas",
    "calc": "calculadora", "explorador de archivos": "explorador", "carpetas": "explorador", "mis archivos": "explorador",
    "el spotify": "spotify", "el discord": "discord", "obsidiana": "obsidian", "el obsidian": "obsidian",
    "ajustes": "configuracion", "ajustes de windows": "configuracion", "task manager": "administrador de tareas",
    "whats app": "whatsapp", "guasap": "whatsapp", "wasap": "whatsapp", "la terminal": "terminal",
}


def _navegador_por_defecto() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0].lower()
        if "chrome" in progid:
            return "chrome"
        if "firefox" in progid:
            return "firefox"
        if "edge" in progid or "msedgehtm" in progid:
            return "edge"
    except Exception:
        pass
    return "chrome"


def resolver_app(nombre: str):
    """Nombre dicho -> (clave, info) de la app, o (None, None) si no la conozco.
    Mira: tabla conocida, alias de config.yaml (apps) y apps del menú Inicio."""
    if re.match(r"^[a-zA-Z]:\\.+\.exe$", str(nombre).strip()):  # ruta directa (escenas guardadas)
        ruta = Path(str(nombre).strip())
        return ruta.stem.lower(), {"nombre": ruta.stem, "procesos": [ruta.name.lower()], "lanzar": [str(ruta)]}
    n = _normalizar(nombre).strip(" .,")
    n = re.sub(r"^(el|la|los|las|mi)\s+", "", n)
    alias = {_normalizar(k): str(v) for k, v in (cfg("apps", {}) or {}).items()}
    for candidato in (n, _normalizar(alias.get(n, ""))):
        if not candidato:
            continue
        clave = SINONIMOS.get(candidato, candidato)
        if clave in APPS:
            if clave == "chrome" and n in ("navegador", "el navegador"):
                clave = _navegador_por_defecto()
            info = dict(APPS[clave])
            # Si está en el menú Inicio, esa es la forma más fiable de abrirla (sirve para apps de la Store)
            import herramientas
            if not herramientas._apps_inicio:
                herramientas.cargar_apps_inicio()
            for nombre_inicio in (clave, _normalizar(info["nombre"]), "epic games launcher" if clave == "epic" else "",
                                  "visual studio code" if clave == "vscode" else ""):
                if nombre_inicio and nombre_inicio in herramientas._apps_inicio:
                    info["appid_inicio"] = herramientas._apps_inicio[nombre_inicio]
                    break
            return clave, info
    # Menú Inicio (apps instaladas, incluidas las de la Microsoft Store)
    import herramientas
    if not herramientas._apps_inicio:
        herramientas.cargar_apps_inicio()
    objetivo = _normalizar(alias.get(n, n))
    real = None
    for nombre_app in herramientas._apps_inicio:
        na = _normalizar(nombre_app)
        if na == objetivo:
            real = nombre_app
            break
    if real is None and len(objetivo) >= 4:
        candidatas = [a for a in herramientas._apps_inicio if _normalizar(a).startswith(objetivo + " ") or _normalizar(a).startswith(objetivo)]
        candidatas = [a for a in candidatas if "uninstall" not in a and "desinstalar" not in a]
        if candidatas:
            real = min(candidatas, key=len)
    if real is None:
        return None, None
    appid = herramientas._apps_inicio[real]
    proceso = Path(appid).name.lower() if appid.lower().endswith(".exe") else None
    return _normalizar(real), {"nombre": real.title() if real.islower() else real, "appid": appid,
                               "procesos": [proceso] if proceso else [], "titulo": _normalizar(real)}


def esta_instalada(info) -> bool:
    if info.get("appid") or info.get("appid_inicio"):
        return True
    for forma in info.get("lanzar", []):
        if isinstance(forma, list):
            if Path(forma[0]).exists():
                return True
        elif ":" in forma and not re.match(r"^[a-zA-Z]:\\", forma):
            return True   # protocolo (spotify:, com.epicgames.launcher://)
        elif Path(forma).exists() or not os.path.isabs(forma):
            return True
    return False


def lanzar(info) -> bool:
    """Arranca la app de la forma que funcione en este PC."""
    import herramientas
    formas = list(info.get("lanzar", []))
    if info.get("appid"):
        formas.insert(0, ("appid", info["appid"]))
    elif info.get("appid_inicio"):  # el acceso del menú Inicio, como último recurso
        formas.append(("appid", info["appid_inicio"]))
    else:
        real = herramientas._apps_inicio.get(_normalizar(info.get("nombre", "")).lower())
        if real:
            formas.append(("appid", real))
    for forma in formas:
        try:
            if isinstance(forma, tuple):
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{forma[1]}"])
                return True
            if isinstance(forma, list):
                if Path(forma[0]).exists():
                    subprocess.Popen(forma, cwd=str(Path(forma[0]).parent), creationflags=0x00000008)  # DETACHED
                    return True
                continue
            if re.match(r"^[a-zA-Z]:\\", forma):
                if Path(forma).exists():
                    subprocess.Popen([forma], cwd=str(Path(forma).parent), creationflags=0x00000008)
                    return True
                continue
            os.startfile(forma)  # protocolo (spotify:) o comando conocido (notepad, calc)
            return True
        except Exception as e:
            log.warning(f"VENTANAS  no pude lanzar {forma}: {e}")
    return False


# ==================================================================
#  VENTANAS
# ==================================================================
def _texto(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def _clase(hwnd) -> str:
    b = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, b, 128)
    return b.value


def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _oculta_por_dwm(hwnd) -> bool:
    """Ventanas 'fantasma' (apps de la Store suspendidas, otros escritorios virtuales...)."""
    valor = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(valor), 4)  # DWMWA_CLOAKED
    return valor.value != 0


def rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


_nombres_proceso = {}


def _nombre_proceso(pid: int) -> str:
    if pid not in _nombres_proceso:
        try:
            _nombres_proceso[pid] = psutil.Process(pid).name().lower()
        except Exception:
            return ""
    return _nombres_proceso[pid]


def ventanas_visibles(incluir_minimizadas=True) -> list:
    """Ventanas de aplicación de verdad, en orden Z (la primera es la de más arriba)."""
    propias = {os.getpid()}
    lista = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def revisar(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER: diálogos y popups fuera
            return True
        titulo = _texto(hwnd)
        if not titulo or _oculta_por_dwm(hwnd):
            return True
        estilo_ex = user32.GetWindowLongW(hwnd, -20)
        if estilo_ex & 0x80 and not estilo_ex & 0x40000:  # WS_EX_TOOLWINDOW sin WS_EX_APPWINDOW
            return True
        clase = _clase(hwnd)
        if clase in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"):
            return True
        minimizada = bool(user32.IsIconic(hwnd))
        if minimizada and not incluir_minimizadas:
            return True
        r = rect(hwnd)
        if not minimizada and (r[2] <= 1 or r[3] <= 1):
            return True
        pid = _pid(hwnd)
        proceso = _nombre_proceso(pid)
        if clase == "ApplicationFrameWindow":  # apps de la Store: el proceso real va dentro
            proceso = proceso or "applicationframehost.exe"
        lista.append({"hwnd": hwnd, "titulo": titulo, "clase": clase, "pid": pid, "proceso": proceso,
                      "minimizada": minimizada, "maximizada": bool(user32.IsZoomed(hwnd)), "rect": rect(hwnd)})
        return True

    user32.EnumWindows(revisar, 0)
    return [v for v in lista if v["pid"] not in propias or "J.A.R.V.I.S." not in v["titulo"]]


def ventanas_de(nombre_o_info, lista=None) -> list:
    """Ventanas de una app (por proceso y, si hace falta, por título). En orden Z."""
    if isinstance(nombre_o_info, dict):
        info = nombre_o_info
        texto = _normalizar(info.get("nombre", ""))
    else:
        texto = _normalizar(nombre_o_info)
        _, info = resolver_app(nombre_o_info)
        info = info or {}
    lista = lista if lista is not None else ventanas_visibles()
    procesos = set(info.get("procesos", []))
    minimo = info.get("minimo", (150, 100))
    encontradas = []
    for v in lista:
        if info.get("clase") and v["clase"] != info["clase"]:
            continue
        coincide = v["proceso"] in procesos if procesos else False
        if not coincide and info.get("titulo"):
            coincide = info["titulo"] in _normalizar(v["titulo"])
        if not coincide and not procesos and not info.get("titulo") and len(texto) > 3:
            coincide = texto in _normalizar(v["titulo"]) or texto.replace(" ", "") in v["proceso"]
        if not coincide:
            continue
        if not v["minimizada"] and (v["rect"][2] < minimo[0] or v["rect"][3] < minimo[1]):
            continue  # splash, actualizador, miniventanas
        encontradas.append(v)
    return encontradas


def esperar_ventana(info, antes: set = frozenset(), espera: float = 25.0, nueva: bool = False):
    """Espera a que aparezca la ventana principal de la app (nueva=True: una que no existía antes)."""
    limite = time.time() + espera
    while time.time() < limite:
        candidatas = [v for v in ventanas_de(info) if not nueva or v["hwnd"] not in antes]
        if candidatas:
            # Damos un instante a que la ventana termine de crearse (Electron la redimensiona al arrancar)
            time.sleep(0.25)
            return candidatas[0]
        time.sleep(0.15)
    return None


# ---------------- colocar ----------------
def _margenes_invisibles(hwnd):
    """Windows 10/11 pone un borde invisible de ~7 px: lo descontamos para que la ventana quede justa."""
    exterior = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(exterior))
    visible = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(visible), ctypes.sizeof(visible)) != 0:  # EXTENDED_FRAME_BOUNDS
        return 0, 0, 0, 0
    return (visible.left - exterior.left, visible.top - exterior.top,
            exterior.right - visible.right, exterior.bottom - visible.bottom)


SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE, SW_SHOWNOACTIVATE = 6, 3, 9, 4
SWP_NOZORDER, SWP_NOACTIVATE, SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x4, 0x10, 0x1, 0x2, 0x40


def colocar(hwnd, pantalla=None, modo: str = "maximizar"):
    """Lleva la ventana a la pantalla indicada (o deja la suya) con el tamaño pedido.
    modo: maximizar | mitad_izquierda | mitad_derecha | centrar | normal"""
    p = pantalla or pantalla_de_ventana(hwnd)
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)  # una ventana maximizada no se puede mover de pantalla
        time.sleep(0.05)
    zx, zy, zw, zh = p["zona"]
    x, y, w, h = rect(hwnd)
    if modo in ("mitad_izquierda", "izquierda"):
        destino = (zx, zy, zw // 2, zh)
    elif modo in ("mitad_derecha", "derecha"):
        destino = (zx + zw // 2, zy, zw - zw // 2, zh)
    elif modo == "centrar":
        w2, h2 = min(w, int(zw * 0.8)), min(h, int(zh * 0.85))
        destino = (zx + (zw - w2) // 2, zy + (zh - h2) // 2, w2, h2)
    else:  # normal / maximizar: mismo tamaño, centrada en la pantalla de destino
        origen = pantalla_de_ventana(hwnd)
        if origen and origen["hmonitor"] == p["hmonitor"] and modo == "normal":
            destino = (x, y, w, h)
        else:
            w2, h2 = min(w, zw), min(h, zh)
            destino = (zx + (zw - w2) // 2, zy + (zh - h2) // 2, w2, h2)
    for _ in range(2):  # dos pasadas: si cambia de escala (DPI) al cruzar de pantalla, la app se redimensiona
        mi, ma, md, mb = _margenes_invisibles(hwnd)
        user32.SetWindowPos(hwnd, None, destino[0] - mi, destino[1] - ma, destino[2] + mi + md, destino[3] + ma + mb,
                            SWP_NOZORDER | SWP_NOACTIVATE)
    if modo == "maximizar":
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    return p


def traer_al_frente(hwnd) -> bool:
    """Pone la ventana delante de todo y con el foco. Windows no deja a un proceso en segundo plano
    robar el foco, así que se combinan varios métodos y se comprueba que de verdad ha funcionado."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    for intento in range(4):
        actual = user32.GetForegroundWindow()
        if actual == hwnd:
            return True
        hilo_actual = user32.GetWindowThreadProcessId(actual, None)
        hilo_mio = kernel32.GetCurrentThreadId()
        hilo_obj = user32.GetWindowThreadProcessId(hwnd, None)
        if intento >= 1:
            # Truco de la tecla Alt: Windows desbloquea el cambio de foco cuando se pulsa Alt
            user32.keybd_event(0x12, 0, 0x1, 0)
        unidos = []
        for h in (hilo_actual, hilo_obj):
            if h and h != hilo_mio and user32.AttachThreadInput(hilo_mio, h, True):
                unidos.append(h)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)  # encima de todo...
            user32.SetWindowPos(hwnd, ctypes.c_void_p(-2), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)  # ...sin quedarse fija
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for h in unidos:
                user32.AttachThreadInput(hilo_mio, h, False)
            if intento >= 1:
                user32.keybd_event(0x12, 0, 0x1 | 0x2, 0)
        time.sleep(0.06)
        if user32.GetForegroundWindow() == hwnd:
            return True
    # Aunque Windows no le dé el foco, la ventana queda delante de las demás (orden Z)
    return False


def minimizar(hwnd):
    user32.ShowWindow(hwnd, SW_MINIMIZE)


def maximizar(hwnd):
    user32.ShowWindow(hwnd, SW_MAXIMIZE)


def cerrar(hwnd):
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: como pulsar la X (si hay algo sin guardar, la app pregunta)


def mostrar_escritorio(restaurar=False):
    import win32com.client
    shell = win32com.client.Dispatch("Shell.Application")
    shell.UndoMinimizeALL() if restaurar else shell.MinimizeAll()


# ==================================================================
#  ACCIONES DE ALTO NIVEL (las usan el camino rápido, las escenas y el modelo)
# ==================================================================
MODOS = {"maximizar", "mitad_izquierda", "mitad_derecha", "centrar", "normal"}


def abrir_en(nombre: str, pantalla=None, modo: str = "maximizar", espera_max: float = None, esperar: bool = True) -> dict:
    """Abre (o reutiliza si ya está abierta) una app y la coloca. Devuelve
    {"ok", "texto", "hwnd", "ya_abierta", "pid"}. Para webs usa abrir_web_en.
    esperar=False: si hay que esperar a que la app arranque, la coloca en segundo plano y responde ya."""
    clave, info = resolver_app(nombre)
    if not info:
        return {"ok": False, "texto": f"No encuentro ninguna aplicación llamada {nombre}."}
    p = resolver_pantalla(pantalla) if pantalla not in (None, "", 0) else None
    if pantalla not in (None, "", 0) and p is None:
        return {"ok": False, "texto": f"No sé qué pantalla es «{pantalla}». Tienes {len(pantallas())}."}
    existentes = ventanas_de(info)
    ya_abierta = bool(existentes)
    if existentes:
        v = existentes[0]
    else:
        if not esta_instalada(info) or not lanzar(info):
            return {"ok": False, "texto": f"{info['nombre']} no está instalado en este PC."}
        if p is None and modo in ("normal", None, ""):
            return {"ok": True, "texto": f"Abriendo {info['nombre']}.", "ya_abierta": False}
        if not esperar:
            def colocar_al_aparecer():
                v2 = esperar_ventana(info, espera=espera_max or info.get("espera", 25))
                if v2:
                    colocar(v2["hwnd"], p, modo if modo in MODOS else "maximizar")
                    traer_al_frente(v2["hwnd"])
                    log.info(f"VENTANAS  {info['nombre']} colocada en {describir_pantalla(p) or 'su pantalla'}")
                else:
                    log.warning(f"VENTANAS  la ventana de {info['nombre']} no apareció")
            threading.Thread(target=colocar_al_aparecer, daemon=True).start()
            donde = f" en la {describir_pantalla(p)}" if p else ""
            return {"ok": True, "texto": f"Abro {info['nombre']}{donde}.", "ya_abierta": False}
        v = esperar_ventana(info, espera=espera_max or info.get("espera", 25))
        if not v:
            return {"ok": False, "texto": f"He lanzado {info['nombre']}, pero su ventana no ha aparecido."}
    hwnd = v["hwnd"]
    if p is not None or modo != "normal":
        colocar(hwnd, p, modo if modo in MODOS else "maximizar")
    traer_al_frente(hwnd)
    donde = f" en la {describir_pantalla(p)}" if p else ""
    como = {"mitad_izquierda": " a la mitad izquierda", "mitad_derecha": " a la mitad derecha", "centrar": " centrado"}.get(modo, "")
    if not ya_abierta:
        texto = f"Abro {info['nombre']}{como}{donde}."
    elif p is None and not como:
        texto = f"{info['nombre']} ya estaba abierto: te lo pongo delante."
    else:
        texto = f"Paso {info['nombre']}{como}{donde}."
    log.info(f"VENTANAS  {texto} (hwnd {hwnd})")
    return {"ok": True, "texto": texto, "hwnd": hwnd, "ya_abierta": ya_abierta, "pid": v["pid"], "app": clave}


def ruta_navegador(clave=None):
    clave = clave or _navegador_por_defecto()
    try:
        import winreg
        exe = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}[clave]
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
            return clave, winreg.QueryValueEx(k, "")[0]
    except Exception:
        return clave, None


def abrir_web_en(url: str, pantalla=None, modo: str = "maximizar", esperar: bool = True) -> dict:
    """Abre la web en una VENTANA NUEVA del navegador y la lleva a la pantalla pedida."""
    if not esperar:
        p = resolver_pantalla(pantalla) if pantalla not in (None, "", 0) else None
        if pantalla not in (None, "", 0) and p is None:
            return {"ok": False, "texto": f"No sé qué pantalla es «{pantalla}»."}
        threading.Thread(target=abrir_web_en, args=(url, pantalla, modo, True), daemon=True).start()
        nombre = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split(".")[0].capitalize()
        return {"ok": True, "texto": f"Abro {nombre}" + (f" en la {describir_pantalla(p)}." if p else ".")}
    import webbrowser
    p = resolver_pantalla(pantalla) if pantalla not in (None, "", 0) else None
    if p is None:
        webbrowser.open(url)
        return {"ok": True, "texto": "Abierta."}
    clave, exe = ruta_navegador()
    if not exe:
        webbrowser.open(url)
        return {"ok": True, "texto": "La abro en el navegador (no he podido elegir la pantalla)."}
    info = APPS[clave]
    antes = {v["hwnd"] for v in ventanas_de(info)}
    subprocess.Popen([exe, "--new-window", url])
    v = esperar_ventana(info, antes, espera=12, nueva=True)
    if not v:
        return {"ok": True, "texto": "La he abierto, pero no he podido moverla de pantalla."}
    colocar(v["hwnd"], p, modo if modo in MODOS else "maximizar")
    traer_al_frente(v["hwnd"])
    return {"ok": True, "texto": f"Abierta en la {describir_pantalla(p)}.", "hwnd": v["hwnd"], "pid": v["pid"]}


def traer(nombre: str, pantalla=None, modo: str = None) -> dict:
    """«Enséñame Discord» / «pon Spotify delante en la pantalla 2»."""
    _, info = resolver_app(nombre)
    vs = ventanas_de(info or nombre)
    if not vs:
        return {"ok": False, "texto": f"No tienes {info['nombre'] if info else nombre} abierto."}
    v = vs[0]
    p = None
    if pantalla not in (None, "", 0):
        p = resolver_pantalla(pantalla)
        if p is None:
            return {"ok": False, "texto": f"No sé qué pantalla es «{pantalla}»."}
        if pantalla_de_ventana(v["hwnd"])["hmonitor"] != p["hmonitor"] or modo:
            colocar(v["hwnd"], p, modo or ("maximizar" if v["maximizada"] else "normal"))
    elif modo:
        colocar(v["hwnd"], None, modo)
    ok = traer_al_frente(v["hwnd"])
    nombre_bonito = info["nombre"] if info else nombre
    donde = f" en la {describir_pantalla(p)}" if p else ""
    log.info(f"VENTANAS  al frente {nombre_bonito} (foco {'sí' if ok else 'no'})")
    return {"ok": True, "texto": f"Ahí tienes {nombre_bonito}{donde}.", "hwnd": v["hwnd"]}


def accion_ventana(nombre: str, accion: str, pantalla=None) -> dict:
    """minimizar | maximizar | cerrar | mover | mitad_izquierda | mitad_derecha | centrar."""
    _, info = resolver_app(nombre)
    vs = ventanas_de(info or nombre)
    nombre_bonito = info["nombre"] if info else nombre
    if not vs:
        return {"ok": False, "texto": f"No veo {nombre_bonito} abierto."}
    v = vs[0]
    if accion == "minimizar":
        for x in vs:
            minimizar(x["hwnd"])
        return {"ok": True, "texto": f"{nombre_bonito} minimizado."}
    if accion == "cerrar":
        for x in vs:
            cerrar(x["hwnd"])
        return {"ok": True, "texto": f"Cierro {nombre_bonito}."}
    p = None
    if pantalla not in (None, "", 0):
        if pantalla == "otra":
            lista = pantallas()
            actual = pantalla_de_ventana(v["hwnd"], lista)
            p = lista[(lista.index(actual) + 1) % len(lista)] if len(lista) > 1 else actual
        else:
            p = resolver_pantalla(pantalla)
        if p is None:
            return {"ok": False, "texto": f"No sé qué pantalla es «{pantalla}»."}
    if accion == "maximizar" and p is None:
        maximizar(v["hwnd"])
        traer_al_frente(v["hwnd"])
        return {"ok": True, "texto": f"{nombre_bonito} maximizado."}
    modo = {"mover": "maximizar" if v["maximizada"] else "normal"}.get(accion, accion)
    colocar(v["hwnd"], p, modo if modo in MODOS else "normal")
    traer_al_frente(v["hwnd"])
    textos = {"mitad_izquierda": " a la mitad izquierda", "mitad_derecha": " a la mitad derecha",
              "centrar": " al centro", "maximizar": " en grande"}
    donde = f" a la {describir_pantalla(p)}" if p else ""
    return {"ok": True, "texto": f"Paso {nombre_bonito}{textos.get(accion, '')}{donde}."}


def mapa() -> dict:
    """Para la interfaz: pantallas y qué ventanas hay en cada una."""
    lista = pantallas()
    ventanas = []
    for v in ventanas_visibles():
        if v["minimizada"]:
            continue
        p = pantalla_de_ventana(v["hwnd"], lista)
        ventanas.append({"titulo": v["titulo"][:60], "proceso": v["proceso"].replace(".exe", ""), "pantalla": p["numero"],
                         "x": v["rect"][0], "y": v["rect"][1], "ancho": v["rect"][2], "alto": v["rect"][3],
                         "maximizada": v["maximizada"]})
    return {"pantallas": [{k: v for k, v in p.items() if k != "hmonitor"} for p in lista], "ventanas": ventanas}


# ==================================================================
#  Pestañas del navegador (Chrome/Edge) con UI Automation de Windows, sin extensiones
# ==================================================================
def pestana(texto: str) -> dict:
    """Busca una pestaña abierta cuyo título contenga el texto y la activa (Chrome/Edge)."""
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
        uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    except Exception as e:
        return {"ok": False, "texto": f"No puedo leer las pestañas ({e})."}
    buscado = re.sub(r"^(?:la|el|los|las|de|del)\s+", "", _normalizar(texto)).strip()
    condicion = uia.CreatePropertyCondition(30003, 50019)  # ControlType = TabItem
    for clave in ("chrome", "edge"):
        for v in ventanas_de(APPS[clave]):
            try:
                raiz = uia.ElementFromHandle(v["hwnd"])
                pestanas = raiz.FindAll(4, condicion)  # TreeScope_Descendants
            except Exception:
                continue
            for i in range(pestanas.Length):
                elemento = pestanas.GetElement(i)
                nombre = elemento.CurrentName or ""
                if buscado in _normalizar(nombre):
                    try:
                        patron = elemento.GetCurrentPattern(10010).QueryInterface(UIA.IUIAutomationSelectionItemPattern)
                        patron.Select()
                    except Exception:
                        try:
                            patron = elemento.GetCurrentPattern(10018).QueryInterface(UIA.IUIAutomationLegacyIAccessiblePattern)
                            patron.DoDefaultAction()
                        except Exception:
                            continue
                    traer_al_frente(v["hwnd"])
                    return {"ok": True, "texto": f"Ahí tienes la pestaña de {texto}."}
    return {"ok": False, "texto": f"No encuentro ninguna pestaña de {texto}."}


# ==================================================================
#  HERRAMIENTAS PARA EL MODELO (lo que no resuelve el camino rápido)
# ==================================================================
import typing  # noqa: E402

from herramientas import herramienta  # noqa: E402


@herramienta()
def ventana(nombre: str,
            accion: typing.Literal["traer", "mover", "minimizar", "maximizar", "cerrar", "mitad_izquierda",
                                   "mitad_derecha", "centrar"] = "traer",
            pantalla: str = "") -> str:
    """Controla la ventana de una app abierta: traer (ponerla delante), mover de pantalla, minimizar, maximizar, cerrar o mitad de pantalla.

    Args:
        nombre: app o parte del título (p. ej. "discord", "chrome")
        accion: traer, mover, minimizar, maximizar, cerrar, mitad_izquierda, mitad_derecha o centrar
        pantalla: "" (la suya), "1", "2", "3", "principal", "izquierda", "centro", "derecha" u "otra"
    """
    if accion == "traer":
        return traer(nombre, pantalla or None)["texto"]
    return accion_ventana(nombre, accion, pantalla or None)["texto"]


@herramienta()
def mostrar_escritorio_o_restaurar(restaurar: bool = False) -> str:
    """Minimiza todas las ventanas para ver el escritorio (o las restaura).

    Args:
        restaurar: true para volver a mostrar las ventanas
    """
    mostrar_escritorio(restaurar)
    return "Ventanas restauradas." if restaurar else "Escritorio a la vista."


@herramienta()
def pestana_navegador(texto: str) -> str:
    """Busca una pestaña abierta de Chrome/Edge por su título y la pone delante.

    Args:
        texto: parte del título de la pestaña
    """
    return pestana(texto)["texto"]


@herramienta()
def pantallas_conectadas() -> str:
    """Dice qué pantallas hay conectadas y cómo se llaman (número, posición, principal)."""
    return "; ".join(f"{describir_pantalla(p)}: {p['ancho']}x{p['alto']}, escala {p['escala']}%" for p in pantallas())
