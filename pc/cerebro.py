"""
Cerebro de Jarvis: habla con el modelo (Ollama local o Claude) y ejecuta las herramientas que pida.
"""
import os
import re
import subprocess
import time
from datetime import datetime

import herramientas
import obsidian  # noqa: F401  (al importarlo se registran las herramientas de Obsidian)
import extras    # noqa: F401  (briefing, visión, rutinas y teclado)
import ventanas  # noqa: F401  (pantallas y ventanas)
import escenas   # noqa: F401  (escenas)
import pc        # noqa: F401  (archivos, sistema, portapapeles, OCR, recordatorios, red)
from nucleo import DATOS, ErrorJarvis, cfg, emitir, log, memoria_leer

# Prompt corto a propósito: el modelo lee ~190 tokens/s en tu GPU, así que cada línea cuenta en el arranque en frío.
# Sin ejemplos con datos concretos: los modelos pequeños los copian como si fueran reales.
PROMPT_BASE = """Eres JARVIS, asistente personal de {nombre} en su PC con Windows. Personalidad: {personalidad}
Hablas en español de España y tratas a {nombre} de tú.
- Tus respuestas se leen en voz alta: una o dos frases, sin markdown, listas ni emojis.
- Para actuar en el PC o consultar datos usa las herramientas; nunca inventes datos que una herramienta puede darte.
- Si piden varias cosas, llama a todas las herramientas necesarias antes de responder.
- Responde solo a lo que te preguntan. Confirma lo hecho con naturalidad, sin rutas ni datos técnicos.
- Agenda, tareas e ideas están en Obsidian: "¿qué tengo hoy?" = leer_nota_diaria y tareas_pendientes; "¿qué apunté sobre X?" = preguntar_a_mis_notas. De las tareas, menciona solo las pendientes.
- No acabes con preguntas de cortesía; pregunta solo si te falta información. Si algo falla, dilo claro y breve.
- Cada mensaje empieza con la fecha y hora entre corchetes. Ciudad de {nombre}: {ciudad}.
{memoria}"""

