"""
ESCENAS: con una frase, Jarvis abre varias apps/webs y coloca cada una en su pantalla.
Se guardan en escenas.yaml (puedes editarlo a mano o desde la interfaz).

Formato de cada escena:
    vamos_a_jugar:
      frases: ["vamos a jugar", "hora de jugar"]     # lo que puedes decir
      pasos:
      - abrir: epic            # app (nombre o alias) o web (youtube, https://...)
        pantalla: principal    # 1, 2, 3, principal, izquierda, centro, derecha o el nombre que le pongas
        tamano: maximizar      # maximizar | mitad_izquierda | mitad_derecha | centrar | normal
    he_terminado:
      frases: ["he terminado"]
      accion: cerrar_anterior  # cierra lo que abrió la última escena (no toca lo que ya tenías abierto)
"""
import json
import re
import threading
import time
from pathlib import Path

import psutil
from ruamel.yaml import YAML

import ventanas
from nucleo import DATOS, RAIZ, avisar, emitir, log

RUTA = RAIZ / "escenas.yaml"
RUTA_ACTIVA = DATOS / "escena_activa.json"
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=2, offset=0)
_cache = {"mtime": None, "datos": {}}
_cerrojo = threading.Lock()

PLANTILLA = """# ============================================================
#  ESCENAS DE JARVIS
#  Una escena abre varias apps/webs y coloca cada una en su pantalla.
#  Pantallas: 1, 2, 3 (número de Windows), principal, izquierda, centro, derecha
#             o el nombre que les pongas en config.yaml (pantallas.nombres).
#  Tamaños:   maximizar | mitad_izquierda | mitad_derecha | centrar | normal
#  Tras guardar este archivo no hace falta reiniciar: Jarvis lo relee solo.
# ============================================================
"""


def cargar() -> dict:
    """Lee escenas.yaml (solo si ha cambiado desde la última vez)."""
    if not RUTA.exists():
        return {}
    mtime = RUTA.stat().st_mtime
    if mtime != _cache["mtime"]:
        with open(RUTA, encoding="utf-8") as f:
            _cache["datos"] = _yaml.load(f) or {}
        _cache["mtime"] = mtime
    return _cache["datos"]


def guardar_todo(datos):
    with _cerrojo:
        with open(RUTA, "w", encoding="utf-8") as f:
            if not hasattr(datos, "ca"):  # dict normal (desde la interfaz): conservamos la cabecera
                f.write(PLANTILLA)
            _yaml.dump(datos, f)
        _cache["mtime"] = None
    emitir("escenas", lista=lista())


def lista() -> list:
    """Para la interfaz."""
    salida = []
    for clave, e in cargar().items():
        salida.append({"clave": clave, "frases": [str(f) for f in (e.get("frases") or [])],
                       "accion": e.get("accion", ""),
                       "pasos": [{k: (str(v) if v is not None else "") for k, v in dict(p).items()} for p in (e.get("pasos") or [])]})
    return salida


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", ventanas._normalizar(texto))).strip()


def buscar_por_frase(texto: str):
    """Devuelve la clave de la escena cuya frase coincide con lo que has dicho (o None)."""
    entero = _norm(texto)
    t = re.sub(r"^(activa|pon|lanza|inicia|ejecuta|abre)( la)?( escena)? ", "", entero)
    t = re.sub(r"^escena (de )?", "", t)
    for clave, e in cargar().items():
        candidatos = [_norm(f) for f in (e.get("frases") or [])] + [_norm(str(clave).replace("_", " "))]
        if entero in candidatos or t in candidatos:
            return clave
    return None


def buscar_por_nombre(nombre: str):
    n = _norm(nombre).replace(" ", "_")
    datos = cargar()
    if n in datos:
        return n
    return buscar_por_frase(nombre)


# ------------------------------------------------------------------
#  Ejecutar
# ------------------------------------------------------------------
def _es_web(objetivo: str):
    """'youtube' o 'https://...' -> URL; si no es una web, None."""
    from nucleo import cfg
    webs = {ventanas._normalizar(k): str(v) for k, v in (cfg("webs", {}) or {}).items()}
    o = ventanas._normalizar(objetivo)
    if o in webs:
        return webs[o]
    if objetivo.startswith("http"):
        return objetivo
    if re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", o):
        return "https://" + objetivo
    return None


