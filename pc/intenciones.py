"""
CAMINO RÁPIDO: las órdenes comunes se resuelven con reglas, sin pasar por el modelo (milisegundos en vez de segundos).

    entender("ponme Spotify en la tercera")  ->  Intencion(abrir_en Spotify, pantalla 3)
    entender("cuéntame un chiste")           ->  None  (no es una orden simple: la contesta el modelo)

Regla de oro: si no está SEGURO de lo que pides, devuelve None y decide el modelo.
Cubre: abrir/cerrar apps y webs (en la pantalla que digas), traer al frente, mover/minimizar/maximizar/mitad,
escritorio, pestañas, volumen, música, hora/fecha, tiempo, temporizadores y alarmas, escenas, modo juego,
búsquedas en YouTube/Google y apuntar en el Inbox de Obsidian. Varias órdenes unidas con "y" también.
"""
import re
import unicodedata
from datetime import datetime

from nucleo import cfg


class Intencion:
    def __init__(self, tipo: str, funcion, /, **argumentos):
        self.accion = tipo            # nombre para el log y el panel de acciones
        self.funcion = funcion        # se llama con **argumentos y devuelve el texto que dirá Jarvis
        self.argumentos = argumentos

    def ejecutar(self) -> str:
        return self.funcion(**self.argumentos)

    def __repr__(self):
        return f"{self.accion}({self.argumentos})"


# ==================================================================
#  NORMALIZAR (sin tildes, minúsculas, sin signos) conservando las posiciones del texto original
# ==================================================================
def _normalizar(texto: str) -> str:
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFD", c)[0].lower()
        salida.append(base if base.isalnum() or base in " :" else " ")
    return "".join(salida)


_RELLENO_INICIO = re.compile(
    r"^\s*(?:(?:oye|hey|eh|venga|vale|bueno|jarvis|por favor|porfa|ahora|rapido|a ver|y)\s+)*"
    r"(?:(?:me\s+)?(?:puedes|podrias|quieres|puedas)\s+|quiero\s+que\s+|necesito\s+que\s+|hazme\s+el\s+favor\s+de\s+)?")
_RELLENO_FIN = re.compile(r"(?:\s+(?:por favor|porfa|gracias|jarvis|ya|ahora|rapido|venga))*\s*$")


def _limpiar(original: str):
    """Devuelve (normalizado, original) recortados igual (mismas posiciones)."""
    norm = _normalizar(original)
    a = _RELLENO_INICIO.match(norm).end()
    b = _RELLENO_FIN.search(norm).start()
    if b < a:
        b = a
    norm, original = norm[a:b], original[a:b]
    # Comprimimos espacios en ambos a la vez para no descuadrar posiciones
    n2, o2, espacio = [], [], False
    for cn, co in zip(norm, original):
        if cn == " ":
            if espacio or not n2:
                continue
            espacio = True
        else:
            espacio = False
        n2.append(cn)
        o2.append(co)
    while n2 and n2[-1] == " ":
        n2.pop()
        o2.pop()
    return "".join(n2), "".join(o2)


# ==================================================================
#  NÚMEROS, DURACIONES Y HORAS DICHAS CON PALABRAS
# ==================================================================
_UNIDADES = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
             "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
             "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
             "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
             "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
             "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
             "noventa": 90, "cien": 100}
NUM = r"(?:\d+(?:[.,]\d+)?|" + "|".join(sorted(_UNIDADES, key=len, reverse=True)) + r")(?:\s+y\s+(?:uno|una|un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve))?"


def numero(texto: str):
    texto = texto.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", texto):
        return float(texto.replace(",", "."))
    partes = re.split(r"\s+y\s+", texto)
    try:
        return float(sum(_UNIDADES[p] for p in partes))
    except KeyError:
        return None


def duracion_minutos(texto: str):
    """'5 minutos', 'media hora', 'una hora y media', '90 segundos', '2 minutos y 30 segundos' -> minutos."""
    t = texto.strip()
    fijos = {"media hora": 30, "un cuarto de hora": 15, "cuarto de hora": 15, "tres cuartos de hora": 45,
             "una hora y media": 90, "hora y media": 90, "un minuto": 1, "un segundo": 1 / 60, "una hora": 60,
             "un minuto y medio": 1.5, "minuto y medio": 1.5}
    if t in fijos:
        return fijos[t]
    total, resto = 0.0, t
    patron = re.compile(r"^(" + NUM + r"|medio|media)\s*(horas?|h|minutos?|mins?|m|segundos?|segs?|s)(?:\s+y\s+(media|medio|cuarto))?(?:\s+y\s+|\s+|$)")
    encontrado = False
    while resto:
        m = patron.match(resto)
        if not m:
            return None
        n = 0.5 if m.group(1) in ("medio", "media") else numero(m.group(1))
        if n is None:
            return None
        unidad = m.group(2)
        factor = 60 if unidad.startswith("h") else (1 / 60 if unidad.startswith("s") else 1)
        extra = {"media": 0.5, "medio": 0.5, "cuarto": 0.25}.get(m.group(3) or "", 0)
        total += (n + extra) * factor
        resto = resto[m.end():].strip()
        encontrado = True
    return total if encontrado and total > 0 else None


def hora_reloj(texto: str):
    """'7', '7:30', 'siete y media', 'ocho menos cuarto', '6 de la tarde', 'las 10 y 10' -> 'HH:MM'."""
    t = re.sub(r"^(?:a\s+)?las?\s+", "", texto.strip())
    tarde = re.search(r"\s+de\s+la\s+(tarde|noche)$", t)
    t = re.sub(r"\s+(?:de\s+la\s+(?:manana|tarde|noche|madrugada)|en\s+punto|horas?)$", "", t)
    m = re.fullmatch(r"(\d{1,2})\s*[:.h ]\s*(\d{2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(" + NUM + r")(?:\s+(y|menos)\s+(media|cuarto|" + NUM + r"))?", t)
        if not m:
            return None
        h = numero(m.group(1))
        if h is None:
            return None
        h, mi = int(h), 0
        if m.group(2):
            extra = {"media": 30, "cuarto": 15}.get(m.group(3))
            if extra is None:
                extra = numero(m.group(3))
                if extra is None:
                    return None
            if m.group(2) == "y":
                mi = int(extra)
            else:
                h, mi = (h - 1) % 24, 60 - int(extra)
    if tarde and h < 12:
        h += 12
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return f"{h:02d}:{mi:02d}"


# ==================================================================
#  PANTALLA Y TAMAÑO DENTRO DE UNA ORDEN
# ==================================================================
_PANT_VALOR = (r"(?P<pant>\d|uno|dos|tres|cuatro|primera|segunda|tercera|cuarta|principal|izquierda|derecha|centro|central|"
               r"medio|grande|otra(?:\s+(?:pantalla|monitor))?|siguiente|esta{nombres})")
_MODOS = [
    (r"(?:en|a)\s+(?:la\s+)?mitad\s+izquierda|en\s+la\s+parte\s+izquierda", "mitad_izquierda"),
    (r"(?:en|a)\s+(?:la\s+)?mitad\s+derecha|en\s+la\s+parte\s+derecha", "mitad_derecha"),
    (r"(?:y\s+)?(?:maximizad[oa]|maximizal[oa]|en\s+grande|(?:a|en)\s+pantalla\s+completa|a\s+toda\s+la\s+pantalla)", "maximizar"),
    (r"(?:y\s+)?(?:centrad[oa]|en\s+el\s+centro\s+de\s+la\s+pantalla)", "centrar"),
    (r"(?:a|en)\s+media\s+pantalla", "mitad_izquierda"),
]


