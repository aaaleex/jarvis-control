"""
Prueba REAL de escenas a través de Jarvis: «vamos a jugar», «he terminado», escena con el modo juego activo
y «guarda esta disposición como...». Solo lanza las apps y comprueba sus ventanas (no pulsa nada dentro).
Al acabar deja las ventanas como estaban y borra la escena de prueba.

    .venv\\Scripts\\python.exe pruebas\\prueba_escenas.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import psutil  # noqa: E402
import websockets  # noqa: E402

import escenas  # noqa: E402
import ventanas as V  # noqa: E402

V.hacer_dpi_aware()
resultados = []
LOG_VIG = RAIZ / "datos" / "vigilante.log"


def comprobar(nombre, ok, detalle=""):
    resultados.append(ok)
    print(f"{'OK ' if ok else 'MAL'} {nombre}  {detalle}")


def pantalla_app(clave):
    vs = V.ventanas_de(V.APPS[clave])
    return V.pantalla_de_ventana(vs[0]["hwnd"])["numero"] if vs else None


def corre(proceso):
    return any((p.info["name"] or "").lower() == proceso for p in psutil.process_iter(["name"]))


async def orden(ws, texto, esperar_escena=False, limite=120):
    t0 = time.time()
    await ws.send(json.dumps({"tipo": "texto", "texto": texto}))
    respuesta = lista = None
    while time.time() - t0 < limite:
        ev = json.loads(await asyncio.wait_for(ws.recv(), limite))
        if ev["tipo"] == "respuesta" and respuesta is None:
            respuesta = time.time() - t0
            print(f"   «{texto}» -> {ev['texto']}  ({respuesta:.2f} s)")
            if not esperar_escena:
                return respuesta, None
        if ev["tipo"] == "escena_lista":
            lista = time.time() - t0
            print(f"   escena colocada en {lista:.1f} s (fallos: {ev.get('fallos')})")
            return respuesta, lista
    return respuesta, lista


async def main():
    inicial = {v["hwnd"]: v for v in V.ventanas_visibles()}
    pant_ini = {h: V.pantalla_de_ventana(h)["numero"] for h in inicial}
    import win32gui
    colocaciones = {h: win32gui.GetWindowPlacement(h) for h in inicial}
    epic_antes = corre("epicgameslauncher.exe")
    tam_log = LOG_VIG.stat().st_size
    ws = await websockets.connect("ws://127.0.0.1:8765/ws", max_size=None)
    await ws.recv()
    try:
        # 1) «Vamos a jugar»
        _, colocada = await orden(ws, "vamos a jugar", esperar_escena=True)
        comprobar("Epic Games en la pantalla principal (2)", pantalla_app("epic") == 2, f"pantalla {pantalla_app('epic')}")
        comprobar("Discord en la pantalla izquierda (1)", pantalla_app("discord") == 1, f"pantalla {pantalla_app('discord')}")
        comprobar("Spotify en la pantalla 3", pantalla_app("spotify") == 3, f"pantalla {pantalla_app('spotify')}")
        time.sleep(8)  # el vigilante mira cada 3 s si hay un juego
        nuevo_log = LOG_VIG.read_bytes()[tam_log:].decode("utf-8", "replace")
        comprobar("el vigilante NO confunde Epic/Discord con un juego", "MODO JUEGO  activado" not in nuevo_log)
        # 2) «He terminado»: cierra solo lo que abrió la escena
        await orden(ws, "he terminado")
        time.sleep(3)
        if not epic_antes:
            comprobar("Epic cerrado (lo abrió la escena)", not V.ventanas_de(V.APPS["epic"]) and not corre("epicgameslauncher.exe"))
        comprobar("Discord y Spotify siguen abiertos (ya estaban antes)", bool(V.ventanas_de(V.APPS["discord"])) and
                  bool(V.ventanas_de(V.APPS["spotify"])))
        # 3) Escena con el modo juego activo
        datos = escenas.cargar()
        datos["prueba_temporal"] = {"frases": ["escena de prueba temporal"],
                                    "pasos": [{"abrir": "calculadora", "pantalla": 3, "tamano": "mitad_derecha"},
                                              {"abrir": "bloc de notas", "pantalla": "izquierda", "tamano": "maximizar"}]}
        escenas.guardar_todo(datos)
        await orden(ws, "activa el modo juego")
        time.sleep(2.5)
        nuevo_log = LOG_VIG.read_bytes()[tam_log:].decode("utf-8", "replace")
        comprobar("modo juego activado por voz/chat en el vigilante", "MODO JUEGO  activado" in nuevo_log)
        _, colocada = await orden(ws, "escena de prueba temporal", esperar_escena=True)
        calc = [v for v in V.ventanas_visibles() if "calculadora" in V._normalizar(v["titulo"])]
        bloc = V.ventanas_de(V.APPS["bloc de notas"])
        comprobar("con modo juego: calculadora en la pantalla 3", bool(calc) and V.pantalla_de_ventana(calc[0]["hwnd"])["numero"] == 3)
        comprobar("con modo juego: bloc de notas en la pantalla 1", bool(bloc) and V.pantalla_de_ventana(bloc[0]["hwnd"])["numero"] == 1)
        await orden(ws, "he terminado")
        time.sleep(2)
        comprobar("«he terminado» cierra la calculadora y el bloc", not [v for v in V.ventanas_visibles()
                                                                       if "calculadora" in V._normalizar(v["titulo"])]
                  and not V.ventanas_de(V.APPS["bloc de notas"]))
        await orden(ws, "desactiva el modo juego")
        # 4) Guardar la disposición actual como escena
        await orden(ws, "guarda esta disposición como prueba guardada")
        guardada = escenas.cargar().get("prueba_guardada")
        comprobar("disposición guardada como escena", bool(guardada), f"{len((guardada or {}).get('pasos', []))} pasos: "
                  f"{[(p['abrir'], p['pantalla'], p['tamano']) for p in (guardada or {}).get('pasos', [])]}")
    finally:
        await ws.close()
        datos = escenas.cargar()
        for clave in ("prueba_temporal", "prueba_guardada"):
            datos.pop(clave, None)
        escenas.guardar_todo(datos)
        for v in V.ventanas_visibles():
            if v["hwnd"] not in inicial and (v["proceso"] in ("notepad.exe",) or "calculadora" in V._normalizar(v["titulo"])):
                V.cerrar(v["hwnd"])
        for h, v in inicial.items():
            if V.user32.IsWindow(h) and V.pantalla_de_ventana(h)["numero"] != pant_ini[h]:
                V.colocar(h, V.resolver_pantalla(pant_ini[h]), "maximizar" if v["maximizada"] else "normal")
            if V.user32.IsWindow(h):
                try:
                    win32gui.SetWindowPlacement(h, colocaciones[h])
                except Exception:
                    pass
        final = {v["hwnd"]: v for v in V.ventanas_visibles()}
        distintas = [v["titulo"][:30] for h, v in inicial.items()
                     if h not in final or V.pantalla_de_ventana(h)["numero"] != pant_ini[h] or final[h]["minimizada"] != v["minimizada"]]
        print(f"\nVentanas restauradas: {'sí' if not distintas else 'NO: ' + str(distintas)}; "
              f"sobran: {[v['titulo'][:30] for h, v in final.items() if h not in inicial]}")
    print(f"\n{sum(resultados)}/{len(resultados)} comprobaciones correctas")


asyncio.run(main())
