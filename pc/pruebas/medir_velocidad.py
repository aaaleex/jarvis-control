"""
Mide la velocidad y el consumo de Jarvis de punta a punta (lo usé antes y después de cada cambio).

    .venv\\Scripts\\python.exe pruebas\\medir_velocidad.py ETIQUETA

Qué hace (con la voz de Jarvis silenciada durante la prueba):
  1. Cierra Jarvis si estaba abierto y saca el modelo de la memoria de Ollama (arranque en frío).
  2. Pulsa Ctrl+Alt+J de verdad (el vigilante lo recibe igual que si lo pulsaras tú) y cronometra
     hasta que la ventana de Jarvis es visible en pantalla.
  3. Manda una orden simple y una conversacional en cuanto Jarvis la acepta (= primera respuesta en frío).
  4. Repite las órdenes con todo cargado (= en caliente).
  5. Mide la RAM del vigilante, de Jarvis (Python + procesos de WebView2) y de Ollama.
Los resultados se añaden a pruebas/mediciones.json.
"""
import asyncio
import ctypes
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil
import websockets

RAIZ = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8765"
OLLAMA = "http://127.0.0.1:11434"
user32 = ctypes.windll.user32


def http(ruta, datos=None, espera=2.0, base=URL):
    try:
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        pet = urllib.request.Request(base + ruta, data=cuerpo, method="POST" if cuerpo is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(pet, timeout=espera) as r:
            return json.loads(r.read() or b"{}")
    except Exception:
        return None


def ventana_jarvis_visible() -> bool:
    """¿Hay en pantalla una ventana «J.A.R.V.I.S.» del proceso de Jarvis? (no vale el orbe del vigilante)"""
    import ctypes.wintypes as wt
    pids = {p.pid for p in procesos_jarvis()}
    if not pids:
        return False
    vista = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def revisar(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            b = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, b, 64)
            if b.value == "J.A.R.V.I.S.":
                vista.append(hwnd)
        return True
    user32.EnumWindows(revisar, 0)
    return bool(vista)


def pulsar_atajo():
    """Ctrl+Alt+J pulsado de verdad (keybd_event): llega al RegisterHotKey del vigilante."""
    for vk in (0x11, 0x12, 0x4A):
        user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    for vk in (0x4A, 0x12, 0x11):
        user32.keybd_event(vk, 0, 2, 0)


def modelo_ollama():
    from ruamel.yaml import YAML
    c = YAML().load(open(RAIZ / "config.yaml", encoding="utf-8"))
    return c["cerebro"]["ollama"]["modelo"]


def procesos_jarvis():
    """Proceso de Jarvis (dueño del puerto 8765) y todos sus hijos (WebView2)."""
    for c in psutil.net_connections("tcp"):
        if c.laddr and c.laddr.port == 8765 and c.status == "LISTEN" and c.pid:
            p = psutil.Process(c.pid)
            return [p] + p.children(recursive=True)
    return []


def ram_mb(procesos):
    total_rss = total_privada = 0
    for p in procesos:
        try:
            m = p.memory_full_info()
            total_rss += m.rss
            total_privada += m.uss
        except Exception:
            pass
    return round(total_rss / 2**20), round(total_privada / 2**20)


def vigilante():
    for p in psutil.process_iter(["name", "cmdline"]):
        if p.info["name"] in ("pythonw.exe", "python.exe") and any("vigilante.py" in a for a in (p.info["cmdline"] or [])):
            if p.memory_info().rss > 30 * 2**20:  # el lanzador del venv ocupa ~6 MB: buscamos el proceso real
                return p
    return None


def ollama_ram():
    total = 0
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower().startswith("ollama"):
            try:
                total += p.memory_info().rss
            except Exception:
                pass
    return round(total / 2**20)


def vram_mb():
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=8).stdout.strip())
    except Exception:
        return None


async def orden(ws, texto, limite=240):
    """Manda una orden por el chat y cronometra el primer texto y la respuesta final."""
    t0 = time.time()
    await ws.send(json.dumps({"tipo": "texto", "texto": texto}))
    primero = herramienta = None
    while time.time() - t0 < limite:
        try:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=limite))
        except asyncio.TimeoutError:
            break
        if ev["tipo"] == "texto_parcial" and primero is None:
            primero = time.time() - t0
        if ev["tipo"] == "herramienta_fin" and herramienta is None:
            herramienta = time.time() - t0
        if ev["tipo"] == "respuesta":
            fin = time.time() - t0
            return {"orden": texto, "accion_hecha_s": round(herramienta, 2) if herramienta else None,
                    "primer_texto_s": round(primero or fin, 2), "respuesta_s": round(fin, 2), "texto": ev["texto"][:120]}
    return {"orden": texto, "error": "sin respuesta"}


