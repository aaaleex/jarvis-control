"""
Prueba de las herramientas nuevas del PC a través del Jarvis REAL (órdenes por el chat, como si las escribieras).
    .venv\\Scripts\\python.exe pruebas\\prueba_pc.py
Necesita Jarvis y el vigilante en marcha, con la voz desactivada (no hace ruido).

Solo usa archivos que crea ella misma en Documentos\\Jarvis\\prueba_pc (y los borra al final). Deja como estaban
el portapapeles, el micrófono, el volumen de las apps y el brillo. No escribe en Obsidian (eso se prueba aparte
con la función sustituida). Cierra lo que abre (Bloc de notas, ventanas del Explorador).
"""
import asyncio
import ctypes
import json
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import pyperclip
import websockets

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))
import medir_velocidad as M  # noqa: E402

LOG = RAIZ / "datos" / "jarvis.log"
LOG_VIG = RAIZ / "datos" / "vigilante.log"
user32 = ctypes.windll.user32
resultados = []
INICIO = time.time()


def comprobar(nombre, ok, detalle=""):
    resultados.append(bool(ok))
    print(f"{'OK ' if ok else 'MAL'} {nombre:55} {str(detalle)[:110]}", flush=True)


async def orden(ws, texto, confirmar=None, limite=90):
    """Manda una orden por el chat y devuelve la respuesta. Si Jarvis pide confirmación, contesta confirmar (sí/no)."""
    await ws.send(json.dumps({"tipo": "texto", "texto": texto}))
    t0 = time.time()
    while time.time() - t0 < limite:
        try:
            d = json.loads(await asyncio.wait_for(ws.recv(), timeout=limite))
        except asyncio.TimeoutError:
            break
        if d.get("tipo") == "confirmar":
            await ws.send(json.dumps({"tipo": "confirmar", "si": bool(confirmar)}))
        if d.get("tipo") == "respuesta":
            return d.get("texto", "")
    return ""


def ventanas_de(proceso):
    import ventanas
    return [v for v in ventanas.ventanas_visibles() if (v.get("proceso") or "").lower() == proceso]


async def main():
    import pc
    docs = pc.carpeta_conocida("documentos")
    base = docs / "Jarvis" / "prueba_pc"
    shutil.rmtree(base, ignore_errors=True)
    (base / "destino").mkdir(parents=True)
    (base / "factura_prueba_jarvis.pdf").write_bytes(b"%PDF-1.4\n% prueba de Jarvis\n")
    (base / "informe_prueba_jarvis.txt").write_text("Informe de prueba de Jarvis.", encoding="utf-8")
    portapapeles_antes = pyperclip.paste()
    explorador_antes = {v["hwnd"] for v in ventanas_de("explorer.exe")}
    notepad_antes = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "notepad.exe"}

    try:
        await _pruebas(base, explorador_antes, notepad_antes)
    finally:
        # --- limpieza (pase lo que pase) ---
        pyperclip.copy(portapapeles_antes)
        shutil.rmtree(base, ignore_errors=True)
        import herramientas
        for c in (herramientas.carpeta_permitida() / "capturas").glob(f"captura_{datetime.now():%Y%m%d}_*.png"):
            if c.stat().st_mtime > INICIO:
                c.unlink()
        pc.borrar_rutina_programada("dime la hora")
        pc.borrar_recordatorio("sacar la prueba del horno")
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() == "notepad.exe" and p.pid not in notepad_antes:
                p.kill()
        M.http("/api/ocultar_orbe", {})
    print(f"\n{sum(resultados)}/{len(resultados)} comprobaciones correctas")


