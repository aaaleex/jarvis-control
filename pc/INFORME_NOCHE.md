# INFORME DE LA NOCHE: 4 de noviembre de 2026, de 01:15 a 03:00

Están hechos y probados los tres bloques, en el orden que pediste: el bug de duplicados, la interfaz y las herramientas nuevas. Al final de este informe digo qué no he podido probar y qué ha salido mal.

- **Voz y pitidos:** silenciados durante todas las pruebas y restaurados al terminar.
- **Copias:**
  - copia completa al empezar: `C:\Users\alexa\jarvis_copias\noche-inicio-20261104-0115.zip` (3,2 GB);
  - una copia del código por bloque: `noche-bloque1/2/3-….zip`;
  - copia final: `noche-final-….zip`.
- **Git:** sigue sin estar instalado.
- **Retomar:** en `NOTAS_NOCHE.md` está todo lo necesario para seguir si algo se corta.

---

## 1. El bug de duplicados

### Qué se duplicaba
Estaba en tu propio log de anoche: a las 01:09:21 y 01:09:22 aparecen **dos «asistente creado» en el mismo proceso**. Con dos asistentes había dos hilos escuchando el mismo micrófono, así que **cada frase se oía, se ejecutaba y se contestaba dos veces**. En el log se ve «OÍDO 'Jarvis.'» repetido y «Abre una pestaña de Google» abierta dos veces, con dos respuestas distintas.

De las cuatro posibilidades que me planteaste, era la (d), con efecto también en la (c):

| Posibilidad | Resultado |
|---|---|
| (a) varias instancias o ventanas | Ya lo impedía el mutex de la sesión anterior; lo he comprobado |
| (b) el orbe dos veces en la ventana | No pasaba |
| (c) mensajes duplicados en la conversación | Sí, como consecuencia de (d) |
| (d) la orden se ejecuta dos veces | **Esta era la causa** |

### Causa raíz: dos carreras al arrancar
1. **En `interfaz.py`:**
   - El vigilante despertaba al Jarvis dormido (`/api/despertar`) mientras su ventana aún se estaba creando.
   - `despertar()` lanzaba el asistente y, un instante después, `al_iniciar_gui()` veía `_dormido=False` y **lanzaba otro**.
   - Además, el voz parcial, la frase final y el atajo podían llamar a `despertar()` a la vez.
2. **En `vigilante.py`:**
   - Si el Jarvis dormido acababa de lanzarse y aún no respondía, el vigilante creía que no había ninguno y **lanzaba otro Jarvis**.
   - El mutex lo frenaba, pero ese segundo arranque llamaba a `/api/mostrar` y provocaba justo la carrera del punto 1.

### Arreglo
- **`interfaz.py`:** `_lanzar_asistente()` con cerrojo crea el asistente **una sola vez por proceso**, venga de donde venga, y `despertar()` ahora es atómico.
- **`vigilante.py`:**
  - `lanzar_jarvis` va con cerrojo (las peticiones se atienden de una en una);
  - si el dormido está arrancando, **espera a que responda y lo despierta**, en vez de lanzar otro.

### Comprobación automática: `pruebas/prueba_duplicados.py`
**Reproduce exactamente la situación del fallo:**
- un vigilante de prueba, con el mismo código y el micrófono sustituido por audio sintético, lanza su Jarvis dormido;
- **mientras arranca**, le llega «Jarvis, ¿qué hora es?» por voz y, a la vez, el atajo.

Después manda 19 órdenes más (9 por voz y 10 por el chat) y comprueba:
- un asistente, un hilo de escucha, un micrófono y un proceso;
- una ventana;
- 20 órdenes oídas, ejecutadas y contestadas una sola vez.

| | Código anterior | Código nuevo |
|---|---|---|
| Asistentes creados | **2** | 1 |
| Micrófono abierto | **2 veces** | 1 vez |
| Órdenes procesadas | 19 de 20 (**una perdida**) | 20 de 20 |
| Resultado | **8 fallos** | **12/12** (repetido al final de la noche: 12/12) |

