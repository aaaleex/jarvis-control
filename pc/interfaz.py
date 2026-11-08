"""
Interfaz de Jarvis: servidor local (FastAPI + WebSocket) y ventana propia (pywebview).
El frontend (HTML/CSS/JS puro) está en la carpeta web/.

El vigilante (vigilante.py) controla esta ventana por HTTP local:
  GET  /api/estado    ¿listo? ¿visible?
  POST /api/mostrar   muestra la ventana (y opcionalmente escucha)
  POST /api/alternar  muestra/oculta (lo usa el atajo de teclado)
  POST /api/audio     frase grabada por el vigilante («Jarvis, abre YouTube») para transcribirla y ejecutarla
  POST /api/escucha   pausa/reanuda la escucha (modo juego)
  POST /api/orden     orden de texto (briefing automático)
  POST /api/movil     orden de texto desde el móvil (app jarvis-control), devuelve {"reply", "actions"}
  POST /api/cerrar    cierra Jarvis y libera la memoria
"""
import asyncio
import io
import json
import os
import socket
import sys
import threading
import time
import wave
import webbrowser
from collections import deque

import psutil
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import nucleo
from nucleo import RAIZ, ErrorJarvis, cfg, emitir, log

WEB = RAIZ / "web"
app = FastAPI()
app.mount("/web", StaticFiles(directory=WEB), name="web")


@app.middleware("http")
async def _sin_cache_vieja(request: Request, siguiente):
    """WebView2 guardaba en caché orbe.js/app.js y seguía usando la versión antigua tras editarlos.
    'no-cache' obliga a revalidar (con ETag, en local: respuesta 304 instantánea si no ha cambiado)."""
    respuesta = await siguiente(request)
    if request.url.path.startswith("/web/"):
        respuesta.headers["Cache-Control"] = "no-cache"
    return respuesta

_clientes = set()
_bucle = None                        # bucle asyncio del servidor
_historial = deque(maxlen=80)        # para repintar la conversación si recargas la ventana
_EVENTOS_HISTORIAL = {"usuario", "respuesta", "herramienta_inicio", "herramienta_fin", "error", "aviso"}
asistente = None                     # se crea en segundo plano
_estado_carga = {"listo": False, "mensaje": "Despertando…"}
_ventana = None
_visible = False
_transparente = True                 # False si Windows no deja la ventana transparente (plan B: fondo oscuro)
_ultimo_uso = time.time()
_ultimo_estado = "reposo"
_escucha_activa = True               # False en modo juego / pausa (lo decide el vigilante)
_escuchar_cuando_listo = False
DESDE_VIGILANTE = "--vigilante" in sys.argv
# DORMIDO: la ventana ya está creada (oculta) pero sin modelos cargados. Al llamar a Jarvis solo hay que
# mostrarla (décimas de segundo) mientras Whisper y el modelo cargan en paralelo.
_dormido = "--dormido" in sys.argv
_clase_asistente = None
_usado_desde_despertar = False       # ¿se ha dado alguna orden desde que despertó? (falsas alarmas)


# ------------------------------------------------------------------
#  Puente: eventos de Jarvis (cualquier hilo) -> todos los navegadores conectados
# ------------------------------------------------------------------
def _reenviar(tipo, datos):
    if tipo in _EVENTOS_HISTORIAL:
        _historial.append({"tipo": tipo, **datos})
    if _bucle is None or not _clientes:
        return
    mensaje = json.dumps({"tipo": tipo, **datos}, ensure_ascii=False, default=str)
    for ws in list(_clientes):
        asyncio.run_coroutine_threadsafe(_enviar(ws, mensaje), _bucle)


async def _enviar(ws, mensaje):
    try:
        await ws.send_text(mensaje)
    except Exception:
        _clientes.discard(ws)


nucleo.suscribir(_reenviar)


def _tocar():
    """Marca que se acaba de usar Jarvis (para el cierre por inactividad)."""
    global _ultimo_uso
    _ultimo_uso = time.time()


def _seguir_actividad(tipo, datos):
    global _ultimo_estado, _usado_desde_despertar
    if tipo == "estado":
        _ultimo_estado = datos.get("estado", "reposo")
        if _ultimo_estado != "reposo":
            _tocar()
    elif tipo in ("usuario", "activado", "texto_parcial", "herramienta_inicio", "respuesta", "aviso"):
        _tocar()
        if tipo == "usuario":
            _usado_desde_despertar = True


nucleo.suscribir(_seguir_actividad)


def _pagina(nombre: str) -> Response:
    # Cada .js/.css lleva ?v=<fecha de modificación>: si lo edito, WebView2 no puede servir la copia vieja de su caché
    import re
    html = (WEB / nombre).read_text(encoding="utf-8")
    html = re.sub(r'(/web/[\w./-]+\.(?:js|css))"',
                  lambda m: f'{m.group(1)}?v={int((WEB / m.group(1)[5:]).stat().st_mtime)}"', html)
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/")
def inicio():
    return _pagina("index.html")   # la ventana del orbe


@app.get("/panel")
def panel():
    return _pagina("panel.html")   # ajustes, escenas, pantallas y actividad (ventana aparte)


@app.get("/favicon.ico")
def icono():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><polygon points="20,2 37,11 37,29 20,38 3,29 3,11" '
           'fill="#02060c" stroke="#00e5ff" stroke-width="2.5"/><circle cx="20" cy="20" r="7" fill="#00e5ff"/></svg>')
    return Response(svg, media_type="image/svg+xml")


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    global _bucle
    _bucle = asyncio.get_running_loop()
    await ws.accept()
    _clientes.add(ws)
    log.info(f"INTERFAZ  conectada ({len(_clientes)} cliente/s)")
    global _visible
    if _ventana is not None and not _dormido and not getattr(_ventana, "_ya_mostrada", False):
        _ventana._ya_mostrada = True
        _visible = True  # la página ya está pintada: el vigilante puede quitar el aviso «despertando»
    await ws.send_text(json.dumps({"tipo": "inicial", "ajustes": _ajustes(), "historial": list(_historial),
                                   "carga": _estado_carga, "transparente": _transparente,
                                   "dormido": _dormido and not _visible},
                                  ensure_ascii=False, default=str))
    try:
        while True:
            datos = json.loads(await ws.receive_text())
            threading.Thread(target=_mensaje_del_cliente, args=(datos,), daemon=True).start()
    except WebSocketDisconnect:
        pass
    finally:
        _clientes.discard(ws)


