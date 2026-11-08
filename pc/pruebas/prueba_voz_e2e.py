"""
Prueba de punta a punta POR VOZ, sin hablar: genera la frase con una voz sintética y se la pasa a un vigilante
(el mismo código) en lugar del micrófono, a velocidad real.

    .venv\\Scripts\\python.exe pruebas\\prueba_voz_e2e.py "Jarvis, ¿qué hora es?"

Mide: aviso (pitido) tras decir «Jarvis», ventana de Jarvis visible, y orden ejecutada (línea JARVIS en el log).
Nota: el vigilante real sigue en marcha con tu micro; esta prueba usa su propio vigilante con audio inyectado.
"""
import asyncio
import ctypes
import os
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))
os.chdir(RAIZ)
import edge_tts  # noqa: E402
import miniaudio  # noqa: E402
import numpy as np  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

import medir_velocidad as M  # noqa: E402
import vigilante as V  # noqa: E402

frase_texto = sys.argv[1] if len(sys.argv) > 1 else "Jarvis, ¿qué hora es?"


async def tts(t):
    b = bytearray()
    async for c in edge_tts.Communicate(t, "es-ES-ElviraNeural").stream():
        if c["type"] == "audio":
            b.extend(c["data"])
    s = miniaudio.decode(bytes(b), output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
    return resample_poly(np.frombuffer(s.samples, np.int16).astype(np.float32), 2, 3).astype(np.int16)

frase = asyncio.run(tts(frase_texto))

# Micro falso: el vigilante cree que está abierto, pero el audio lo ponemos nosotros
V.Microfono.abrir = lambda self: (setattr(self, "stream", object()), setattr(self, "nombre", "micro de prueba"), True)[2]
V.Microfono.cerrar = lambda self: setattr(self, "stream", None)
V.Microfono.colgado = lambda self: False
V.Vigilante._gestionar_precarga = lambda self: None  # de la precarga se encarga el vigilante real

vig = V.Vigilante()
vig.icono = None
for nombre in ("evento_abrir", "evento_juego_on", "evento_juego_off"):
    setattr(vig, nombre, ctypes.windll.kernel32.CreateEventW(None, False, False, None))
marcas = {}
original = vig.avisar_que_te_oigo


def avisar(*a, **k):
    marcas.setdefault("aviso", time.time())
    original(*a, **k)


vig.avisar_que_te_oigo = avisar
_despertar, _enviar = vig.despertar, vig._enviar_frase
vig.despertar = lambda *a, **k: (marcas.setdefault("final_vosk", time.time()), _despertar(*a, **k))[1]
vig._enviar_frase = lambda c: (marcas.setdefault("frase_enviada", time.time()), _enviar(c))[1]
vig.aviso.preparar()
time.sleep(1.5)
threading.Thread(target=vig._hilo_audio, daemon=True).start()
threading.Thread(target=vig._hilo_control, daemon=True).start()
while vig.reconocedor is None:
    time.sleep(0.1)
estado = V.estado_jarvis()
print(f"Jarvis antes de la prueba: {'cerrado' if not estado else 'dormido' if estado.get('dormido') else 'despierto'}")

log = RAIZ / "datos" / "jarvis.log"
tam_log = log.stat().st_size
ruido = lambda n: (np.random.randn(n) * 60).astype(np.int16)  # noqa: E731
flujo = np.concatenate([ruido(16000), frase, ruido(40000)])
fin_jarvis = fin_frase = None
respuesta = {}


def vigilar_log():
    """En paralelo: apunta el momento exacto en que aparece la respuesta de Jarvis en el log."""
    while "t" not in respuesta:
        nuevo = log.read_bytes()[tam_log:].decode("utf-8", "replace")
        lineas = [x for x in nuevo.splitlines() if "| JARVIS  " in x]
        if lineas:
            respuesta.update(t=time.time(), texto=lineas[0].split("JARVIS  ")[1])
        time.sleep(0.02)


threading.Thread(target=vigilar_log, daemon=True).start()
t_visible = None
for i in range(0, len(flujo) - 1599, 1600):
    vig.cola_audio.put(flujo[i:i + 1600].tobytes())
    if fin_jarvis is None and i >= 16000 + int(0.55 * 16000):
        fin_jarvis = time.time()  # ~fin de la palabra «Jarvis»
    if fin_frase is None and i >= 16000 + len(frase):
        fin_frase = time.time()
    if t_visible is None and M.ventana_jarvis_visible():
        t_visible = time.time()
    time.sleep(0.1)  # a velocidad real, como un micro
while t_visible is None and time.time() - fin_jarvis < 20:
    if M.ventana_jarvis_visible():
        t_visible = time.time()
    time.sleep(0.02)

print(f"aviso (pitido) tras acabar «Jarvis»: {marcas['aviso'] - fin_jarvis:+.2f} s")
print(f"ventana visible tras acabar «Jarvis»: {t_visible - fin_jarvis:+.2f} s" if t_visible else "ventana NO visible")
limite = time.time() + 120
for clave in ("final_vosk", "frase_enviada"):
    if clave in marcas:
        print(f"{clave}: {marcas[clave] - fin_frase:+.2f} s respecto al final de la frase")
while time.time() < limite:
    if "t" in respuesta:
        print(f"orden respondida {respuesta['t'] - fin_frase:+.2f} s después de acabar la frase: {respuesta['texto']}")
        break
    time.sleep(0.05)
else:
    print("sin respuesta en 120 s")
print("\n".join(x for x in log.read_bytes()[tam_log:].decode("utf-8", "replace").splitlines()[-12:]))