def _patron_pantalla():
    nombres = [re.escape(_normalizar(str(n)).strip()) for n in (cfg("pantallas.nombres", {}) or {}).values() if str(n).strip()]
    valor = _PANT_VALOR.format(nombres="".join("|" + n for n in nombres))
    return re.compile(r"\s+(?:en|a|al|hacia|para|de)\s+(?:la\s+|el\s+)?(?:(?:pantalla|monitor|escritorio)\s+)?"
                      r"(?:de\s+la\s+|del\s+|de\s+)?(?:(?:pantalla|monitor)\s+)?" + valor + r"\b")


def _extraer_pantalla_y_modo(norm: str):
    """Quita de la orden 'en la pantalla 2' / 'maximizada' / 'en la mitad izquierda' y los devuelve aparte."""
    modo = None
    for patron, nombre in _MODOS:
        m = re.search(r"\s+" + patron + r"\b", norm)
        if m:
            modo = nombre
            norm = (norm[:m.start()] + norm[m.end():]).strip()
            break
    pantalla = None
    m = _patron_pantalla().search(norm)
    if m:
        pantalla = m.group("pant")
        if pantalla.startswith(("siguiente", "otra")):
            pantalla = "otra"
        norm = (norm[:m.start()] + norm[m.end():]).strip()
    norm = re.sub(r"\s+de\s+la\s+pantalla$", "", norm)  # "...en la mitad izquierda de la pantalla"
    return norm, pantalla, modo


# ==================================================================
#  ¿APP O WEB?
# ==================================================================
def _objetivo(texto: str):
    """'spotify' -> ('app', 'spotify'); 'youtube' -> ('web', url); si no lo conozco -> (None, None)."""
    import ventanas
    t = re.sub(r"^(?:el|la|los|las|mi|un|una)\s+", "", texto.strip())
    t = re.sub(r"\s+(?:por favor|porfa)$", "", t)
    if not t or len(t) > 40:
        return None, None
    webs = {_normalizar(k).strip(): str(v) for k, v in (cfg("webs", {}) or {}).items()}
    if t in webs:
        return "web", webs[t]
    if re.fullmatch(r"[a-z0-9-]+(?:\s*(?:punto|\.)\s*[a-z]{2,6})+", t):
        return "web", "https://" + re.sub(r"\s*(?:punto|\.)\s*", ".", t)
    if t in ("web", "pagina", "navegador nuevo"):
        return None, None
    clave, info = ventanas.resolver_app(t)
    if info:
        return "app", t
    return None, None


# ==================================================================
#  ACCIONES (devuelven el texto que dirá Jarvis)
# ==================================================================
def _abrir(tipo, valor, pantalla=None, modo=None):
    import ventanas
    if tipo == "web":
        return ventanas.abrir_web_en(valor, pantalla, modo or "maximizar", esperar=False)["texto"] if pantalla else _abrir_web_simple(valor)
    return ventanas.abrir_en(valor, pantalla, modo or ("maximizar" if pantalla else "normal"), esperar=False)["texto"]


def _abrir_web_simple(url):
    import webbrowser
    webbrowser.open(url)
    nombre = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split(".")[0]
    return f"Abro {nombre.capitalize()}."


def _traer(nombre, pantalla=None, modo=None):
    import ventanas
    return ventanas.traer(nombre, pantalla, modo)["texto"]


def _ventana(nombre, accion, pantalla=None):
    import ventanas
    return ventanas.accion_ventana(nombre, accion, pantalla)["texto"]


def _escritorio(restaurar=False):
    import ventanas
    ventanas.mostrar_escritorio(restaurar)
    return "Ventanas restauradas." if restaurar else "Ahí tienes el escritorio."


def _pestana(texto):
    import ventanas
    return ventanas.pestana(texto)["texto"]


def _hora():
    return f"Son las {datetime.now():%H:%M}."


def _fecha():
    import herramientas
    return f"Hoy es {herramientas.fecha_bonita()}."


def _volumen(accion, cantidad=10):
    import herramientas
    r = herramientas.volumen(accion, int(cantidad))
    m = re.search(r"al (\d+)%\.$", r)
    if accion in ("subir", "bajar", "fijar") and m:
        return f"Volumen al {m.group(1)}."
    return r


def _musica(accion):
    import herramientas
    return herramientas.controlar_musica(accion)


def _temporizador(minutos, etiqueta=""):
    import herramientas
    herramientas.poner_temporizador(minutos, etiqueta)
    if minutos < 1:
        cuanto = f"{round(minutos * 60)} segundos"
    elif minutos >= 60 and minutos % 60 == 0:
        cuanto = f"{int(minutos // 60)} hora{'s' if minutos >= 120 else ''}"
    else:
        cuanto = f"{minutos:g} minuto{'s' if minutos != 1 else ''}"
    return f"Temporizador de {cuanto}{' para ' + etiqueta if etiqueta else ''} en marcha."


def _alarma(hora, etiqueta=""):
    import herramientas
    r = herramientas.poner_alarma(hora, etiqueta)
    return re.sub(r"^Alarma \d+ puesta", "Alarma puesta", r)


def _cancelar_temporizadores():
    import herramientas
    return herramientas.cancelar_temporizador(0)


def _inbox(texto):
    import obsidian
    r = obsidian.captura_rapida(texto)
    return "Apuntado en tu Inbox." if not r.startswith("Error") else r


def _youtube(consulta):
    import herramientas
    herramientas.buscar_en_youtube(consulta)
    return f"Busco {consulta} en YouTube."


def _google(consulta):
    import herramientas
    herramientas.buscar_en_google(consulta)
    return f"Busco {consulta} en Google."


def _escena(clave):
    import escenas
    return escenas.activar(clave)


def _guardar_escena(nombre):
    import escenas
    return escenas.guardar_disposicion(nombre)


def _modo_juego(activar: bool):
    """El modo juego lo lleva el vigilante: se lo pedimos con un evento de Windows (sin red ni archivos)."""
    import ctypes
    nombre = "Local\\JarvisModoJuegoOn" if activar else "Local\\JarvisModoJuegoOff"
    evento = ctypes.windll.kernel32.OpenEventW(0x0002, False, nombre)  # EVENT_MODIFY_STATE
    if not evento:
        return "El vigilante no está en marcha, así que no puedo cambiar el modo juego."
    ctypes.windll.kernel32.SetEvent(evento)
    ctypes.windll.kernel32.CloseHandle(evento)
    return "Modo juego activado: solo te atiendo con el atajo." if activar else "Modo juego desactivado: vuelvo a escucharte."