async def medir(etiqueta):
    resultado = {"etiqueta": etiqueta, "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
    # --- 0. estado de partida: Jarvis cerrado (o dormido) y modelo fuera de memoria ---
    estado = http("/api/estado")
    if estado and not estado.get("dormido"):
        http("/api/cerrar", {})
        time.sleep(2)
    http("/api/generate", {"model": modelo_ollama(), "keep_alive": 0}, espera=20, base=OLLAMA)
    # Si la precarga está activa, esperamos a que el vigilante tenga listo el Jarvis dormido
    from ruamel.yaml import YAML
    if YAML().load(open(RAIZ / "config.yaml", encoding="utf-8"))["interfaz"].get("precargar"):
        for _ in range(120):
            e = http("/api/estado")
            if e and e.get("dormido"):
                break
            time.sleep(0.5)
        time.sleep(8)  # que termine de cargar la página oculta
    time.sleep(3)
    vig = vigilante()
    if vig:
        psutil.cpu_percent()
        resultado["vigilante_ram_mb"] = ram_mb([vig])
    if http("/api/estado"):  # proceso de interfaz precargado (dormido)
        resultado["dormido_ram_mb"] = ram_mb(procesos_jarvis())
    resultado["ollama_reposo_ram_mb"] = ollama_ram()
    resultado["vram_reposo_mb"] = vram_mb()

    # --- 1. atajo -> ventana visible ---
    t0 = time.time()
    pulsar_atajo()
    visible = None
    while time.time() - t0 < 120:
        if ventana_jarvis_visible():
            visible = time.time() - t0
            break
        time.sleep(0.02)
    resultado["atajo_a_ventana_visible_s"] = round(visible, 2) if visible else None

    # --- 2. órdenes en frío (se mandan en cuanto la interfaz conecta) ---
    ws = None
    for _ in range(300):
        try:
            ws = await websockets.connect("ws://127.0.0.1:8765/ws", max_size=None)
            break
        except Exception:
            await asyncio.sleep(0.1)
    await ws.recv()  # mensaje inicial
    # Las órdenes salen en cuanto la interfaz conecta: medimos desde que se pulsa el atajo
    t_orden = time.time()
    frio = [await orden(ws, "¿Qué hora es?")]
    frio[0]["desde_atajo_s"] = round(time.time() - t0, 2)
    frio.append(await orden(ws, "Hola, ¿qué tal estás?"))
    frio[1]["desde_atajo_s"] = round(time.time() - t0, 2)
    resultado["frio"] = frio
    for _ in range(600):
        e = http("/api/estado")
        if e and e.get("listo"):
            break
        await asyncio.sleep(0.1)
    resultado["oido_listo_s"] = round(time.time() - t0, 1)
    await asyncio.sleep(1)
    # --- 3. en caliente ---
    caliente = []
    for texto in ("¿Qué hora es?", "Hola, ¿qué tal estás?", "Cuéntame en una frase un dato curioso sobre los pulpos.",
                  "¿Qué día de la semana es hoy?", "Sube el volumen un poco", "Baja el volumen un poco",
                  "¿Por qué el cielo es azul? Contesta en una frase."):
        caliente.append(await orden(ws, texto))
        await asyncio.sleep(1.5)
    resultado["caliente"] = caliente
    await ws.close()
    resultado["jarvis_abierto_ram_mb"] = ram_mb(procesos_jarvis())
    resultado["ollama_cargado_ram_mb"] = ollama_ram()
    resultado["vram_cargado_mb"] = vram_mb()
    return resultado


def main():
    etiqueta = sys.argv[1] if len(sys.argv) > 1 else "medicion"
    config = RAIZ / "config.yaml"
    copia = RAIZ / "pruebas" / "config.durante_prueba.yaml"
    shutil.copy2(config, copia)
    texto = config.read_text(encoding="utf-8")
    # Voz de Jarvis silenciada durante la prueba (se restaura al acabar)
    config.write_text(texto.replace("  activada: true", "  activada: false", 1), encoding="utf-8")
    http("/api/cerrar", {})  # el Jarvis dormido se recrea ya con la voz silenciada
    time.sleep(2)
    try:
        resultado = asyncio.run(medir(etiqueta))
    finally:
        shutil.copy2(copia, config)
        copia.unlink()
        http("/api/cerrar", {})
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    ruta = RAIZ / "pruebas" / "mediciones.json"
    todas = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    todas.append(resultado)
    ruta.write_text(json.dumps(todas, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