---

## 2. La interfaz

### Qué se ve ahora
**Solo el orbe**, flotando sobre el escritorio:
- **La ventana:** transparente de verdad, con alfa por píxel (el resplandor se funde con lo que hay detrás). No tiene marco ni botón en la barra de tareas. Está encima de todo mientras se ve, en el centro de la pantalla donde tienes el ratón, y mide 480 px.
- **Ratón:**
  - los **clics fuera del círculo pasan a lo que hay detrás**;
  - arrastrar el orbe lo mueve;
  - clic: te escucha;
  - clic derecho: abre el panel.
- **`Esc` o el atajo:** lo ocultan con un desvanecido de 0,2 s.
- **Subtítulo opcional:** una línea fina y desvanecida con lo último dicho (`interfaz.subtitulos`).

### Panel aparte
Se abre con clic derecho o desde el menú del icono › *Ajustes, escenas y pantallas*. Es una ventana normal y sobria: fondo neutro, una sola tipografía del sistema, un acento y barra de título oscura. Tiene cuatro secciones:
- **Actividad:** conversación, acciones, sistema y una caja para escribir órdenes.
- **Escenas.**
- **Pantallas.**
- **Ajustes.**

### El orbe (`web/orbe.js`)
Three.js r170 local con shaders GLSL propios. Tres estilos, que se eligen en `interfaz.estilo_orbe`:
- **`nucleo` (elegido):**
  - esfera muy subdividida, deformada con ruido simplex de dominio deformado; **las normales se calculan en el shader**, así que no hay «cristales rotos»;
  - fresnel que pasa a blanco en el borde y cuerpo casi transparente;
  - **núcleo volumétrico por raymarching** (un plasma de filamentos con remolino), con un corazón de luz;
  - polvo de partículas en la GPU;
  - **onda circular que sigue 16 bandas del espectro** de tu voz o de la de Jarvis; el espectro se calcula en `voz.py`, calibrado con voz sintética.
- **`anillo`:** 14.000 partículas en anillo que se abre con la voz, alrededor de un núcleo.
- **`malla`:** esfera de meridianos y paralelos.

**Postproceso propio:**
- bloom en 5 niveles (bajar con 13 muestras, subir con filtro tienda);
- aberración cromática radial muy leve;
- curva tonal suave;
- **tramado** contra las bandas;
- velo azul noche muy suave detrás, para fondos claros.

**Estados:**

| Estado | Cómo se ve |
|---|---|
| Reposo | Respiración casi imperceptible: cambio medio entre fotogramas de 0,78 sobre 255 |
| Escuchando | Se contrae y sigue el micrófono |
| Pensando | Remolino interno y ruido más fino |
| Hablando | Amplitud y onda guiadas por la voz real |
| Error | Ámbar suave, sin parpadeos |
| Despertando | Aparición en 180 ms |

Las transiciones duran unos 0,35 s.

**Paleta:** cian eléctrico, blancos y azul noche. Nada de morados, glassmorphism ni Orbitron (he borrado las fuentes futuristas).

### Bucle de mejora: 10 iteraciones con capturas
Las hice con `pruebas/estudio_orbe.py` (el orbe solo, sobre fondos oscuro, claro y «escritorio») y con capturas de la ventana real.