def activar(clave: str, en_segundo_plano: bool = True) -> str:
    escena = cargar().get(clave)
    if escena is None:
        return f"No existe la escena {clave}."
    if escena.get("accion") == "cerrar_anterior":
        return cerrar_anterior()
    pasos = [dict(p) for p in (escena.get("pasos") or [])]
    if not pasos:
        return f"La escena {clave} no tiene pasos."
    inicio = time.time()
    lanzar, no_instaladas = [], []
    for paso in pasos:
        objetivo = str(paso.get("abrir", "")).strip()
        url = _es_web(objetivo)
        if url:
            lanzar.append((paso, None, url))
            continue
        _, info = ventanas.resolver_app(objetivo)
        if not info or not ventanas.esta_instalada(info):
            no_instaladas.append(objetivo)
            continue
        lanzar.append((paso, info, None))

    registro = {"clave": clave, "inicio": inicio, "abiertas": [], "ya_abiertas": []}
    resultados = []

    def ejecutar_paso(paso, info, url):
        pantalla = paso.get("pantalla")
        tamano = str(paso.get("tamano", paso.get("tamaño", "maximizar")) or "maximizar")
        try:
            if url:
                r = ventanas.abrir_web_en(url, pantalla or "principal", tamano)
                if r.get("hwnd"):
                    registro["abiertas"].append({"nombre": url, "hwnd": r["hwnd"], "procesos": [], "web": True})
            else:
                ya = bool(ventanas.ventanas_de(info))
                r = ventanas.abrir_en(str(paso["abrir"]), pantalla, tamano)
                datos = {"nombre": info["nombre"], "hwnd": r.get("hwnd"), "procesos": info.get("procesos", [])}
                (registro["ya_abiertas"] if ya else registro["abiertas"]).append(datos)
            resultados.append(r)
        except Exception as e:
            log.exception("ESCENA  fallo en un paso")
            resultados.append({"ok": False, "texto": f"Fallo con {paso.get('abrir')}: {e}"})

    hilos = [threading.Thread(target=ejecutar_paso, args=x, daemon=True) for x in lanzar]
    for h in hilos:
        h.start()

    def terminar():
        for h in hilos:
            h.join(90)
        RUTA_ACTIVA.write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")
        fallos = [r["texto"] for r in resultados if not r.get("ok")]
        log.info(f"ESCENA  {clave} lista en {time.time() - inicio:.1f}s; fallos: {fallos}")
        emitir("escena_lista", clave=clave, segundos=round(time.time() - inicio, 1), fallos=fallos)
        if fallos:
            avisar(" ".join(fallos))

    nombres = [info["nombre"] if info else str(p.get("abrir")) for p, info, _ in lanzar]
    texto = f"Escena {str(clave).replace('_', ' ')}: abro {_unir(nombres)}." if nombres else ""
    if no_instaladas:
        texto += f" {_unir(no_instaladas).capitalize()} no {'está instalado' if len(no_instaladas) == 1 else 'están instalados'}."
    if en_segundo_plano:
        threading.Thread(target=terminar, daemon=True).start()
    else:
        terminar()
    return texto.strip() or "No he podido abrir nada de esa escena."


def _unir(nombres) -> str:
    nombres = [str(n) for n in nombres]
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1] if nombres else ""


# Apps que al pulsar la X se quedan en la bandeja: para cerrarlas de verdad hay que terminar su proceso
EN_BANDEJA = {"spotify.exe", "discord.exe", "epicgameslauncher.exe", "steam.exe", "steamwebhelper.exe"}


def cerrar_anterior() -> str:
    """Cierra solo lo que abrió la última escena. Lo que ya tenías abierto antes, no se toca."""
    if not RUTA_ACTIVA.exists():
        return "No hay ninguna escena que cerrar."
    registro = json.loads(RUTA_ACTIVA.read_text(encoding="utf-8"))
    cerradas = []
    for a in registro.get("abiertas", []):
        if a.get("hwnd") and ventanas.user32.IsWindow(a["hwnd"]):
            ventanas.cerrar(a["hwnd"])
        cerradas.append(a["nombre"] if not a.get("web") else "la web")
    time.sleep(1.5)
    # Las que se quedan en la bandeja y arrancó la escena (proceso creado después de activarla): las terminamos
    for a in registro.get("abiertas", []):
        for p in psutil.process_iter(["name", "create_time"]):
            nombre = (p.info["name"] or "").lower()
            if nombre in EN_BANDEJA and nombre in a.get("procesos", []) and p.info["create_time"] >= registro["inicio"] - 2:
                try:
                    p.terminate()
                except Exception:
                    pass
    RUTA_ACTIVA.unlink()
    texto = f"Cierro {_unir(cerradas)}." if cerradas else "La escena no había abierto nada nuevo."
    ya = [a["nombre"] for a in registro.get("ya_abiertas", [])]
    if ya:
        texto += f" Dejo {_unir(ya)}, que ya lo tenías abierto antes."
    log.info(f"ESCENA  cerrada {registro.get('clave')}: {texto}")
    return texto