def _mensaje_del_cliente(datos: dict):
    """Lo que llega desde la interfaz: chat, micro, parar, confirmaciones, ajustes, ventana."""
    tipo = datos.get("tipo")
    _tocar()
    try:
        if tipo == "ventana":
            _accion_ventana(datos.get("accion"))
            return
        if tipo == "panel":
            abrir_panel(datos.get("seccion"))
            return
        if tipo == "ajuste":
            _cambiar_ajuste(datos["clave"], datos["valor"])
            return
        if tipo == "diag":
            log.info(f"DIAG  {datos.get('texto')}")
            return
        if tipo == "error_js":
            log.warning(f"INTERFAZ  error de JavaScript: {datos.get('texto')}")
            return
        if tipo == "pantallas":
            import ventanas
            emitir("pantallas", **ventanas.mapa())
            return
        if tipo == "renombrar_pantalla":
            nombres = dict(cfg("pantallas.nombres", {}) or {})
            if datos.get("nombre"):
                nombres[int(datos["numero"])] = str(datos["nombre"])
            else:
                nombres.pop(int(datos["numero"]), None)
            nucleo.cambiar_cfg("pantallas.nombres", nombres)
            import ventanas
            emitir("pantallas", **ventanas.mapa())
            return
        if tipo in ("escenas", "guardar_escena", "borrar_escena"):
            import escenas
            if tipo == "guardar_escena":
                todas = escenas.cargar() if escenas.RUTA.exists() else {}
                todas[str(datos["clave"]).strip().replace(" ", "_")] = {
                    "frases": [str(f) for f in datos.get("frases", [])],
                    "pasos": [{"abrir": p["abrir"], "pantalla": int(p["pantalla"]) if str(p["pantalla"]).isdigit() else p["pantalla"],
                               "tamano": p.get("tamano", "maximizar")} for p in datos.get("pasos", [])]}
                escenas.guardar_todo(todas)
            elif tipo == "borrar_escena":
                todas = escenas.cargar()
                todas.pop(datos.get("clave"), None)
                escenas.guardar_todo(todas)
            emitir("escenas", lista=escenas.lista())
            return
        if asistente is None:
            if _dormido:
                despertar(mostrar=False)
            limite = time.time() + 60  # la orden espera a que Jarvis termine de despertar (no se pierde)
            while asistente is None and time.time() < limite:
                time.sleep(0.05)
            if asistente is None:
                emitir("aviso_ui", texto="Aún estoy despertando, dame un momento.")
                return
        if tipo == "texto":
            from voz import PALABRAS_PARAR
            # «para», «calla»... escrito en el chat: lo mismo que el botón de parar (antes iba al modelo
            # y contestaba cualquier cosa)
            if datos.get("texto", "").lower().strip(" .,!¡¿?") in PALABRAS_PARAR:
                tipo = "parar"
            else:
                asistente.procesar(datos.get("texto", ""), origen="texto")
        if tipo == "parar":
            asistente.cerebro.cancelado = True
            if asistente.voz:
                asistente.voz.interrumpir()
            emitir("estado", estado="reposo")
        elif tipo == "microfono":
            if asistente.voz and asistente.voz.activa:
                asistente.voz.activar_manual()
            else:
                emitir("error", texto="El micrófono no está disponible. Escríbeme por el chat.")
        elif tipo == "confirmar":
            asistente.responder_confirmacion(bool(datos.get("si")))
        elif tipo == "rutina":
            asistente.procesar(f"Activa la rutina {datos.get('nombre')}", origen="texto")
        elif tipo == "probar_escena":
            import escenas
            texto = escenas.activar(datos.get("clave"))
            emitir("respuesta", texto=texto, rapido=True)
    except Exception as e:
        log.exception("Error atendiendo a la interfaz")
        emitir("error", texto=f"Algo ha fallado: {e}")


# ------------------------------------------------------------------
#  API para el vigilante
# ------------------------------------------------------------------
async def _json(request: Request) -> dict:
    try:
        return json.loads(await request.body() or b"{}")
    except Exception:
        return {}


@app.get("/api/estado")
def api_estado():
    return {"listo": _estado_carga["listo"], "visible": _visible, "estado": _ultimo_estado, "dormido": _dormido}


_cerrojo_arranque = threading.Lock()
_asistente_lanzado = False


def _lanzar_asistente(ClaseAsistente) -> bool:
    """Crea el asistente UNA sola vez por proceso.
    BUG DE LOS DUPLICADOS: si el vigilante despertaba al Jarvis dormido mientras la ventana aún se estaba
    creando, despertar() lanzaba un asistente y al_iniciar_gui() (que veía _dormido=False) lanzaba otro.
    Dos asistentes = dos hilos de escucha con el mismo micro: cada frase se oía, ejecutaba y contestaba dos veces."""
    global _asistente_lanzado
    with _cerrojo_arranque:
        if _asistente_lanzado:
            log.info("ARRANQUE  el asistente ya estaba creado o creándose: no creo otro")
            return False
        _asistente_lanzado = True
    threading.Thread(target=_crear_asistente, args=(ClaseAsistente,), daemon=True, name="arranque").start()
    return True


def despertar(mostrar: bool = True, activar: bool = True):
    """Sale del modo dormido: muestra la ventana al momento y carga los modelos en segundo plano."""
    global _dormido, _usado_desde_despertar
    with _cerrojo_arranque:  # varias peticiones de despertar a la vez (voz + atajo + audio): solo cuenta una
        recien_despierto = _dormido
        _dormido = False
    if recien_despierto:
        _usado_desde_despertar = False
        _estado_carga.update(listo=False, mensaje="Despertando…")
        emitir("despertando")
        log.info("DESPIERTO  cargo los modelos")
        _lanzar_asistente(_clase_asistente)
    if mostrar:
        mostrar_ventana(activar=activar)


