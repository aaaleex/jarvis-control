"""
Prueba del bug de duplicados («cada vez que le pido algo se pone duplicado»).

    .venv\\Scripts\\python.exe pruebas\\prueba_duplicados.py

Reproduce la situación que lo provocaba (vista en el log del 4/11 a la 01:09):
  1. Para el vigilante real y cualquier Jarvis (se vuelven a arrancar al acabar).
  2. Arranca un vigilante de prueba (el mismo código, con el micro sustituido por audio inyectado) que lanza
     su Jarvis dormido. JUSTO mientras ese proceso arranca, le llega «Jarvis, ¿qué hora es?» por voz y,
     a la vez, el atajo de teclado: es la carrera que creaba dos asistentes.
  3. Manda 19 órdenes más (9 por voz como audio y 10 por el chat): 20 en total.
  4. Comprueba: un solo asistente creado, una sola ventana de Jarvis, un solo proceso de interfaz
     y cada orden oída, ejecutada y contestada UNA vez (log y eventos de la interfaz).
La voz de Jarvis y los pitidos deben estar desactivados en config.yaml (lo comprueba).
"""
import asyncio
import ctypes
import ctypes.wintypes as wt
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))
os.chdir(RAIZ)
import edge_tts  # noqa: E402
import miniaudio  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402
import websockets  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

import medir_velocidad as M  # noqa: E402

user32 = ctypes.windll.user32
LOG = RAIZ / "datos" / "jarvis.log"
TEXTOS_VOZ = ["Jarvis, ¿qué hora es?", "¿Qué día es hoy?", "¿Qué hora es?"]
TEXTOS_CHAT = ["¿Qué hora es?", "¿Qué día es hoy?"]


def comprobar_silencio():
    from ruamel.yaml import YAML
    c = YAML().load(open(RAIZ / "config.yaml", encoding="utf-8"))
    if c["voz"]["activada"] or c["vigilante"].get("sonido_activacion", True):
        sys.exit("Pon voz.activada y vigilante.sonido_activacion a false antes de la prueba (para no hacer ruido)")


async def sintetizar(texto):
    b = bytearray()
    async for c in edge_tts.Communicate(texto, "es-ES-ElviraNeural").stream():
        if c["type"] == "audio":
            b.extend(c["data"])
    s = miniaudio.decode(bytes(b), output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
    return resample_poly(np.frombuffer(s.samples, np.int16).astype(np.float32), 2, 3).astype(np.int16)


def wav(audio):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(audio.tobytes())
    return b.getvalue()


def procesos(patron):
    """Procesos Python «reales» con ese script (el lanzador del venv crea un hijo: contamos solo el hijo)."""
    lista = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if p.info["name"] in ("python.exe", "pythonw.exe") and any(patron in a for a in p.info["cmdline"] or []):
                lista.append(p)
        except Exception:
            pass
    pids = {p.pid for p in lista}
    return [p for p in lista if not any(h.pid in pids for h in p.children())]


def ventanas_jarvis():
    """Todas las ventanas de primer nivel llamadas J.A.R.V.I.S. (visibles u ocultas, de cualquier proceso)."""
    encontradas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def revisar(h, _):
        b = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, b, 64)
        if b.value == "J.A.R.V.I.S.":
            encontradas.append(h)
        return True
    user32.EnumWindows(revisar, 0)
    return encontradas


def lineas_log(desde):
    return LOG.read_bytes()[desde:].decode("utf-8", "replace").splitlines()


def parar_todo():
    for p in procesos("vigilante.py") + procesos("jarvis.py"):
        try:
            for h in p.children(recursive=True):
                h.kill()
            p.kill()
        except Exception:
            pass
    for p in psutil.process_iter(["name", "cmdline"]):  # lanzadores del venv que queden
        try:
            if p.info["name"] in ("python.exe", "pythonw.exe") and any(
                    x in a for a in p.info["cmdline"] or [] for x in ("vigilante.py", "jarvis.py")):
                p.kill()
        except Exception:
            pass
    time.sleep(1.5)