def guardar_disposicion(nombre: str) -> str:
    """Captura las ventanas abiertas (qué app y en qué pantalla) y lo guarda como escena."""
    clave = re.sub(r"\W+", "_", ventanas._normalizar(nombre)).strip("_") or "mi_escena"
    lista_p = ventanas.pantallas()
    pasos, vistas = [], set()
    inversa = {p: k for k, info in ventanas.APPS.items() for p in info["procesos"]}
    for v in ventanas.ventanas_visibles(incluir_minimizadas=False):
        if v["proceso"] in ("explorer.exe", "applicationframehost.exe", "textinputhost.exe", "pythonw.exe", "python.exe",
                            "msedgewebview2.exe"):
            continue
        app = inversa.get(v["proceso"])
        if app is None:
            try:
                app = psutil.Process(v["pid"]).exe()
            except Exception:
                continue
        p = ventanas.pantalla_de_ventana(v["hwnd"], lista_p)
        zx, zy, zw, zh = p["zona"]
        x, y, w, h = v["rect"]
        if v["maximizada"]:
            tamano = "maximizar"
        elif abs(w - zw / 2) < 40 and abs(x - zx) < 20:
            tamano = "mitad_izquierda"
        elif abs(w - zw / 2) < 40 and abs(x + w - zx - zw) < 20:
            tamano = "mitad_derecha"
        else:
            tamano = "normal"
        if (app, p["numero"]) in vistas:
            continue
        vistas.add((app, p["numero"]))
        pasos.append({"abrir": app, "pantalla": p["numero"], "tamano": tamano})
    if not pasos:
        return "No veo ventanas que guardar."
    datos = cargar() if RUTA.exists() else {}
    datos[clave] = {"frases": [ventanas._normalizar(nombre)], "pasos": pasos}
    guardar_todo(datos)
    return f"Guardada la escena {nombre} con {len(pasos)} ventanas. Dime «{ventanas._normalizar(nombre)}» para activarla."


def crear_ejemplos():
    """La primera vez crea escenas.yaml con las escenas de ejemplo."""
    if RUTA.exists():
        return
    RUTA.write_text(PLANTILLA + """
vamos_a_jugar:
  frases: ["vamos a jugar", "a jugar", "hora de jugar", "modo gaming"]
  pasos:
  - abrir: epic
    pantalla: principal
    tamano: maximizar
  - abrir: discord
    pantalla: izquierda      # tu pantalla 2 de Windows es la principal: Discord va a la de la izquierda (pantalla 1)
    tamano: maximizar
  - abrir: spotify
    pantalla: 3
    tamano: maximizar

modo_estudio:
  frases: ["modo estudio", "a estudiar", "vamos a estudiar", "hora de estudiar"]
  pasos:
  - abrir: vscode
    pantalla: principal
    tamano: mitad_izquierda
  - abrir: obsidian
    pantalla: principal
    tamano: mitad_derecha
  - abrir: spotify
    pantalla: 3
    tamano: maximizar

he_terminado:
  frases: ["he terminado", "ya he terminado", "hemos terminado", "cierra la escena", "fin de la escena"]
  accion: cerrar_anterior
""", encoding="utf-8")


# ==================================================================
#  HERRAMIENTAS PARA EL MODELO
# ==================================================================
from herramientas import herramienta  # noqa: E402


@herramienta()
def activar_escena(nombre: str) -> str:
    """Activa una escena guardada (abre varias apps, cada una en su pantalla), p. ej. "vamos a jugar" o "modo estudio".

    Args:
        nombre: nombre o frase de la escena
    """
    clave = buscar_por_nombre(nombre)
    if not clave:
        return f"No existe esa escena. Escenas: {', '.join(cargar())}."
    return activar(clave)


@herramienta()
def guardar_escena(nombre: str) -> str:
    """Guarda las ventanas abiertas ahora (qué app y en qué pantalla) como una escena nueva.

    Args:
        nombre: nombre de la escena
    """
    return guardar_disposicion(nombre)