| Iteración | Defecto que vi | Corrección |
|---|---|---|
| 1 | Orbe enorme y cortado, cuerpo de «bola de neón» opaca, núcleo como mancha blanca plana, aberración que teñía de rojo/verde las líneas finas, onda caótica y superficie nerviosa | Cámara más lejos, cuerpo casi transparente, filamentos en el núcleo, aberración ×0,25 solo en los bordes, onda más contenida |
| 2 | Relleno azul saturado, onda punteada (menos de 1 px) y **bajada de calidad falsa** (el límite de 60 fps en un monitor de 165 Hz se leía como «no llega») | Azul profundo más oscuro, onda más ancha, nuevo planificador de fotogramas y cálculo de fps contra el objetivo |
| 3 | **Bug real:** el remolino de «pensando» acumulaba torsión sin límite y a los pocos minutos la superficie salía rayada en espiral | Torsión acotada (oscila) |
| 4-6 | En fondo claro el orbe perdía contraste y el velo gris quedaba sucio | Velo de azul noche; anillo más tranquilo |
| 7 | Movimiento medido (cambio entre fotogramas): reposo 0,78, pensando 2,6 constante, hablando 3,8 con picos ×1,6 | Sin saltos; nada que corregir |
| 8 | Las dos ondas parecían un «alambre doble desalineado» | Una principal y otra muy tenue que gira al revés |
| 9 | Versión final de los 3 estilos × 6 estados × 3 fondos | Guardada en `capturas/estudio/` |
| 10 | Probé un brillo especular de vidrio: salía una nube blanca borrosa con aspecto de plástico | **Descartado y revertido** |

**Capturas:**
- `capturas/estudio/`: estilos y estados (`_hoja_xescritoriox.png` es la hoja resumen);
- `capturas/ventana_real/`: el orbe real transparente sobre el escritorio, en todos los estados, con subtítulo y una secuencia hablando;
- `capturas/panel/`: las 4 secciones del panel;
- `capturas/aviso_vigilante.png`: el aviso del vigilante rediseñado.

**Por qué elegí `nucleo`:**
- es el único con **profundidad real** (núcleo volumétrico dentro de un vidrio luminoso);
- los estados se distinguen sin texto;
- se lee bien sobre fondos oscuros y claros.

El `anillo` es elegante en reposo pero menos expresivo, y la `malla` recuerda a un globo terráqueo «tech». Los otros dos quedan como opción.

### Comprobaciones de la ventana real (`pruebas/prueba_orbe_ventana.py`): 13/13
- Aparece centrada en cada una de las 3 pantallas, según dónde esté el ratón.
- Sin botón en la barra de tareas y encima de todo.
- Clic fuera: atraviesa. Clic dentro: es para Jarvis.
- El clic derecho abre el panel, y cerrar el panel solo lo oculta.
- `Esc` la oculta en 0,2 s con desvanecido.
- Oculta, no dibuja.

Además lo probé a mano: **arrastrar** movió el orbe −150, +79 px (lo esperado) y el **clic** lo puso a escuchar en 0,1 s.

### Problemas que encontré por el camino
- **`transparent=True` de pywebview no sirve en Windows:** deja un fondo gris y enseña la ventana al cargar. Lo hice a mano: formulario negro, fondo de WebView2 transparente, marco de DWM extendido a toda la ventana y capas `WS_EX_LAYERED`.
- **Bug antiguo: «encima de todo» nunca funcionaba.** `SetWindowPos(hwnd, -1, …)` sin `argtypes` pasa el −1 como entero de 32 bits y no llega como `HWND_TOPMOST`. Estaba en 4 sitios, entre ellos el truco de `traer_al_frente`. Corregido con `c_void_p(-1)`.
- **El orbe tardaba 1,9 s en verse al despertar.** Lo medí por píxeles: three.js compilaba los shaders en el primer fotograma. Ahora se **precompilan nada más cargar la página**, aunque esté oculta: **35 ms**.
- **WebView2 servía `.js` antiguos de su caché.** Ahora `?v=<fecha>` y `no-cache`.

---

## 3. Herramientas nuevas (`pc.py` y `recordatorios.py`)

Todas tienen **camino rápido** (reglas, sin modelo, en milisegundos) y están registradas para el modelo **en categorías**, así que el prompt base sigue con 7 herramientas. Las frases de ejemplo están en el README, sección «Más cosas en tu PC».