# ------------------------------------------------------------------
#  Herramientas por categorías: al modelo solo le mandamos las que pueden hacer falta.
#  Las BASE van siempre y en el mismo orden (Ollama guarda en caché ese trozo del prompt);
#  las extra se añaden al final solo si la orden habla de ese tema.
# ------------------------------------------------------------------
BASE = ["hora_y_fecha", "clima", "abrir_aplicacion", "abrir_web", "ventana", "buscar_web", "recordar"]
CATEGORIAS = {
    "apps": (r"cierr|cerrar|quita|escena|modo|jugar|estudi|termin|app|programa|ventana|abiert",
             ["cerrar_aplicacion", "activar_escena", "apps_abiertas"]),
    "musica": (r"music|cancion|volumen|sonido|youtube|pon |ponme|reproduc|escuch|play|pausa|spotify|tema|disco|cant|video|alto|bajo",
               ["volumen", "controlar_musica", "buscar_en_youtube", "volumen_app"]),
    "temporizadores": (r"temporizador|alarma|avisa|despierta|recuerdame|minuto|segundo|queda|cancela|timer|cuenta atras",
                       ["poner_temporizador", "poner_alarma", "listar_temporizadores", "cancelar_temporizador",
                        "crear_recordatorio", "listar_recordatorios", "borrar_recordatorio"]),
    "agenda": (r"hoy|tengo|agenda|tarea|pendiente|diari|briefing|buenos dias|resumen|apunt|anot|inbox|semana|manana",
               ["captura_rapida", "leer_nota_diaria", "tareas_pendientes", "briefing_del_dia", "anadir_a_nota_diaria"]),
    "notas": (r"nota|obsidian|idea|escrib\w* en|apunte|que (?:dije|apunte|anote|guarde)",
              ["crear_nota", "anadir_a_nota", "leer_nota", "buscar_notas", "notas_recientes", "preguntar_a_mis_notas"]),
    "web": (r"busca|google|investiga|pagina|web|articulo|lee |leer|noticia|enlace|url|informa", ["buscar_en_google", "leer_pagina_web"]),
    "archivos": (r"archivo|fichero|carpeta|documento|txt|guarda\w* en|borra|descarg|pdf|foto|imagen|mueve|copia|busca",
                 ["listar_archivos", "leer_archivo", "crear_archivo", "borrar_archivo", "buscar_archivos", "abrir_archivo",
                  "abrir_carpeta", "descargas_recientes", "copiar_archivo", "mover_archivo"]),
    "sistema": (r"apaga|reinici|suspend|bloquea|sesion|cpu|ram|gpu|sistema|rendimiento|comando|powershell|consola|ordenador|equipo|"
                r"disco|espacio|bateria|proceso|consum|brillo|energia|ahorro|micro",
                ["energia_equipo", "bloquear_equipo", "estado_del_sistema", "ejecutar_comando", "discos", "bateria",
                 "procesos_que_mas_consumen", "cerrar_proceso", "brillo", "plan_energia", "microfono"]),
    "pantalla": (r"pantalla|captura|mira|ves|que pone|error|monitor|escritorio|pestana",
                 ["mirar_pantalla", "captura_de_pantalla", "pantallas_conectadas", "mostrar_escritorio_o_restaurar",
                  "pestana_navegador", "leer_texto_pantalla", "abrir_ultima_captura"]),
    "teclado": (r"escrib|teclea|pulsa|tecla|copia|pega|portapapeles|resum|tradu",
                ["escribir_texto", "pulsar_teclas", "leer_portapapeles", "copiar_al_portapapeles", "resumir_portapapeles",
                 "traducir_portapapeles", "portapapeles_a_obsidian"]),
    "memoria":(r"olvida|recuerda|memoria|sabes de mi", ["olvidar"]),
    "rutinas": (r"rutina|modo|escena|disposicion|di |dile|repite|cada dia|todos los|programa",
                ["ejecutar_rutina", "guardar_escena", "decir", "programar_rutina", "listar_rutinas_programadas",
                 "borrar_rutina_programada"]),
    "red": (r"internet|red\b|wifi|wi-fi|\bip\b|conexion|conectad|vpn|velocidad|ping|latencia",
            ["estado_red", "velocidad_internet", "vpn"]),
}
# Descripciones más cortas que las del código (menos tokens que leer)
CORTAS = {
    "hora_y_fecha": "Hora y fecha actuales.",
    "clima": "Tiempo actual y previsión (dias=2 para mañana, 7 para la semana).",
    "cerrar_aplicacion": "Cierra una app como pulsar la X (forzar=true solo si lo piden).",
    "volumen": "Volumen del PC: subir, bajar, fijar (a un %), silenciar, quitar_silencio o consultar.",
    "controlar_musica": "Música/vídeo que suena: play_pausa, siguiente, anterior o parar.",
    "poner_temporizador": "Temporizador en minutos (decimales permitidos).",
    "poner_alarma": "Alarma a una hora HH:MM (hoy o mañana).",
    "buscar_web": "Busca en internet y te devuelve resultados para responder preguntas de actualidad.",
    "buscar_en_youtube": "Abre una búsqueda en YouTube (canciones, vídeos).",
    "captura_rapida": "Apunta una idea o recordatorio en el Inbox de Obsidian.",
    "leer_nota_diaria": "Lee la nota diaria de Obsidian (agenda de hoy u otro día).",
    "tareas_pendientes": "Tareas pendientes de Obsidian.",
    "recordar": "Guarda en memoria permanente un dato del usuario.",
}


def _normalizar(texto: str) -> str:
    import unicodedata
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def categorias_para(texto: str) -> list:
    t = _normalizar(texto)
    return [nombre for nombre, (patron, _) in CATEGORIAS.items() if re.search(patron, t)]


def nombres_herramientas(categorias=()) -> list:
    """BASE (fijas) + las herramientas sin categoría + las de las categorías pedidas, sin repetir."""
    con_categoria = set(BASE) | {h for _, lista in CATEGORIAS.values() for h in lista}
    nombres = [n for n in BASE if n in herramientas.HERRAMIENTAS]
    nombres += [n for n in herramientas.HERRAMIENTAS if n not in con_categoria]
    for c in CATEGORIAS:
        if c in categorias:
            nombres += [n for n in CATEGORIAS[c][1] if n in herramientas.HERRAMIENTAS and n not in nombres]
    return nombres


