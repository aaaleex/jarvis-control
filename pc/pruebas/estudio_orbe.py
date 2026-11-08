"""
Estudio del orbe: lo renderiza en una ventana propia (sin Jarvis) y captura cada estado para revisarlo.

    .venv\\Scripts\\python.exe pruebas\\estudio_orbe.py CARPETA [--estilos nucleo,anillo,malla] [--fondos oscuro,claro]
                                                        [--estados reposo,escuchando,...] [--secuencia N] [--tam 520]

Por cada estilo, fondo y estado guarda CARPETA/<estilo>_<fondo>_<estado>.png (con --secuencia N, N fotogramas
seguidos cada 80 ms) y apunta en CARPETA/info.json los fps y ms por fotograma que mide el propio orbe.
Al hablar y escuchar usa voz simulada (sílabas con espectro de voz) para que la captura sea repetible.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import functools
import http.server
import json
import sys
import threading
import time
from pathlib import Path

import mss
import mss.tools
import webview

RAIZ = Path(__file__).resolve().parent.parent
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

ap = argparse.ArgumentParser()
ap.add_argument("carpeta")
ap.add_argument("--estilos", default="nucleo")
ap.add_argument("--fondos", default="oscuro")
ap.add_argument("--estados", default="reposo,escuchando,pensando,hablando,error,despertando")
ap.add_argument("--secuencia", type=int, default=1)
ap.add_argument("--tam", type=int, default=520)
ap.add_argument("--espera", type=float, default=1.6)
args = ap.parse_args()
carpeta = Path(args.carpeta)
carpeta.mkdir(parents=True, exist_ok=True)

# Servidor de archivos estático solo para la carpeta web (otro puerto: no molesta a Jarvis)
manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(RAIZ / "web"))
manejador.log_message = lambda *a: None
servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 8799), manejador)
threading.Thread(target=servidor.serve_forever, daemon=True).start()

ventana = webview.create_window("estudio-orbe", "http://127.0.0.1:8799/estudio.html", width=args.tam, height=args.tam,
                                x=200, y=150, frameless=True, on_top=True, background_color="#0b0d11")
resultados = {}


def hwnd():
    return ctypes.windll.user32.FindWindowW(None, "estudio-orbe")


def capturar(nombre):
    r = wt.RECT()
    ctypes.windll.user32.GetClientRect(hwnd(), ctypes.byref(r))
    p = wt.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd(), ctypes.byref(p))
    with mss.MSS() as s:
        img = s.grab({"left": p.x, "top": p.y, "width": r.right, "height": r.bottom})
        mss.tools.to_png(img.rgb, img.size, output=str(carpeta / f"{nombre}.png"))


def guion():
    time.sleep(2.5)
    h = hwnd()
    ctypes.windll.user32.SetWindowPos(h, ctypes.c_void_p(-1), 200, 150, args.tam, args.tam, 0x10)
    for estilo in args.estilos.split(","):
        for fondo in args.fondos.split(","):
            ventana.load_url(f"http://127.0.0.1:8799/estudio.html?estilo={estilo}&fondo={'claro' if fondo == 'claro' else fondo}")
            time.sleep(2.0)
            for estado in args.estados.split(","):
                voz = estado in ("hablando", "escuchando")
                ventana.evaluate_js(f"window.orbe && (orbe.simular({str(voz).lower()}), orbe.estado('reposo'), orbe.estado('{estado}'))")
                time.sleep(0.12 if estado == "despertando" else args.espera)
                for i in range(args.secuencia):
                    capturar(f"{estilo}_{fondo}_{estado}" + (f"_{i:02d}" if args.secuencia > 1 else ""))
                    time.sleep(0.08)
                info = ventana.evaluate_js("JSON.stringify(window.orbe ? orbe.info : {})")
                resultados[f"{estilo}_{fondo}_{estado}"] = json.loads(info or "{}")
                print(estilo, fondo, estado, resultados[f"{estilo}_{fondo}_{estado}"], flush=True)
    (carpeta / "info.json").write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    ventana.destroy()


webview.start(guion)
servidor.shutdown()
sys.exit(0)