| Área | Qué hay | Cómo pedirlo |
|---|---|---|
| Archivos | Buscar por nombre, tipo y fecha; abrir un resultado o su carpeta; descargas recientes; copiar; mover (**siempre pregunta**) | «busca el pdf de la factura», «busca las fotos de hoy», «abre el segundo», «abre la carpeta del primero», «¿qué he descargado hoy?», «copia el primero a documentos», «mueve el 2 a la carpeta proyectos» |
| Sistema | Discos, batería, qué consume más CPU o RAM, cerrar un proceso (**pregunta**; nunca toca procesos de Windows ni a Jarvis), volumen por app, micrófono, brillo por DDC/CI, plan de energía, bloquear | «¿cuánto espacio me queda?», «¿qué está consumiendo tanta CPU?», «mata el proceso de chrome», «baja el volumen de Spotify», «silencia el micro», «pon el brillo al 70», «activa el ahorro de energía», «bloquea el ordenador» |
| Apps | Apps abiertas con su pantalla; abrir cualquier app del menú Inicio (ya existía) | «¿qué apps tengo abiertas?» |
| Portapapeles | Resumir, traducir (deja la traducción copiada), guardar en el Inbox, dictar | «resume lo que he copiado», «traduce lo que he copiado al inglés», «guarda lo que he copiado en Obsidian», «dicta …» |
| Pantalla | Leer el texto de la ventana o de la pantalla con el **OCR que trae Windows** (local, sin instalar nada; la captura se borra); capturas; abrir la última | «lee la pantalla», «¿qué pone aquí?», «haz una captura», «abre la última captura» |
| Rutinas | **Recordatorios persistentes** y **rutinas programadas** que dispara el vigilante aunque Jarvis esté cerrado. En modo juego, el recordatorio llega como aviso de Windows y la rutina no interrumpe | «recuérdame mañana a las 10 llamar al médico», «cada día a las 9 lee mi agenda», «de lunes a viernes a las 7 y media dime el tiempo», «¿qué recordatorios tengo?» |
| Red | Conexión, IP local, Wi-Fi, latencia, velocidad aproximada (descarga 25 MB de Cloudflare), VPN ya configuradas | «¿tengo internet?», «¿cuál es mi IP?», «haz un test de velocidad», «conecta la VPN» |

**Límites que cumple:**
- confirmación en todo lo destructivo;
- sin administrador ni puertos abiertos (todo en 127.0.0.1);
- no lee contraseñas;
- todo queda en `datos/jarvis.log`, en las líneas `RÁPIDO`, `HERRAMIENTA`, `ARCHIVOS`, `PROCESOS`, `OCR`, `CONFIRMACIÓN` y `RECORDATORIO`.

### Pruebas
- **`pruebas/probar_intenciones.py`:** 105/105, que son 57 frases anteriores y 48 nuevas. Incluye frases que deben ir al modelo, como «busca un buen restaurante cerca» o «escribe un correo a mi jefe…».
- **`pruebas/prueba_pc.py`:** 32/32 de punta a punta, a través del Jarvis real por el chat:
  - buscar, abrir carpeta, copiar, y mover con «no» (no toca nada) y con «sí»;
  - disco, batería, procesos y apps;
  - silenciar y reactivar el micrófono, volumen de Discord, brillo al mismo valor y plan de energía;
  - cerrar un Bloc de notas que abrí yo (con confirmación) y negarse con explorer;
  - resumir y traducir con el modelo;
  - Inbox con la función sustituida, para no tocar tu vault;
  - OCR, captura, red, velocidad y VPN;
  - **un recordatorio y una rutina a +1 min que el vigilante disparó a su hora**.
- **Un bug grave encontrado por la prueba:** el COM del micrófono usaba `ctypes.cast`, que libera el objeto dos veces. Acababa en un cierre del proceso (0xC0000005); dentro de Jarvis habría pasado tras un «silencia el micro». Ahora se usa `QueryInterface`, y lo comprobé con 40 vueltas de silenciar, activar y cambiar volumen.

---

## 4. Mediciones antes / después