@app.post("/api/despertar")
async def api_despertar(request: Request):
    datos = await _json(request)
    threading.Thread(target=despertar, args=(bool(datos.get("mostrar", True)), bool(datos.get("activar", True))),
                     daemon=True).start()
    return {"ok": True}


@app.post("/api/falsa_alarma")
def api_falsa_alarma():
    """El vigilante creyó oír «Jarvis» pero no era: si no se ha llegado a usar, vuelve a dormir (sale y el
    vigilante crea otro proceso dormido limpio, sin modelos en memoria)."""
    if not _usado_desde_despertar:
        log.info("FALSA ALARMA  vuelvo a dormir")
        threading.Timer(0.1, _apagar).start()
    return {"ok": True}


@app.post("/api/mostrar")
async def api_mostrar(request: Request):
    datos = await _json(request)
    threading.Thread(target=despertar, daemon=True).start()
    if datos.get("escuchar"):
        threading.Thread(target=mostrar_ventana, args=(True,), daemon=True).start()
    return {"ok": True}


@app.post("/api/panel")
async def api_panel(request: Request):
    """Menú del icono de la bandeja › «Ajustes, escenas y pantallas»."""
    datos = await _json(request)
    if _dormido:
        threading.Thread(target=despertar, kwargs={"mostrar": False}, daemon=True).start()
    threading.Thread(target=abrir_panel, args=(datos.get("seccion"),), daemon=True).start()
    return {"ok": True}


@app.post("/api/ocultar_orbe")
def api_ocultar_orbe():
    threading.Thread(target=ocultar_ventana, daemon=True).start()
    return {"ok": True}


@app.post("/api/alternar")
def api_alternar():
    if _visible and not _dormido:
        threading.Thread(target=ocultar_ventana, daemon=True).start()
    else:
        threading.Thread(target=despertar, daemon=True).start()
        threading.Thread(target=mostrar_ventana, args=(True,), daemon=True).start()
    return {"ok": True}


@app.post("/api/audio")
async def api_audio(request: Request, conf: float = 0.0, forzar: int = 0):
    datos = await request.body()
    if _dormido:
        threading.Thread(target=despertar, daemon=True).start()
    threading.Thread(target=_procesar_audio, args=(datos, conf, bool(forzar)), daemon=True).start()
    return {"ok": True}


@app.post("/api/escucha")
async def api_escucha(request: Request):
    global _escucha_activa
    _escucha_activa = bool((await _json(request)).get("activa", True))
    if asistente and asistente.voz:
        asistente.voz.pausar(not _escucha_activa)
    log.info(f"ESCUCHA  {'activa' if _escucha_activa else 'en pausa (modo juego/pausa)'}")
    return {"ok": True}


@app.post("/api/aviso")
async def api_aviso(request: Request):
    """Recordatorio que dispara el vigilante: aparece el orbe (sin quitarte el foco) y Jarvis lo dice."""
    texto = (await _json(request)).get("texto", "")
    threading.Thread(target=despertar, kwargs={"mostrar": True, "activar": False}, daemon=True).start()
    threading.Thread(target=_cuando_listo, args=(lambda: nucleo.avisar(texto),), daemon=True).start()
    return {"ok": True}


