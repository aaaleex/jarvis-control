# INFORME — Mejoras de Jarvis (3 de noviembre de 2026)

Están hechas y probadas de verdad las cinco fases. A las 23:23 abriste Fortnite y paré; el resto (medición final, capturas, GPU y regresiones) lo terminé el 4 de noviembre entre las 00:44 y la 01:10, en cuanto cerraste el juego.

## Fase 0 · Copias de seguridad
- **Git no está instalado,** así que he usado zips fechados en `C:\Users\alexa\jarvis_copias\`:
  - `completa-20261103-1917`: copia íntegra antes de tocar nada.
  - `fase0-…zip`, `fase1-…zip` y `fase2y3-…zip`: un punto bueno por fase.
- `config.yaml`: copia previa en `config.backup-20261103-1944.yaml` (más la de la sesión anterior).
- **No he tocado tu vault de Obsidian** ni he abierto Obsidian: al arrancar escribe en `.obsidian/workspace.json`.

## Antes / después (medido con `pruebas/medir_velocidad.py` y `pruebas/prueba_voz_e2e.py`)

| Medida | Antes | Después |
|---|---|---|
| Ctrl+Alt+J → ventana visible | 6–9 s | **0,05 s** (*) |
| Decir «Jarvis» → pitido | 0,20 s | 0,25 s |
| Decir «Jarvis» → ventana visible | ~6 s | **0,35 s** |
| Orden simple por voz (Jarvis dormido) → hecha, desde que acabas la frase | 15 s o más (cargaba todo) | **0,77 s** |
| Orden simple con Jarvis abierto («qué hora es», «sube el volumen») | 2,3–3,2 s | **0,00–0,34 s** |
| Primera respuesta del modelo en frío, desde el atajo | ~77 s o más (+30 s si buscaba en web) | **12,5 s** (21,7 s justo después de cerrar Fortnite, ver «Límites») |
| Respuesta del modelo en caliente | 1,1 s (sin herramientas) / 17 s (buscando en web) | **0,4–1,6 s** (peor caso medido: 3,75 s) |
| Instrucciones que lee el modelo al arrancar | 5.491 tokens | **1.284 tokens** |
| RAM del vigilante | 116 MB (80 privada) | 117 MB (80 privada) |
| Jarvis dormido en reposo, con Whisper precargado (Python + 6 procesos WebView2) | no existía | 1.077 MB (662 privada); +~1 GB de VRAM; GPU 0,3 % |
| Jarvis dormido sin Whisper (`precargar_oido: false`) | no existía | 488 MB (169 privada), 0,08 % de CPU |
| Jarvis abierto | 1.268 MB (726 privada) | 1.209 MB (753 privada) |
| VRAM con todo cargado | 5,65 GB | 5,20 GB |
| GPU del orbe 3D (GTX 1660 Super) | — | 1,8 % en reposo visible · 3,9 % hablando · ~0,3 % oculto |

(*) Medición final del 4 de noviembre, con el código definitivo: el marco de la ventana aparece en 0,05 s y el contenido se pinta unos 0,4 s después (`show()` de pywebview, que hace falta para que WebView2 no deje la ventana en negro).

La medición final completa está en `pruebas/mediciones.json` (etiqueta `final`).

**Objetivos:**
- Ventana visible en menos de 1,5 s: ✅ (0,04–0,4 s).
- Órdenes simples en menos de 1,5 s: ✅ (0,77 s por voz desde Jarvis dormido; 0,1 s con Jarvis abierto).
- Modelo en caliente en 3 s o menos: ✅ en lo normal (0,65–0,83 s). Hubo un caso de 3,6 s.
- Modelo en frío: 12,5 s. Mejor que los 77 s de antes, pero no instantáneo (ver «Límites»).

## Fase 1 · Velocidad: qué hice
1. **Camino rápido sin IA** (`intenciones.py`):
   - Resuelve con reglas abrir/cerrar apps y webs, pantallas y ventanas, traer al frente, escritorio y pestañas.
   - También volumen, música, hora y fecha, tiempo (hoy y mañana), temporizadores y alarmas (en palabras: «siete y media», «media hora», «ocho menos cuarto», «6 de la tarde»), escenas, modo juego, YouTube y Google, e Inbox de Obsidian.
   - Entiende varias órdenes unidas con «y».
   - Si no está seguro, pasa la orden al modelo.
   - Prueba sin ejecutar nada: `pruebas/probar_intenciones.py` → **57/57 frases correctas**, 19 ms de media. Esto incluye 10 frases que deben ir al modelo, como «qué tengo hoy», «pon música relajante» o «abre fortnite».
2. **Prompt corto y herramientas por categorías** (`cerebro.py`):
   - Siempre van 7 herramientas base, en el mismo orden para que Ollama guarde ese trozo en caché.
   - El resto solo se añade si la orden habla de ese tema.
   - Las descripciones son más cortas y he quitado los ejemplos con datos que el modelo copiaba.
   - Resultado: de 5.491 a 1.284 tokens.
3. **Precalentar al oír «Jarvis»:**
   - El vigilante manda a Ollama la petición de precalentado, que Jarvis guarda en `datos/precalentar.json`, en cuanto Vosk oye «Jarvis» (resultado parcial). La frase aún no ha terminado.
   - A la vez despierta al Jarvis precargado.
   - Si era una falsa alarma, Jarvis vuelve a dormir solo (`/api/falsa_alarma`).
4. **Ventana precargada** (`interfaz.precargar: true`):
   - El vigilante mantiene un Jarvis «dormido», con la ventana ya creada y oculta. Tiene el código ya importado, openWakeWord preparado y Whisper en la GPU (`interfaz.precargar_oido: true`).
   - Despertar es mostrar la ventana. Las alternativas eran peores: crear la ventana en el momento tardaba 6 s, y el orbe Tk ya existía pero no resolvía la carga de modelos.
   - En modo juego el dormido se cierra.
   - Tras el cierre por inactividad se crea uno nuevo, limpio.
5. **Otras mejoras:**
   - Whisper con `int8_float16`: carga en 1,6 s (antes 2,9) y transcribe en 0,4 s (antes 1,0), con el mismo texto.
   - Fin de frase más corto: 0,7 s en Jarvis; en el vigilante, 0,25 s tras el final de Vosk.
   - openWakeWord carga en segundo plano.
   - La comprobación de Ollama ya no bloquea el arranque.
   - Caché de voz para frases cortas (`datos/cache_voz`).
   - La voz ya empezaba a hablar con la primera frase (streaming) y se mantiene.
6. **Claude preparado, no activado:**
   - En `config.yaml` (`cerebro.claude`) está explicado cómo activarlo: pon la clave y `proveedor: claude`. Con el camino rápido, solo lo ambiguo iría a la API.
   - Modelo propuesto: `claude-haiku-5-5`, por velocidad. No lo he podido probar sin clave.

**Probé y descarté Vulkan en Ollama.** Lee el prompt 3 veces más rápido (668 frente a 220 tokens/s), pero tarda unos 12 s en cargar el modelo cada vez, frente a 3 s con CUDA. En frío sale peor, así que sigo con CUDA. No he cambiado nada de tu Ollama.

## Fase 2 · Pantallas y ventanas (`ventanas.py`)
- **Monitores:** posición, tamaño, cuál es el principal y escala por monitor. Se leen de nuevo en cada orden, así que se entera si conectas o desconectas uno.
  - **Nombres:** número de Windows (pantalla 1 = izquierda, 2 = centro y principal, 3 = derecha), «principal», «izquierda/centro/derecha» y nombres propios (pestaña Pantallas o `pantallas.nombres`).
  - **DPI:** el proceso de Jarvis es DPI-aware por monitor (PER_MONITOR_AWARE_V2).
- **Abrir en una pantalla:** si la app ya está abierta, no la duplica: la mueve. Si no, la lanza, espera a su ventana y la coloca. Las webs se abren en una ventana nueva de Chrome.
- **Traer al frente:** restaura si está minimizada, la sube en el orden de ventanas y le da el foco. Combina AttachThreadInput, el truco de la tecla Alt y el cambio de orden de ventanas, y comprueba que de verdad ha funcionado.
- **Más acciones:** minimizar, maximizar, cerrar (como pulsar la X), mover a otra pantalla, mitad izquierda o derecha, escritorio y restaurar.
- **Pestañas del navegador:** «enséñame la pestaña de X» funciona en Chrome y Edge sin extensiones, con UI Automation de Windows (comtypes ya estaba instalado). Probado: 0,21 s. En Firefox no lo he probado.
- **Prueba real** (`pruebas/prueba_ventanas.py`), con órdenes enviadas a Jarvis en segundo plano, como en el uso normal, y posiciones comprobadas enumerando ventanas: **12/12 correctas.**
  - La calculadora se abrió en la pantalla 3, pasó a la 2 y se cerró.
  - El bloc de notas quedó en la mitad izquierda de la 3 y luego en la mitad derecha.
  - YouTube se abrió en una ventana nueva en la 1.
  - Con Chrome tapando Discord, «enséñame Discord» dejó **Discord delante y con el foco, y Chrome detrás**. Lo mismo con Spotify, que es una app Electron.
  - Pestaña encontrada; escritorio y restaurar.
  - Al acabar cerré lo que abrí y recoloqué tus ventanas.
  - Una incidencia: en la primera pasada, la restauración automática no devolvió Spotify a la pantalla 1, y mi comprobación tenía un error que no lo detectaba. Lo devolví a mano y corregí la prueba.

## Fase 3 · Escenas (`escenas.py`, `escenas.yaml`)
- **Escenas de ejemplo creadas:** «vamos a jugar», «modo estudio» y «he terminado». Se gestionan por voz («guarda esta disposición como X») y desde la pestaña Escenas (ver, crear, editar, probar y borrar).
- **Apps encontradas en tu PC:**
  - Epic Games: `C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe`.
  - Discord: `%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe`.
  - Spotify: versión de la Microsoft Store, se abre con el protocolo `spotify:`.
  - VS Code y Obsidian: en `%LOCALAPPDATA%\Programs`.
  - Como último recurso, cualquier app del menú Inicio.
- **Prueba real** (`pruebas/prueba_escenas.py`): **10/10 correctas.**
  - «Vamos a jugar»: Jarvis responde en 0,38 s y deja todo colocado en 1,5 s. Epic quedó en la 2, Discord en la 1 y Spotify en la 3.
  - El vigilante no activó el modo juego con Epic ni Discord a pantalla completa.
  - «He terminado» cerró solo la ventana de Epic (ya estaba en la bandeja desde ayer, así que su proceso no se tocó) y dejó Discord y Spotify, que ya estaban abiertos.
  - Con el modo juego activado por chat («activa el modo juego»), una escena de prueba (calculadora en la 3 y bloc de notas en la 1) funcionó, y «he terminado» la cerró.
  - «Guarda esta disposición» guardó 5 ventanas con su pantalla y tamaño. Borré después esa escena de prueba.
- **No probé «modo estudio» completo,** porque abre Obsidian y Obsidian escribe en tu vault. El mecanismo es el mismo que el de las escenas probadas.

## Fase 4 · Interfaz (`web/`)
- **Diseño nuevo:**
  - Tema oscuro con un solo acento cian.
  - Espaciado en múltiplos de 4, Segoe UI para el texto y Orbitron solo para la marca.
  - A la izquierda la conversación; en el centro el orbe, el subtítulo y la caja de texto; a la derecha pestañas (Acciones, Pantallas, Escenas, Ajustes).
  - Sistema, tiempo y notas van plegados.
  - Modo compacto (barra) y un botón para ocultar paneles.
- **Orbe 3D con Three.js r170, incluido en `web/lib`** (690 KB, sin Internet):
  - Núcleo deformado con ruido 3D y brillo de borde (fresnel), corazón luminoso y halo.
  - Tres anillos segmentados en planos distintos y 1.800 partículas animadas en la GPU.
  - Reacciona a tu voz y a la de Jarvis.
  - Estados: reposo, escuchando, pensando, hablando, error y despertando.
  - Calidad automática (alta, media o baja según los fps); 30 fps en reposo; render parado con la ventana oculta.
- **Errores de JavaScript:** se mandan a `datos/jarvis.log` (línea `INTERFAZ error de JavaScript`). En las pruebas hechas no apareció ninguno.
- **Revisado con capturas:** los seis estados del orbe, las cuatro pestañas y el modo compacto. Arreglé tres cosas:
  - **Al hablar, el orbe parecía cristal roto:** la deformación era demasiado grande para las normales de la esfera. La reduje; ahora ondula sin romperse.
  - **Modo compacto:** el orbe salía diminuto (solo se veían partículas) y cortado en cuadrado, había un hueco vacío en medio y el texto de la caja salía cortado. Ahora acerco la cámara, el orbe se recorta en círculo, aparece «Di «Jarvis» o escribe una orden» cuando no hay subtítulo y la caja es más ancha.
  - **WebView2 seguía usando los `.js` antiguos de su caché** después de editarlos. Ahora `index.html` añade a cada archivo `?v=<fecha de modificación>` y los recursos se sirven con `Cache-Control: no-cache`.
- **Errores de JavaScript en el log:** 0.

## Problemas que encontré y corregí por el camino
- **Ventana dormida visible:** pywebview no respetaba `hidden=True` y dejaba un rectángulo negro en mitad de la pantalla principal. Ahora la oculto explícitamente y lo verifiqué: queda oculta.
- **Bloqueo total de Jarvis al despertar con el atajo:** venía de cambiar `on_top` (propiedad de .NET) desde otro hilo. Ahora uso la API de Windows por ctypes.
- **Ventana en negro:** la mostraba sin avisar a WebView2. Ahora se muestra por ctypes y además por `show()` de pywebview.
- **Dos procesos de Jarvis en el mismo puerto:** uvicorn usa `SO_REUSEADDR` y en Windows lo permite. He añadido un mutex de instancia única (`Local\JarvisInterfaz`). Comprobado en real: un segundo arranque sale enseguida con «ya hay un Jarvis en marcha».
- **«para» escrito en el chat iba al modelo,** que contestaba cualquier cosa. Por voz ya funcionaba. Ahora «para», «calla», «stop»… escritos hacen lo mismo que el botón de parar.
- **La precarga dejaba de relanzarse** tras varios cierres seguidos. Ahora solo cuenta como fallo si el proceso nunca llegó a responder.

## Decisiones que tomé por mi cuenta
- **Copias en zips** (sin git disponible).
- **Escena «vamos a jugar»:** tu pantalla 2 de Windows es la principal, así que puse Discord en la izquierda (pantalla 1) para que cada app tenga su pantalla. Es una línea en `escenas.yaml`.
- **«He terminado» termina el proceso** de Spotify, Discord y Epic **solo si los abrió la escena**, porque al pulsar la X se quedan en la bandeja.
- **Whisper precargado en reposo,** activado por defecto. Hace que las órdenes por voz sean instantáneas, pero ocupa VRAM y RAM en reposo. Se quita con `interfaz.precargar_oido: false`.
- **Una frase reconocida por voz enciende la ventana sin quitarte el foco;** el atajo sí la activa.
- **CUDA en vez de Vulkan** en Ollama.

## Librerías nuevas
- **Three.js r170** (local, en `web/lib`): necesaria para el orbe 3D.
- No hay paquetes nuevos de Python.

## Límites que quedan
- **Justo después de cerrar Fortnite, la primera respuesta en frío tardó 21,7 s.** Lo más probable es que el juego hubiera sacado de la caché de Windows el archivo del modelo, que tuvo que leerse otra vez del disco. Es un caso puntual.
- **La primera respuesta del modelo en frío sigue tardando unos 12 s.** El modelo tiene que cargar en tu GTX 1660 Super y leer sus instrucciones a unos 220 tokens/s. Las órdenes simples no lo notan porque no usan el modelo. Para mejorarlo:
  - subir `vigilante.inactividad_minutos`, para que no se libere tan a menudo;
  - o activar Claude.
- **La primera respuesta conversacional de la prueba fue rara** («¿Ya has terminado de ver el partido?»). Probablemente viene de un dato de tu memoria permanente (`datos/memoria.json`), que no he tocado.
- **Las pestañas** funcionan en Chrome y Edge, no en Firefox.

## Fase 5 · Pruebas finales (4 de noviembre, con el código definitivo)
Todas se hicieron con la voz de Jarvis silenciada.
- **Medición final** (`medir_velocidad.py final`): ver la tabla de arriba.
- **Intenciones:** 57/57. **Ventanas:** 12/12, con tus ventanas restauradas. **Escenas:** 10/10, con las escenas de prueba borradas.
- **«¿Qué tengo hoy?»:** contestó con tu tarea («repasar Mockito») y el tiempo, en 12,5 s. Es el modelo en frío.
- **«para»:** ahora se calla sin pasar por el modelo; antes, escrito en el chat, contestaba una tontería.
- **Inbox:** solo comprobé que «apunta en el inbox comprar leche» se entiende como `inbox(texto='comprar leche')`. **No lo ejecuté** para no escribir en tu vault.
- **Cierre por inactividad:** Jarvis se cerró a los 5 min exactos (01:05:54), liberó los modelos y el vigilante creó un nuevo Jarvis dormido.
- **Instancia única:** comprobada en real.
- **Copia final:** `C:\Users\alexa\jarvis_copias\final-20261104-0107.zip`. Contiene el código, la configuración y la web. No incluye `.venv`, `modelos`, `datos` ni el modelo antiguo `_antiguo\phi3-mini.gguf`, que sí están en la copia completa del principio.
- **Estado al acabar:** vigilante y Jarvis dormido en marcha, voz activada, modo completo y tus ventanas como estaban.

## Lo que tienes que hacer tú
Nada obligatorio. Si quieres usar Claude para lo ambiguo, pon la clave en `config.yaml` y cambia el proveedor.
