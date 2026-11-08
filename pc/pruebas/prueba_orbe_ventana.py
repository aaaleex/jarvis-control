"""
Prueba de la ventana del orbe en el escritorio real (Jarvis debe estar en marcha, dormido o despierto).
    .venv\\Scripts\\python.exe pruebas\\prueba_orbe_ventana.py

Comprueba: sin botón en la barra de tareas, encima de todo, centrada en la pantalla del ratón, los clics fuera
del orbe pasan a la ventana de detrás (y dentro no), clic derecho abre el panel, cerrar el panel solo lo oculta,
Esc oculta el orbe con desvanecido y, oculto, el orbe deja de dibujarse. Deja el ratón donde estaba.
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import captura_interfaz as C  # noqa: E402

user32 = ctypes.windll.user32
URL = "http://127.0.0.1:8765"
LOG = Path(__file__).resolve().parent.parent / "datos" / "jarvis.log"


def post(ruta, datos=None):
    pet = urllib.request.Request(URL + ruta, data=json.dumps(datos or {}).encode(), method="POST")
    return json.loads(urllib.request.urlopen(pet, timeout=5).read() or b"{}")


def get(ruta):
    return json.loads(urllib.request.urlopen(URL + ruta, timeout=5).read() or b"{}")


def diag():
    """Estado real de la página del orbe (lo apunta en el log la propia página)."""
    tam = LOG.stat().st_size
    get("/api/diag")
    time.sleep(0.8)
    for linea in reversed(LOG.read_bytes()[tam:].decode("utf-8", "replace").splitlines()):
        if "DIAG  " in linea and '"tam"' in linea:
            d = json.loads(linea.split("DIAG  ", 1)[1])
            if d.get("orbe"):
                return d
    return {}


def raiz_en(x, y):
    return user32.GetAncestor(user32.WindowFromPoint(wt.POINT(x, y)), 2)


def monitores():
    lista = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    def cada(h, _dc, r, _):
        lista.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
        return True
    user32.EnumDisplayMonitors(None, None, cada, 0)
    return lista


def main():
    resultados = []

    def comprobar(nombre, ok, detalle=""):
        resultados.append(ok)
        print(f"{'OK ' if ok else 'MAL'} {nombre:58} {detalle}")

    ratón = wt.POINT()
    user32.GetCursorPos(ctypes.byref(ratón))
    try:
        # 1) Aparece en la pantalla donde está el ratón (pruebo en todas)
        for (izq, arr, der, aba) in monitores():
            if get("/api/estado").get("visible"):
                post("/api/ocultar_orbe")
                time.sleep(0.5)
            user32.SetCursorPos((izq + der) // 2 + 300, (arr + aba) // 2 + 200)
            post("/api/despertar", {"mostrar": True, "activar": False})
            time.sleep(1.2)
            z = C.rect("J.A.R.V.I.S.")
            cx, cy = (z["left"] + z["width"] // 2, z["top"] + z["height"] // 2) if z else (-1, -1)
            comprobar(f"aparece centrada en la pantalla del ratón ({izq},{arr})", bool(z) and izq <= cx < der and arr <= cy < aba
                      and abs(cx - (izq + der) // 2) < 80, f"centro {cx},{cy}")
        h = C.buscar("J.A.R.V.I.S.")
        ex = user32.GetWindowLongW(h, -20)
        comprobar("sin botón en la barra de tareas (WS_EX_TOOLWINDOW, sin APPWINDOW)", bool(ex & 0x80) and not ex & 0x40000, hex(ex))
        comprobar("encima de todo mientras se ve (WS_EX_TOPMOST)", bool(ex & 0x8), hex(ex))
        d = diag()
        comprobar("el orbe se dibuja (página visible, fps > 0)", d.get("visibilidad") == "visible" and d.get("info", {}).get("fps", 0) > 0,
                  f"{d.get('visibilidad')} · {d.get('info', {}).get('fps')} fps")

        # 2) Clics: fuera del orbe atraviesan, dentro son para Jarvis
        z = C.rect("J.A.R.V.I.S.")
        esquina = (z["left"] + 15, z["top"] + 15)
        centro = (z["left"] + z["width"] // 2, z["top"] + z["height"] // 2)
        user32.SetCursorPos(*esquina)
        time.sleep(0.3)
        comprobar("un clic fuera del orbe va a la ventana de detrás", raiz_en(*esquina) != h, f"ventana bajo el ratón {raiz_en(*esquina)}")
        user32.SetCursorPos(*centro)
        time.sleep(0.3)
        comprobar("un clic sobre el orbe es para Jarvis", raiz_en(*centro) == h)

        # 3) Clic derecho: panel; cerrar el panel lo oculta (no lo destruye)
        C.clic(z, z["width"] // 2, z["height"] // 2, "derecho")
        time.sleep(2.5)
        p = C.buscar("Jarvis · Panel")
        comprobar("clic derecho en el orbe abre el panel", bool(p) and bool(user32.IsWindowVisible(p)))
        if p:
            user32.PostMessageW(p, 0x10, 0, 0)  # WM_CLOSE (como pulsar la X)
            time.sleep(1.0)
            comprobar("cerrar el panel lo oculta (sigue existiendo)", bool(user32.IsWindow(p)) and not user32.IsWindowVisible(p))

        # 4) Esc: se oculta con desvanecido; oculto no se dibuja
        post("/api/despertar", {"mostrar": True, "activar": True})
        time.sleep(1.0)
        user32.SetCursorPos(*centro)
        t0 = time.time()
        user32.keybd_event(0x1B, 0, 0, 0)
        user32.keybd_event(0x1B, 0, 2, 0)
        oculto = None
        alfas = set()
        while time.time() - t0 < 3:
            k, a, f = wt.DWORD(), ctypes.c_ubyte(), wt.DWORD()
            user32.GetLayeredWindowAttributes(h, ctypes.byref(k), ctypes.byref(a), ctypes.byref(f))
            alfas.add(a.value)
            if not user32.IsWindowVisible(h):
                oculto = time.time() - t0
                break
            time.sleep(0.01)
        comprobar("Esc oculta el orbe", oculto is not None, f"en {oculto:.2f} s" if oculto else "")
        comprobar("…con desvanecido (pasa por alfas intermedios)", len([x for x in alfas if 0 < x < 255]) >= 2, f"{len(alfas)} valores de alfa")
        time.sleep(1.0)
        d = diag()
        comprobar("oculto, el orbe deja de dibujarse", not d or d.get("visibilidad") == "hidden" or d.get("info", {}).get("corriendo") is False,
                  d.get("visibilidad", "sin respuesta (página en pausa)"))
    finally:
        user32.SetCursorPos(ratón.x, ratón.y)
    print(f"\n{sum(resultados)}/{len(resultados)} comprobaciones correctas")


if __name__ == "__main__":
    main()