@app.post("/api/orden")
async def api_orden(request: Request):
    datos = await _json(request)
    texto = datos.get("texto", "")
    if _dormido or datos.get("mostrar"):
        threading.Thread(target=despertar, kwargs={"mostrar": bool(datos.get("mostrar")), "activar": False}, daemon=True).start()
    threading.Thread(target=_cuando_listo, args=(lambda: asistente.procesar(texto, origen="sistema"),), daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------
#  Móvil (app jarvis-control): orden de texto CON respuesta
#  El servidor del móvil (Node, en este PC) envía POST {"text": "..."} y espera {"reply": "...", "actions": [...]}.
#  La orden va a asistente.procesar(), lo mismo que la voz o el chat. Igual que con Telegram: si Jarvis pide
#  confirmación («¿seguro?»), la pregunta vuelve al móvil y el siguiente mensaje («sí»/«no») la contesta.
# ------------------------------------------------------------------
class _OrdenMovil:
    def __init__(self, texto: str):
        self.texto = texto
        self.acciones = []        # herramientas que ha usado Jarvis (se ven en el móvil)
        self.errores = []
        self.pregunta = None      # confirmación pendiente
        self.respuesta = None
        self.hecho = threading.Event()
        nucleo.suscribir(self._al_evento)
        threading.Thread(target=self._ejecutar, daemon=True, name="movil").start()

    def _ejecutar(self):
        try:
            self.respuesta = asistente.procesar(self.texto, origen="movil")
        except Exception as e:
            log.exception("MÓVIL  fallo atendiendo la orden")
            self.errores.append(f"Algo ha fallado: {e}")
        finally:
            try:
                nucleo._suscriptores.remove(self._al_evento)
            except ValueError:
                pass
            self.hecho.set()

    def _al_evento(self, tipo, datos):
        if tipo == "herramienta_fin" and datos.get("resultado") != "(paso al modelo)":
            self.acciones.append({"label": str(datos.get("nombre", "")).replace("_", " ").capitalize(),
                                  "detail": str(datos.get("resultado", ""))[:200],
                                  "status": "ok" if datos.get("ok") else "error"})
        elif tipo == "confirmar":
            self.pregunta = datos.get("pregunta", "¿Seguro?")
        elif tipo == "error":
            self.errores.append(str(datos.get("texto", "")))

    def esperar(self, segundos: float = 110) -> dict:
        """Espera a que acabe o a que pida confirmación (el servidor del móvil corta a los 120 s)."""
        limite = time.time() + segundos
        while time.time() < limite and not self.hecho.is_set() and not self.pregunta:
            time.sleep(0.05)
        if self.hecho.is_set():
            texto = self.respuesta or " ".join(self.errores) or "Hecho."
        elif self.pregunta:
            texto = f"{self.pregunta} Responde «sí» o «no»."
        else:
            texto = "Sigo con ello, tarda más de lo normal."
        return {"reply": texto, "actions": self.acciones}


_orden_movil = None


def _atender_movil(texto: str) -> dict:
    global _orden_movil
    _tocar()
    pendiente = _orden_movil
    if pendiente and pendiente.pregunta and not pendiente.hecho.is_set():  # esperaba «sí» o «no»
        from voz import es_afirmativo
        pendiente.pregunta = None
        asistente.responder_confirmacion(es_afirmativo(texto))
        return pendiente.esperar()
    if asistente is None:  # dormido: despierta sin mostrar el orbe (no estás delante del PC)
        if _dormido:
            despertar(mostrar=False)
        _cuando_listo(lambda: None, espera=90)
        if asistente is None:
            return {"reply": "Aún estoy despertando, dame unos segundos y repítemelo."}
    from voz import PALABRAS_PARAR
    if texto.lower().strip(" .,!¡¿?") in PALABRAS_PARAR:  # «para», «calla»: como el botón de parar
        asistente.cerebro.cancelado = True
        if asistente.voz:
            asistente.voz.interrumpir()
        emitir("estado", estado="reposo")
        return {"reply": "Vale, paro.", "actions": []}
    _orden_movil = _OrdenMovil(texto)
    return _orden_movil.esperar()


@app.post("/api/movil")
async def api_movil(request: Request):
    texto = str((await _json(request)).get("text", "")).strip()[:2000]
    if not texto:
        return {"reply": "No me ha llegado ningún mensaje.", "actions": []}
    log.info(f"MÓVIL  {texto}")
    return await asyncio.to_thread(_atender_movil, texto)


@app.post("/api/demo")
async def api_demo(request: Request):
    """Solo para pruebas y capturas: pone el orbe en un estado (y un nivel de voz) sin hacer nada más."""
    datos = await _json(request)
    if datos.get("estado"):
        emitir("estado", estado=datos["estado"])
    if "nivel" in datos:
        emitir("nivel_mic", nivel=float(datos["nivel"]))
        emitir("nivel_voz", nivel=float(datos["nivel"]))
    if "simular" in datos:  # voz simulada dentro del orbe (sílabas con espectro de voz), para capturas
        emitir("demo", simular=bool(datos["simular"]))
    if "subtitulo" in datos:
        emitir("subtitulo", texto=str(datos["subtitulo"]))
    return {"ok": True}


@app.get("/api/depurar")
def api_depurar():
    """Vuelca lo que está haciendo cada hilo en datos/hilos.txt (para diagnosticar bloqueos)."""
    import faulthandler
    with open(RAIZ / "datos" / "hilos.txt", "w", encoding="utf-8") as f:
        faulthandler.dump_traceback(file=f, all_threads=True)
    return {"ok": True}


@app.get("/api/diag")
def api_diag():
    """Pide a las páginas abiertas su estado real (visible, fps del orbe...) y lo apunta en el log."""
    emitir("diag_pedir")
    return {"ok": True}


@app.get("/api/hilos")
def api_hilos():
    """Cuántos hilos hay de cada tipo (la prueba de duplicados comprueba que solo hay UNA escucha)."""
    cuenta = {}
    for h in threading.enumerate():
        cuenta[h.name] = cuenta.get(h.name, 0) + 1
    return {"hilos": cuenta, "clientes_interfaz": len(_clientes)}


@app.post("/api/cerrar")
def api_cerrar():
    threading.Timer(0.2, _apagar).start()
    return {"ok": True}


def _cuando_listo(funcion, espera: float = 300):
    """Espera a que Jarvis pueda atender (oído cargado; el modelo puede seguir calentándose)."""
    limite = time.time() + espera
    while not (asistente is not None and _estado_carga["listo"]) and time.time() < limite:
        time.sleep(0.05)
    if asistente is not None:
        funcion()


def _procesar_audio(datos_wav: bytes, conf: float, forzar: bool):
    """Frase grabada por el vigilante: la transcribe Whisper y se ejecuta como si la hubieras dicho aquí."""
    import numpy as np
    _tocar()
    log.info(f"AUDIO  frase recibida del vigilante ({len(datos_wav) / 32000:.1f}s)")
    try:
        with wave.open(io.BytesIO(datos_wav)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    except Exception:
        audio = np.zeros(0, dtype=np.int16)
    _cuando_listo(lambda: asistente.procesar_audio(audio, conf, forzar))


# ------------------------------------------------------------------
#  Ajustes (panel de la interfaz -> config.yaml)
# ------------------------------------------------------------------
VOCES = ["es-ES-AlvaroNeural", "es-ES-ElviraNeural", "es-ES-XimenaNeural", "es-MX-JorgeNeural", "es-MX-DaliaNeural"]


def _modelos_ollama() -> list:
    try:
        import ollama
        nombres = [m.model for m in ollama.Client(host=cfg("cerebro.ollama.url")).list().models]
        return [n for n in nombres if "embed" not in n and "bge" not in n and "vl" not in n]
    except Exception:
        return [cfg("cerebro.ollama.modelo")]


def _inicio_con_windows() -> bool:
    from vigilante import inicio_con_windows
    return inicio_con_windows()


def _ajustes() -> dict:
    return {
        "proveedor": cfg("cerebro.proveedor", "ollama"), "modelo": cfg("cerebro.ollama.modelo"),
        "modelos": _modelos_ollama(), "modelo_claude": cfg("cerebro.claude.modelo"),
        "motor_tts": cfg("voz.motor_tts", "edge"), "voz_edge": cfg("voz.voz_edge"), "voces": VOCES,
        "volumen_voz": cfg("voz.volumen_voz", 100), "voz_activada": cfg("voz.activada", True),
        "modo_activacion": cfg("voz.modo_activacion", "hibrido"), "umbral": cfg("voz.umbral_activacion", 0.35),
        "atajo": cfg("vigilante.atajo", "ctrl+alt+j"), "inactividad": cfg("vigilante.inactividad_minutos", 5),
        "estilo_orbe": cfg("interfaz.estilo_orbe", "nucleo"), "subtitulos": bool(cfg("interfaz.subtitulos", True)),
        "sombra_orbe": bool(cfg("interfaz.sombra_orbe", True)), "tamano_orbe": int(cfg("interfaz.tamano_orbe", 480)),
        "personalidad": cfg("personalidad", "clasico"), "personalidades": list((cfg("personalidades") or {}).keys()),
        "arrancar_con_windows": _inicio_con_windows(), "rutinas": list((cfg("rutinas") or {}).keys()),
        "nombre": cfg("usuario.nombre", ""), "ciudad": cfg("usuario.ciudad", ""),
        "orbe_calidad": cfg("interfaz.orbe_calidad", "auto"),
    }


_RUTAS_AJUSTES = {
    "proveedor": "cerebro.proveedor", "modelo": "cerebro.ollama.modelo", "motor_tts": "voz.motor_tts",
    "voz_edge": "voz.voz_edge", "volumen_voz": "voz.volumen_voz", "voz_activada": "voz.activada",
    "modo_activacion": "voz.modo_activacion", "umbral": "voz.umbral_activacion", "personalidad": "personalidad",
    "ciudad": "usuario.ciudad", "nombre": "usuario.nombre", "inactividad": "vigilante.inactividad_minutos",
    "orbe_calidad": "interfaz.orbe_calidad", "estilo_orbe": "interfaz.estilo_orbe", "subtitulos": "interfaz.subtitulos",
    "sombra_orbe": "interfaz.sombra_orbe", "tamano_orbe": "interfaz.tamano_orbe",
}


def _cambiar_ajuste(clave: str, valor):
    if clave == "arrancar_con_windows":
        from vigilante import configurar_inicio_con_windows
        configurar_inicio_con_windows(bool(valor))
    elif clave in _RUTAS_AJUSTES:
        if clave == "tamano_orbe":
            valor = max(280, min(900, int(valor or 480)))
        nucleo.cambiar_cfg(_RUTAS_AJUSTES[clave], valor)
        if clave == "tamano_orbe" and _visible:
            colocar_orbe()
        if clave in ("proveedor", "modelo") and asistente:
            try:
                asistente.cerebro.preparar()
            except ErrorJarvis as e:
                emitir("error", texto=str(e))
        if clave in ("proveedor", "modelo", "personalidad", "nombre", "ciudad") and asistente:
            # Cambian las instrucciones del modelo: rehacemos su caché ya, para que la próxima respuesta no tarde
            threading.Thread(target=asistente.cerebro.precalentar, daemon=True).start()
        if clave == "modo_activacion":
            emitir("aviso_ui", texto="El modo de activación se aplicará la próxima vez que se abra Jarvis.")
    emitir("ajustes", ajustes=_ajustes())


# ------------------------------------------------------------------
#  Datos periódicos para los paneles: sistema, clima, notas
# ------------------------------------------------------------------
def _bucle_sistema():
    """CPU/RAM/GPU para la sección Actividad del panel: solo mientras el panel está abierto."""
    from herramientas import datos_gpu
    psutil.cpu_percent()
    while True:
        time.sleep(2)
        if _panel_visible:
            memoria = psutil.virtual_memory()
            emitir("sistema", cpu=psutil.cpu_percent(), ram=memoria.percent, ram_usada=round(memoria.used / 2**30, 1),
                   ram_total=round(memoria.total / 2**30, 1), gpu=datos_gpu())


# ------------------------------------------------------------------
#  Cierre por inactividad: libera Ollama y Whisper y deja solo al vigilante
# ------------------------------------------------------------------
def _bucle_inactividad():
    while True:
        time.sleep(5)
        minutos = float(cfg("vigilante.inactividad_minutos", 5) or 0)
        if minutos <= 0 or asistente is None:
            continue
        if time.time() - _ultimo_uso < minutos * 60 or _ultimo_estado != "reposo":
            continue
        confirmacion = getattr(asistente, "_confirmacion", None)
        if confirmacion and not confirmacion["evento"].is_set():
            continue
        import herramientas
        if herramientas._temporizadores:  # hay alarmas pendientes: me quedo (oculto) para poder avisarte
            if _visible:
                log.info("INACTIVIDAD  hay temporizadores pendientes: oculto la ventana pero sigo en marcha")
                ocultar_ventana()
            continue
        log.info(f"INACTIVIDAD  {minutos:g} min sin uso: cierro Jarvis y libero memoria")
        _apagar()


# ------------------------------------------------------------------
#  Ventana
# ------------------------------------------------------------------
def _monitor_del_raton():
    """Zona útil (sin barra de tareas) y escala del monitor donde está el ratón: (x, y, ancho, alto, escala)."""
    import ctypes
    import win32api
    x, y = win32api.GetCursorPos()
    monitor = win32api.MonitorFromPoint((x, y), 2)  # MONITOR_DEFAULTTONEAREST (si no, el principal)
    izq, arr, der, aba = win32api.GetMonitorInfo(monitor)["Work"]
    dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
    try:
        ctypes.windll.shcore.GetDpiForMonitor(int(monitor), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        escala = dpi_x.value / 96 or 1
    except Exception:
        escala = 1
    return izq, arr, der - izq, aba - arr, escala


def colocar_orbe():
    """Centra la ventana del orbe en la pantalla donde está el ratón (sin mostrarla si está oculta)."""
    hwnd = _hwnd_ventana()
    if not hwnd:
        return
    import ctypes
    x, y, ancho, alto, escala = _monitor_del_raton()
    lado = int(int(cfg("interfaz.tamano_orbe", 480)) * escala)
    lado = min(lado, ancho, alto)
    ctypes.windll.user32.SetWindowPos(hwnd, None, x + (ancho - lado) // 2, y + (alto - lado) // 2, lado, lado,
                                      0x4 | 0x10)  # NOZORDER | NOACTIVATE (y sin SHOWWINDOW: oculta sigue oculta)


def _preparar_ventana_orbe():
    """Ventana del orbe: fondo transparente de verdad, sin barra de tareas, sin borde ni esquinas redondeadas.
    Transparencia: WebView2 con fondo transparente + formulario negro + marco de DWM extendido a toda la ventana
    (así Windows mezcla cada píxel con su alfa: el resplandor se funde con el escritorio).
    Capas (WS_EX_LAYERED con alfa 255): permite el desvanecido al mostrar/ocultar y que los clics fuera del
    orbe pasen a lo que haya detrás (WS_EX_TRANSPARENT, que se activa según dónde esté el ratón)."""
    global _transparente
    import ctypes
    from ctypes import wintypes
    hwnd = None
    for _ in range(100):
        hwnd = _hwnd_ventana()
        if hwnd:
            break
        time.sleep(0.05)
    if not hwnd:
        log.warning("VENTANA  no encuentro la ventana del orbe")
        return
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    ex = user32.GetWindowLongW(hwnd, -20)
    ex = (ex | 0x80 | 0x80000) & ~0x40000            # TOOLWINDOW (sin barra de tareas) | LAYERED, sin APPWINDOW
    user32.SetWindowLongW(hwnd, -20, ex)
    user32.SetLayeredWindowAttributes(hwnd, 0, 0 if (_dormido and not _visible) else 255, 2)  # LWA_ALPHA
    valor = ctypes.c_int(1)                           # DWMWCP_DONOTROUND: sin esquinas redondeadas
    dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(valor), 4)
    sin_borde = ctypes.c_uint(0xFFFFFFFE)             # DWMWA_COLOR_NONE: sin el borde fino de Windows 11
    dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(sin_borde), 4)
    ok = False
    if cfg("interfaz.transparente", True):
        try:
            from System import Action
            from System.Drawing import Color
            from webview.platforms.winforms import BrowserView
            forma = next(f for f in BrowserView.instances.values() if f.Text == "J.A.R.V.I.S.")

            def poner_transparente():
                forma.BackColor = Color.Black
                forma.browser.webview.DefaultBackgroundColor = Color.Transparent
            forma.Invoke(Action(poner_transparente))

            class MARGENES(ctypes.Structure):
                _fields_ = [("i", ctypes.c_int), ("d", ctypes.c_int), ("a", ctypes.c_int), ("b", ctypes.c_int)]
            habilitada = wintypes.BOOL()
            dwm.DwmIsCompositionEnabled(ctypes.byref(habilitada))
            ok = bool(habilitada.value) and dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGENES(-1, -1, -1, -1))) == 0
        except Exception as e:
            log.warning(f"VENTANA  transparencia no disponible: {e}")
    if not ok:
        try:  # plan B: el mismo orbe sobre fondo oscuro (la página pone su propio fondo con class="opaco")
            from System import Action
            from System.Drawing import ColorTranslator
            from webview.platforms.winforms import BrowserView
            forma = next(f for f in BrowserView.instances.values() if f.Text == "J.A.R.V.I.S.")
            def poner_oscuro():
                forma.BackColor = ColorTranslator.FromHtml("#05070c")
                forma.browser.webview.DefaultBackgroundColor = ColorTranslator.FromHtml("#05070c")
            forma.Invoke(Action(poner_oscuro))
        except Exception:
            pass
    _transparente = ok
    emitir("ventana_transparente", transparente=ok)
    log.info(f"VENTANA  orbe {'transparente' if ok else 'con fondo oscuro (sin transparencia)'}, sin barra de tareas")
    colocar_orbe()
    threading.Thread(target=_hilo_raton, args=(hwnd,), daemon=True, name="raton").start()