async def _pruebas(base, explorador_antes, notepad_antes):
    import pc
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        for _ in range(60):
            if (M.http("/api/estado") or {}).get("listo"):
                break
            M.http("/api/despertar", {"mostrar": False, "activar": False})
            await asyncio.sleep(1)

        # --- archivos ---
        r = await orden(ws, f"busca el pdf de factura prueba jarvis")
        comprobar("busca el pdf de… (encuentra mi archivo de prueba)", "factura_prueba_jarvis.pdf" in r, r)
        r = await orden(ws, "busca los archivos que se llaman informe prueba jarvis de hoy")
        comprobar("busca archivos por nombre y fecha", "informe_prueba_jarvis.txt" in r, r)
        r = await orden(ws, "¿qué he descargado hoy?")
        comprobar("qué he descargado", r.startswith(("Lo último", "La carpeta")), r)
        r = await orden(ws, f"busca los archivos que se llaman informe prueba jarvis")
        r = await orden(ws, "abre la carpeta del primero")
        time.sleep(2.0)
        nuevas = [v for v in ventanas_de("explorer.exe") if v["hwnd"] not in explorador_antes]
        comprobar("abre la carpeta del primero (Explorador)", bool(nuevas), r)
        for v in nuevas:
            user32.PostMessageW(v["hwnd"], 0x10, 0, 0)
        r = await orden(ws, f"copia el primero a la carpeta {base / 'destino'}")
        comprobar("copia el 1 a una carpeta", (base / "destino" / "informe_prueba_jarvis.txt").exists(), r)
        await orden(ws, "busca el pdf de factura prueba jarvis")
        r = await orden(ws, f"mueve el primero a la carpeta {base / 'destino'}", confirmar=False)
        comprobar("mover pide confirmación y con «no» no toca nada", (base / "factura_prueba_jarvis.pdf").exists() and "no" in r.lower(), r)
        r = await orden(ws, f"mueve el primero a la carpeta {base / 'destino'}", confirmar=True)
        comprobar("…y con «sí» lo mueve", (base / "destino" / "factura_prueba_jarvis.pdf").exists(), r)

        # --- sistema ---
        r = await orden(ws, "¿cuánto espacio me queda en el disco?")
        comprobar("espacio en disco", "libres" in r, r)
        r = await orden(ws, "¿cuánta batería me queda?")
        comprobar("batería", "bater" in r.lower(), r)
        r = await orden(ws, "¿qué programa está consumiendo más memoria?")
        comprobar("qué consume más RAM", "RAM" in r, r)
        r = await orden(ws, "qué está consumiendo tanta cpu")
        comprobar("qué consume más CPU", "CPU" in r, r)
        r = await orden(ws, "¿qué apps tengo abiertas?")
        comprobar("apps abiertas", "abiertas" in r, r)
        micro = pc.microfono("consultar")
        r1 = await orden(ws, "silencia el micro")
        silenciado = pc.microfono("consultar")
        r2 = await orden(ws, "activa el micrófono")
        comprobar("silencia y activa el micro (vuelve a como estaba)", "silenciado" in silenciado and pc.microfono("consultar") == micro, f"{r1} / {r2}")
        sesiones = [s.Process.name() for s in pc._sesiones_audio()]
        app = next((n.removesuffix(".exe") for n in sesiones if n.lower() in ("spotify.exe", "discord.exe", "chrome.exe")), None)
        if app:
            antes = pc.volumen_app(app, "consultar")
            r1 = await orden(ws, f"baja el volumen de {app}")
            r2 = await orden(ws, f"sube el volumen de {app}")
            comprobar(f"volumen de {app} (baja y sube: queda igual)", pc.volumen_app(app, "consultar") == antes, f"{r1} / {r2}")
        b = pc.brillo("consultar")
        m = re.findall(r"pantalla (\d+) al (\d+)%", b)
        if m:
            r = pc.brillo("fijar", int(m[0][1]))  # al mismo valor: comprueba que el monitor acepta la orden, sin cambiar nada
            comprobar("brillo por DDC/CI (fijado al valor que ya tenía)", "No he podido" not in r, r)
        r = await orden(ws, "¿qué plan de energía tengo?")
        comprobar("plan de energía", "Plan de energía" in r, r)

        # --- cerrar un proceso (uno que abro yo: el Bloc de notas) ---
        if not notepad_antes:
            import subprocess
            p = subprocess.Popen(["notepad.exe"])
            time.sleep(1.5)
            r = await orden(ws, "mata el proceso de notepad", confirmar=True)
            time.sleep(1.0)
            vivos = [x for x in psutil.process_iter(["name"]) if (x.info["name"] or "").lower() == "notepad.exe"]
            comprobar("mata el proceso (con confirmación «sí»)", not vivos, r)
            for x in vivos:
                x.kill()
        r = await orden(ws, "mata el proceso de explorer", confirmar=True)
        comprobar("no cierra procesos de Windows (explorer)", "no lo cierro" in r, r)

        # --- portapapeles ---
        pyperclip.copy("La fotosíntesis es el proceso por el que las plantas transforman la luz del sol, el agua y el "
                       "dióxido de carbono en glucosa y oxígeno. Ocurre en los cloroplastos gracias a la clorofila.")
        r = await orden(ws, "resume lo que he copiado")
        comprobar("resume lo copiado (modelo)", len(r) > 20 and "No hay" not in r, r)
        pyperclip.copy("Buenos días, la reunión empieza a las diez.")
        r = await orden(ws, "traduce lo que he copiado al inglés")
        comprobar("traduce lo copiado al inglés", re.search(r"meeting|morning|ten", r, re.I), r)
        pyperclip.copy("texto de prueba de Jarvis para Obsidian")
        import obsidian
        original, guardado = obsidian.captura_rapida, []
        obsidian.captura_rapida = lambda t: guardado.append(t) or "ok"   # sin tocar tu vault
        try:
            r = pc.portapapeles_a_obsidian()
        finally:
            obsidian.captura_rapida = original
        comprobar("guarda lo copiado en el Inbox (función sustituida)", guardado == ["texto de prueba de Jarvis para Obsidian"], r)

        # --- pantalla ---
        r = pc.leer_texto_pantalla("pantalla")
        comprobar("lee el texto de la pantalla (OCR de Windows)", len(r) > 20 and "No veo" not in r, r.replace("\n", " ")[:100])
        r = await orden(ws, "haz una captura de pantalla")
        comprobar("captura de pantalla", "aptura" in r, r)
        comprobar("hay una «última captura» que abrir", bool(pc._capturas_recientes()), pc._capturas_recientes()[:1])

        # --- red ---
        r = await orden(ws, "¿tengo internet?")
        comprobar("estado de la red", "Internet" in r or "internet" in r, r)
        r = await orden(ws, "haz un test de velocidad")
        comprobar("velocidad de internet", "Mbps" in r, r)
        r = await orden(ws, "¿qué vpn tengo?")
        comprobar("VPN (lista las configuradas)", "VPN" in r, r)

        # --- recordatorio y rutina programada: los dispara el VIGILANTE ---
        dentro = datetime.now() + timedelta(minutes=1)
        r = await orden(ws, f"recuérdame a las {dentro:%H:%M} sacar la prueba del horno")
        comprobar("crea un recordatorio persistente", "recordar" in r, r)
        r = await orden(ws, f"cada día a las {dentro:%H:%M} dime la hora")
        comprobar("programa una rutina diaria", "haré" in r, r)
        tam_vig, tam_log = LOG_VIG.stat().st_size, LOG.stat().st_size
        limite = time.time() + 120
        disparo_r = disparo_p = False
        while time.time() < limite and not (disparo_r and disparo_p):
            fin_lectura = time.time() + 2  # seguir leyendo la conexión mientras espero (si no, se llena y se corta)
            try:
                while time.time() < fin_lectura:
                    await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            nuevo = LOG_VIG.read_bytes()[tam_vig:].decode("utf-8", "replace")
            disparo_r = disparo_r or "RECORDATORIO  sacar la prueba del horno" in nuevo
            disparo_p = disparo_p or "PROGRAMADA  «dime la hora»" in nuevo
        for _ in range(8):
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
        jarvis_log = LOG.read_bytes()[tam_log:].decode("utf-8", "replace")
        comprobar("el vigilante dispara el recordatorio a su hora", disparo_r and "AVISO  Recordatorio: sacar la prueba del horno" in jarvis_log)
        comprobar("…y la rutina programada (Jarvis la ejecuta)", disparo_p and "USUARIO  dime la hora" in jarvis_log)
        r = await orden(ws, "borra la rutina de dime la hora")
        comprobar("borra la rutina programada", "Quitada" in r, r)


asyncio.run(main())
