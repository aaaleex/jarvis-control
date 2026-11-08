"""
Tiempo REAL hasta que se VE el orbe tras pulsar Ctrl+Alt+J (no basta con que la ventana exista: mide píxeles).
    .venv\\Scripts\\python.exe pruebas\\medir_aparicion.py [repeticiones]
Captura la zona donde aparecerá el orbe cada pocos milisegundos y apunta cuándo cambia de verdad el centro.
Mide desde Jarvis dormido (precargado) y desde Jarvis despierto pero oculto. Deja el orbe oculto y el ratón donde estaba.
"""
import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import mss
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import medir_velocidad as M  # noqa: E402

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
RAIZ = Path(__file__).resolve().parent.parent


def post(ruta, datos=None):
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8765" + ruta, data=json.dumps(datos or {}).encode(),
                                                      method="POST"), timeout=5).read()
    except Exception:
        pass


def zona_orbe():
    """Donde aparecerá: centro de la zona útil del monitor del ratón (igual que hace Jarvis), 120×120 px del centro."""
    import win32api
    x, y = win32api.GetCursorPos()
    izq, arr, der, aba = win32api.GetMonitorInfo(win32api.MonitorFromPoint((x, y), 2))["Work"]
    cx, cy = (izq + der) // 2, (arr + aba) // 2
    return {"left": cx - 60, "top": cy - 60, "width": 120, "height": 120}


def orbe_visible():
    import captura_interfaz as C
    h = C.buscar("J.A.R.V.I.S.")
    return bool(h and user32.IsWindowVisible(h))


def medir_una(etiqueta):
    for _ in range(20):  # que de verdad esté oculto antes de pulsar (si no, el atajo lo OCULTARÍA y mediría eso)
        if not orbe_visible():
            break
        post("/api/ocultar_orbe")
        time.sleep(0.5)
    time.sleep(0.5)
    zona = zona_orbe()
    with mss.MSS() as s:
        base = np.asarray(s.grab(zona), dtype=np.int16)[:, :, :3]
        M.pulsar_atajo()
        t0 = time.perf_counter()
        visto = None
        while time.perf_counter() - t0 < 3:
            img = np.asarray(s.grab(zona), dtype=np.int16)[:, :, :3]
            if np.abs(img - base).mean() > 6:   # el centro del orbe (núcleo brillante) ya está en pantalla
                visto = time.perf_counter() - t0
                break
    print(f"{etiqueta:34} orbe visible en {visto * 1000:.0f} ms" if visto else f"{etiqueta:34} NO se ha visto en 3 s", flush=True)
    return visto


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    raton = wt.POINT()
    user32.GetCursorPos(ctypes.byref(raton))
    # el ratón en la pantalla principal, bajo la que no se esté escribiendo nada (si no, el texto que cambia
    # detrás da falsos «ya se ve»): el centro de la pantalla 1 si existe
    import win32api
    monitores = [win32api.GetMonitorInfo(m[0])["Monitor"] for m in win32api.EnumDisplayMonitors()]
    izquierda = min(monitores, key=lambda r: r[0])
    user32.SetCursorPos((izquierda[0] + izquierda[2]) // 2, (izquierda[1] + izquierda[3]) // 2)
    resultados = {"dormido": [], "despierto_oculto": []}
    try:
        for i in range(n):
            # desde dormido: cierro Jarvis y espero al dormido nuevo
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'jarvis.py' } | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)
            for _ in range(80):
                time.sleep(0.5)
                e = M.http("/api/estado")
                if e and e.get("dormido"):
                    break
            time.sleep(8)  # que termine de precargar (código + Whisper)
            resultados["dormido"].append(medir_una(f"dormido -> visible ({i + 1})"))
            time.sleep(2.5)
            for j in range(2):
                post("/api/ocultar_orbe")
                time.sleep(1.5)
                resultados["despierto_oculto"].append(medir_una(f"despierto y oculto -> visible ({j + 1})"))
                time.sleep(1.5)
            post("/api/ocultar_orbe")
            time.sleep(1)
    finally:
        user32.SetCursorPos(raton.x, raton.y)
        post("/api/ocultar_orbe")
    for clave, v in resultados.items():
        v = [x for x in v if x]
        if v:
            print(f"{clave:18} media {sum(v) / len(v) * 1000:.0f} ms · mín {min(v) * 1000:.0f} · máx {max(v) * 1000:.0f} ({len(v)} medidas)")


if __name__ == "__main__":
    main()