def _hilo_raton(hwnd):
    """Clics fuera del orbe: pasan a la ventana de detrás. Dentro del círculo del orbe: son para Jarvis
    (arrastrar, clic para hablar, clic derecho para el panel). Se comprueba 30 veces por segundo solo
    mientras la ventana se ve; oculta, una vez cada 0,3 s (nada de gasto)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    atraviesa = None
    while True:
        if not _visible:
            time.sleep(0.3)
            continue
        time.sleep(0.033)
        r, p = wintypes.RECT(), wintypes.POINT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)) or not user32.GetCursorPos(ctypes.byref(p)):
            continue
        lado = r.right - r.left
        cx, cy = (r.left + r.right) / 2, (r.top + r.bottom) / 2
        dentro = (p.x - cx) ** 2 + (p.y - cy) ** 2 <= (lado * 0.30) ** 2
        if user32.GetAsyncKeyState(0x01) & 0x8000 and atraviesa is False:
            continue  # arrastrando (botón pulsado): no cambiar a mitad del gesto
        if atraviesa is not None and atraviesa == (not dentro):
            continue  # ya está como toca
        ex = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, (ex & ~0x20) if dentro else (ex | 0x20))  # WS_EX_TRANSPARENT
        atraviesa = not dentro


def _alfa(hwnd, valor: int):
    import ctypes
    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(255, int(valor))), 2)


def _desvanecer(hwnd, desde: int, hasta: int, segundos: float):
    pasos = max(1, int(segundos / 0.016))
    for i in range(1, pasos + 1):
        t = i / pasos
        _alfa(hwnd, desde + (hasta - desde) * (1 - (1 - t) ** 2))
        time.sleep(segundos / pasos)


def _ocultar_si_dormido():
    """pywebview no siempre respeta hidden=True: si estamos dormidos, la escondemos nosotros."""
    if _dormido and not _visible:
        hwnd = _hwnd_ventana()
        if hwnd:
            import ctypes
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE


_hwnd_cache = []


def _buscar_ventana(titulo: str):
    """Ventana de ESTE proceso con ese título (FindWindow puede devolver un «TabProxyWindow» del shell)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    encontrada = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def revisar(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            b = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, b, 64)
            if b.value == titulo:
                encontrada.append(hwnd)
                return False
        return True
    user32.EnumWindows(revisar, 0)
    return encontrada[0] if encontrada else None


