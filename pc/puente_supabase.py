"""
Puente Supabase -> Jarvis del PC.

La app del móvil inserta filas en la tabla «comandos» (estado «pendiente»). Este proceso:
  1. Se suscribe por Realtime a las filas nuevas (y cada 30 s mira también la tabla, por si se perdió algo).
  2. Al arrancar recoge las «pendiente» que llegaron con el PC apagado (las de más de 1 h se marcan caducadas).
  3. Para cada orden: «ejecutando» -> se la pasa a Jarvis (POST 127.0.0.1:8765/api/movil, la misma lógica que la
     voz: camino rápido, escenas, apps en pantallas, modelo...) -> «hecho» o «error» con la respuesta.
  4. Si Jarvis pide confirmación («¿seguro?»), la fila queda en «confirmar» con la pregunta; la siguiente orden
     que llegue («sí» / «no») es la respuesta y el resultado se guarda en la fila original.

Va en su propio entorno (.venv-puente) para no tocar las librerías de Jarvis.
Configuración en pc/.env (nunca en git): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ALLOWED_USER_ID.
Registro en pc/datos/puente.log.
"""
import asyncio
import ctypes
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
from realtime import AsyncRealtimeClient

RAIZ = Path(__file__).resolve().parent
CADUCIDAD = timedelta(hours=1)        # pendientes más viejas que esto no se ejecutan al encender
REVISION_CADA = 30                    # segundos entre revisiones de la tabla (red de seguridad de Realtime)
ESPERA_CONFIRMACION = 35              # Jarvis espera 30 s el «sí/no»; después la pregunta caduca

# ------------------------------------------------------------------
#  Configuración y registro
# ------------------------------------------------------------------
def leer_env(ruta: Path) -> dict:
    """Lector mínimo de .env (CLAVE=valor por línea, # comentarios)."""
    datos = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                datos[clave.strip()] = valor.strip().strip('"').strip("'")
    return datos


ENV = leer_env(RAIZ / ".env")
URL = ENV.get("SUPABASE_URL", "").rstrip("/")
CLAVE = ENV.get("SUPABASE_SERVICE_ROLE_KEY", "")
USUARIO = ENV.get("ALLOWED_USER_ID", "")
JARVIS = ENV.get("JARVIS_URL", "http://127.0.0.1:8765/api/movil")

