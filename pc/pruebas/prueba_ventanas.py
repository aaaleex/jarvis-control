"""
Prueba REAL de pantallas y ventanas a través de Jarvis (proceso en segundo plano, como en el uso normal):
manda órdenes por el chat y comprueba con la lista de ventanas de Windows dónde ha quedado cada una.
Al terminar deja las ventanas como estaban (cierra lo que abrió la prueba y recoloca lo demás).

    .venv\\Scripts\\python.exe pruebas\\prueba_ventanas.py
"""
import asyncio
import ctypes
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import websockets  # noqa: E402

import ventanas as V  # noqa: E402

V.hacer_dpi_aware()
user32 = ctypes.windll.user32
resultados = []


def foto():
    """Estado de todas las ventanas: para comprobar y para restaurar al final."""
    return {v["hwnd"]: v for v in V.ventanas_visibles()}


def placement(hwnd):
    import win32gui
    return win32gui.GetWindowPlacement(hwnd)


def comprobar(nombre, ok, detalle=""):
    resultados.append((nombre, ok, detalle))
    print(f"{'OK ' if ok else 'MAL'} {nombre}  {detalle}")


def pantalla_de(hwnd):
    return V.pantalla_de_ventana(hwnd)["numero"]


def de_app(clave):
    return V.ventanas_de(V.APPS[clave])


async def orden(ws, texto, espera=8):
    await ws.send(json.dumps({"tipo": "texto", "texto": texto}))
    limite = time.time() + 60
    while time.time() < limite:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 60))
        if ev["tipo"] == "respuesta":
            print(f"   «{texto}» -> {ev['texto']}")
            break
    await asyncio.sleep(espera)


def encima(a, b):
    """¿Está la ventana a por encima de b en el orden Z?"""
    orden = [v["hwnd"] for v in V.ventanas_visibles()]
    return a in orden and b in orden and orden.index(a) < orden.index(b)