def _clima(cuando="hoy", ciudad=""):
    import herramientas
    try:
        d = herramientas.datos_clima(ciudad, 2)
    except Exception:
        return None
    a, dd = d["current"], d["daily"]
    desc = herramientas._CODIGOS_CLIMA
    if cuando == "manana":
        return (f"Mañana en {d['lugar']}: {desc.get(dd['weather_code'][1], 'variable')}, entre "
                f"{dd['temperature_2m_min'][1]:.0f} y {dd['temperature_2m_max'][1]:.0f} grados, "
                f"con un {dd['precipitation_probability_max'][1]}% de probabilidad de lluvia.")
    return (f"En {d['lugar']} ahora: {desc.get(a['weather_code'], 'variable')}, {a['temperature_2m']:.0f} grados. "
            f"Hoy entre {dd['temperature_2m_min'][0]:.0f} y {dd['temperature_2m_max'][0]:.0f}, "
            f"lluvia {dd['precipitation_probability_max'][0]}%.")


# ==================================================================
#  ÓRDENES DEL PC (bloque 3): llaman a las herramientas de pc.py
# ==================================================================
def _h(nombre_herramienta):
    """Función que ejecuta una herramienta de pc.py/herramientas.py/extras.py por su nombre
    (las peligrosas, como cerrar_proceso o mover_archivo, piden confirmación dentro)."""
    def ejecutar(**argumentos):
        import extras  # noqa: F401  (registran sus herramientas)
        import herramientas
        import pc  # noqa: F401
        return herramientas.HERRAMIENTAS[nombre_herramienta]["funcion"](**argumentos)
    return ejecutar


ORDINAL = r"(?:primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|septim[oa]|octav[oa]|ultim[oa]|\d)"
_TIPO_ARCHIVO = {"archivo": "", "archivos": "", "fichero": "", "ficheros": "", "documento": "documento", "documentos": "documento",
                 "pdf": "pdf", "pdfs": "pdf", "foto": "imagen", "fotos": "imagen", "imagen": "imagen", "imagenes": "imagen",
                 "captura": "imagen", "capturas": "imagen", "video": "video", "videos": "video", "excel": "excel",
                 "excels": "excel", "word": "word", "words": "word", "presentacion": "presentacion", "presentaciones": "presentacion",
                 "zip": "comprimido", "zips": "comprimido", "carpeta": "", "carpetas": "", "instalador": "instalador",
                 "instaladores": "instalador", "cancion": "audio", "canciones": "audio", "audio": "audio", "audios": "audio"}
_CARPETAS = r"(?P<carpeta>descargas|documentos|escritorio|imagenes|fotos|videos|musica)"
_CUANDO_DIAS = {"hoy": 1, "ayer": 2, "esta semana": 7, "estos dias": 7, "la semana pasada": 14, "este mes": 31, "ultimamente": 14}
_DIA = r"(?:pasado\s+manana|manana|hoy|lunes|martes|miercoles|jueves|viernes|sabado|domingo)"


def _partir_hora(texto: str):
    """'9 lee mi agenda' / 'nueve y media dime el tiempo' -> ('09:00', 'lee mi agenda'). Prueba la hora más larga que valga."""
    palabras = texto.split()
    for n in range(min(6, len(palabras) - 1), 0, -1):
        hora = hora_reloj(" ".join(palabras[:n]))
        if hora:
            return hora, n
    return None, 0


