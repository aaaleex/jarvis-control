"""
Recordatorios persistentes y rutinas programadas: dónde se guardan y cuáles tocan ahora.
Solo biblioteca estándar: lo usa el VIGILANTE (siempre en marcha y ligero) para dispararlos aunque Jarvis esté
cerrado. Las órdenes para crearlos/borrarlos están en pc.py.

    datos/recordatorios.json  [{"id", "texto", "cuando": "2026-11-05T10:00"}]
    datos/programadas.json    [{"id", "orden", "hora": "09:00", "dias": "diario|laborables|fines_de_semana|lunes,martes", "ultima"}]
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

DATOS = Path(__file__).resolve().parent / "datos"
RECORDATORIOS = DATOS / "recordatorios.json"
PROGRAMADAS = DATOS / "programadas.json"
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def leer(ruta: Path) -> list:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return []


def escribir(ruta: Path, datos: list):
    ruta.parent.mkdir(exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta)


def toca_hoy(dias: str, ahora: datetime) -> bool:
    return {"diario": True, "laborables": ahora.weekday() < 5, "fines_de_semana": ahora.weekday() >= 5}.get(
        dias, DIAS[ahora.weekday()] in dias.split(","))


def pendientes_ahora(ahora: datetime = None):
    """(avisos, ordenes) que tocan ahora. Los marca como hechos para no repetirlos.
    Margen de 10 minutos para las rutinas (por si el PC estaba suspendido justo a esa hora)."""
    ahora = ahora or datetime.now()
    avisos, ordenes = [], []
    lista = leer(RECORDATORIOS)
    vencidos = [r for r in lista if datetime.fromisoformat(r["cuando"]) <= ahora]
    if vencidos:
        escribir(RECORDATORIOS, [r for r in lista if r not in vencidos])
        avisos = [r["texto"] for r in vencidos]
    programadas = leer(PROGRAMADAS)
    hoy, cambio = ahora.strftime("%Y-%m-%d"), False
    for r in programadas:
        h, m = map(int, r["hora"].split(":"))
        momento = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if toca_hoy(r["dias"], ahora) and r.get("ultima") != hoy and momento <= ahora < momento + timedelta(minutes=10):
            r["ultima"] = hoy
            ordenes.append(r["orden"])
            cambio = True
    if cambio:
        escribir(PROGRAMADAS, programadas)
    return avisos, ordenes
