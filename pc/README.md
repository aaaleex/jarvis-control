# J.A.R.V.I.S. — Asistente personal para Windows

Asistente de voz estilo Iron Man que funciona **en local** en tu PC: te escucha («Jarvis, …»), entiende lo que pides con un modelo de IA (Ollama), actúa en el PC, lee y escribe en tu Obsidian y te responde con voz natural en español, todo con una interfaz HUD futurista.

---

## 1. Instalación

### Lo que necesitas (ya lo tienes instalado en este PC)
| Programa | Para qué |
|---|---|
| **Python 3.12** | Ejecutar Jarvis (3.15 es demasiado nuevo para algunas librerías) |
| **Ollama** (https://ollama.com) | El "cerebro" local |
| Tarjeta NVIDIA (opcional) | Acelera el modelo y el reconocimiento de voz |

### Pasos
1. Haz doble clic en **`instalar.bat`**. Crea el entorno virtual `.venv`, instala las librerías de `requirements.txt` y descarga los modelos (Ollama, unos 7 GB, y Vosk, 40 MB).
2. Abre `config.yaml` y revisa tu nombre, tu ciudad y la ruta de tu vault de Obsidian.
3. Haz doble clic en **`iniciar_jarvis.bat`**. Aparece el icono ⬡ en la bandeja del sistema, junto al reloj.
4. Clic derecho en el icono › **Iniciar con Windows**. Desde entonces ya no tendrás que arrancarlo a mano.

> El primer arranque tarda más: se descarga el modelo de reconocimiento de voz (Whisper *small*, unos 500 MB).

---

## 2. Cómo funciona: vigilante + Jarvis bajo demanda

Jarvis tiene **dos partes**:

| | **Vigilante** (`vigilante.py`) | **Jarvis** (`jarvis.py`) |
|---|---|---|
| Cuándo está en marcha | Siempre, desde que inicias sesión | Solo cuando lo llamas |
| Qué hace | Icono en la bandeja, oye «Jarvis» y vigila el atajo de teclado | Interfaz, cerebro (Ollama), oído (Whisper) y voz |
| Consumo (medido) | **~130 MB de RAM y 0,4% de CPU** escuchando; **~70 MB y 0,01%** en modo juego | 4–6 GB entre RAM y VRAM |

1. Dices «Jarvis…» o pulsas el atajo.
2. Suena un pitido y el **orbe** aparece flotando en el centro de la pantalla donde tienes el ratón. Con Jarvis precargado se ve en unos 35 ms (medido); si lo llamaste por voz, no le quita el foco a lo que estás haciendo.
3. Lo que dijiste en la misma frase («Jarvis, **abre YouTube**») se ejecuta sin repetirlo.
4. Tras **5 minutos sin uso**, Jarvis se cierra solo, libera la memoria de Ollama y Whisper, y vuelve a quedar solo el vigilante.

> Si tienes un temporizador o una alarma pendiente, Jarvis no se cierra (solo se oculta) para poder avisarte.

### Cómo activarlo
- **Por voz:** di **«Jarvis»** en cualquier parte de la frase: *«Jarvis, abre YouTube»*, *«Cierra Chrome, Jarvis»*. También vale decir solo «Jarvis», esperar al pitido y dar la orden.
- **Con el atajo** **`Ctrl+Alt+J`**: abre Jarvis y te escucha. Si ya está abierto, lo muestra u oculta.
- **Con el ratón:** doble clic en el icono de la bandeja, o **clic en el orbe** para que te escuche.
- **Interrumpir:** *«Jarvis, para»* (o escribe «para» en el panel).
- **Ocultar:** `Esc` o el atajo; se desvanece en 0,2 s.

### Menú del icono de la bandeja (clic derecho)
| Opción | Qué hace |
|---|---|
| Abrir Jarvis | Lo abre o lo trae al frente |
| Ajustes, escenas y pantallas | Abre el panel (sin enseñar el orbe) |
| Pausar escucha | Deja de escuchar «Jarvis» (el atajo sigue funcionando) |
| Modo juego | Lo fuerza manualmente (normalmente se activa solo) |
| Iniciar con Windows | Casilla para arrancar el vigilante al iniciar sesión |
| Reiniciar | Reinicia el vigilante (y cierra Jarvis) |
| Salir | Cierra todo |

**Color del icono:** cian = escuchando · ámbar = modo juego · gris = en pausa · núcleo grande = Jarvis abierto.

### Modo juego
Cuando hay un juego a pantalla completa en primer plano (o uno de la lista `modo_juego.procesos`), el vigilante **apaga el micrófono y descarga el detector**. Gasta unos 70 MB y prácticamente nada de CPU, y solo responde al atajo. Al salir del juego vuelve a escuchar a los 9 segundos.
- Nunca roba el foco: el orbe de "despertando" no se muestra en modo juego.
- El atajo no usa ganchos de teclado, así que no añade retardo a tus pulsaciones.
- Si un programa a pantalla completa no es un juego (por ejemplo, una película), añádelo a `modo_juego.excluir`.

### Interfaz
A la vista **solo está el orbe**, flotando sobre el escritorio:
- **La ventana:** transparente de verdad, sin marco y sin botón en la barra de tareas. Está encima de todo mientras se ve y aparece centrada en la pantalla donde tienes el ratón.
- **Los clics fuera del orbe** pasan a la ventana que haya detrás.
- **Arrastrar el orbe** lo mueve.
- **Clic en el orbe:** te escucha.
- **Clic derecho en el orbe:** abre el **panel**.
- **`Esc`:** lo oculta con un desvanecido. Si estaba hablando o pensando, antes lo para.
- **Subtítulo (opcional):** una línea fina bajo el orbe con lo último que dijiste o respondió Jarvis. Se quita en `interfaz.subtitulos`.
- **Confirmaciones** («¿Cierro a la fuerza…?»): aparecen en esa línea. Contesta «sí» o «no» por voz, o pulsa `Intro` / `Esc`.

**El panel** (clic derecho en el orbe, o el menú del icono › *Ajustes, escenas y pantallas*) es una ventana normal y sobria:
- **Actividad:** la conversación, las acciones en tiempo real (las del camino rápido marcadas como «rápido»), el uso del sistema y una caja para **escribir órdenes**.
- **Escenas:** ver, crear, editar, probar y borrar.
- **Pantallas:** el mapa de tus monitores con sus ventanas, y la opción de renombrarlos.
- **Ajustes:** orbe (estilo, calidad, tamaño, subtítulo, velo), voz, cerebro y general. Se guardan al momento en `config.yaml`.

Cerrar el panel solo lo oculta: vuelve a abrirse al instante.

Si tu Windows no mostrara bien la transparencia, pon `interfaz.transparente: false`: el mismo orbe sobre un fondo oscuro.

### Pantallas y ventanas
Jarvis detecta tus monitores solo, también si conectas o desconectas uno. Puedes nombrarlos así:
- **Número de Windows:** «pantalla 1, 2, 3» o «la primera, segunda, tercera». En este PC: 1 = izquierda, 2 = centro (principal) y 3 = derecha.
- **«La principal».**
- **Por posición:** «izquierda», «centro» o «del medio», «derecha».
- **Por el nombre que les pongas:** desde Panel › Pantallas o en `config.yaml`, en `pantallas.nombres`, por ejemplo `3: "la tele"`.

| Dices | Hace |
|---|---|
| Abre Spotify en la tercera / Ponme Discord en la pantalla de la izquierda | La abre (o la mueve, si ya estaba abierta) y la maximiza en esa pantalla |
| Abre YouTube en la pantalla 2 | Ventana **nueva** del navegador en esa pantalla |
| Abre VS Code en la mitad izquierda de la principal | Media pantalla |
| Enséñame Discord / Pon Spotify delante | La restaura si está minimizada y la pone delante con el foco; lo demás queda detrás |
| Muéstrame Spotify en la pantalla 2 | La trae a esa pantalla y la pone delante |
| Pasa Chrome a la pantalla 3 / Mueve Spotify a la otra pantalla | La mueve de pantalla |
| Minimiza Discord / Maximiza Spotify / Cierra el bloc de notas | Lo que dice |
| Pon Chrome en la mitad derecha | Media pantalla |
| Muéstrame el escritorio / Restaura las ventanas | Minimiza todo o lo devuelve |
| Enséñame la pestaña de la clasificación | Busca esa pestaña en Chrome o Edge y la activa (sin extensiones, con UI Automation de Windows) |

### Escenas
Una escena abre varias apps y webs a la vez, cada una en su pantalla. Están en `escenas.yaml` (se relee solo al guardarlo) y en **Panel › Escenas**.
```yaml
vamos_a_jugar:
  frases: ["vamos a jugar", "hora de jugar"]   # lo que puedes decir
  pasos:
  - abrir: epic            # app (spotify, discord, vscode, obsidian…), web (youtube, https://…) o ruta a un .exe
    pantalla: principal    # 1, 2, 3, principal, izquierda, centro, derecha o tu nombre propio
    tamano: maximizar      # maximizar | mitad_izquierda | mitad_derecha | centrar | normal
he_terminado:
  frases: ["he terminado"]
  accion: cerrar_anterior  # cierra lo que abrió la última escena
```
- **«Vamos a jugar»:** Epic Games en la principal, Discord en la izquierda y Spotify en la tercera. Lanza las apps a la vez y coloca cada una en cuanto aparece su ventana.
- **«Modo estudio»:** VS Code y Obsidian, cada uno en media pantalla de la principal, y Spotify en la tercera.
- **«He terminado»:** cierra solo lo que abrió la última escena. **No toca lo que ya tenías abierto antes** y te dice qué ha dejado. Discord, Spotify y Epic se quedan en la bandeja al cerrarlos; si los abrió la escena, Jarvis termina también su proceso.
- **«Guarda esta disposición como trabajo»:** guarda qué apps tienes abiertas y en qué pantalla como la escena «trabajo».
- **Si una app no está instalada**, te lo dice y sigue con las demás.
- **Funcionan también en modo juego.** El launcher de Epic, Discord y Steam están en `modo_juego.excluir`, así que no se confunden con un juego.

### Velocidad: cómo responde tan rápido
- **Camino rápido:** las órdenes comunes se resuelven con reglas, sin pasar por el modelo, en milisegundos. Son abrir o cerrar apps y webs, pantallas y ventanas, volumen, música, hora y fecha, tiempo, temporizadores y alarmas, escenas, modo juego, búsquedas en YouTube y Google, y el Inbox. Si no está seguro, la orden pasa al modelo. Para comprobar qué entiende sin ejecutar nada: `.venv\Scripts\python.exe pruebas\probar_intenciones.py`.
- **Jarvis precargado (`interfaz.precargar`):** la ventana ya está creada y oculta, así que al llamarlo solo hay que mostrarla. Con `interfaz.precargar_oido`, Whisper también está cargado. En modo juego se cierra para no ocupar nada. El coste en reposo está en INFORME.md.
- **Al oír «Jarvis»**, el vigilante empieza a cargar el modelo mientras sigues hablando.
- **El modelo solo recibe las herramientas que puede necesitar** para cada orden, con un prompt corto.
- **Frases cortas cacheadas:** se guardan en `datos/cache_voz`, así que «Abro Spotify» suena al instante.

### Orbe 3D
Está hecho con Three.js (incluido en `web/lib`, sin Internet) y shaders GLSL propios, en `web/orbe.js`.

**Tres estilos** (`interfaz.estilo_orbe`, o Panel › Ajustes):

| Estilo | Qué es |
|---|---|
| `nucleo` (por defecto) | Esfera de energía con aspecto de vidrio luminoso: superficie deformada por ruido 3D con las normales calculadas en el shader, borde con fresnel, núcleo interior volumétrico (raymarching de un plasma con remolino), polvo de partículas y una onda circular que sigue el espectro de la voz |
| `anillo` | Anillo de 14.000 partículas que se abre con la voz, alrededor de un núcleo |
| `malla` | Esfera de meridianos y paralelos que ondula |

- **Postproceso propio:** bloom en 5 niveles, aberración cromática muy leve y tramado, para que los degradados no hagan bandas.
- **Estados:**
  - **reposo:** respiración casi imperceptible;
  - **escuchando:** se contrae y sigue tu voz;
  - **pensando:** remolino interno y un ruido más fino;
  - **hablando:** la amplitud y la onda siguen la voz real de Jarvis (16 bandas de su espectro);
  - **error:** pasa a ámbar suave, sin parpadeos;
  - **despertando:** aparición en 180 ms.

  Las transiciones entre estados son suaves (unos 0,35 s).
- **Paleta:** un solo acento cian eléctrico, más blancos y azul noche.
- **Velo detrás del orbe** (`interfaz.sombra_orbe`): es oscuro y muy suave. No se nota sobre fondos oscuros y en fondos claros mantiene el contraste.
- **Calidad:** `interfaz.orbe_calidad` admite `auto`, `alta`, `media` o `baja`. En `auto` baja sola la resolución, los pasos del núcleo y las partículas si no llega al 80 % de su objetivo de fps.
- **Rendimiento** (medido en la GTX 1660 Super):

  | Estado | fps | GPU |
  |---|---|---|
  | Reposo | 30 | 3,5 % |
  | Hablando o pensando | 60 (aunque el monitor vaya a 165 Hz) | 6,9 % |
  | Oculto | no dibuja | 0 % |
- **Tamaño de la ventana:** `interfaz.tamano_orbe` (280-900 px, 480 por defecto).
- **Para cambiar el diseño:** los colores y parámetros de cada estado están al principio de `web/orbe.js` (`ESTADOS`).
- **Para probar cambios sin abrir Jarvis:** `.venv\Scripts\python.exe pruebas\estudio_orbe.py CARPETA --estilos nucleo,anillo --fondos oscuro,claro`. Captura cada estado; las de la versión final están en `capturas/`.

### Cambiar el atajo
En `config.yaml`:
```yaml
vigilante:
  atajo: "ctrl+alt+j"     # por ejemplo "ctrl+shift+space", "alt+f12", "ctrl+alt+k"
```
Después, clic derecho en el icono › **Reiniciar**.
- Si otra aplicación ya usa esa combinación, te saldrá un aviso de Windows: elige otra.
- Evita las combinaciones con `win`, que están reservadas por Windows.
- En teclado español, `Ctrl+Alt` es lo mismo que `AltGr`. Evita `ctrl+alt+2`, `3`, `4` o `e`, que escriben `@ # ~ €`.

### Quitar el inicio automático
Elige una de estas tres formas:
- Clic derecho en el icono › desmarca **Iniciar con Windows**.
- En el panel: Ajustes › General › Iniciar con Windows.
- A mano: borra `Jarvis.lnk` de la carpeta Inicio. Ábrela con `Win+R` › escribe `shell:startup` › Enter.

No hace falta ser administrador para nada de esto.

### Ejemplos
| Dices | Hace |
|---|---|
| ¿Qué tengo hoy? | Lee tu nota diaria y tus tareas pendientes de Obsidian |
| Buenos días / Dame el briefing | Fecha, tiempo, agenda, tareas y alarmas |
| Apunta en mi inbox que debo repasar Mockito | Añade `- [ ] repasar Mockito` a `Inbox.md` |
| ¿Qué apunté sobre el proyecto X? | Búsqueda semántica en todas tus notas |
| Crea una nota «Ideas TFG» con etiqueta tfg | Nota nueva con frontmatter |
| Añade a mi nota diaria que he terminado el tema 3 | Lo añade al final de la nota de hoy |
| Abre YouTube y sube el volumen | Las dos cosas, una tras otra |
| Abre Spotify / Cierra Chrome | Abre o cierra aplicaciones |
| Pon música / Siguiente canción / Pausa | Teclas multimedia |
| Pon un temporizador de 10 minutos | Te avisa en voz alta al terminar |
| Recuérdame a las 18:00 que llame a mamá | Alarma con aviso por voz |
| ¿Qué tiempo hará mañana? | Clima con Open-Meteo |
| Mira mi pantalla, ¿qué error es este? | Captura la pantalla y la analiza con IA de visión |
| Investiga qué es Docker, resúmelo y guárdalo en Obsidian | Modo agente: busca, lee, resume y guarda |
| Modo estudio / Modo descanso | Ejecuta tus rutinas |
| Pon Chrome en la mitad izquierda / Abre Spotify en la pantalla 3 | Coloca ventanas (más en «Pantallas y ventanas») |
| Vamos a jugar / Modo estudio / He terminado | Escenas |
| Activa el modo juego | Modo juego sin tocar el icono |
| Recuerda que mi lenguaje favorito es Java | Lo guarda en su memoria permanente |
| Copia esto al portapapeles: … | Portapapeles |
| ¿Cuánta RAM estoy usando? | Estado del sistema |

### Más cosas en tu PC
Todas tienen camino rápido (milisegundos, sin modelo). Las que pueden hacer daño **piden confirmación**: mover un archivo, sobrescribir, cerrar un proceso a la fuerza o ejecutar un programa. Contesta «sí» o «no», o pulsa `Intro` / `Esc`. Nada se borra, y todo queda en `datos/jarvis.log`.

| Dices | Hace |
|---|---|
| Busca el pdf de la factura / Busca las fotos de hoy / Encuentra los archivos que se llaman informe en descargas | Busca por nombre, tipo (pdf, foto, vídeo, word, excel, zip, instalador…) y fecha en escritorio, documentos, descargas, imágenes, vídeos y música |
| Abre el segundo / Abre la carpeta del primero | Abre un resultado de la última búsqueda o su carpeta |
| ¿Qué he descargado hoy? / Abre la carpeta de descargas | Lo último descargado / la carpeta |
| Copia el primero a documentos / Mueve el 2 a la carpeta proyectos | Copia (pregunta antes de sobrescribir) / mueve (siempre pregunta) |
| ¿Cuánto espacio me queda? / ¿Cuánta batería me queda? | Discos / batería |
| ¿Qué está consumiendo tanta CPU? / ¿Qué programa gasta más memoria? | Los 5 que más consumen |
| Mata el proceso de chrome / Cierra a la fuerza notepad | Lo cierra **tras confirmar**. Nunca toca procesos de Windows ni el propio Jarvis |
| Baja el volumen de Spotify / Pon el volumen de Discord al 30 / Silencia Discord | Volumen de una sola app |
| Silencia el micro / Activa el micrófono | Micrófono de Windows (silenciado, Jarvis solo te atiende con el atajo) |
| Baja el brillo / Pon el brillo al 70 | Brillo de los monitores (DDC/CI; en este PC funciona en las pantallas 1 y 2) |
| Activa el ahorro de energía / Modo alto rendimiento / ¿Qué plan de energía tengo? | Plan de energía de Windows |
| Bloquea el ordenador | Bloquea la sesión |
| ¿Qué apps tengo abiertas? | Lista de apps con su pantalla |
| Resume lo que he copiado / Traduce lo que he copiado al inglés | Con el modelo; la traducción te la deja copiada |
| Guarda lo que he copiado en Obsidian | Al Inbox |
| Dicta hola qué tal / Teclea … | Lo escribe en la ventana activa |
| Lee la pantalla / ¿Qué pone aquí? | OCR local de Windows (sin instalar nada) de la pantalla o la ventana activa; Jarvis te lo lee |
| Haz una captura / Abre la última captura | Capturas |
| Recuérdame mañana a las 10 llamar al médico / Recuérdame el viernes a las 9 y media que tengo dentista | **Recordatorio guardado**: salta aunque Jarvis esté cerrado o hayas reiniciado (lo dispara el vigilante). En modo juego llega como aviso de Windows, sin voz |
| Cada día a las 9 lee mi agenda / De lunes a viernes a las 7 y media dime el tiempo / Todos los lunes a las 8 … | **Rutina programada**: Jarvis la hace sola a esa hora |
| ¿Qué recordatorios tengo? / ¿Qué rutinas programadas tengo? / Borra la rutina de las 9 | Ver y quitar |
| ¿Tengo internet? / ¿Cuál es mi IP? / Haz un test de velocidad | Conexión, IP local, Wi-Fi, latencia y bajada aproximada |
| Conecta la VPN / Desconecta la VPN | Solo las VPN que ya tengas configuradas en Windows (ahora mismo no hay ninguna) |

### Modos de arranque (para pruebas)
```
.venv\Scripts\pythonw.exe vigilante.py          (lo normal: el vigilante, que abre Jarvis cuando hace falta)
.venv\Scripts\python.exe jarvis.py              (Jarvis directamente, sin vigilante ni cierre por inactividad)
.venv\Scripts\python.exe jarvis.py --navegador  (la interfaz en tu navegador)
.venv\Scripts\python.exe jarvis.py --voz        (solo voz, en la terminal)
.venv\Scripts\python.exe jarvis.py --consola    (chat de texto en la terminal)
```

---

## 3. Configuración (`config.yaml`)

Todo se configura aquí, sin tocar el código. Lo más útil:

| Clave | Qué es |
|---|---|
| `usuario.nombre`, `usuario.ciudad` | Cómo te llama Jarvis y la ciudad del clima |
| `cerebro.proveedor` | `ollama` (local y gratis) o `claude` (API de Anthropic, de pago) |
| `cerebro.ollama.modelo` | `qwen3:4b-instruct` por defecto. `qwen3:8b` es más listo pero más lento con 6 GB de VRAM |
| `cerebro.claude.api_key` | Tu clave de Claude. Mejor ponla en la variable de entorno `ANTHROPIC_API_KEY` |
| `personalidad` | `clasico`, `informal` o `serio`, o crea la tuya en `personalidades` |
| `voz.motor_tts` | `edge` (voces neuronales de Microsoft, necesita internet) o `piper` (100% local) |
| `voz.voz_edge` | `es-ES-AlvaroNeural` (masculina), `es-ES-ElviraNeural` (femenina)… |
| `voz.modo_activacion` | `hibrido`, `whisper`, `wakeword` o `tecla` |
| `voz.microfono` | `null` usa el micrófono predeterminado; también puedes poner parte del nombre, p. ej. `"G733"` |
| `seguridad.carpeta_permitida` | La única carpeta donde Jarvis puede crear, leer o borrar archivos |
| `obsidian.vault` | Ruta de tu vault |
| `apps`, `webs` | Nombres cortos para tus apps y webs favoritas |
| `rutinas` | Tus rutinas (ver más abajo) |
| `briefing.automatico` | Resumen del día automático por la mañana |
| `telegram` | Control desde el móvil |
| `interfaz.estilo_orbe` | `nucleo` (por defecto), `anillo` o `malla` |
| `interfaz.tamano_orbe` | Lado de la ventana del orbe en px (480) |
| `interfaz.subtitulos` | Línea discreta bajo el orbe con lo último dicho (`true`/`false`) |
| `interfaz.sombra_orbe` | Velo oscuro muy suave detrás del orbe (contraste en fondos claros) |
| `interfaz.transparente` | `false` = el orbe sobre fondo oscuro, si la transparencia diera problemas |
| `interfaz.orbe_calidad` | `auto`, `alta`, `media` o `baja` |

Muchas opciones también se cambian desde el panel (clic derecho en el orbe › Ajustes).

**Recordatorios y rutinas programadas** se guardan en `datos/recordatorios.json` y `datos/programadas.json`. Se crean por voz, pero también puedes editar esos archivos a mano.

---

## 4. Seguridad

- **Pide confirmación** (en voz alta, o con `Intro` / `Esc` en el orbe) antes de:
  - borrar archivos, mover un archivo o sobrescribir uno;
  - ejecutar comandos de PowerShell o un programa desde «abre el archivo»;
  - apagar o reiniciar el equipo;
  - cerrar apps o procesos a la fuerza.
- **Procesos protegidos:** nunca cierra procesos de Windows (explorer, svchost, dwm…), de otros usuarios ni el propio Jarvis.
- **Sin privilegios:** no pide permisos de administrador, no abre puertos (todo escucha solo en `127.0.0.1`) y no lee contraseñas.
- **El OCR de la pantalla** no guarda la captura: la borra al terminar.
- **Archivos:** solo trabaja dentro de `seguridad.carpeta_permitida`.
- **Obsidian:** nunca borra ni sobrescribe notas. Solo añade al final o crea una copia con otro nombre, como `Nota (2).md`.
- **Apagar el PC:** se programa a 30 segundos, así que puedes cancelarlo con `shutdown /a`.
- **Registro:** todo lo que hace queda en **`datos/jarvis.log`**, en un formato legible.
- **Claves:** ninguna clave va dentro del código; todas están en `config.yaml` o en variables de entorno.

---

## 5. Arquitectura

```
vigilante.py     Proceso ligero siempre activo: bandeja, «Jarvis» (Vosk), atajo, modo juego, abre/cierra Jarvis
jarvis.py        Punto de entrada y "Asistente": une cerebro + voz + interfaz
nucleo.py        Configuración, log, eventos, memoria y confirmaciones
cerebro.py       Habla con Ollama o Claude y ejecuta las herramientas que pide el modelo
herramientas.py  Herramientas del PC (apps, webs, volumen, clima, archivos…)
pc.py            Más herramientas del PC: buscar/abrir/copiar/mover archivos, sistema, procesos, volumen por app,
                 micro, brillo, energía, portapapeles, OCR, capturas, recordatorios, rutinas programadas y red
recordatorios.py Recordatorios y rutinas programadas (ligero: lo usa el vigilante para dispararlos)
intenciones.py   Camino rápido: órdenes comunes resueltas con reglas, sin modelo
ventanas.py      Pantallas y ventanas (colocar, traer al frente, pestañas)
escenas.py       Escenas (escenas.yaml)
obsidian.py      Herramientas de Obsidian + índice semántico
extras.py        Briefing, visión, rutinas, teclado/ventanas, Telegram
voz.py           Micrófono, palabra de activación, Whisper, síntesis de voz y espectro para el orbe
interfaz.py      Servidor FastAPI + WebSocket + ventana del orbe (transparente) + panel
web/             index.html + orbe.js (orbe 3D, Three.js en web/lib) + app.js · panel.html/css/js (panel)
pruebas/         Pruebas y mediciones (duplicados, ventana del orbe, PC, ventanas, escenas, velocidad…)
capturas/        Capturas del orbe y del panel
datos/           memoria.json, jarvis.log, vigilante.log, índice de Obsidian (se crea solo)
modelos/         Whisper, Piper y Vosk (se descargan solos)
```

**Comunicación vigilante ↔ Jarvis:** HTTP local en `127.0.0.1:8765`.
- `/api/mostrar` y `/api/alternar`: mostrar u ocultar la ventana.
- `/api/audio`: el vigilante le pasa a Jarvis la frase grabada y Whisper la transcribe.
- `/api/escucha`: pausar la escucha en modo juego.
- `/api/cerrar`: cerrar Jarvis.

Mientras Jarvis está abierto, el vigilante suelta el micrófono para no oír dos veces.

**Detección de «Jarvis» en el vigilante:** Vosk con un modelo español pequeño y un vocabulario cerrado. El vocabulario incluye «jarvis» y palabras "señuelo" (Javier, jardín, Travis, Harvard, «has visto»…) para que no las confunda. Antes de elegirlo medí varias opciones con 128 frases sintéticas:

| Opción | Aciertos | Falsas activaciones |
|---|---|---|
| **Vosk + señuelos** (elegida) | **97%** | **0%** |
| Whisper tiny | 77% | 11% (y 10 veces más CPU) |

Con 48 frases nuevas, después de los ajustes: 24/24 aciertos y 0/24 falsas activaciones.

Al modelo de Vosk le quito el modelo de lenguaje general, que no hace falta con un vocabulario cerrado. Ocupa 52 MB en lugar de 99 MB, con la misma precisión. Lo genera solo en `modelos/vosk/jarvis-ligero`.

**Cómo funciona una orden:**
1. El micrófono pasa por un detector de voz (Silero).
2. Whisper la transcribe y Jarvis comprueba si dijiste «Jarvis».
3. El cerebro (qwen3) decide qué herramientas usar, las ejecuta y redacta la respuesta.
4. La respuesta se lee frase a frase en cuanto se genera (edge-tts), así empieza a hablar antes de terminar de escribir.
5. Todo se emite como eventos que la interfaz muestra en tiempo real.

**Decisiones importantes:**
- **`qwen3:4b-instruct`:** cabe entero en tus 6 GB de VRAM, maneja bien las herramientas y responde sin "pensar en voz alta".
- **Prompt fijo y precalentado:** las instrucciones y las 7 herramientas base ocupan unos 1.300 tokens (el resto solo se añaden si la orden habla de ese tema). Al arrancar, Jarvis las procesa una vez y Ollama las guarda en caché; por eso responde en segundos y no en minutos.
- **Activación híbrida:** el modelo «Hey Jarvis» de openWakeWord está entrenado en inglés y no reconoce el «Jarvis» español. Por eso Whisper revisa cada frase que dices y busca el nombre en ella.
- **Embeddings en CPU:** así no le quitan VRAM al modelo de chat ni a Whisper.
- **Obsidian por archivos:** no hace falta ningún plugin. El plugin *Local REST API* solo aportaría abrir notas en la ventana de Obsidian o lanzar comandos suyos; si algún día lo quieres, se puede añadir como herramienta extra.

---

## 6. Ampliar Jarvis

### Añadir una herramienta
En `herramientas.py` (o `extras.py`) escribe una función con tipos y un docstring, y ponle el decorador:

```python
@herramienta()
def tirar_dado(caras: int = 6) -> str:
    """Tira un dado y dice el resultado.

    Args:
        caras: número de caras del dado
    """
    import random
    return f"Ha salido un {random.randint(1, caras)}."
```

Eso es todo: el modelo la verá y la usará cuando encaje. Si es peligrosa, usa
`@herramienta(peligrosa=True, confirmacion="¿Seguro que…?")`.

### Añadir una rutina
En `config.yaml`, cada paso es `nombre_herramienta: {argumentos}`:

```yaml
rutinas:
  gaming:
    - cerrar_aplicacion: {nombre: "Code"}
    - abrir_aplicacion: {nombre: "Discord"}
    - volumen: {accion: "fijar", cantidad: 70}
    - decir: {texto: "Modo gaming. Que gane el mejor."}
```

Luego dile: *«Jarvis, modo gaming»*.

### Control desde el móvil (Telegram)
1. En Telegram, habla con **@BotFather**, escribe `/newbot` y sigue los pasos. Te dará un **token**.
2. Pega ese token en `config.yaml`, en `telegram.token`, y reinicia Jarvis.
3. Escríbele cualquier cosa a tu bot. Te contestará con **tu ID numérico**.
4. Pon ese ID en `telegram.usuarios_permitidos: [123456789]` y reinicia Jarvis.

Desde entonces solo obedece a ti. Si una orden necesita confirmación, te la pide por el chat.

### Usar Claude en lugar del modelo local
1. Crea una clave en https://console.anthropic.com.
2. Ponla en `cerebro.claude.api_key` o en la variable de entorno `ANTHROPIC_API_KEY`.
3. Cambia `cerebro.proveedor: claude`, o hazlo desde Panel › Ajustes › Cerebro.

Es mucho más listo (y también "ve" la pantalla), pero de pago. `claude-haiku-5-5` es la opción barata.

---

## 7. Solución de problemas

| Problema | Solución |
|---|---|
| «No consigo conectar con Ollama» | Abre Ollama desde el menú Inicio |
| «Falta el modelo …» | Ejecuta `ollama pull <modelo>` en una terminal |
| Responde muy lento | Cierra los juegos: comparten GPU y RAM con Jarvis. Con 6 GB de VRAM no caben ambos a la vez |
| **No reacciona a «Jarvis»** | 1) ¿El icono está ámbar o gris? Estás en modo juego o en pausa: usa el atajo o quítalo desde el menú. 2) ¿Ha salido el aviso «No encuentro el micrófono»? Conéctalo: se reconecta solo en unos segundos. 3) Prueba `voz.microfono: "G733"` en config.yaml. 4) Baja `vigilante.umbral_confianza` (por ejemplo a 0.45). 5) Mira `datos/vigilante.log`: cada activación queda como `ACTIVACIÓN «Jarvis»` |
| No me oye una vez abierto | Mira el nivel del micrófono en el orbe al hablar; revisa Configuración de Windows › Privacidad › Micrófono |
| Se activa sin llamarle | Sube `vigilante.umbral_confianza` (por ejemplo 0.8) o usa Pausar escucha. Si te pasa con una palabra concreta, añádela como señuelo en `PALABRAS` de `vigilante.py` |
| El atajo no hace nada | Puede que otra app lo use (te habrá salido un aviso). Cámbialo en `vigilante.atajo` y elige Reiniciar en el menú del icono |
| No aparece el icono de la bandeja | Puede estar escondido en la flecha ^ junto al reloj. Si no está, haz doble clic en `iniciar_jarvis.bat` y mira `datos/vigilante.log` |
| Jarvis se cierra solo | Es el ahorro de memoria tras 5 min sin uso. Cámbialo en `vigilante.inactividad_minutos` (0 = nunca) |
| No habla | Sin internet, edge-tts falla y Jarvis usa Piper automáticamente. Revisa también tus altavoces |
| Una app no se abre en la pantalla que digo | Comprueba en Panel › Pantallas qué número tiene cada monitor. Algunas apps tardan en mostrar su ventana: Jarvis espera hasta 25 s (60 s Epic) y, si no aparece, lo apunta en `datos/jarvis.log` (`VENTANAS`) |
| «Enséñame X» no la pone delante | Windows a veces bloquea el foco: la ventana queda delante pero sin foco. Vuelve a pedirlo o haz clic en ella |
| Una escena no hace lo que quiero | Edítala en Panel › Escenas o en `escenas.yaml`. El nombre de la app puede ser el del menú Inicio o la ruta a su `.exe` |
| El orbe va a tirones o la GPU se calienta | Pon `interfaz.orbe_calidad: baja` o el estilo `malla`. Con la ventana oculta no consume nada |
| La ventana tarda en salir | Comprueba que `interfaz.precargar: true` y que no estás en modo juego (en modo juego no hay ventana precargada) |
| El orbe sale con un cuadro negro o gris detrás | Tu Windows no hace la transparencia: pon `interfaz.transparente: false` |
| No puedo hacer clic en algo que está detrás del orbe | Solo el círculo del orbe recoge clics; si molesta, arrástralo a otro sitio o ocúltalo con `Esc` |
| El brillo no cambia en un monitor | Ese monitor no tiene DDC/CI activado (búscalo en su menú) |
| Un recordatorio no sonó | Si estabas jugando, llega como aviso de Windows y sin voz. El vigilante tiene que estar en marcha. Revisa `datos/recordatorios.json` y `datos/vigilante.log` (`RECORDATORIO`) |
| ¿Sigue habiendo duplicados? | `.venv\Scripts\python.exe pruebas\prueba_duplicados.py`: prueba 20 órdenes con el arranque más delicado y comprueba que todo pasa una sola vez |
| Entendió mal una orden simple | Las reglas están en `intenciones.py`. Para desactivarlas: `camino_rapido.activado: false` |
| Cualquier otra cosa | Mira `datos/jarvis.log`: todo queda registrado ahí (con milisegundos) |