def _orden_pc(t: str, original: str):
    """Devuelve Intencion, None (es de este grupo pero no está claro) o False (no es de este grupo)."""
    # --- archivos ---
    m = re.fullmatch(r"(?:busca|buscame|encuentra|encuentrame|localiza|donde\s+(?:esta|estan|tengo))\s+(?:el|la|los|las|mis|un|una|algun|alguna)?\s*"
                     r"(?P<tipo>" + "|".join(sorted(_TIPO_ARCHIVO, key=len, reverse=True)) + r")\b(?P<resto>.*)", t)
    if m:
        resto = m.group("resto").strip()
        dias, carpeta = 0, ""
        for frase, n in _CUANDO_DIAS.items():
            mm = re.search(r"(?:\s|^)(?:de\s+|desde\s+|del?\s+)?" + frase + r"$", resto)
            if mm:
                dias, resto = n, resto[:mm.start()].strip()
                break
        mm = re.search(r"(?:\s|^)(?:en|de)\s+(?:la\s+carpeta\s+(?:de\s+)?|mis\s+|el\s+)?" + _CARPETAS + r"$", resto)
        if mm:
            carpeta, resto = mm.group("carpeta"), resto[:mm.start()].strip()
        if not dias:  # «de hoy» puede ir antes de la carpeta
            for frase, n in _CUANDO_DIAS.items():
                mm = re.search(r"(?:\s|^)(?:de\s+|desde\s+)?" + frase + r"$", resto)
                if mm:
                    dias, resto = n, resto[:mm.start()].strip()
                    break
        texto = re.sub(r"^(?:que\s+se\s+llama|que\s+se\s+llaman|llamad[oa]s?|con\s+el\s+nombre|del?|sobre|que\s+tenga|con)\s+", "", resto).strip()
        texto = re.sub(r"^(?:la|el|los|las)\s+", "", texto)
        return Intencion("buscar_archivos", _h("buscar_archivos"), texto=texto, tipo=_TIPO_ARCHIVO[m.group("tipo")], dias=dias, carpeta=carpeta) \
            if (texto or dias or carpeta or _TIPO_ARCHIVO[m.group("tipo")]) else None
    if re.fullmatch(r"(?:que\s+(?:he|me\s+he)\s+descargado(?:\s+(?:hoy|ultimamente|antes))?|(?:las\s+)?ultimas\s+descargas|"
                    r"lo\s+ultimo\s+que\s+(?:he|me\s+he)\s+descargado|ensename\s+(?:mis\s+|las\s+)?(?:ultimas\s+)?descargas)", t):
        return Intencion("descargas_recientes", _h("descargas_recientes"), cuantos=5)
    m = re.fullmatch(r"(?:abre|abreme|ensename|muestrame)\s+(?:la\s+carpeta\s+(?:de\s+(?:las\s+)?|del\s+|de\s+)?(?:archivo\s+)?|mis\s+|las\s+|el\s+)?"
                     r"(?:" + _CARPETAS + r"|(?P<n>" + ORDINAL + r"))", t)
    if m and (m.group("carpeta") or "carpeta" in t):
        return Intencion("abrir_carpeta", _h("abrir_carpeta"), cual=m.group("carpeta") or m.group("n"))
    m = re.fullmatch(r"(?:abre|abreme|ensename)\s+(?:el|la)\s+(?:archivo\s+|resultado\s+|numero\s+)?(?P<n>" + ORDINAL + r")", t)
    if m:
        return Intencion("abrir_archivo", _h("abrir_archivo"), cual=m.group("n"))
    m = re.fullmatch(r"(?P<v>copia|copiame|mueve|muevelo|muevela|pasa)\s+(?:el|la)\s+(?:archivo\s+)?(?P<n>" + ORDINAL + r")\s+(?:a|al|en)\s+"
                     r"(?:la\s+carpeta\s+(?:de\s+)?|mis\s+|el\s+)?(?P<d>.+)", t)
    if m:
        if re.search(r"pantalla|monitor", m.group("d")):
            return None
        nombre = "mover_archivo" if m.group("v").startswith(("mueve", "muev", "pasa")) else "copiar_archivo"
        return Intencion(nombre, _h(nombre), cual=m.group("n"), destino=original[m.start("d"):].strip())

    # --- sistema ---
    if re.fullmatch(r"(?:cuanto|que)\s+espacio\s+(?:libre\s+)?(?:me\s+queda|queda|tengo|hay)(?:\s+(?:libre|en\s+(?:el\s+|los\s+)?discos?|en\s+el\s+ordenador|en\s+el\s+pc))*|"
                    r"espacio\s+(?:libre\s+)?(?:en|del)\s+(?:el\s+)?discos?|como\s+(?:van|estan)\s+los\s+discos|cuanto\s+disco\s+(?:me\s+)?queda", t):
        return Intencion("discos", _h("discos"))
    if re.fullmatch(r"(?:cuanta\s+bateria\s+(?:me\s+)?(?:queda|tengo|hay)|(?:como\s+(?:va|esta)\s+la\s+)?bateria|nivel\s+de\s+bateria)", t):
        return Intencion("bateria", _h("bateria"))
    m = re.fullmatch(r"que\s+(?:programas?|procesos?|apps?|aplicaciones?|cosa)\s+(?:esta\s+|estan\s+)?(?:consume|consumen|gasta|gastan|usa|usan|chupa|chupan|consumiendo|gastando|usando)\s+"
                     r"(?:mas|tanto)(?:\s+(?:de\s+)?(?P<r>cpu|procesador|ram|memoria))?|que\s+esta\s+(?:consumiendo|gastando)\s+(?:tanta\s+|tanto\s+|mas\s+)?(?P<r2>cpu|procesador|ram|memoria)?", t)
    if m:
        recurso = m.group("r") or m.group("r2") or "cpu"
        return Intencion("procesos", _h("procesos_que_mas_consumen"), por="ram" if recurso in ("ram", "memoria") else "cpu", cuantos=5)
    m = re.fullmatch(r"(?:cierra\s+(?:a\s+la\s+fuerza|forzando|forzado)|mata|termina|finaliza)\s+(?:el\s+proceso\s+(?:de\s+)?|la\s+tarea\s+(?:de\s+)?|el\s+programa\s+)?(?P<x>[a-z0-9 ._-]{2,40})"
                     r"|cierra\s+el\s+proceso\s+(?:de\s+)?(?P<y>[a-z0-9 ._-]{2,40})(?:\s+a\s+la\s+fuerza)?", t)
    if m:
        return Intencion("cerrar_proceso", _h("cerrar_proceso"), nombre=(m.group("x") or m.group("y")).strip())
    if re.fullmatch(r"(?:silencia|mutea|apaga|desactiva|corta)\s+(?:el\s+|mi\s+)?micro(?:fono)?", t):
        return Intencion("microfono", _h("microfono"), accion="silenciar")
    if re.fullmatch(r"(?:activa|enciende|desmutea|quita\s+el\s+silencio\s+(?:del|al)|reactiva)\s+(?:el\s+|mi\s+)?micro(?:fono)?", t):
        return Intencion("microfono", _h("microfono"), accion="activar")
    if re.fullmatch(r"(?:(?:esta|tengo)\s+(?:el\s+)?micro(?:fono)?\s+(?:silenciado|muteado|activo|encendido)|como\s+esta\s+(?:el\s+)?micro(?:fono)?)", t):
        return Intencion("microfono", _h("microfono"), accion="consultar")
    m = re.fullmatch(r"(?P<v>sube|subeme|baja|bajame|pon|ponme|fija|deja)\s+(?:el\s+)?(?:volumen|sonido)\s+(?:de|del|a)\s+(?P<app>[a-z0-9 ]{2,30}?)"
                     r"(?:\s+(?:a|al|hasta|en)\s+(?:el\s+)?(?P<n>" + NUM + r")(?:\s+por\s+ciento)?|\s+(?P<poco>un\s+poco|mucho))?", t)
    if m and not re.fullmatch(r"(?:todo|pc|ordenador|sistema|equipo|windows)", m.group("app")):
        n = numero(m.group("n")) if m.group("n") else None
        if m.group("v").startswith(("pon", "fija", "deja")):
            if n is None:
                return None
            return Intencion("volumen_app", _h("volumen_app"), app=m.group("app"), accion="fijar", cantidad=int(n))
        return Intencion("volumen_app", _h("volumen_app"), app=m.group("app"), accion="subir" if m.group("v").startswith("sub") else "bajar",
                         cantidad=25 if m.group("poco") == "mucho" else 10)
    m = re.fullmatch(r"(?:silencia|mutea|calla)\s+(?:a\s+)?(?P<app>[a-z0-9]{3,20})", t)
    if m and m.group("app") not in ("todo", "pc", "ordenador", "sonido", "volumen", "micro", "microfono", "equipo"):
        return Intencion("volumen_app", _h("volumen_app"), app=m.group("app"), accion="silenciar")
    m = re.fullmatch(r"(?:desmutea|quita\s+el\s+silencio\s+(?:a|de))\s+(?P<app>[a-z0-9]{3,20})", t)
    if m and m.group("app") not in ("todo", "pc", "ordenador", "sonido", "volumen", "micro", "microfono"):
        return Intencion("volumen_app", _h("volumen_app"), app=m.group("app"), accion="quitar_silencio")
    m = re.fullmatch(r"(?P<v>sube|subeme|baja|bajame|pon|ponme|fija)\s+(?:el\s+)?brillo(?:\s+de\s+(?:las?\s+)?pantallas?)?"
                     r"(?:\s+(?:a|al|hasta)\s+(?:el\s+)?(?P<n>" + NUM + r")(?:\s+por\s+ciento)?|\s+(?P<poco>un\s+poco|mucho|al\s+maximo|al\s+minimo))?", t)
    if m:
        if m.group("poco") in ("al maximo", "al minimo"):
            return Intencion("brillo", _h("brillo"), accion="fijar", cantidad=100 if "maximo" in m.group("poco") else 0)
        if m.group("n"):
            n = numero(m.group("n"))
            return Intencion("brillo", _h("brillo"), accion="fijar", cantidad=int(n)) if n is not None else None
        if m.group("v").startswith(("pon", "fija")):
            return None
        return Intencion("brillo", _h("brillo"), accion="subir" if m.group("v").startswith("sub") else "bajar", cantidad=25 if m.group("poco") == "mucho" else 10)
    if re.fullmatch(r"(?:a\s+)?(?:cuanto|como|que)\s+(?:esta\s+)?(?:el\s+)?brillo(?:\s+tengo)?", t):
        return Intencion("brillo", _h("brillo"), accion="consultar")
    if re.fullmatch(r"(?:activa|pon|ponme|entra\s+en)\s+(?:el\s+)?(?:modo\s+)?(?:de\s+)?ahorro\s+de\s+energia|modo\s+ahorro(?:\s+de\s+energia)?", t):
        return Intencion("plan_energia", _h("plan_energia"), plan="ahorro")
    if re.fullmatch(r"(?:activa|pon|ponme)\s+(?:el\s+)?(?:modo\s+|plan\s+)?(?:de\s+)?alto\s+rendimiento|modo\s+alto\s+rendimiento", t):
        return Intencion("plan_energia", _h("plan_energia"), plan="alto_rendimiento")
    if re.fullmatch(r"(?:activa|pon|ponme)\s+(?:el\s+)?(?:modo\s+|plan\s+)?equilibrado|(?:quita|desactiva)\s+(?:el\s+)?(?:modo\s+)?ahorro\s+de\s+energia", t):
        return Intencion("plan_energia", _h("plan_energia"), plan="equilibrado")
    if re.fullmatch(r"(?:que|cual\s+es\s+el)\s+plan\s+de\s+energia(?:\s+tengo|\s+esta\s+puesto)?", t):
        return Intencion("plan_energia", _h("plan_energia"), plan="consultar")
    if re.fullmatch(r"(?:bloquea|bloqueame)\s+(?:el\s+|la\s+)?(?:pc|ordenador|equipo|pantalla|sesion)", t):
        return Intencion("bloquear", _h("bloquear_equipo"))
    if re.fullmatch(r"(?:como\s+(?:va|esta)\s+(?:el\s+)?(?:pc|ordenador|equipo|sistema)|estado\s+del\s+(?:sistema|pc|ordenador)|"
                    r"cuanta\s+(?:ram|memoria)\s+(?:estoy\s+usando|uso|queda|tengo\s+libre)|como\s+va\s+la\s+(?:cpu|ram|gpu))", t):
        return Intencion("estado_del_sistema", _h("estado_del_sistema"))

    # --- apps abiertas ---
    if re.fullmatch(r"(?:que|cuantas|cuales)\s+(?:apps|aplicaciones|programas|ventanas)\s+(?:tengo|hay)\s+(?:abiert[oa]s|en\s+marcha)|"
                    r"(?:dime|lista)\s+(?:las\s+)?(?:apps|aplicaciones|ventanas)\s+abiertas", t):
        return Intencion("apps_abiertas", _h("apps_abiertas"))

    # --- portapapeles y dictado ---
    COPIADO = r"(?:lo\s+que\s+(?:he|acabo\s+de|te\s+he)\s+copiad[oa]|el\s+portapapeles|esto\s+que\s+(?:he\s+)?copiado|lo\s+copiado|el\s+texto\s+copiado)"
    if re.fullmatch(r"(?:resume|resumeme|hazme\s+un\s+resumen\s+de)\s+" + COPIADO, t):
        return Intencion("resumir_portapapeles", _h("resumir_portapapeles"))
    m = re.fullmatch(r"(?:traduce|traduceme)\s+" + COPIADO + r"(?:\s+al?\s+(?P<i>[a-z]+))?", t)
    if m:
        return Intencion("traducir_portapapeles", _h("traducir_portapapeles"), idioma=m.group("i") or "español")
    if re.fullmatch(r"(?:guarda|apunta|mete|anade|pasa)\s+" + COPIADO + r"\s+(?:en|a)\s+(?:el\s+|mi\s+)?(?:obsidian|inbox|notas|bandeja)", t):
        return Intencion("portapapeles_a_obsidian", _h("portapapeles_a_obsidian"))
    if re.fullmatch(r"(?:lee|leeme|dime|que\s+hay\s+en)\s+" + COPIADO + r"|que\s+he\s+copiado", t):
        return Intencion("leer_portapapeles", _h("leer_portapapeles"))
    m = re.fullmatch(r"(?:dicta|teclea|escribe\s+aqui|escribe\s+en\s+la\s+ventana)\s+(?:que\s+)?(?P<x>.+)", t)
    if m:
        return Intencion("escribir_texto", _h("escribir_texto"), texto=original[m.start("x"):].strip())

    # --- pantalla ---
    m = re.fullmatch(r"(?:lee|leeme)\s+(?:lo\s+que\s+(?:hay|pone)\s+en\s+)?(?:la\s+|esta\s+)?(?P<z>pantalla|ventana)|que\s+pone\s+(?:aqui|en\s+(?:la\s+|esta\s+)?(?P<z2>pantalla|ventana))", t)
    if m:
        return Intencion("leer_texto_pantalla", _h("leer_texto_pantalla"), zona="pantalla" if "pantalla" in (m.group("z"), m.group("z2")) else "ventana")
    if re.fullmatch(r"(?:abre|abreme|ensename|muestrame)\s+(?:la\s+)?ultima\s+captura(?:\s+de\s+pantalla)?", t):
        return Intencion("abrir_ultima_captura", _h("abrir_ultima_captura"))
    if re.fullmatch(r"(?:haz|hazme|saca|sacame)\s+(?:una\s+)?captura(?:\s+de\s+pantalla)?|captura\s+(?:la\s+)?pantalla", t):
        return Intencion("captura_de_pantalla", _h("captura_de_pantalla"))

    # --- recordatorios (con fecha/hora: se guardan y los avisa el vigilante) ---
    m = re.fullmatch(r"(?:recuerdame|recordatorio\s+(?:para|de))\s+(?P<c>(?:(?:el\s+)?" + _DIA + r"\s+)?a\s+las?\s+.+?|(?:el\s+)?" + _DIA + r")\s+(?:que\s+(?:tengo\s+que\s+)?|de\s+|para\s+)?(?P<x>[a-z].+)", t)
    cuando = texto = None
    if m:
        import pc
        # la hora puede ocupar varias palabras: prueba de la más larga a la más corta
        palabras = (m.group("c") + " " + m.group("x")).split()
        for n in range(len(palabras) - 1, 0, -1):
            if pc.fecha_de_texto(" ".join(palabras[:n])):
                cuando, texto = " ".join(palabras[:n]), " ".join(palabras[n:])
                break
    if not cuando:
        m2 = re.fullmatch(r"(?:recuerdame)\s+(?:que\s+(?:tengo\s+que\s+)?)?(?P<x>[a-z].+?)\s+(?P<c>(?:el\s+)?" + _DIA + r"(?:\s+a\s+las?\s+.+)?|a\s+las?\s+.+)", t)
        if m2:
            import pc
            if pc.fecha_de_texto(m2.group("c")):
                cuando, texto = m2.group("c"), m2.group("x")
    if cuando and texto:
        texto = re.sub(r"^(?:que\s+(?:tengo\s+que\s+)?|de\s+|para\s+)", "", texto)
        posicion = _normalizar(original).find(texto)
        texto_original = original[posicion:posicion + len(texto)] if posicion >= 0 else texto
        return Intencion("recordatorio", _h("crear_recordatorio"), texto=texto_original, cuando=cuando)
    if m:
        return None
    if re.fullmatch(r"que\s+recordatorios\s+tengo(?:\s+pendientes)?|(?:dime|lista)\s+(?:mis\s+|los\s+)?recordatorios", t):
        return Intencion("listar_recordatorios", _h("listar_recordatorios"))
    m = re.fullmatch(r"(?:borra|quita|cancela|elimina)\s+(?:el\s+)?recordatorio(?:\s+(?:de|del|para)\s+(?P<x>.+))?", t)
    if m:
        return Intencion("borrar_recordatorio", _h("borrar_recordatorio"), texto=m.group("x") or "")

    # --- rutinas programadas ---
    DIAS_TXT = r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)s?"
    m = re.fullmatch(r"(?P<d>cada\s+dia|todos\s+los\s+dias|a\s+diario|de\s+lunes\s+a\s+viernes|entre\s+semana|los\s+dias\s+laborables|"
                     r"(?:todos\s+)?los\s+fines\s+de\s+semana|(?:todos\s+los|cada|los)\s+" + DIAS_TXT + r"(?:\s+y\s+(?:los\s+)?" + DIAS_TXT + r")*)"
                     r"\s+a\s+las?\s+(?P<resto>.+)", t)
    if m:
        hora, n = _partir_hora(m.group("resto"))
        if not hora:
            return None
        orden_norm = " ".join(m.group("resto").split()[n:])
        orden_norm = re.sub(r"^(?:quiero\s+que\s+|que\s+)", "", orden_norm)
        posicion = _normalizar(original).rfind(orden_norm)
        orden = original[posicion:].strip() if posicion >= 0 else orden_norm
        return Intencion("programar_rutina", _h("programar_rutina"), orden=orden, hora=hora, dias=m.group("d"))
    if re.fullmatch(r"que\s+rutinas\s+(?:programadas\s+)?tengo|(?:dime|lista)\s+(?:las\s+|mis\s+)?rutinas\s+programadas", t):
        return Intencion("listar_rutinas_programadas", _h("listar_rutinas_programadas"))
    m = re.fullmatch(r"(?:borra|quita|cancela|elimina)\s+la\s+rutina\s+(?:programada\s+)?(?:de\s+(?:las?\s+)?)?(?P<x>.+)", t)
    if m:
        return Intencion("borrar_rutina_programada", _h("borrar_rutina_programada"), texto=m.group("x"))

    # --- red ---
    if re.fullmatch(r"(?:tengo|hay)\s+(?:internet|conexion(?:\s+a\s+internet)?|red)|como\s+(?:va|esta)\s+(?:el\s+|la\s+)?(?:internet|conexion|red|wifi)|"
                    r"(?:cual\s+es\s+)?mi\s+ip(?:\s+local)?|que\s+ip\s+tengo|estado\s+de\s+(?:la\s+)?red|funciona\s+(?:el\s+)?internet", t):
        return Intencion("estado_red", _h("estado_red"))
    if re.fullmatch(r"(?:que|cuanta)\s+velocidad\s+(?:de\s+internet\s+)?(?:tengo|tiene\s+(?:el\s+)?internet)(?:\s+de\s+internet)?|"
                    r"(?:haz|hazme|pasa)\s+(?:un\s+)?test\s+de\s+velocidad|mide\s+(?:la\s+velocidad\s+de\s+)?(?:internet|la\s+conexion)|a\s+cuanto\s+va\s+(?:el\s+)?internet", t):
        return Intencion("velocidad_internet", _h("velocidad_internet"))
    m = re.fullmatch(r"(?P<v>conecta|conectate\s+a|activa|desconecta|desconectate\s+de|apaga|quita)\s+(?:la\s+)?vpn(?:\s+(?P<n>.+))?|que\s+vpn\s+tengo", t)
    if m:
        if not m.group("v"):
            return Intencion("vpn", _h("vpn"), accion="listar")
        return Intencion("vpn", _h("vpn"), accion="desconectar" if m.group("v").startswith(("desc", "apaga", "quita")) else "conectar",
                         nombre=m.group("n") or "")
    return False