(RAIZ / "datos").mkdir(exist_ok=True)
log = logging.getLogger("puente")
log.setLevel(logging.INFO)
_manejador = RotatingFileHandler(RAIZ / "datos" / "puente.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_manejador.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
log.addHandler(_manejador)
if sys.stdout:  # con python.exe también se ve en la consola (con pythonw no hay consola)
    log.addHandler(logging.StreamHandler(sys.stdout))

CABECERAS = {"apikey": CLAVE, "Content-Type": "application/json"}
if CLAVE.startswith("eyJ"):  # clave service_role clásica (JWT): también va como Authorization
    CABECERAS["Authorization"] = f"Bearer {CLAVE}"
REST = f"{URL}/rest/v1/comandos"


# ------------------------------------------------------------------
#  Tabla «comandos» (REST de Supabase con la service role, que se salta RLS)
# ------------------------------------------------------------------
async def pendientes(http: httpx.AsyncClient) -> list:
    r = await http.get(REST, params={"estado": "eq.pendiente", "user_id": f"eq.{USUARIO}",
                                     "order": "created_at.asc", "select": "*"})
    r.raise_for_status()
    return r.json()


async def caducar_viejas(http: httpx.AsyncClient):
    limite = (datetime.now(timezone.utc) - CADUCIDAD).isoformat()
    r = await http.patch(REST, params={"estado": "eq.pendiente", "user_id": f"eq.{USUARIO}", "created_at": f"lt.{limite}"},
                         json={"estado": "error", "respuesta": "Caducada: llegó con el PC apagado hace más de 1 hora y no la he ejecutado."},
                         headers={"Prefer": "return=representation"})
    r.raise_for_status()
    for fila in r.json():
        log.info(f"CADUCADA  {fila['texto']!r} ({fila['created_at']})")


async def reclamar(http: httpx.AsyncClient, id_: str) -> bool:
    """Pasa a «ejecutando» solo si seguía «pendiente» (si hay dos puentes, solo uno la coge)."""
    r = await http.patch(REST, params={"id": f"eq.{id_}", "estado": "eq.pendiente"},
                         json={"estado": "ejecutando"}, headers={"Prefer": "return=representation"})
    r.raise_for_status()
    return bool(r.json())


async def guardar(http: httpx.AsyncClient, id_: str, estado: str, respuesta: str, acciones=None):
    r = await http.patch(REST, params={"id": f"eq.{id_}"},
                         json={"estado": estado, "respuesta": respuesta, "acciones": acciones or []})
    r.raise_for_status()


# ------------------------------------------------------------------
#  Jarvis
# ------------------------------------------------------------------
async def pedir_a_jarvis(texto: str) -> dict:
    """Le pasa la orden a Jarvis. Si no está en marcha (p. ej. reiniciándose), lo reintenta 20 s."""
    limite = time.time() + 20
    async with httpx.AsyncClient(timeout=httpx.Timeout(125, connect=3)) as cliente:
        while True:
            try:
                r = await cliente.post(JARVIS, json={"text": texto})
                r.raise_for_status()
                return r.json()
            except httpx.ConnectError:
                if time.time() > limite:
                    raise RuntimeError("Jarvis no está en marcha en el PC (¿modo juego o cerrado?).")
                await asyncio.sleep(2)


_confirmando = None  # (id de la fila que espera «sí/no», hora límite)


async def ejecutar(http: httpx.AsyncClient, fila: dict):
    global _confirmando
    id_, texto = fila["id"], fila["texto"]
    if fila.get("user_id") != USUARIO:
        log.warning(f"IGNORADA  fila de otro usuario ({fila.get('user_id')})")
        return
    if not await reclamar(http, id_):
        return  # ya la cogió otro o ya no está pendiente
    log.info(f"ORDEN  {texto!r}")
    inicio = time.time()
    try:
        r = await pedir_a_jarvis(texto)
    except Exception as e:
        log.warning(f"ERROR  {texto!r}: {e}")
        await guardar(http, id_, "error", str(e) or e.__class__.__name__)
        return
    respuesta, acciones = r.get("reply") or "Hecho.", r.get("actions") or []

    # ¿Era la respuesta (sí/no) a una pregunta pendiente? Entonces el resultado es de la orden original
    if _confirmando and time.time() < _confirmando[1]:
        original = _confirmando[0]
        _confirmando = None
        if r.get("confirmar"):  # vuelve a preguntar: la original sigue esperando
            _confirmando = (original, time.time() + ESPERA_CONFIRMACION)
            await guardar(http, original, "confirmar", respuesta, acciones)
        else:
            await guardar(http, original, "hecho", respuesta, acciones)
        await guardar(http, id_, "hecho", "Respuesta enviada a Jarvis.")
        log.info(f"CONFIRMACIÓN  {texto!r} -> {respuesta!r}")
        return

    if r.get("confirmar"):
        _confirmando = (id_, time.time() + ESPERA_CONFIRMACION)
        await guardar(http, id_, "confirmar", respuesta, acciones)
        log.info(f"PREGUNTA  {respuesta!r}")
        return
    await guardar(http, id_, "hecho", respuesta, acciones)
    log.info(f"HECHO  {respuesta!r} [{time.time() - inicio:.1f} s]")


async def trabajador(http: httpx.AsyncClient, cola: asyncio.Queue):
    """Ejecuta las órdenes de una en una, en el orden en que llegan."""
    while True:
        fila = await cola.get()
        try:
            await ejecutar(http, fila)
        except Exception:
            log.exception(f"Fallo con la orden {fila.get('texto')!r}")
            try:
                await guardar(http, fila["id"], "error", "Fallo interno del puente del PC.")
            except Exception:
                pass


async def revisor(http: httpx.AsyncClient, cola: asyncio.Queue):
    """Al arrancar y cada 30 s: caduca las viejas y encola las pendientes (por si Realtime perdió alguna)."""
    global _confirmando
    while True:
        try:
            await caducar_viejas(http)
            for fila in await pendientes(http):
                await cola.put(fila)
            if _confirmando and time.time() > _confirmando[1]:
                await guardar(http, _confirmando[0], "error", "No llegó tu respuesta a tiempo: cancelado.")
                log.info("CONFIRMACIÓN  caducada")
                _confirmando = None
        except Exception as e:
            log.warning(f"REVISIÓN  sin conexión con Supabase: {e}")
        await asyncio.sleep(REVISION_CADA)


# ------------------------------------------------------------------
#  Realtime (con reconexión propia si se cae internet)
# ------------------------------------------------------------------
async def escuchar(cola: asyncio.Queue):
    espera = 2
    while True:
        cliente = None
        try:
            cliente = AsyncRealtimeClient(f"{URL}/realtime/v1", CLAVE, auto_reconnect=True)
            await cliente.connect()
            canal = cliente.channel("comandos-pc")

            def al_insertar(cambio):
                fila = (cambio.get("data") or {}).get("record") or {}
                if fila.get("estado") == "pendiente":
                    cola.put_nowait(fila)

            canal.on_postgres_changes("INSERT", al_insertar, table="comandos", schema="public",
                                      filter=f"user_id=eq.{USUARIO}")
            await canal.subscribe()
            if not canal.is_joined:
                raise RuntimeError("no se pudo suscribir al canal")
            log.info("REALTIME  conectado")
            espera = 2
            caido_desde = None
            while True:  # vigilo la conexión: si lleva 15 s caída, la rehago desde cero
                await asyncio.sleep(5)
                if canal.is_joined and cliente.is_connected:
                    caido_desde = None
                elif caido_desde is None:
                    caido_desde = time.time()
                elif time.time() - caido_desde > 15:
                    raise RuntimeError("conexión caída")
        except Exception as e:
            log.warning(f"REALTIME  {e}; reintento en {espera} s")
        finally:
            if cliente:
                try:
                    await asyncio.wait_for(cliente.close(), 5)
                except Exception:
                    pass
        await asyncio.sleep(espera)
        espera = min(espera * 2, 60)


async def principal():
    cola = asyncio.Queue()
    async with httpx.AsyncClient(headers=CABECERAS, timeout=20) as http:
        await asyncio.gather(trabajador(http, cola), revisor(http, cola), escuchar(cola))


def main():
    faltan = [n for n, v in (("SUPABASE_URL", URL), ("SUPABASE_SERVICE_ROLE_KEY", CLAVE), ("ALLOWED_USER_ID", USUARIO)) if not v]
    if faltan:
        log.error(f"Faltan en pc/.env: {', '.join(faltan)}")
        sys.exit(1)
    # Una sola copia del puente a la vez (mutex de Windows, sin abrir puertos)
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\JarvisPuenteSupabase")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        log.info("Ya hay un puente en marcha: salgo")
        return
    log.info(f"PUENTE  arrancado ({URL}, usuario {USUARIO[:8]}…)")
    asyncio.run(principal())


if __name__ == "__main__":
    main()