def _acortar(esquema: dict) -> dict:
    esquema = {**esquema, "parameters": {**esquema["parameters"], "properties": dict(esquema["parameters"]["properties"])}}
    if esquema["name"] in CORTAS:
        esquema["description"] = CORTAS[esquema["name"]]
    for nombre, prop in esquema["parameters"]["properties"].items():
        prop = dict(prop)
        if prop.get("description", "").strip().lower() in ("", nombre):
            prop.pop("description", None)
        esquema["parameters"]["properties"][nombre] = prop
    return esquema


def esquemas(nombres, formato="ollama") -> list:
    salida = []
    for n in nombres:
        e = _acortar(herramientas.HERRAMIENTAS[n]["esquema"])
        if formato == "ollama":
            salida.append({"type": "function", "function": e})
        else:
            salida.append({"name": e["name"], "description": e["description"], "input_schema": e["parameters"]})
    return salida


def _prompt_sistema() -> str:
    """Prompt fijo (sin la hora): así Ollama/Claude pueden reutilizar su caché y responder mucho antes."""
    nombre = cfg("usuario.nombre", "señor")
    clave = cfg("personalidad", "clasico")
    personalidad = (cfg("personalidades", {}) or {}).get(clave, "Elegante, eficiente e ingenioso.")
    datos = memoria_leer()
    memoria = ""
    if datos:
        memoria = f"- Lo que sabes de {nombre} (memoria permanente):\n" + "\n".join(f"  · {m['dato']}" for m in datos[-60:])
    return PROMPT_BASE.format(nombre=nombre, personalidad=" ".join(str(personalidad).split()),
                              ciudad=cfg("usuario.ciudad", ""), memoria=memoria)


def _con_fecha(texto: str) -> str:
    ahora = datetime.now()
    return f"[{herramientas.fecha_bonita(ahora)}, {ahora:%H:%M}] {texto}"


def _sin_eco_inicial(texto: str, pregunta: str, final: bool):
    """Quita del principio de la respuesta el eco «[fecha, hora]» y la pregunta repetida.
    Devuelve (texto que ya se puede decir, ¿hay que seguir reteniendo?)."""
    t = texto.lstrip()
    if not t:
        return "", not final
    if t.startswith("["):
        if "]" not in t:
            return ("", True) if not final and len(t) < 90 else (texto, False)
        t = t.split("]", 1)[1].lstrip()
        p = (pregunta or "").strip()
        if p and t.lower().startswith(p.lower()):
            t = t[len(p):].lstrip()
        elif not final and p and p.lower().startswith(t.lower()[:len(p)]) and len(t) < len(p):
            return "", True  # aún puede estar llegando la pregunta repetida
        return t, False
    return texto, False


# Preguntas de cortesía que no aportan nada ("¿Necesitas algo más?", "¿Quieres que...?")
CORTESIA = re.compile(r"\s*¿\s*(?:(?:y\s+)?(?:en\s+)?qu[eé]\s+(?:m[aá]s\s+)?(?:necesitas|puedo|quieres|deseas|te\s+(?:ayudo|apetece))|"
                      r"(?:necesitas|quieres|deseas)\s+(?:algo|que|alguna)|algo\s+m[aá]s)[^?]*\?\s*$", re.I)


def limpiar_texto(texto: str) -> str:
    """Quita restos que no queremos leer en voz alta (bloques de pensamiento, markdown)."""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)
    texto = re.sub(r"[*_#`]+", "", texto)
    texto = texto.strip()
    # Los modelos pequeños tienden a acabar con "¿Necesitas algo más?": lo quitamos si hay algo antes
    sin_cortesia = CORTESIA.sub("", texto)
    return sin_cortesia if len(sin_cortesia) > 3 else texto