# ==================================================================
#  REGLAS
# ==================================================================
V_ABRIR = r"(?:abre|abreme|abrir|abrid|lanza|lanzame|ejecuta|inicia|iniciame|arranca|arrancame|pon|ponme|carga|enciende)"
V_TRAER = r"(?:ensename|ensena|muestrame|muestra|traeme|trae|saca|sacame|quiero ver|ve a|vete a|cambia a|ir a|llevame a)"
V_MOVER = r"(?:mueve|muevela|muevelo|muevemela|muevemelo|pasa|pasame|pasala|pasalo|lleva|llevate|llevame|manda|mandame|envia|tira|coloca|colocame|pon|ponme)"
DELANTE = r"\s+(?:delante|al\s+frente|en\s+primer\s+plano|por\s+encima|encima|arriba)"


def _una_orden(norm: str, original: str):
    """Intenta entender UNA orden (sin 'y'). Devuelve Intencion o None."""
    import escenas
    t = norm

    # --- escenas ---
    clave = escenas.buscar_por_frase(t)
    if clave:
        return Intencion("escena", _escena, clave=clave)
    m = re.fullmatch(r"(?:guarda|guardame|graba|salva)\s+(?:esta|la|esa)?\s*(?:disposicion|distribucion|configuracion|organizacion|escena|ventanas|las ventanas)?\s*(?:actual\s+)?como\s+(?:la\s+)?(?:escena\s+)?(?P<n>.+)", t)
    if m:
        return Intencion("guardar_escena", _guardar_escena, nombre=original[m.start("n"):].strip())

    # --- modo juego ---
    if re.fullmatch(r"(?:activa|pon|entra\s+en|enciende|activame)\s+(?:el\s+)?modo\s+juego", t):
        return Intencion("modo_juego", _modo_juego, activar=True)
    if re.fullmatch(r"(?:desactiva|quita|sal\s+del|apaga|salir\s+del)\s+(?:el\s+)?modo\s+juego", t):
        return Intencion("modo_juego", _modo_juego, activar=False)

    # --- hora y fecha ---
    if re.fullmatch(r"(?:que\s+hora\s+es|que\s+horas\s+son|dime\s+la\s+hora|me\s+dices\s+la\s+hora|la\s+hora|hora|que\s+hora\s+tenemos)", t):
        return Intencion("hora", _hora)
    if re.fullmatch(r"(?:que\s+dia\s+es(?:\s+hoy)?|a\s+que\s+(?:dia\s+)?estamos(?:\s+hoy)?|que\s+fecha\s+es(?:\s+hoy)?|dime\s+la\s+fecha|"
                    r"en\s+que\s+dia\s+estamos|que\s+dia\s+de\s+la\s+semana\s+es(?:\s+hoy)?|a\s+cuantos\s+estamos(?:\s+hoy)?)", t):
        return Intencion("fecha", _fecha)

    # --- clima ---
    m = re.fullmatch(r"(?:que\s+tiempo\s+(?:hace|hara|va\s+a\s+hacer)|como\s+esta\s+el\s+tiempo|que\s+temperatura\s+hace|"
                     r"como\s+(?:va|viene)\s+el\s+tiempo|dime\s+el\s+tiempo|el\s+tiempo)"
                     r"(?:\s+(?P<c1>hoy|ahora|manana|fuera))?(?:\s+en\s+(?P<ciudad>[a-z ]{3,30}?))?(?:\s+(?P<c2>hoy|ahora|manana))?", t)
    if m:
        cuando = "manana" if "manana" in (m.group("c1"), m.group("c2")) else "hoy"
        ciudad = original[m.start("ciudad"):m.end("ciudad")] if m.group("ciudad") else ""
        return Intencion("clima", _clima, cuando=cuando, ciudad=ciudad)

    # --- volumen ---
    m = re.fullmatch(r"(?P<v>sube|subeme|aumenta|baja|bajame|disminuye|reduce)\s+(?:el\s+|un\s+poco\s+el\s+)?(?:volumen|sonido|audio)"
                     r"(?:\s+(?:un\s+poco|un\s+poquito|un\s+pelin|(?P<mucho>mucho|bastante)|(?P<tope>a\s+tope|al\s+maximo|al\s+minimo)|"
                     r"(?P<a>a\s+|al\s+|hasta\s+(?:el\s+)?)?(?P<n>" + NUM + r")(?:\s+por\s+ciento|\s+%)?))?", t)
    if m:
        subir = m.group("v").startswith(("sub", "aum"))
        if m.group("tope"):
            return Intencion("volumen", _volumen, accion="fijar", cantidad=100 if "maximo" in m.group("tope") or "tope" in m.group("tope") else 0)
        if m.group("n"):
            n = numero(m.group("n"))
            if n is None:
                return None
            if m.group("a"):
                return Intencion("volumen", _volumen, accion="fijar", cantidad=int(n))
            return Intencion("volumen", _volumen, accion="subir" if subir else "bajar", cantidad=int(n))
        return Intencion("volumen", _volumen, accion="subir" if subir else "bajar", cantidad=25 if m.group("mucho") else 10)
    m = re.fullmatch(r"(?:pon|ponme|deja|fija)?\s*(?:el\s+)?(?:volumen|sonido)\s+(?:a|al|en|en\s+el)?\s*(?P<n>" + NUM + r")(?:\s+por\s+ciento|\s+%)?", t)
    if m and numero(m.group("n")) is not None:
        return Intencion("volumen", _volumen, accion="fijar", cantidad=int(numero(m.group("n"))))
    if re.fullmatch(r"(?:mas\s+alto|sube\s+(?:un\s+poco|eso)|subelo)", t):
        return Intencion("volumen", _volumen, accion="subir", cantidad=10)
    if re.fullmatch(r"(?:mas\s+bajo|baja\s+(?:un\s+poco|eso)|bajalo)", t):
        return Intencion("volumen", _volumen, accion="bajar", cantidad=10)
    if re.fullmatch(r"(?:silencia|silencio\s+total|mutea|mute|quita\s+el\s+(?:sonido|volumen))(?:\s+(?:el\s+)?(?:sonido|volumen|pc|ordenador|todo))?", t):
        return Intencion("volumen", _volumen, accion="silenciar")
    if re.fullmatch(r"(?:quita\s+el\s+silencio|activa\s+el\s+sonido|desmutea|unmute|vuelve\s+a\s+poner\s+el\s+sonido|reactiva\s+el\s+sonido)", t):
        return Intencion("volumen", _volumen, accion="quitar_silencio")
    if re.fullmatch(r"(?:a\s+)?(?:cuanto|que)\s+(?:esta\s+)?(?:el\s+)?volumen(?:\s+tengo)?|(?:a\s+cuanto|como)\s+esta\s+el\s+volumen", t):
        return Intencion("volumen", _volumen, accion="consultar")

    # --- música (teclas multimedia) ---
    if re.fullmatch(r"(?:pausa|pausala|pausalo|para\s+la\s+(?:musica|cancion)|pausa\s+(?:la\s+)?(?:musica|cancion|video)|deten\s+la\s+musica|"
                    r"para\s+el\s+video|stop\s+(?:a\s+la\s+)?musica)", t):
        return Intencion("musica", _musica, accion="play_pausa")
    if re.fullmatch(r"(?:reanuda|reanudala|continua|play|dale\s+al\s+play|sigue\s+con\s+la\s+musica|reanuda\s+la\s+(?:musica|cancion)|"
                    r"pon\s+la\s+musica|vuelve\s+a\s+poner\s+la\s+musica|quita\s+la\s+pausa|despausa|pon\s+play)", t):
        return Intencion("musica", _musica, accion="play_pausa")
    if re.fullmatch(r"(?:siguiente|siguiente\s+(?:cancion|tema|pista)|la\s+siguiente|pasa(?:\s+de|\s+la)?\s+cancion|salta(?:\s+(?:la|esta))?\s+cancion|"
                    r"otra\s+cancion|cambia\s+(?:de|la)\s+cancion|next|pon\s+la\s+siguiente)", t):
        return Intencion("musica", _musica, accion="siguiente")
    if re.fullmatch(r"(?:anterior|cancion\s+anterior|la\s+anterior|pon\s+la\s+anterior|vuelve\s+a\s+la\s+(?:anterior|cancion\s+anterior)|"
                    r"la\s+de\s+antes|pon\s+la\s+de\s+antes)", t):
        return Intencion("musica", _musica, accion="anterior")

    # --- temporizadores y alarmas ---
    m = re.fullmatch(r"(?:pon|ponme|crea|programa|activa|haz)?\s*(?:un\s+|una\s+)?(?:temporizador|timer|cuenta\s+atras|crono)\s+(?:de\s+)?(?P<d>.+?)"
                     r"(?:\s+(?:para|de|por)\s+(?:la\s+|el\s+|los\s+|las\s+)?(?P<e>[a-z ]{2,40}))?", t)
    if not m:
        m = re.fullmatch(r"(?:avisame|recuerdame|dime\s+algo|llamame)\s+(?:en|dentro\s+de)\s+(?P<d>.+?)(?:\s+(?:para|de|que)\s+(?P<e>[a-z ]{2,60}))?", t)
    if m:
        minutos = duracion_minutos(m.group("d"))
        if minutos:
            etiqueta = original[m.start("e"):m.end("e")] if m.group("e") else ""
            return Intencion("temporizador", _temporizador, minutos=round(minutos, 3), etiqueta=etiqueta)
        # «recuérdame en 5 minutos sacar la ropa»: la duración más larga que se entienda y el resto es la etiqueta
        palabras = m.group("d").split()
        for n in range(len(palabras) - 1, 0, -1):
            minutos = duracion_minutos(" ".join(palabras[:n]))
            if minutos:
                resto = " ".join(palabras[n:])
                pos = _normalizar(original).rfind(resto)
                return Intencion("temporizador", _temporizador, minutos=round(minutos, 3),
                                 etiqueta=original[pos:pos + len(resto)] if pos >= 0 else resto)
        return None
    m = re.fullmatch(r"(?:pon|ponme|programa|crea)?\s*(?:una\s+|la\s+)?(?:alarma|despertador)\s+(?:a|para)\s+(?P<h>.+?(?:\s+de\s+la\s+(?:manana|tarde|noche|madrugada))?)"
                     r"(?:\s+(?:para|de|por)\s+(?P<e>[a-z ]{2,40}))?", t) or \
        re.fullmatch(r"(?:despiertame|avisame|llamame)\s+a\s+(?P<h>las?\s+.+?)(?:\s+(?:para|de|que)\s+(?P<e>[a-z ]{2,40}))?", t)
    if m:
        hora = hora_reloj(m.group("h"))
        if hora:
            etiqueta = original[m.start("e"):m.end("e")] if m.group("e") else ""
            return Intencion("alarma", _alarma, hora=hora, etiqueta=etiqueta)
        return None
    if re.fullmatch(r"(?:cancela|quita|borra|elimina|para|apaga)\s+(?:el\s+|la\s+|los\s+|las\s+|todos\s+los\s+|todas\s+las\s+|mis\s+)?"
                    r"(?:temporizador(?:es)?|alarmas?|timers?|cuenta\s+atras)", t):
        return Intencion("cancelar_temporizadores", _cancelar_temporizadores)

    # --- Inbox de Obsidian ---
    m = re.fullmatch(r"(?:apunta|anota|apuntame|anotame|apuntalo|anotalo)(?:\s+en\s+(?:el\s+|mi\s+)?(?:inbox|obsidian|bandeja))?\s*(?::\s*)?(?:que\s+)?(?P<x>.+?)"
                     r"(?:\s+en\s+(?:el\s+|mi\s+)?(?:inbox|obsidian|bandeja))?", t) or \
        re.fullmatch(r"(?:anade|agrega|guarda|mete)\s+(?:en|a)\s+(?:el\s+|mi\s+)?inbox\s*(?:que\s+)?(?P<x>.+)", t)
    if m:
        x = m.group("x")
        if re.match(r"(?:en|a)\s+(?:la\s+|mi\s+)?(?:nota|agenda|diaria|lista|tarea)|como\s+tarea|una\s+tarea|una\s+nota", x) or len(x) < 3:
            return None  # nota diaria, tareas, otras notas: mejor el modelo
        return Intencion("inbox", _inbox, texto=original[m.start("x"):m.end("x")].strip())

    # --- búsquedas que se abren en el navegador ---
    m = re.fullmatch(r"(?:busca|buscame|pon|ponme)\s+(?P<q>.+?)\s+en\s+youtube", t) or \
        re.fullmatch(r"(?:busca|buscame|pon|ponme)\s+en\s+youtube\s+(?P<q>.+)", t)
    if m:
        return Intencion("youtube", _youtube, consulta=original[m.start("q"):m.end("q")].strip())
    m = re.fullmatch(r"(?:busca|buscame|googlea)\s+(?P<q>.+?)\s+en\s+google", t) or \
        re.fullmatch(r"(?:busca|buscame)\s+en\s+google\s+(?P<q>.+)", t)
    if m:
        return Intencion("google", _google, consulta=original[m.start("q"):m.end("q")].strip())

    # --- escritorio ---
    if re.fullmatch(r"(?:muestrame|ensename|ensena|muestra|ver|pon|ve\s+al|vete\s+al|ir\s+al|llevame\s+al|quiero\s+ver)\s+(?:el\s+)?escritorio|"
                    r"minimiza(?:lo)?\s+todo|esconde\s+todo|minimiza\s+todas\s+las\s+ventanas", t):
        return Intencion("escritorio", _escritorio)
    if re.fullmatch(r"(?:restaura|recupera|vuelve\s+a\s+poner|devuelveme)\s+(?:las\s+|todas\s+las\s+|mis\s+)?ventanas", t):
        return Intencion("escritorio", _escritorio, restaurar=True)

    # --- pestañas del navegador ---
    m = re.fullmatch(r"(?:ensename|muestrame|ve\s+a|vete\s+a|cambia\s+a|pon|ponme|trae|traeme|abre)\s+(?:la\s+)?pestana\s+(?:de\s+|del\s+|de\s+la\s+|con\s+|que\s+tiene\s+)?(?P<x>.+)", t)
    if m:
        return Intencion("pestana", _pestana, texto=m.group("x"))

    # --- PC: archivos, sistema, portapapeles, pantalla, recordatorios, rutinas programadas, red ---
    intencion = _orden_pc(t, original)
    if intencion is not False:
        return intencion  # una Intencion, o None si es de este grupo pero no está claro (que decida el modelo)

    # --- ventanas y apps ---
    resto, pantalla, modo = _extraer_pantalla_y_modo(t)
    delante = re.search(DELANTE + r"$", resto)
    if delante:
        resto = resto[:delante.start()].strip()

    m = re.fullmatch(r"(?P<v>minimiza|minimizame|esconde|oculta|maximiza|maximizame|agranda|cierra|cierrame|cierralo|quita|quitame)\s+(?P<x>.+)", resto)
    if m and not delante:
        tipo, valor = _objetivo(m.group("x"))
        if tipo != "app":
            return None
        v = m.group("v")
        accion = "minimizar" if v.startswith(("minim", "escond", "ocult")) else "maximizar" if v.startswith(("maxim", "agrand")) else "cerrar"
        if accion == "cerrar" and (pantalla or modo):
            return None
        return Intencion(f"ventana_{accion}", _ventana, nombre=valor, accion=accion, pantalla=pantalla)

    m = re.fullmatch(V_TRAER + r"\s+(?P<x>.+)", resto) or (re.fullmatch(V_MOVER + r"\s+(?P<x>.+)", resto) if delante else None)
    if m:
        tipo, valor = _objetivo(m.group("x"))
        if tipo == "app":
            return Intencion("traer", _traer, nombre=valor, pantalla=pantalla, modo=modo)
        return None

    m = re.fullmatch(r"(?:mueve|muevela|muevelo|muevemela|muevemelo|pasa|pasame|pasala|pasalo|lleva|llevate|manda|mandame|envia|tira|coloca|colocame)\s+(?P<x>.+)", resto)
    if m and (pantalla or modo):
        tipo, valor = _objetivo(m.group("x"))
        if tipo == "app":
            accion = modo if modo in ("mitad_izquierda", "mitad_derecha", "centrar", "maximizar") else "mover"
            return Intencion("ventana_mover", _ventana, nombre=valor, accion=accion, pantalla=pantalla)
        return None

    m = re.fullmatch(V_ABRIR + r"\s+(?P<x>.+)", resto)
    if m:
        tipo, valor = _objetivo(m.group("x"))
        if tipo is None:
            return None
        if resto.startswith("pon") and tipo == "app" and not (pantalla or modo):
            # "pon Spotify" = ábrelo; pero "pon música/la radio/algo" no es una app conocida y ya habría devuelto None
            pass
        return Intencion("abrir", _abrir, tipo=tipo, valor=valor, pantalla=pantalla, modo=modo)

    # "Spotify a la pantalla 3" (sin verbo)
    if pantalla or modo:
        tipo, valor = _objetivo(resto)
        if tipo == "app":
            return Intencion("ventana_mover", _ventana, nombre=valor, accion=modo or "mover", pantalla=pantalla)
    return None