def main():
    comprobar_silencio()
    vigilante_real = bool(procesos("vigilante.py"))
    print("Generando las frases de prueba (voz sintética, no suena nada)…")
    audios = {t: asyncio.run(sintetizar(t)) for t in TEXTOS_VOZ}
    parar_todo()

    import vigilante as V
    V.Microfono.abrir = lambda self: (setattr(self, "stream", object()), setattr(self, "nombre", "micro de prueba"), True)[2]
    V.Microfono.cerrar = lambda self: setattr(self, "stream", None)
    V.Microfono.colgado = lambda self: False
    vig = V.Vigilante()
    vig.icono = None
    for nombre in ("evento_abrir", "evento_juego_on", "evento_juego_off"):
        setattr(vig, nombre, ctypes.windll.kernel32.CreateEventW(None, False, False, None))
    vig.aviso.preparar()
    inicio_log = LOG.stat().st_size
    threading.Thread(target=vig._hilo_audio, daemon=True).start()
    threading.Thread(target=vig._hilo_control, daemon=True).start()   # lanza el Jarvis dormido (precarga)
    while vig.reconocedor is None:
        time.sleep(0.1)

    # --- La carrera: en cuanto el dormido EXISTE (aún arrancando), llega la voz y el atajo ---
    limite = time.time() + 30
    while time.time() < limite and not (vig.proceso_dormido and vig.proceso_dormido.poll() is None):
        time.sleep(0.05)
    print(f"Jarvis dormido lanzado por el vigilante de prueba (pid {vig.proceso_dormido.pid}); "
          "le hablo y pulso el atajo mientras arranca")
    ruido = lambda n: (np.random.randn(n) * 60).astype(np.int16)  # noqa: E731
    flujo = np.concatenate([ruido(4800), audios[TEXTOS_VOZ[0]], ruido(32000)])
    threading.Timer(0.6, lambda: vig.despertar(desde_atajo=False)).start()   # el atajo, a la vez que la voz
    for i in range(0, len(flujo) - 1599, 1600):
        vig.cola_audio.put(flujo[i:i + 1600].tobytes())
        time.sleep(0.1)

    # Espera a que la primera orden se conteste
    limite = time.time() + 120
    while time.time() < limite and not any("| JARVIS  " in x for x in lineas_log(inicio_log)):
        time.sleep(0.2)

    # --- 19 órdenes más: 9 por voz (audio como lo manda el vigilante) y 10 por el chat ---
    eventos = []

    async def chat():
        async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
            async def escuchar():
                async for m in ws:
                    d = json.loads(m)
                    if d.get("tipo") in ("respuesta", "usuario", "herramienta_inicio"):
                        eventos.append(d)
            tarea = asyncio.create_task(escuchar())
            await asyncio.sleep(0.5)
            for n in range(19):
                if n % 2 == 0 and n < 18:   # 9 por voz
                    texto = TEXTOS_VOZ[1 + (n // 2) % 2]
                    pet = urllib.request.Request("http://127.0.0.1:8765/api/audio?conf=1&forzar=1",
                                                 data=wav(audios[texto]), method="POST")
                    urllib.request.urlopen(pet, timeout=5).read()
                else:                       # 10 por el chat
                    await ws.send(json.dumps({"tipo": "texto", "texto": TEXTOS_CHAT[n % 2]}))
                # espera a la respuesta de ESTA orden y luego 0,8 s más por si llega duplicada
                antes = sum(1 for e in eventos if e["tipo"] == "respuesta")
                t0 = time.time()
                while time.time() - t0 < 30 and sum(1 for e in eventos if e["tipo"] == "respuesta") == antes:
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.8)
            tarea.cancel()
    asyncio.run(chat())
    time.sleep(1)

    # --- Comprobaciones ---
    lineas = lineas_log(inicio_log)
    creados = [x for x in lineas if "ARRANQUE  asistente creado" in x]
    usuario = [x for x in lineas if "| USUARIO  " in x]
    jarvis = [x for x in lineas if "| JARVIS  " in x]
    oido = [x for x in lineas if "| OÍDO  " in x]
    ejecutadas = [x for x in lineas if "| RÁPIDO  " in x or "| HERRAMIENTA  " in x]
    hilos = (M.http("/api/hilos") or {}).get("hilos", {})
    duenos_puerto = {c.pid for c in psutil.net_connections("tcp") if c.laddr and c.laddr.port == 8765 and c.status == "LISTEN"}
    resultados = [
        ("un solo asistente creado", len(creados) == 1, f"{len(creados)}"),
        ("un solo hilo escuchando el micro", hilos.get("escucha") == 1, f"{hilos.get('escucha')}"),
        ("un solo hilo de voz (síntesis)", hilos.get("sintesis") == 1, f"{hilos.get('sintesis')}"),
        ("micrófono abierto una sola vez", sum("| MICRÓFONO  " in x for x in lineas) == 1,
         f"{sum('| MICRÓFONO  ' in x for x in lineas)}"),
        ("un solo proceso de interfaz (jarvis.py)", len(procesos("jarvis.py")) == 1, f"{len(procesos('jarvis.py'))}"),
        ("un solo proceso escuchando en el puerto 8765", len(duenos_puerto) == 1, f"{duenos_puerto}"),
        ("una sola ventana J.A.R.V.I.S.", len(ventanas_jarvis()) == 1, f"{len(ventanas_jarvis())}"),
        ("20 órdenes recibidas, ni una más", len(usuario) == 20, f"{len(usuario)} líneas USUARIO"),
        ("20 órdenes ejecutadas, ni una más", len(ejecutadas) == 20, f"{len(ejecutadas)} acciones"),
        ("20 respuestas, ni una más", len(jarvis) == 20, f"{len(jarvis)} líneas JARVIS"),
        ("10 frases oídas (voz), ni una más", len(oido) == 10, f"{len(oido)} líneas OÍDO"),
        ("19 respuestas en la interfaz para 19 órdenes", sum(1 for e in eventos if e["tipo"] == "respuesta") == 19,
         f"{sum(1 for e in eventos if e['tipo'] == 'respuesta')}"),
    ]
    print()
    for nombre, ok, detalle in resultados:
        print(f"{'OK ' if ok else 'MAL'} {nombre:48} {detalle}")
    if not all(ok for _, ok, _ in resultados):
        print("\nLog de la prueba:")
        print("\n".join(lineas[-60:]))

    # --- Limpieza: cierro lo que abrí y vuelvo a poner el vigilante real ---
    M.http("/api/cerrar", {})
    vig.salir_evento.set()
    time.sleep(1)
    parar_todo()
    if vigilante_real:
        pythonw = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
        subprocess.Popen([str(pythonw), str(RAIZ / "vigilante.py")], cwd=str(RAIZ), creationflags=0x08000000)
        print("\nVigilante real arrancado de nuevo")
    print(f"\n{sum(ok for _, ok, _ in resultados)}/{len(resultados)} comprobaciones correctas")
    sys.stdout.flush()
    os._exit(0 if all(ok for _, ok, _ in resultados) else 1)


if __name__ == "__main__":
    main()