class Cerebro:
    def __init__(self):
        self.historial = []          # mensajes de la conversación (formato del proveedor activo)
        self.proveedor = None
        self.cancelado = False       # se pone a True si dices "Jarvis, para"
        self._ollama = None
        self._claude = None
        self.preparar()

    # --------------------------------------------------------------
    def preparar(self):
        """Conecta con el proveedor configurado y comprueba que todo está listo."""
        proveedor = cfg("cerebro.proveedor", "ollama")
        if proveedor == "claude":
            clave = cfg("cerebro.claude.api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
            if not clave:
                log.warning("Proveedor 'claude' sin clave API: uso Ollama")
                emitir("error", texto="Has elegido Claude pero no hay clave API en config.yaml. Uso el modelo local.")
                proveedor = "ollama"
            else:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=clave)
        if proveedor == "ollama":
            self._preparar_ollama()
        if proveedor != self.proveedor:
            self.historial = []
        self.proveedor = proveedor
        log.info(f"CEREBRO  proveedor={proveedor} modelo={self.modelo}")

    @property
    def modelo(self) -> str:
        if self.proveedor == "claude":
            return cfg("cerebro.claude.modelo", "claude-opus-5-5")
        return cfg("cerebro.ollama.modelo", "qwen3:4b-instruct")

    def _preparar_ollama(self):
        import ollama

        self._ollama = ollama.Client(host=cfg("cerebro.ollama.url", "http://localhost:11434"))
        # La comprobación va en segundo plano: si Ollama está cargando el modelo (lo pidió el vigilante al oír
        # «Jarvis»), puede tardar unos segundos en contestar y no queremos que Jarvis espere para arrancar.
        import threading
        threading.Thread(target=self._comprobar_ollama, daemon=True, name="comprobar_ollama").start()

    def _comprobar_ollama(self):
        try:
            self._comprobar_ollama_bloqueante()
        except ErrorJarvis as e:
            log.error(str(e))
            emitir("error", texto=str(e))

    def _comprobar_ollama_bloqueante(self):
        for intento in range(20):
            try:
                modelos = [m.model for m in self._ollama.list().models]
                break
            except Exception:
                if intento == 0:  # Ollama no está abierto: intento arrancarlo yo
                    log.info("Ollama no responde; intento arrancarlo")
                    try:
                        subprocess.Popen(["ollama", "serve"], creationflags=0x08000000)
                    except FileNotFoundError:
                        raise ErrorJarvis("Ollama no está instalado. Descárgalo de https://ollama.com e instálalo.")
                time.sleep(1)
        else:
            raise ErrorJarvis("No consigo conectar con Ollama. Ábrelo desde el menú Inicio y vuelve a intentarlo.")
        modelo = cfg("cerebro.ollama.modelo", "qwen3:4b-instruct")
        if not any(m == modelo or m == f"{modelo}:latest" for m in modelos):
            raise ErrorJarvis(f"Falta el modelo '{modelo}'. Abre una terminal y ejecuta: ollama pull {modelo}")

    def _mantener(self):
        """-1 = el modelo se queda en memoria mientras Jarvis esté abierto (respuestas instantáneas)."""
        return -1 if cfg("cerebro.ollama.mantener_cargado", True) else "10m"

    def liberar(self):
        """Al cerrar Jarvis: saca los modelos de la memoria (si no, Ollama los mantendría cargados)."""
        if self.proveedor != "ollama" or not self._ollama:
            return
        for modelo in (self.modelo, cfg("cerebro.ollama.modelo_embeddings", "bge-m3")):
            try:
                self._ollama.generate(model=modelo, keep_alive=0)
            except Exception:
                pass
        log.info("CEREBRO  modelos descargados de memoria")

    def precalentar(self):
        """Carga el modelo y procesa ya las instrucciones + herramientas (lo más lento).
        Ollama guarda ese trabajo en caché, así que tu primera orden se responde rápido."""
        if self.proveedor != "ollama":
            return
        inicio = time.time()
        peticion = {"model": self.modelo, "tools": esquemas(nombres_herramientas()), "think": False,
                    "messages": [{"role": "system", "content": _prompt_sistema()}, {"role": "user", "content": _con_fecha("hola")}],
                    "options": {"num_ctx": int(cfg("cerebro.ollama.contexto", 8192)), "num_predict": 1}}
        try:
            # Guardamos la petición: el vigilante la manda a Ollama en cuanto oye «Jarvis», antes incluso
            # de que Jarvis arranque, y así el modelo ya tiene leídas las instrucciones cuando le llega tu orden.
            import json
            (DATOS / "precalentar.json").write_text(json.dumps({**peticion, "stream": False, "keep_alive": "5m"},
                                                               ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning(f"No pude guardar precalentar.json: {e}")
        try:
            r = self._ollama.chat(**peticion, keep_alive=self._mantener())
            log.info(f"CEREBRO  precalentado en {time.time() - inicio:.1f}s ({r.prompt_eval_count} tokens nuevos de prompt)")
        except Exception as e:
            log.warning(f"No pude precalentar el modelo: {e}")

    def anotar(self, texto_usuario: str, respuesta: str):
        """Una orden resuelta por el camino rápido también queda en la conversación (para que el modelo
        entienda luego «súbelo más» o «ciérralo»)."""
        self.historial.append({"role": "user", "content": _con_fecha(texto_usuario)})
        self.historial.append({"role": "assistant", "content": respuesta})
        self._recortar_historial()

    # --------------------------------------------------------------
    def pensar(self, texto_usuario: str, al_texto=None) -> str:
        """Procesa una orden. al_texto(trozo) recibe la respuesta a medida que se genera."""
        self.cancelado = False
        log.info(f"USUARIO  {texto_usuario}")
        emitir("estado", estado="pensando")
        try:
            if self.proveedor == "claude":
                respuesta = self._pensar_claude(texto_usuario, al_texto)
            else:
                respuesta = self._pensar_ollama(texto_usuario, al_texto)
        except ErrorJarvis as e:
            respuesta = str(e)
            if al_texto:
                al_texto(respuesta)
        except Exception as e:
            log.exception("Error del cerebro")
            respuesta = self._explicar_error(e)
            if al_texto:
                al_texto(respuesta)
        respuesta = limpiar_texto(respuesta)
        log.info(f"JARVIS  {respuesta}")
        emitir("respuesta", texto=respuesta)
        self._recortar_historial()
        return respuesta

    def _categorias(self, texto: str) -> list:
        """Categorías de herramientas para esta orden (+ las de la orden anterior, por si es una continuación)."""
        actuales = categorias_para(texto)
        todas = list(dict.fromkeys(actuales + getattr(self, "_categorias_previas", [])))
        self._categorias_previas = actuales
        return todas

    def _explicar_error(self, e: Exception) -> str:
        texto = str(e).lower()
        if "connect" in texto or "refused" in texto:
            return "He perdido la conexión con el modelo. Comprueba que Ollama está abierto."
        if "not found" in texto and self.proveedor == "ollama":
            return f"No encuentro el modelo {self.modelo}. Ejecuta: ollama pull {self.modelo}"
        if "authentication" in texto or "401" in texto:
            return "La clave de la API de Claude no es válida. Revísala en config.yaml."
        return f"Ha ocurrido un error inesperado: {e}"

    def _recortar_historial(self, max_mensajes: int = 30):
        """Mantiene la conversación corta para que el modelo vaya rápido.
        Siempre corta justo antes de un mensaje del usuario para no romper pares herramienta/resultado."""
        if len(self.historial) <= max_mensajes:
            return
        recorte = self.historial[-max_mensajes:]
        while recorte and not (recorte[0].get("role") == "user" and isinstance(recorte[0].get("content"), str)):
            recorte.pop(0)
        self.historial = recorte

    # --------------------------------------------------------------
    #  OLLAMA (local)
    # --------------------------------------------------------------
    def _pensar_ollama(self, texto_usuario: str, al_texto) -> str:
        self.historial.append({"role": "user", "content": _con_fecha(texto_usuario)})
        herramientas_ollama = esquemas(nombres_herramientas(self._categorias(texto_usuario)))
        texto_final = ""
        for paso in range(int(cfg("cerebro.max_pasos_herramientas", 8)) + 1):
            mensajes = [{"role": "system", "content": _prompt_sistema()}] + self.historial
            contenido, llamadas = "", []
            flujo = self._ollama.chat(
                model=self.modelo, messages=mensajes, tools=herramientas_ollama, stream=True, think=False,
                options={"num_ctx": int(cfg("cerebro.ollama.contexto", 8192)), "temperature": 0.5},
                keep_alive=self._mantener(),
            )
            # El modelo pequeño a veces empieza copiando el prefijo del mensaje («[miércoles…, 02:42] ¿Qué tengo
            # hoy?»): se retiene el principio mientras pueda serlo y se quita (ni se dice ni queda en el historial)
            retenido, filtrando = "", True
            for trozo in flujo:
                if self.cancelado:
                    break
                if trozo.message.content:
                    contenido += trozo.message.content
                    if filtrando:
                        retenido += trozo.message.content
                        salida, filtrando = _sin_eco_inicial(retenido, texto_usuario, final=False)
                        if not filtrando and salida and al_texto:
                            al_texto(salida)
                    elif al_texto:
                        al_texto(trozo.message.content)
                if trozo.message.tool_calls:
                    llamadas.extend(trozo.message.tool_calls)
            if filtrando and retenido:
                salida, _ = _sin_eco_inicial(retenido, texto_usuario, final=True)
                if salida and al_texto:
                    al_texto(salida)
            contenido = _sin_eco_inicial(contenido, texto_usuario, final=True)[0]

            mensaje = {"role": "assistant", "content": contenido}
            if llamadas:
                mensaje["tool_calls"] = [{"function": {"name": c.function.name, "arguments": c.function.arguments}}
                                         for c in llamadas]
            self.historial.append(mensaje)
            texto_final += contenido
            if not llamadas or self.cancelado:
                break
            for llamada in llamadas:
                if self.cancelado:
                    break
                resultado = herramientas.ejecutar(llamada.function.name, llamada.function.arguments)
                self.historial.append({"role": "tool", "content": resultado, "tool_name": llamada.function.name})
            if paso == int(cfg("cerebro.max_pasos_herramientas", 8)) - 1:
                self.historial.append({"role": "user", "content": "(Sistema: límite de pasos alcanzado. Responde ya al usuario con lo que tengas, sin usar más herramientas.)"})
        return texto_final

    # --------------------------------------------------------------
    #  CLAUDE (API de Anthropic)
    # --------------------------------------------------------------
    def _pensar_claude(self, texto_usuario: str, al_texto) -> str:
        import anthropic

        self.historial.append({"role": "user", "content": _con_fecha(texto_usuario)})
        herramientas_claude = esquemas(nombres_herramientas(self._categorias(texto_usuario)), formato="claude")
        texto_final = ""
        for _ in range(int(cfg("cerebro.max_pasos_herramientas", 8)) + 1):
            try:
                respuesta = self._claude.beta.messages.create(
                    model=self.modelo,
                    max_tokens=4096,
                    system=_prompt_sistema(),
                    tools=herramientas_claude,
                    messages=self.historial,
                    output_config={"effort": cfg("cerebro.claude.esfuerzo", "low")},
                    # Si el modelo rechaza una petición, la API reintenta con otro modelo adecuado
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except anthropic.AuthenticationError:
                raise ErrorJarvis("La clave de la API de Claude no es válida. Revísala en config.yaml.")
            except anthropic.RateLimitError:
                raise ErrorJarvis("La API de Claude me pide que espere un poco (límite de uso). Prueba en un minuto.")
            except anthropic.APIConnectionError:
                raise ErrorJarvis("No hay conexión con la API de Claude. ¿Tienes internet?")

            # Guardamos el contenido completo (incluye bloques de pensamiento que hay que devolver tal cual)
            self.historial.append({"role": "assistant", "content": respuesta.content})
            if respuesta.stop_reason == "refusal":
                texto = "Prefiero no hacer eso."
                if al_texto:
                    al_texto(texto)
                return texto_final + texto
            for bloque in respuesta.content:
                if bloque.type == "text" and bloque.text:
                    texto_final += bloque.text
                    if al_texto:
                        al_texto(bloque.text)
            llamadas = [b for b in respuesta.content if b.type == "tool_use"]
            if not llamadas or self.cancelado:
                break
            resultados = [{"type": "tool_result", "tool_use_id": b.id,
                           "content": herramientas.ejecutar(b.name, b.input)} for b in llamadas]
            self.historial.append({"role": "user", "content": resultados})
        return texto_final