async def main():
    inicial = foto()
    pantallas_ini = {h: pantalla_de(h) for h in inicial}
    colocaciones = {h: placement(h) for h in inicial}
    orden_z = list(inicial)
    print("Ventanas al empezar:", [(v["proceso"], pantalla_de(h), "min" if v["minimizada"] else "max" if v["maximizada"] else "")
                                   for h, v in inicial.items()])
    ws = await websockets.connect("ws://127.0.0.1:8765/ws", max_size=None)
    await ws.recv()
    try:
        # 1) Abrir una app en una pantalla concreta (no estaba abierta)
        await orden(ws, "abre la calculadora en la pantalla de la derecha", 4)
        calc = [v for v in V.ventanas_visibles() if "calculadora" in V._normalizar(v["titulo"])]
        comprobar("calculadora abierta en la pantalla 3 (derecha)", bool(calc) and pantalla_de(calc[0]["hwnd"]) == 3,
                  f"pantalla {pantalla_de(calc[0]['hwnd']) if calc else '-'}")
        # 2) Mover de pantalla y mitades
        await orden(ws, "pasa la calculadora a la pantalla 2", 2)
        calc = [v for v in V.ventanas_visibles() if "calculadora" in V._normalizar(v["titulo"])]
        comprobar("calculadora movida a la pantalla 2", bool(calc) and pantalla_de(calc[0]["hwnd"]) == 2)
        await orden(ws, "cierra la calculadora", 2)
        comprobar("calculadora cerrada", not [v for v in V.ventanas_visibles() if "calculadora" in V._normalizar(v["titulo"])])

        await orden(ws, "abre el bloc de notas en la mitad izquierda de la pantalla 3", 3)
        bloc = V.ventanas_de(V.APPS["bloc de notas"])
        if bloc:
            x, y, w, h = V.rect(bloc[0]["hwnd"])
            comprobar("bloc de notas en la mitad izquierda de la pantalla 3",
                      pantalla_de(bloc[0]["hwnd"]) == 3 and abs(w - 960) < 30 and abs(x - 1920) < 15, f"rect {x},{y},{w},{h}")
            await orden(ws, "pon el bloc de notas en la mitad derecha", 2)
            x, y, w, h = V.rect(bloc[0]["hwnd"])
            comprobar("bloc de notas en la mitad derecha", abs(x - 2880) < 15 and abs(w - 960) < 30, f"rect {x},{y},{w},{h}")
        else:
            comprobar("bloc de notas abierto", False)

        # 3) Web en una ventana nueva del navegador, en la pantalla pedida
        antes_chrome = {v["hwnd"] for v in de_app("chrome")}
        await orden(ws, "abre YouTube en la pantalla de la izquierda", 4)
        nuevas = [v for v in de_app("chrome") if v["hwnd"] not in antes_chrome]
        comprobar("YouTube en una ventana nueva de Chrome en la pantalla 1 (izquierda)",
                  bool(nuevas) and pantalla_de(nuevas[0]["hwnd"]) == 1, f"{len(nuevas)} ventana(s) nueva(s)")

        # 4) Traer al frente: la nueva ventana de Chrome tapa Discord en la pantalla 1; «enséñame Discord»
        discord = de_app("discord")
        if discord and nuevas:
            comprobar("(previo) Chrome está encima de Discord", encima(nuevas[0]["hwnd"], discord[0]["hwnd"]))
            await orden(ws, "enséñame Discord", 1.5)
            fg = user32.GetForegroundWindow()
            comprobar("Discord delante y con el foco; Chrome queda detrás",
                      fg == discord[0]["hwnd"] and encima(discord[0]["hwnd"], nuevas[0]["hwnd"]),
                      f"primer plano: {V._texto(fg)[:40]!r}")
        spotify = de_app("spotify")
        if spotify:
            await orden(ws, "pon Spotify delante", 1.5)
            fg = user32.GetForegroundWindow()
            comprobar("Spotify delante y con el foco", fg == spotify[0]["hwnd"], f"primer plano: {V._texto(fg)[:40]!r}")
            await orden(ws, "muéstrame Spotify en la pantalla 3", 2)
            comprobar("Spotify traído a la pantalla 3", pantalla_de(spotify[0]["hwnd"]) == 3)
        # 5) Pestañas
        await orden(ws, "enséñame la pestaña de la clasificación", 2)
        fg = user32.GetForegroundWindow()
        comprobar("pestaña de Chrome encontrada y Chrome delante", "clasificaci" in V._texto(fg).lower(), V._texto(fg)[:50])
        # 6) Escritorio
        await orden(ws, "muéstrame el escritorio", 1.5)
        visibles = [v for v in V.ventanas_visibles() if not v["minimizada"]]
        comprobar("escritorio a la vista (ventanas minimizadas)", len(visibles) <= 2, f"{len(visibles)} sin minimizar")
        await orden(ws, "restaura las ventanas", 2)
    finally:
        await ws.close()
        # --- Dejar todo como estaba ---
        for v in V.ventanas_visibles():
            if v["hwnd"] not in inicial and (v["proceso"] in ("chrome.exe", "notepad.exe")
                                             or "calculadora" in V._normalizar(v["titulo"])):
                V.cerrar(v["hwnd"])
        time.sleep(1)
        import win32gui
        for h, pl in colocaciones.items():
            if user32.IsWindow(h):
                try:
                    win32gui.SetWindowPlacement(h, pl)
                except Exception:
                    pass
        # Las que acabaron en otra pantalla (SetWindowPlacement no basta con apps como Spotify): las devolvemos
        for h, v in inicial.items():
            if user32.IsWindow(h) and pantalla_de(h) != pantallas_ini[h]:
                V.colocar(h, V.resolver_pantalla(pantallas_ini[h]), "maximizar" if v["maximizada"] else "normal")
                if v["minimizada"]:
                    V.minimizar(h)
        for h in reversed(orden_z):  # de abajo arriba: la de más arriba queda la última
            if user32.IsWindow(h) and not user32.IsIconic(h):
                user32.SetWindowPos(h, 0, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        final = foto()
        distintas = [v["titulo"][:30] for h, v in inicial.items()
                     if h not in final or final[h]["minimizada"] != v["minimizada"] or pantalla_de(h) != pantallas_ini[h]]
        iguales = not distintas
        if distintas:
            print("No han quedado igual:", distintas)
        sobran = [v["titulo"][:30] for h, v in final.items() if h not in inicial]
        print(f"\nRestaurado: {'sí' if iguales else 'NO'}; ventanas que sobran: {sobran}")
    print(f"\n{sum(ok for _, ok, _ in resultados)}/{len(resultados)} comprobaciones correctas")


asyncio.run(main())