def entender(texto: str):
    """Devuelve una lista de Intencion (varias si dices «abre X y sube el volumen») o None si no está claro."""
    if not cfg("camino_rapido.activado", True):
        return None
    norm, original = _limpiar(texto)
    if not norm or len(norm) > 160:
        return None
    unica = _una_orden(norm, original)
    if unica:
        return [unica]
    # Varias órdenes: "abre Spotify y Discord", "abre YouTube y sube el volumen"
    partes = [(m.start(), m.end()) for m in re.finditer(r"\s+(?:y|y\s+luego|y\s+despues|luego|despues)\s+", norm)]
    if not partes or len(partes) > 3:
        return None
    trozos, inicio = [], 0
    for a, b in partes:
        trozos.append((norm[inicio:a], original[inicio:a]))
        inicio = b
    trozos.append((norm[inicio:], original[inicio:]))
    intenciones, verbo = [], ""
    for n, o in trozos:
        i = _una_orden(n, o)
        if i is None and verbo:  # "abre Spotify y Discord": el segundo hereda el verbo
            i = _una_orden(f"{verbo} {n}", f"{verbo} {o}")
        if i is None:
            return None
        verbo = n.split()[0] if n.split() and re.fullmatch(V_ABRIR, n.split()[0]) else verbo
        intenciones.append(i)
    return intenciones
