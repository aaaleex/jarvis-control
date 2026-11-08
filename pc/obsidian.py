"""
Integración con Obsidian: lee y escribe directamente los archivos .md del vault.
  - Búsqueda por texto, título, #etiquetas y [[enlaces]]
  - Leer, crear notas, añadir al final, nota diaria, Inbox (captura rápida)
  - Búsqueda semántica ("¿qué apunté sobre X?") con embeddings de Ollama y un índice numpy local
Reglas de seguridad: nunca borra ni sobrescribe notas. Para modificar, añade al final o crea una copia.
"""
import difflib
import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from herramientas import fecha_bonita, herramienta, _DIAS, _MESES
from nucleo import DATOS, cfg, emitir, log

CARPETAS_IGNORADAS = {".obsidian", ".trash", ".git", "node_modules"}
RE_ENLACE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
RE_ETIQUETA = re.compile(r"(?<![\w#/&])#([A-Za-zÀ-ÿ0-9_\-/]*[A-Za-zÀ-ÿ_\-/][A-Za-zÀ-ÿ0-9_\-/]*)")


# ==================================================================
#  UTILIDADES DEL VAULT
# ==================================================================
def vault() -> Path:
    ruta = Path(str(cfg("obsidian.vault", ""))).expanduser()
    if not str(cfg("obsidian.vault", "")).strip():
        raise FileNotFoundError("No has configurado la ruta del vault de Obsidian (obsidian.vault en config.yaml).")
    if not ruta.is_dir():
        raise FileNotFoundError(f"No encuentro el vault de Obsidian en {ruta}. Revisa obsidian.vault en config.yaml.")
    return ruta.resolve()


def _dentro_del_vault(ruta: Path) -> Path:
    base = vault()
    ruta = ruta.resolve()
    if ruta != base and base not in ruta.parents:
        raise PermissionError("Esa ruta está fuera del vault.")
    return ruta


def todas_las_notas() -> list:
    base = vault()
    return [p for p in base.rglob("*.md") if not (set(p.relative_to(base).parts[:-1]) & CARPETAS_IGNORADAS)]


def leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8", errors="replace")


def separar_frontmatter(texto: str):
    """Devuelve (diccionario_frontmatter, cuerpo)."""
    if texto.startswith("---"):
        fin = texto.find("\n---", 3)
        if fin != -1:
            from ruamel.yaml import YAML
            try:
                datos = YAML(typ="safe").load(texto[3:fin]) or {}
                return (datos if isinstance(datos, dict) else {}), texto[fin + 4:].lstrip("\n")
            except Exception:
                pass
    return {}, texto


def etiquetas_de(texto: str) -> set:
    frontmatter, cuerpo = separar_frontmatter(texto)
    etiquetas = frontmatter.get("tags") or frontmatter.get("tag") or []
    if isinstance(etiquetas, str):
        etiquetas = re.split(r"[,\s]+", etiquetas)
    resultado = {str(e).lstrip("#").lower() for e in etiquetas if e}
    cuerpo_sin_codigo = re.sub(r"```.*?```", "", cuerpo, flags=re.S)
    resultado |= {e.lower() for e in RE_ETIQUETA.findall(cuerpo_sin_codigo)}
    return resultado


def titulo(ruta: Path) -> str:
    return ruta.stem


def buscar_nota_por_titulo(nombre: str):
    """Encuentra una nota por su título aunque no lo digas exacto."""
    nombre = nombre.strip().removesuffix(".md").strip("[]").lower()
    notas = todas_las_notas()
    por_titulo = {n.stem.lower(): n for n in notas}
    if nombre in por_titulo:
        return por_titulo[nombre]
    contienen = [n for t, n in por_titulo.items() if nombre in t]
    if contienen:
        return min(contienen, key=lambda n: len(n.stem))
    parecidas = difflib.get_close_matches(nombre, list(por_titulo), n=1, cutoff=0.55)
    return por_titulo[parecidas[0]] if parecidas else None