| Medida | Al empezar la noche | Ahora |
|---|---|---|
| Atajo → **orbe visible** (medido por píxeles), Jarvis dormido | La interfaz anterior no la medí por píxeles (el marco salía en 0,05 s y el contenido unos 0,4 s después). Con la interfaz nueva antes del arreglo: 1,9 s | **35 ms** de media (18-47) |
| Atajo → orbe visible, Jarvis despierto y oculto | — | **10 ms** de media |
| Orden simple con Jarvis abierto | 0,00-0,34 s | 0,00-0,07 s |
| Modelo en frío (primera respuesta) | 12,5 s | 12,5 s (sin cambios: es la carga en tu GPU) |
| Modelo en caliente | 0,4-1,6 s (peor 3,75) | 0,4-1,5 s (peor 3,7) |
| RAM del vigilante | 117 MB (80 privada) | 129 MB (94 privada) |
| RAM del Jarvis dormido (con Whisper) | 1.077 MB (662) | 1.123 MB (704) |
| RAM de Jarvis abierto | 1.209 MB (753) | 1.163 MB (716) |
| VRAM con todo cargado | 5,20 GB | 5,16 GB |
| GPU del orbe: reposo / hablando / oculto | 1,8 % / 3,9 % / ~0,3 % (orbe anterior) | **3,5 % / 6,9 % / 0 %** |
| fps del orbe: reposo / activo | 30 / sin límite (165 en tu monitor) | **30 / 60 exactos** |
| CPU del orbe (WebView2 + Python) | — | 1,8-2 % del equipo visible, 0,3 % oculto |

- **El orbe nuevo gasta el doble de GPU que el anterior**, porque tiene núcleo volumétrico y bloom. Aun así se queda por debajo del 7 % y oculto gasta 0.
- **La RAM del dormido sube unos 45 MB**, por los shaders precompilados y los búferes del postproceso.
- **El vigilante sube unos 12 MB.**

---

## 5. Verificación final (con el código definitivo)

| Prueba | Resultado |
|---|---|
| Duplicados (20 órdenes con el arranque delicado) | 12/12 |
| Ventana del orbe | 13/13 |
| Intenciones | 105/105 |
| Herramientas del PC | 32/32 |
| Escenas («vamos a jugar», «he terminado», modo juego por chat, guardar disposición) | 10/10 |
| Ventanas (mover y traer entre pantallas, mitades, escritorio) | **8/10** (ver abajo) |
| «¿Qué tengo hoy?» | Correcto («Tienes que repasar Mockito… lloverá») tras arreglar un eco (ver abajo) |
| «para» escrito | Para sin pasar por el modelo |
| Ctrl+Alt+J | Medido con el atajo real: 35 ms / 10 ms |
| Cierre por inactividad | Se cerró solo a los 5 min (02:24) y el vigilante creó un dormido nuevo |
| Modo juego | Activado por chat dentro de la prueba de escenas; la detección automática no la pude probar sin abrir un juego |

**Los 2 fallos de ventanas no son del código de esta noche:**
- Chrome estaba cerrado: lo cerraste antes de dormir.
- La prueba lo abrió en frío, Chrome **restauró tu sesión anterior** con otras pestañas, y:
  - la pestaña «clasificación» que buscaba ya no existe;
  - la ventana nueva de YouTube tardó más de lo que espera la prueba.
- La prueba cerró el Chrome que abrió.
- Quise repetir el caso de YouTube a mano, pero el sistema de permisos me bloqueó cerrar Chrome por la fuerza, así que lo dejé. **Queda sin confirmar: «abre YouTube en la pantalla 1» con Chrome cerrado.**

**Otro arreglo de la verificación:**
- **El fallo:** el modelo pequeño a veces empezaba la respuesta copiando el prefijo de fecha del mensaje («[miércoles 4…, 02:39] ¿Qué tengo hoy?…»).
- **El arreglo:** un filtro en `cerebro.py` retiene el principio de la respuesta mientras pueda ser ese eco y lo quita. No se dice ni queda en el historial.
- **Comprobación:** 3 respuestas seguidas sin eco.

---

