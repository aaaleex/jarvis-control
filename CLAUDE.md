# jarvis-control

Jarvis es un asistente personal que vive en un PC con Windows. Este repo tiene las dos partes y lo que las une:

```
app/        PWA del móvil (HTML/CSS/JS sin framework). Desplegada en Vercel con Root Directory = app
pc/         Jarvis del ordenador (Python 3.12): voz, orbe 3D, camino rápido, herramientas del PC
            + puente_supabase.py, que recoge las órdenes del móvil
supabase/   migraciones SQL (tabla comandos, RLS, Realtime)
server/     servidor Node opcional (panel del PC por Tailscale)
API.md      contrato exacto de los mensajes app <-> PC
```

## Cómo se conectan

El móvil inserta una fila `pendiente` en `comandos` (Supabase). El puente del PC la recibe por Realtime, se la pasa a
Jarvis por `POST 127.0.0.1:8765/api/movil` (la misma función que la voz) y guarda `hecho`/`error` con la respuesta,
que la app ve en directo. Todo el detalle en [API.md](API.md).

## Arrancar cada parte

### PC (Windows)
- Primera vez: `pc\instalar.bat` (Jarvis, crea `.venv`) y `pc\instalar_puente.bat` (puente, crea `.venv-puente` y
  el acceso de Inicio). Copia `pc\config.example.yaml` como `pc\config.yaml` y `pc\.env.example` como `pc\.env`.
- Arrancar: `pc\start.bat` (vigilante + puente). Con Windows arrancan solos por dos accesos en la carpeta Inicio:
  `Jarvis.lnk` (vigilante) y `Jarvis puente Supabase.lnk`.
- El vigilante (`vigilante.py`) es ligero: icono de bandeja, «Jarvis» por voz, Ctrl+Alt+J, modo juego. Mantiene un
  `jarvis.py --dormido` (FastAPI + ventana del orbe en `127.0.0.1:8765`) que carga los modelos al despertar.
- Registros: `pc\datos\jarvis.log` y `pc\datos\puente.log`.
- Pruebas: `pc\.venv\Scripts\python pc\pruebas\probar_intenciones.py` (sin efectos) y el resto de `pc\pruebas`.

### App
- Local: `cd app && node build.js` (con `SUPABASE_URL` y `SUPABASE_ANON_KEY` en el entorno) y sirve la carpeta
  (`python -m http.server 8080`). Sin `config.js` funciona en modo demo / servidor.
- Vercel: Root Directory `app`, variables `SUPABASE_URL` y `SUPABASE_ANON_KEY` (la **pública**). `vercel.json`
  ejecuta `node build.js`, que genera `config.js` y falla si le pasas la clave secreta.

### Supabase
- Proyecto `jarvis-control` (eu-west-3). Migraciones en `supabase/migrations/` (aplicar en orden).
- Auth: email y contraseña, un solo usuario, registro público desactivado.

## Reglas
- Secretos solo en `pc/.env` y `server/.env` (ignorados). La service role **nunca** en `app/`. El repo es público.
- No se suben: `.venv*`, `pc/modelos`, `pc/datos`, `pc/capturas`, `pc/config.yaml`, `app/config.js`.
- El puente va en su propio entorno: `supabase`/`realtime` traen `websockets` 15 y Jarvis usa 17 (uvicorn).
- No cambiar la activación por voz, el micrófono ni el arranque de Jarvis sin preguntar.
- Código y comentarios en español, sin abstracciones innecesarias.