def _fragmento(texto: str, consulta: str, ancho: int = 160) -> str:
    _, cuerpo = separar_frontmatter(texto)
    i = cuerpo.lower().find(consulta.lower()) if consulta else -1
    if i == -1:
        return re.sub(r"\s+", " ", cuerpo[:ancho]).strip()
    inicio = max(0, i - ancho // 2)
    return ("…" if inicio else "") + re.sub(r"\s+", " ", cuerpo[inicio:i + ancho // 2]).strip() + "…"


def _escribir_nota_nueva(ruta: Path, contenido: str) -> Path:
    """Crea una nota SIN sobrescribir nunca: si ya existe, crea 'Título (2).md'."""
    ruta = _dentro_del_vault(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    final, n = ruta, 2
    while final.exists():
        final = ruta.with_name(f"{ruta.stem} ({n}).md")
        n += 1
    final.write_text(contenido, encoding="utf-8")
    log.info(f"OBSIDIAN  creada {final}")
    emitir("notas")
    return final


def _anadir_al_final(ruta: Path, contenido: str):
    ruta = _dentro_del_vault(ruta)
    previo = leer(ruta) if ruta.exists() else ""
    separador = "" if not previo or previo.endswith("\n") else "\n"
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(separador + contenido.rstrip("\n") + "\n")
    log.info(f"OBSIDIAN  añadido a {ruta.name}: {contenido[:80]!r}")
    emitir("notas")


# ==================================================================
#  NOTA DIARIA (respeta la configuración del plugin de Obsidian)
# ==================================================================
def _config_nota_diaria() -> dict:
    ruta = vault() / ".obsidian" / "daily-notes.json"
    datos = {}
    if ruta.exists():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8") or "{}")
        except Exception:
            pass
    return {"carpeta": datos.get("folder", "") or "", "formato": datos.get("format", "") or "YYYY-MM-DD",
            "plantilla": datos.get("template", "") or ""}


def formatear_fecha_moment(formato: str, d: datetime) -> str:
    """Convierte el formato de fecha de Obsidian (moment.js: YYYY-MM-DD, dddd...) a texto."""
    sustituciones = {
        "YYYY": f"{d.year}", "YY": f"{d.year % 100:02d}", "MMMM": _MESES[d.month - 1], "MMM": _MESES[d.month - 1][:3],
        "MM": f"{d.month:02d}", "M": f"{d.month}", "DD": f"{d.day:02d}", "Do": f"{d.day}º", "D": f"{d.day}",
        "dddd": _DIAS[d.weekday()], "ddd": _DIAS[d.weekday()][:3], "HH": f"{d.hour:02d}", "mm": f"{d.minute:02d}",
        "ww": f"{d.isocalendar()[1]:02d}", "w": f"{d.isocalendar()[1]}",
    }
    patron = re.compile(r"\[([^\]]*)\]|" + "|".join(sorted(map(re.escape, sustituciones), key=len, reverse=True)))
    return patron.sub(lambda m: m.group(1) if m.group(1) is not None else sustituciones[m.group(0)], formato)


def ruta_nota_diaria(d: datetime = None) -> Path:
    conf = _config_nota_diaria()
    nombre = formatear_fecha_moment(conf["formato"], d or datetime.now())
    return vault() / conf["carpeta"] / f"{nombre}.md"


def _crear_nota_diaria(d: datetime) -> Path:
    ruta = ruta_nota_diaria(d)
    if ruta.exists():
        return ruta
    conf = _config_nota_diaria()
    contenido = f"# {fecha_bonita(d).capitalize()}\n\n"
    if conf["plantilla"]:
        plantilla = vault() / (conf["plantilla"] if conf["plantilla"].endswith(".md") else conf["plantilla"] + ".md")
        if plantilla.exists():
            contenido = (leer(plantilla).replace("{{date}}", d.strftime("%Y-%m-%d"))
                         .replace("{{time}}", d.strftime("%H:%M")).replace("{{title}}", ruta.stem))
    return _escribir_nota_nueva(ruta, contenido)


def _interpretar_fecha(fecha: str) -> datetime:
    fecha = (fecha or "hoy").strip().lower()
    hoy = datetime.now()
    if fecha in ("hoy", "today", ""):
        return hoy
    if fecha in ("ayer", "yesterday"):
        return hoy - timedelta(days=1)
    if fecha in ("mañana", "tomorrow"):
        return hoy + timedelta(days=1)
    return datetime.fromisoformat(fecha)


# ==================================================================
#  HERRAMIENTAS DE OBSIDIAN
# ==================================================================
@herramienta()
def leer_nota_diaria(fecha: str = "hoy") -> str:
    """Lee la nota diaria de Obsidian (agenda, tareas y apuntes del día). Úsala para "¿qué tengo hoy?".

    Args:
        fecha: "hoy", "ayer", "mañana" o una fecha AAAA-MM-DD
    """
    try:
        d = _interpretar_fecha(fecha)
    except ValueError:
        return "Error: fecha no válida; usa hoy, ayer, mañana o AAAA-MM-DD."
    ruta = ruta_nota_diaria(d)
    if not ruta.exists():
        return f"No existe nota diaria para el {fecha_bonita(d)}."
    texto = leer(ruta).strip()
    return f"Nota diaria del {fecha_bonita(d)}:\n{texto[:6000]}" if texto else "La nota diaria existe pero está vacía."


@herramienta()
def anadir_a_nota_diaria(contenido: str, como_tarea: bool = False) -> str:
    """Añade texto al final de la nota diaria de hoy en Obsidian (la crea si no existe).

    Args:
        contenido: lo que hay que apuntar
        como_tarea: true si es algo pendiente por hacer (se guarda como casilla - [ ])
    """
    ahora = datetime.now()
    ruta = _crear_nota_diaria(ahora)
    linea = f"- [ ] {contenido}" if como_tarea else f"- {ahora:%H:%M} {contenido}"
    _anadir_al_final(ruta, linea)
    return f"Apuntado en la nota diaria ({ruta.name})."


@herramienta()
def captura_rapida(idea: str) -> str:
    """Guarda al instante una idea, tarea o recordatorio en la nota Inbox de Obsidian.
    Úsala cuando el usuario diga "apunta en mi inbox...", "anota esta idea...", "captura...".

    Args:
        idea: la idea a guardar, redactada de forma clara y breve
    """
    ruta = vault() / str(cfg("obsidian.nota_inbox", "Inbox.md"))
    if not ruta.exists():
        _escribir_nota_nueva(ruta, "---\ntags: [inbox]\n---\n# Inbox\n\nIdeas y tareas capturadas por Jarvis.\n\n")
    _anadir_al_final(ruta, f"- [ ] {idea} _({datetime.now():%Y-%m-%d %H:%M})_")
    return f"Guardado en {ruta.stem}: {idea}"


@herramienta()
def crear_nota(titulo: str, contenido: str, etiquetas: str = "", carpeta: str = "") -> str:
    """Crea una nota nueva en Obsidian con frontmatter y etiquetas. Nunca sobrescribe: si existe, crea una copia.

    Args:
        titulo: título de la nota (será el nombre del archivo)
        contenido: texto de la nota en Markdown
        etiquetas: etiquetas separadas por comas, sin #, por ejemplo "java,estudio"
        carpeta: carpeta dentro del vault ("" = la configurada por defecto)
    """
    titulo_limpio = re.sub(r'[\\/:*?"<>|#^\[\]]', "", titulo).strip() or "Nota de Jarvis"
    lista = [e.strip().lstrip("#").replace(" ", "-") for e in etiquetas.split(",") if e.strip()]
    frontmatter = ["---", f"creado: {datetime.now():%Y-%m-%d %H:%M}"]
    frontmatter.append("tags: [" + ", ".join(lista) + "]" if lista else "tags: []")
    frontmatter += ["origen: jarvis", "---", ""]
    carpeta = carpeta or str(cfg("obsidian.carpeta_notas_nuevas", "") or "")
    ruta = _escribir_nota_nueva(vault() / carpeta / f"{titulo_limpio}.md",
                                "\n".join(frontmatter) + f"# {titulo_limpio}\n\n{contenido.strip()}\n")
    aviso = "" if ruta.stem == titulo_limpio else f" (ya existía una con ese nombre, la he llamado '{ruta.stem}')"
    return f"Nota '{ruta.stem}' creada{aviso}."


@herramienta()
def anadir_a_nota(titulo: str, contenido: str) -> str:
    """Añade texto AL FINAL de una nota existente de Obsidian (nunca borra lo que ya hay).

    Args:
        titulo: título (o parte del título) de la nota
        contenido: texto a añadir
    """
    ruta = buscar_nota_por_titulo(titulo)
    if not ruta:
        return f"No encuentro ninguna nota llamada '{titulo}'. ¿Quieres que la cree?"
    _anadir_al_final(ruta, "\n" + contenido.strip())
    return f"Añadido al final de '{ruta.stem}'."


@herramienta()
def leer_nota(titulo: str) -> str:
    """Lee el contenido de una nota de Obsidian por su título (para resumirla o consultarla).

    Args:
        titulo: título o parte del título de la nota
    """
    ruta = buscar_nota_por_titulo(titulo)
    if not ruta:
        return f"No encuentro ninguna nota parecida a '{titulo}'."
    texto = leer(ruta)
    return f"Nota '{ruta.stem}' ({ruta.relative_to(vault())}):\n{texto[:7000]}" + ("\n…(recortada)" if len(texto) > 7000 else "")


@herramienta()
def buscar_notas(texto: str = "", etiqueta: str = "", enlaza_a: str = "") -> str:
    """Busca notas en Obsidian por palabras (en título y contenido), por #etiqueta o por las que enlazan a [[otra nota]].
    Para preguntas abiertas sobre el contenido usa mejor preguntar_a_mis_notas.

    Args:
        texto: palabras a buscar ("" = no filtrar por texto)
        etiqueta: etiqueta sin # ("" = no filtrar)
        enlaza_a: título de la nota enlazada con [[...]] ("" = no filtrar)
    """
    if not (texto or etiqueta or enlaza_a):
        return "Error: dime qué buscar (texto, etiqueta o enlace)."
    resultados = []
    palabras = [p for p in texto.lower().split() if len(p) > 2]
    for ruta in todas_las_notas():
        contenido = leer(ruta)
        bajo = contenido.lower()
        if etiqueta and etiqueta.lstrip("#").lower() not in etiquetas_de(contenido):
            continue
        if enlaza_a and enlaza_a.lower() not in {e.strip().lower() for e in RE_ENLACE.findall(contenido)}:
            continue
        puntos = 1
        if palabras:
            puntos = sum(3 * (p in ruta.stem.lower()) + bajo.count(p) for p in palabras)
            if puntos == 0:
                continue
        resultados.append((puntos, ruta, contenido))
    if not resultados:
        return "No he encontrado ninguna nota con esos criterios."
    resultados.sort(key=lambda r: (-r[0], -r[1].stat().st_mtime))
    return f"{len(resultados)} nota(s):\n" + "\n".join(
        f"- {r.stem}: {_fragmento(c, palabras[0] if palabras else '')}" for _, r, c in resultados[:8])


@herramienta()
def notas_recientes(cantidad: int = 5) -> str:
    """Lista las notas de Obsidian modificadas más recientemente.

    Args:
        cantidad: cuántas notas mostrar
    """
    notas = sorted(todas_las_notas(), key=lambda p: p.stat().st_mtime, reverse=True)[:max(1, min(20, cantidad))]
    if not notas:
        return "El vault no tiene notas todavía."
    return "\n".join(f"- {n.stem} (modificada {datetime.fromtimestamp(n.stat().st_mtime):%d/%m %H:%M})" for n in notas)


@herramienta()
def tareas_pendientes() -> str:
    """Lista las tareas sin hacer (casillas - [ ]) de todo el vault de Obsidian."""
    tareas = []
    for ruta in sorted(todas_las_notas(), key=lambda p: p.stat().st_mtime, reverse=True):
        for linea in leer(ruta).splitlines():
            m = re.match(r"\s*[-*] \[ \] (.+)", linea)
            if m:
                tareas.append(f"- {m.group(1).strip()} ({ruta.stem})")
    if not tareas:
        return "No hay tareas pendientes en Obsidian."
    return f"{len(tareas)} tarea(s) pendiente(s):\n" + "\n".join(tareas[:25])


@herramienta()
def preguntar_a_mis_notas(pregunta: str) -> str:
    """Busca por SIGNIFICADO en todas las notas de Obsidian y devuelve los fragmentos más relevantes.
    Úsala para preguntas como "¿qué apunté sobre el proyecto X?" o "¿qué sé de Mockito?".

    Args:
        pregunta: la pregunta o tema, en lenguaje natural
    """
    try:
        resultados = INDICE.buscar(pregunta, k=5)
    except Exception as e:
        log.warning(f"Búsqueda semántica falló: {e}")
        return f"Error: la búsqueda semántica no está disponible ({e}). Prueba con buscar_notas."
    if not resultados:
        return "No he encontrado nada relacionado en tus notas."
    return "Fragmentos relevantes de tus notas:\n" + "\n\n".join(
        f"[{r['titulo']}] (relevancia {r['puntuacion']:.2f})\n{r['texto']}" for r in resultados)


# ==================================================================
#  ÍNDICE SEMÁNTICO (embeddings de Ollama + numpy). Se actualiza solo con lo que cambia.
# ==================================================================
class IndiceSemantico:
    def __init__(self):
        self.ruta_meta = DATOS / "indice_obsidian.json"
        self.ruta_vectores = DATOS / "indice_obsidian.npy"
        self.cerrojo = threading.Lock()
        self.archivos = {}       # ruta relativa -> {"mtime": float, "trozos": [índices]}
        self.trozos = []         # [{"ruta", "titulo", "texto"}]
        self.vectores = np.zeros((0, 0), dtype=np.float32)
        self._cargar()

    def _cargar(self):
        try:
            if self.ruta_meta.exists() and self.ruta_vectores.exists():
                meta = json.loads(self.ruta_meta.read_text(encoding="utf-8"))
                if meta.get("vault") == str(vault()) and meta.get("modelo") == self._modelo():
                    self.archivos, self.trozos = meta["archivos"], meta["trozos"]
                    self.vectores = np.load(self.ruta_vectores)
        except Exception as e:
            log.warning(f"Índice de Obsidian dañado, se rehará: {e}")

    def _guardar(self):
        self.ruta_meta.write_text(json.dumps({"vault": str(vault()), "modelo": self._modelo(), "archivos": self.archivos,
                                              "trozos": self.trozos}, ensure_ascii=False), encoding="utf-8")
        np.save(self.ruta_vectores, self.vectores)

    @staticmethod
    def _modelo():
        return cfg("cerebro.ollama.modelo_embeddings", "bge-m3")

    def _embeber(self, textos: list) -> np.ndarray:
        import ollama

        cliente = ollama.Client(host=cfg("cerebro.ollama.url", "http://localhost:11434"))
        vectores = []
        for i in range(0, len(textos), 16):
            r = cliente.embed(model=self._modelo(), input=textos[i:i + 16], keep_alive="1m",
                              options={"num_gpu": 0})  # en CPU: no quita VRAM al modelo de chat ni a Whisper
            vectores.extend(r.embeddings)
        v = np.array(vectores, dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)

    @staticmethod
    def _trocear(texto: str, maximo: int = 900) -> list:
        """Divide una nota en trozos por encabezados y párrafos (~900 caracteres)."""
        _, cuerpo = separar_frontmatter(texto)
        bloques = re.split(r"\n(?=#{1,6} )|\n\s*\n", cuerpo)
        trozos, actual = [], ""
        for bloque in (b.strip() for b in bloques):
            if not bloque:
                continue
            if len(actual) + len(bloque) > maximo and actual:
                trozos.append(actual)
                actual = ""
            actual = (actual + "\n\n" + bloque).strip()
            while len(actual) > maximo * 1.5:
                trozos.append(actual[:maximo])
                actual = actual[maximo:]
        if actual:
            trozos.append(actual)
        return trozos

    def actualizar(self) -> int:
        """Reindexa solo las notas nuevas o modificadas, y quita las borradas. Devuelve cuántas ha procesado."""
        with self.cerrojo:
            base = vault()
            actuales = {str(p.relative_to(base)): p for p in todas_las_notas()}
            cambiadas = [r for r, p in actuales.items()
                         if r not in self.archivos or abs(self.archivos[r]["mtime"] - p.stat().st_mtime) > 1e-3]
            borradas = [r for r in self.archivos if r not in actuales]
            if not cambiadas and not borradas:
                return 0
            inicio = time.time()
            quitar = set(cambiadas) | set(borradas)
            conservar = [i for i, t in enumerate(self.trozos) if t["ruta"] not in quitar]
            trozos = [self.trozos[i] for i in conservar]
            vectores = self.vectores[conservar] if len(self.vectores) else np.zeros((0, 0), np.float32)
            nuevos = []
            for r in cambiadas:
                p = actuales[r]
                for texto in self._trocear(leer(p)):
                    nuevos.append({"ruta": r, "titulo": p.stem, "texto": texto})
            if nuevos:
                # El título se incluye para que "proyecto X" encuentre la nota "Proyecto X"
                v = self._embeber([f"{t['titulo']}\n{t['texto']}" for t in nuevos])
                vectores = v if not len(vectores) else np.vstack([vectores, v])
                trozos += nuevos
            self.trozos, self.vectores = trozos, vectores
            self.archivos = {r: {"mtime": actuales[r].stat().st_mtime} for r in actuales}
            self._guardar()
            log.info(f"ÍNDICE  {len(cambiadas)} nota(s) reindexadas, {len(borradas)} quitadas, "
                     f"{len(self.trozos)} trozos en total [{time.time() - inicio:.1f}s]")
            return len(cambiadas) + len(borradas)

    def buscar(self, consulta: str, k: int = 5) -> list:
        self.actualizar()
        if not self.trozos:
            return []
        q = self._embeber([consulta])[0]
        puntuaciones = self.vectores @ q
        orden = np.argsort(-puntuaciones)[:k]
        return [{**self.trozos[i], "puntuacion": float(puntuaciones[i])} for i in orden if puntuaciones[i] > 0.35]


class _IndicePerezoso:
    """Crea el índice la primera vez que se usa (así un vault mal configurado no impide arrancar Jarvis)."""
    _indice = None

    def __getattr__(self, nombre):
        if _IndicePerezoso._indice is None:
            _IndicePerezoso._indice = IndiceSemantico()
        return getattr(_IndicePerezoso._indice, nombre)


INDICE = _IndicePerezoso()


def vigilar_cambios(cada_segundos: int = 120):
    """Hilo en segundo plano: mantiene el índice al día sin que tengas que hacer nada."""
    def bucle():
        while True:
            try:
                INDICE.actualizar()
            except Exception as e:
                log.warning(f"No pude actualizar el índice de Obsidian: {e}")
            time.sleep(cada_segundos)
    threading.Thread(target=bucle, daemon=True, name="indice-obsidian").start()