def _hwnd_ventana():
    import ctypes
    if _hwnd_cache and ctypes.windll.user32.IsWindow(_hwnd_cache[0]):
        return _hwnd_cache[0]
    hwnd = _buscar_ventana("J.A.R.V.I.S.")
    if hwnd:
        _hwnd_cache[:] = [hwnd]
    return hwnd


_cerrojo_ventana = threading.Lock()


def mostrar_ventana(escuchar: bool = False, activar: bool = True):
    """Aparece el orbe en la pantalla del ratón, encima de todo, con un desvanecido corto (~0,12 s).
    activar=False: no te quita el foco (cuando lo despierta la voz y no el atajo)."""
    global _visible, _escuchar_cuando_listo
    _tocar()
    if _ventana:
        # OJO: nada de tocar propiedades de .NET (on_top, etc.) desde este hilo: bloquea Python entero.
        # show() de pywebview pasa por el hilo de la ventana (Invoke) y avisa a WebView2 de que se ve;
        # el resto (encima, foco, alfa) con la API de Windows vía ctypes, que no retiene a Python.
        import ctypes
        user32 = ctypes.windll.user32
        with _cerrojo_ventana:
            anterior = user32.GetForegroundWindow()
            hwnd = _hwnd_ventana()
            ya_visible = _visible and hwnd and user32.IsWindowVisible(hwnd)
            if hwnd and not ya_visible:
                colocar_orbe()
                # Alfa a 255 ANTES de enseñarla: si aparece con alfa 0 (para un desvanecido), Chromium la da por
                # tapada y tarda ~1,7 s en volver a pintar (medido). La aparición suave la hace el propio orbe (180 ms).
                _alfa(hwnd, 255)
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE: al instante, sin esperar a Python
            _visible = True
            emitir("mostrar")
            emitir("visibilidad", visible=True)
            t0 = time.time()
            _ventana.show()  # para que WebView2 sepa que se ve y pinte
            log.info(f"VENTANA  show() de pywebview en {time.time() - t0:.2f}s")
            if hwnd:
                user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)  # encima de todo mientras está activa
                if activar:
                    import ventanas
                    ventanas.traer_al_frente(hwnd)
                elif anterior and anterior != hwnd:
                    user32.SetForegroundWindow(anterior)  # te ha oído por voz: no te quita el foco de lo que hacías
    else:
        _visible = True
        emitir("mostrar")
        emitir("visibilidad", visible=True)
    if escuchar:
        if asistente and asistente.voz and asistente.voz.activa:
            asistente.voz.activar_manual()
        else:
            _escuchar_cuando_listo = True


