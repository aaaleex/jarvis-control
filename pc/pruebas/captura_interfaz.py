"""
Capturas de la ventana REAL del orbe (transparente, sobre lo que haya en el escritorio) en cada estado.
    .venv\\Scripts\\python.exe pruebas\\captura_interfaz.py CARPETA [paso ...]
Pasos: reposo escuchando pensando hablando error despertando · "sub:texto" (subtítulo) · "clic:X,Y" (relativo a
la ventana) · "derecho:X,Y" (clic derecho) · "panel" (captura la ventana del panel) · "seq:estado:N" (N fotogramas).
Al hablar/escuchar usa la voz simulada del propio orbe. Devuelve el orbe a reposo al acabar.
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
import urllib.request
from pathlib import Path

import mss
import mss.tools

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def demo(**datos):
    peticion = urllib.request.Request("http://127.0.0.1:8765/api/demo", data=json.dumps(datos).encode(), method="POST")
    urllib.request.urlopen(peticion, timeout=3).read()


def buscar(titulo):
    """La ventana WinForms de Jarvis con ese título (FindWindow a veces devuelve un «TabProxyWindow» del
    shell que se llama igual y mide 136×39)."""
    encontradas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def revisar(h, _):
        b, c = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(h, b, 64)
        user32.GetClassNameW(h, c, 128)
        if b.value == titulo and c.value.startswith("WindowsForms"):
            encontradas.append(h)
        return True
    user32.EnumWindows(revisar, 0)
    return encontradas[0] if encontradas else None


def rect(titulo):
    h = buscar(titulo)
    if not h or not user32.IsWindowVisible(h):
        return None
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}


def guardar(zona, ruta):
    with mss.MSS() as s:
        img = s.grab(zona)
        mss.tools.to_png(img.rgb, img.size, output=str(ruta))
    print(ruta)


def clic(zona, x, y, boton="izquierdo"):
    user32.SetCursorPos(zona["left"] + x, zona["top"] + y)
    time.sleep(0.15)
    abajo, arriba = (2, 4) if boton == "izquierdo" else (8, 16)
    user32.mouse_event(abajo, 0, 0, 0, 0)
    user32.mouse_event(arriba, 0, 0, 0, 0)


if __name__ == "__main__":
    carpeta = Path(sys.argv[1])
    carpeta.mkdir(parents=True, exist_ok=True)
    zona = rect("J.A.R.V.I.S.")
    if not zona:
        sys.exit("La ventana del orbe no está visible")
    for paso in sys.argv[2:]:
        if paso.startswith(("clic:", "derecho:")):
            tipo, xy = paso.split(":", 1)
            x, y = map(int, xy.split(","))
            clic(zona, x, y, "izquierdo" if tipo == "clic" else "derecho")
            time.sleep(1.5)
            continue
        if paso == "panel":
            time.sleep(1.0)
            z = rect("Jarvis · Panel")
            if z:
                guardar(z, carpeta / "panel.png")
            continue
        if paso.startswith("sub:"):
            demo(subtitulo=paso[4:])
            time.sleep(0.9)
            guardar(zona, carpeta / "subtitulo.png")
            continue
        n = 1
        if paso.startswith("seq:"):
            _, paso, n = paso.split(":")
            n = int(n)
        demo(estado="reposo", simular=False)
        time.sleep(0.15)
        demo(estado=paso, simular=paso in ("hablando", "escuchando"))
        time.sleep(0.1 if paso == "despertando" else 1.8)
        for i in range(n):
            guardar(zona, carpeta / (f"{paso}_{i:02d}.png" if n > 1 else f"{paso}.png"))
            time.sleep(0.05)
    demo(estado="reposo", simular=False)
