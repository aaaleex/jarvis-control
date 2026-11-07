# Jarvis · servidor

Un servidor pequeño (Node, sin dependencias) que corre en el PC de Jarvis. Protege todo con un token, ejecuta las órdenes en el PC y, si quieres, también sirve la app del móvil (los archivos de la carpeta de arriba).

## 1. Requisitos
- Node 18.15 o superior (`node -v`). Si no lo tienes: https://nodejs.org
- Ollama con el modelo (`ollama pull gemma3:4b`) si quieres el cerebro por defecto.
  Si ya tienes tu propio Jarvis con una URL, mira el paso 5.

## 2. Primer arranque
Desde esta carpeta (`server/`):
1. Crea la configuración:
   - Linux/Mac: `cp .env.example .env`
   - Windows (PowerShell): `copy .env.example .env`
2. Genera un token: `node server.js --gen-token` y pégalo en `JARVIS_TOKEN=` del `.env`.
3. Arranca: `node server.js` → debe decir "Jarvis escuchando en http://127.0.0.1:3000".
4. En ese mismo PC abre http://127.0.0.1:3000 : la app detecta el servidor y te pide el token.

## 3. Usarlo desde el móvil (Tailscale)
Tailscale crea una red privada entre tus dispositivos: solo tú entras, sin abrir puertos del router.
1. Instala Tailscale en el PC y en el móvil (https://tailscale.com/download), con la MISMA cuenta.
2. En el panel de Tailscale (login.tailscale.com > DNS) activa **HTTPS Certificates**.
3. En el PC: `tailscale serve --bg 3000` → te da una dirección tipo `https://nombre-pc.tu-red.ts.net`.
4. Ábrela en el móvil, pega el token en Ajustes y guarda.
5. Instálala como app: menú del navegador > "Añadir a pantalla de inicio". (Hace falta https para instalarla y para el micrófono.)

### Si la app está alojada en Vercel
En el `.env` pon `ALLOWED_ORIGIN=https://tu-app.vercel.app` (dirección exacta, sin barra final; varias separadas por comas) y reinicia el servidor. En la app de Vercel: Ajustes > desactivar "Modo demo" > en "Dirección del servidor" la `https://…ts.net` y el token. El móvil debe tener Tailscale encendido. Usa el dominio de producción de Vercel: cada vista previa tiene una dirección distinta y habría que añadirla también.

## 4. Que arranque solo con el PC
**Linux (systemd)**: crea `/etc/systemd/system/jarvis.service`

    [Unit]
    Description=Jarvis server
    After=network.target

    [Service]
    WorkingDirectory=/RUTA/A/jarvis-control/server
    ExecStart=/usr/bin/node server.js
    Restart=always
    User=TU_USUARIO

    [Install]
    WantedBy=multi-user.target

y luego `sudo systemctl enable --now jarvis`. (Comprueba la ruta de node con `which node`.)

**Windows**: Programador de tareas > Crear tarea > desencadenador "Al iniciar sesión" > acción "Iniciar programa": `node` con argumentos `server.js` y "Iniciar en" la carpeta `server`.

## 5. Personalizarlo
- **Tu propio Jarvis** (lo normal si ya lo usas por voz en el PC): en `.env` pon `JARVIS_CHAT_URL=http://127.0.0.1:PUERTO/ruta`. El servidor le envía `POST {"text": "..."}` y espera `{"reply": "..."}`. Todo lo que dices desde el móvil llega a ese Jarvis, igual que si se lo dijeras en voz alta; solo apagar, reiniciar y suspender se interceptan para pedirte confirmación en el móvil. Con `LOCAL_INTENTS=1` también se usan las escenas y apps de `actions.json`. Si quieres que muestre lo que ha ejecutado, puede devolver también `"actions": [{"label": "Abrir Spotify", "detail": "Pantalla 3", "status": "ok"}]`.
- **Apps, escenas y acciones**: copia `actions.example.json` como `actions.json` y edítalo. Solo se abren las apps que definas ahí. Reinicia el servidor tras cambiarlo.
- **Terminal del móvil**: ejecuta comandos reales en el PC. Viene apagada; actívala con `ALLOW_EXEC=1` solo si te hace falta.
- **Pantallas concretas** (Discord en la segunda pantalla): el servidor lanza las apps, pero colocar ventanas en un monitor concreto necesita una herramienta extra según tu sistema. Está pendiente.

## 6. Seguridad (esto controla tu PC)
- Deja `HOST=127.0.0.1` y usa `tailscale serve`: así el servidor no es visible en tu red local.
- El token es la llave. No lo compartas ni lo subas al repositorio (`.env` está en `.gitignore`).
- Apagar, reiniciar y suspender siempre piden confirmación en el móvil, también por voz.
- 8 intentos fallidos bloquean la IP un minuto. Todo lo que se ejecuta queda en `audit.log`.
- El servidor solo sirve una lista cerrada de archivos de la app, nunca el resto de carpetas.
- Si el token se filtra: genera otro, cámbialo en `.env`, reinicia el servidor y ponlo de nuevo en el móvil.

## 7. Problemas típicos
- "No puedo conectar con Ollama": arranca Ollama (`ollama serve`) o revisa `OLLAMA_URL` y `OLLAMA_MODEL`.
- "Token incorrecto": el del móvil no coincide con el del `.env` (cuidado con espacios al pegar).
- Error de red desde Vercel: revisa que `ALLOWED_ORIGIN` sea exactamente la dirección de la app y que el móvil tenga Tailscale encendido.
- La temperatura sale "–": en Windows no hay forma fiable sin programas extra; en Linux se lee sola.
- El micrófono no funciona: hace falta https y permiso del navegador. Si falla, el orbe abre la caja de texto.

## v2: personalizar el PC desde el móvil

Las escenas, los sitios y los ajustes se editan desde la app y se guardan en `server/data/config.json`
(no se sube a git). Nuevos endpoints, todos con el mismo token:

| Endpoint | Qué hace |
|---|---|
| `GET/PUT /api/config` | Escenas, sitios, apps fijadas y ajustes (se valida todo antes de guardar) |
| `GET /api/apps` | Apps instaladas (Windows: Get-StartApps · Linux: .desktop · macOS: /Applications) |
| `POST /api/open` | `{url}` abre una web (solo http/https) o `{app}` abre una app por su id |
| `GET/POST /api/volume` | Leer o poner volumen, subir/bajar, silenciar |
| `POST /api/media` | Reproducir/pausar, siguiente, anterior, parar |
| `GET/POST /api/clipboard` | Leer o escribir el portapapeles del PC |
| `GET /api/screenshot` | Captura de pantalla (PNG) |
| `GET /api/processes` · `POST /api/kill` | Procesos principales; cerrar uno exige `ALLOW_EXEC=1` |

Seguridad: el móvil nunca manda comandos sueltos, solo ids y valores. Los pasos de tipo «comando propio»
y cerrar procesos solo funcionan con `ALLOW_EXEC=1`. Apagar, reiniciar y suspender siguen pidiendo confirmación.
Para probar sin tocar nada: `JARVIS_DRY_RUN=1 node server.js`.

Notas: el volumen en Windows se ajusta con las teclas multimedia (no se puede leer el valor actual);
los controles multimedia en Linux necesitan `playerctl`; las capturas en Linux necesitan `grim`, `scrot` o `gnome-screenshot`
y una sesión de escritorio activa (si el servidor corre como servicio sin pantalla, no funcionarán).