def ocultar_ventana():
    """Desvanecido suave (~0,18 s) y fuera; el orbe deja de dibujarse (0 GPU mientras está oculto)."""
    global _visible
    with _cerrojo_ventana:
        hwnd = _hwnd_ventana() if _ventana else None
        if hwnd and _visible:
            _desvanecer(hwnd, 255, 0, 0.18)
        if _ventana:
            _ventana.hide()  # por pywebview (hilo de la ventana): así el siguiente show() funciona
        _visible = False
        emitir("visibilidad", visible=False)


def _accion_ventana(accion: str):
    if accion in ("minimizar", "ocultar"):
        ocultar_ventana()
    elif accion == "cerrar":
        _apagar()


# ------------------------------------------------------------------
#  Panel (ventana aparte): actividad, escenas, pantallas y ajustes
# ------------------------------------------------------------------
_panel = None
_panel_visible = False


def abrir_panel(seccion: str = None):
    global _panel, _panel_visible
    import webview
    if seccion:
        emitir("ir_a", seccion=seccion)
    if _panel is None:
        _panel = webview.create_window("Jarvis · Panel", f"http://127.0.0.1:{int(cfg('interfaz.puerto', 8765))}/panel",
                                       width=1120, height=740, min_size=(860, 560), background_color="#111317")

        def al_cerrar():  # cerrar el panel solo lo oculta (abrirlo otra vez es instantáneo)
            global _panel_visible
            _panel_visible = False
            threading.Thread(target=_panel.hide, daemon=True).start()
            return False
        _panel.events.closing += al_cerrar

        def barra_oscura():  # barra de título oscura, a juego con el panel (DWMWA_USE_IMMERSIVE_DARK_MODE)
            import ctypes
            for _ in range(60):
                hwnd = _buscar_ventana("Jarvis · Panel")
                if hwnd:
                    si = ctypes.c_int(1)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(si), 4)
                    return
                time.sleep(0.1)
        threading.Thread(target=barra_oscura, daemon=True).start()
        log.info("PANEL  abierto")
    else:
        _panel.show()
        _panel.restore()
        import ventanas
        hwnd = _buscar_ventana("Jarvis · Panel")
        if hwnd:
            ventanas.traer_al_frente(hwnd)
    _panel_visible = True


def _puerto_libre(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


def _preimportar():
    """Dormido: dejamos importado el código (no los modelos) para que despertar no espere ~3 s a Python.
    Prioridad baja para no molestar si estás jugando o trabajando."""
    import ctypes
    ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), -2)
    inicio = time.time()
    try:
        import cerebro  # noqa: F401  (herramientas, obsidian, ventanas, escenas, ollama...)
        import voz      # noqa: F401  (numpy, sounddevice)
        import onnxruntime  # noqa: F401
        import faster_whisper  # noqa: F401  (ctranslate2)
        if cfg("voz.modo_activacion", "hibrido") in ("hibrido", "wakeword"):
            # openWakeWord tarda ~1,5 s en importarse y, mientras, acapara Python: si lo dejáramos para el
            # despertar, retrasaría la llegada de tu frase. Lo dejamos importado y el modelo creado.
            from openwakeword.model import Model
            from openwakeword.utils import download_models
            nombre = cfg("voz.palabra_activacion", "hey_jarvis")
            download_models([nombre])
            voz.WAKEWORD_PRECARGADO = Model(wakeword_models=[nombre], inference_framework="onnx")
        log.info(f"DORMIDO  código precargado en {time.time() - inicio:.1f}s")
        if cfg("interfaz.precargar_oido", True) and _dormido:
            # Whisper ya en la GPU: una orden por voz se entiende al acabar la frase, sin esperar a que cargue
            voz.PRECARGANDO.set()
            try:
                voz.WHISPER_PRECARGADO = voz.cargar_modelo_whisper()
            finally:
                voz.PRECARGANDO.clear()
            log.info(f"DORMIDO  oído (Whisper) precargado en {time.time() - inicio:.1f}s")
    except Exception as e:
        log.warning(f"DORMIDO  no pude precargar el código: {e}")