## 6. Qué NO he probado de verdad
- **Hablándole con tu voz real y el micrófono:** de noche usé voz sintética inyectada. Tampoco he visto el orbe reaccionando a la voz real de Jarvis, porque estaba silenciada. El espectro se calibró con audio sintético, y en las capturas se usa una voz simulada del propio orbe.
- **Partes de herramientas sin ejecutar:**
  - «abre el archivo N»: abriría el programa del archivo;
  - dictar en una ventana;
  - bloquear el PC: habría cortado mis pruebas;
  - **cambiar** el brillo (lo fijé al mismo valor) o el plan de energía (solo consultado);
  - conectar una VPN: no tienes ninguna;
  - abrir la última captura.

  Las reglas que las entienden sí están probadas.
- **El Inbox real:** no he escrito en tu vault. Probé la función sustituida y la regla.
- **La detección automática del modo juego** con un juego real.
- **YouTube en la pantalla 1 con Chrome cerrado** (ver arriba).

## 7. Decisiones que tomé por mi cuenta
- **Lo que sale al arrancar:**
  - el subtítulo y el velo detrás del orbe, **activados por defecto** (se quitan en config.yaml);
  - tamaño de 480 px;
  - estilo `nucleo`.
- **Lo que he quitado:**
  - el **modo compacto** y «siempre encima» (con el orbe ya no tienen sentido), junto con sus claves de config.yaml. Habías puesto `modo: compacto` a la 01:14: queda sustituido por el orbe;
  - las fuentes Orbitron y Rajdhani.
- **Ni desvanecido de entrada en la ventana ni «no molestar»:**
  - el desvanecido de entrada no lo hace la ventana: si aparece con alfa 0, Chromium la da por tapada y tarda 1,7 s en pintar. Entra con la animación del propio orbe (180 ms). El de salida sí es de la ventana;
  - «modo no molestar» no está: Windows no tiene una API pública para eso y no quise tocar el registro sin documentar.
- **Cómo se hacen ahora algunas cosas:**
  - las confirmaciones salen en el subtítulo, con `Intro` / `Esc`, además de por voz;
  - el panel incluye una caja para escribir órdenes, porque ya no hay chat en la ventana principal;
  - los recordatorios los dispara el **vigilante**, para que funcionen con Jarvis cerrado. Uso un módulo ligero aparte (`recordatorios.py`) para no engordar el vigilante;
  - he rediseñado también el aviso «despertando» del vigilante (solo sale si no hay Jarvis precargado), para que no desentone.
- **Lo que no añadí:**
  - **grabación de pantalla**: necesitaría ffmpeg (no está) y era una dependencia nueva;
  - **«describe lo que hay en pantalla» con visión**: necesita descargar el modelo `qwen2.5vl:3b` (3,2 GB), y eso es instalar algo. A cambio está el OCR local de Windows.

## 8. Límites y cosas a tener en cuenta
- ⚠️ **Tu portapapeles:**
  - **qué pasó:** la primera ejecución de la prueba de herramientas se cortó (fue cuando encontré el bug del micro) antes de devolverte el portapapeles. **Lo que tuvieras copiado antes de las 02:13 se ha perdido**;
  - **por qué no se puede recuperar:** el historial del portapapeles de Windows está desactivado;
  - **lo que he cambiado:** la prueba ya restaura siempre lo que haya (`finally`).
- **El brillo** solo responde en las pantallas 1 y 2: la 3 no tiene DDC/CI, o lo tiene desactivado en su menú.
- **El modelo en frío sigue tardando unos 12 s** en la primera respuesta conversacional. Las órdenes del camino rápido no lo notan.
- **El orbe gasta algo más que el anterior:** 3,5 % de GPU en reposo y visible.
- **El OCR** lee bien texto normal; en la terminal, con fuentes pequeñas, comete erratas («Winc» por «Windows»).

## 9. Al terminar
- `voz.activada: true` y `vigilante.sonido_activacion: true` restaurados en `config.yaml`.
- Vigilante y Jarvis dormido en marcha con el código final, y comprobado que arranca bien.
- Tus ventanas, en su sitio. No queda ningún proceso de prueba abierto.