def _crear_asistente(ClaseAsistente):
    global asistente, _escuchar_cuando_listo, _asistente_lanzado
    try:
        emitir("cargando", texto="Conectando con el cerebro (Ollama)…")
        _estado_carga["mensaje"] = "Conectando con el cerebro…"
        t0 = time.time()
        nuevo = ClaseAsistente(con_voz=True)   # el modelo empieza a calentarse ya, en otro hilo
        log.info(f"ARRANQUE  asistente creado en {time.time() - t0:.2f}s")
        asistente = nuevo                      # las órdenes escritas y el camino rápido ya funcionan
        emitir("cargando", texto="Cargando el oído (Whisper)…")
        _estado_carga["mensaje"] = "Cargando el oído…"
        voz_ok = nuevo.iniciar_voz()
        if nuevo.voz and not _escucha_activa:
            nuevo.voz.pausar(True)
        # No esperamos al modelo: las órdenes simples no lo necesitan, y las demás esperan solas a que esté listo
        asistente.iniciar_extras(con_briefing=not DESDE_VIGILANTE)
        _estado_carga.update(listo=True, mensaje="")
        log.info(f"ARRANQUE  listo para escuchar (modelo {'ya caliente' if nuevo.precalentado.is_set() else 'aún calentándose'})")
        emitir("listo", voz=voz_ok)
        emitir("estado", estado="reposo")
        _tocar()
        if "--briefing" in sys.argv:
            asistente.procesar("Buenos días. Dame el briefing de hoy.", origen="sistema")
        elif not DESDE_VIGILANTE:
            nombre = cfg("usuario.nombre", "")
            asistente.decir(f"Sistemas en línea. A tu servicio{', ' + nombre if nombre else ''}.")
        if _escuchar_cuando_listo and asistente.voz and asistente.voz.activa:
            _escuchar_cuando_listo = False
            asistente.voz.activar_manual()
    except ErrorJarvis as e:
        _estado_carga.update(listo=False, mensaje=str(e))
        emitir("error_fatal", texto=str(e))
    except Exception as e:
        log.exception("Error arrancando Jarvis")
        if asistente is None:
            _asistente_lanzado = False  # no llegó a crearse: se podrá reintentar
        _estado_carga.update(listo=False, mensaje=f"Error inesperado al arrancar: {e}")
        emitir("error_fatal", texto=f"Error inesperado al arrancar: {e}")


def arrancar_interfaz(ClaseAsistente):
    global _ventana, _clase_asistente
    _clase_asistente = ClaseAsistente
    import ctypes
    import ventanas
    ventanas.hacer_dpi_aware()  # antes de crear ninguna ventana: coordenadas reales en todas las pantallas
    puerto = int(cfg("interfaz.puerto", 8765))
    # UNA sola instancia de Jarvis: uvicorn usa SO_REUSEADDR y en Windows eso permite que dos procesos
    # escuchen en el mismo puerto a la vez (pasó: dos Jarvis repartiéndose las órdenes). El mutex lo impide.
    ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\JarvisInterfaz")
    ya_hay_otro = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    if ya_hay_otro or not _puerto_libre(puerto):
        log.info("ARRANQUE  ya hay un Jarvis en marcha: no abro otro")
        if _dormido:
            return  # ya hay un Jarvis (dormido o despierto): no hace falta otro precargado
        # Ya hay un Jarvis abierto: no lanzamos otro, le pedimos que se muestre
        import urllib.request
        try:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{puerto}/api/mostrar", data=b"{}"), timeout=2)
        except Exception:
            webbrowser.open(f"http://127.0.0.1:{puerto}")
        return
    url = f"http://127.0.0.1:{puerto}"
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True, name="servidor").start()
    for _ in range(50):
        if not _puerto_libre(puerto):
            break
        time.sleep(0.05)
    threading.Thread(target=_bucle_sistema, daemon=True, name="sistema").start()
    if DESDE_VIGILANTE:
        threading.Thread(target=_bucle_inactividad, daemon=True, name="inactividad").start()

    def cargar_modelos():  # después de abrir la ventana, para que se vea cuanto antes
        _lanzar_asistente(ClaseAsistente)

    if "--servidor" in sys.argv:          # sin ventana: accesible en la URL (útil para pruebas)
        print(f"Jarvis en modo servidor: {url}")
        global _visible
        _visible = True
        cargar_modelos()
        threading.Event().wait()
    if cfg("interfaz.ventana_propia", True) and "--navegador" not in sys.argv:
        try:
            import webview
            lado = int(cfg("interfaz.tamano_orbe", 480))
            # Siempre se crea oculta: la transparencia y el estilo se preparan antes de que se vea nada
            # (transparent=True de pywebview no sirve: deja un fondo gris y la enseña al navegar)
            _ventana = webview.create_window("J.A.R.V.I.S.", url, width=lado, height=lado, min_size=(200, 200),
                                             frameless=True, easy_drag=False, background_color="#000000",
                                             on_top=False, hidden=True, shadow=False, focus=True)

            def al_cargar():
                global _visible
                if not _dormido:
                    _visible = True
                if _dormido:
                    _ocultar_si_dormido()
                    threading.Thread(target=_preimportar, daemon=True, name="preimportar").start()
                log.info(f"INTERFAZ  página cargada ({'oculta, dormido' if _dormido else 'visible'})")

            _ventana.events.loaded += al_cargar

            def al_iniciar_gui():
                _ocultar_si_dormido()
                _preparar_ventana_orbe()
                _ocultar_si_dormido()
                if not _dormido:
                    mostrar_ventana(activar=True)
                    cargar_modelos()
                else:  # por si la ventana se muestra al terminar de crearse el control web
                    for _ in range(40):
                        time.sleep(0.25)
                        _ocultar_si_dormido()

            webview.start(al_iniciar_gui, private_mode=False)
            log.info("Ventana cerrada: Jarvis se apaga")
            _apagar()
        except Exception as e:
            log.warning(f"No se pudo abrir la ventana propia ({e}); uso el navegador")
    cargar_modelos()
    webbrowser.open(url)
    print(f"Jarvis abierto en {url}  (Ctrl+C para salir)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        _apagar()


def _apagar():
    """Cierra Jarvis del todo: libera la memoria de los modelos y termina al momento (micro, servidor, todo)."""
    log.info("APAGADO  libero modelos y cierro")
    try:
        if asistente:
            asistente.cerebro.liberar()
    finally:
        os._exit(0)
