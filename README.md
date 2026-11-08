# Jarvis · mando móvil

App web (PWA) para hablar con Jarvis y controlar el PC desde el móvil, y el propio Jarvis del PC, en un solo repo.

```
móvil (app/) ──Supabase (tabla comandos + Realtime)──▶ PC (pc/puente_supabase.py) ──▶ Jarvis (misma lógica que la voz)
móvil (app/) ──https · Tailscale (opcional)──────────▶ server/ (panel del PC: volumen, pantalla, procesos…)
```

## Qué hay en el repo
- `app/` · la PWA (en Vercel: **Root Directory = `app`**). Login y órdenes por Supabase en `app/nube.js`.
- `pc/` · el Jarvis de Windows y el puente con Supabase. Arranque: `pc\start.bat`.
- `supabase/migrations/` · la tabla `comandos` con RLS y Realtime.
- `server/` · servidor Node opcional para el panel del PC por Tailscale ([`server/README.md`](server/README.md)).
- [`CLAUDE.md`](CLAUDE.md) (arquitectura y cómo arrancar cada parte) y [`API.md`](API.md) (formato de los mensajes).

## Por Supabase (lo principal)
En la app: inicia sesión con tu correo y contraseña. Lo que digas o escribas va a la tabla `comandos`, tu PC lo
ejecuta y la respuesta aparece en directo. Funciona sin Tailscale y aunque el PC esté apagado un rato
(las órdenes esperan hasta 1 hora).

## Servidor por Tailscale (opcional)
1. **Servida por el propio servidor** (la más simple): abres el link de Tailscale del PC y la app detecta el servidor sola.
2. **Alojada en Vercel** (u otro sitio): en `server/.env` pon `ALLOWED_ORIGIN=https://tu-app.vercel.app`. Luego, en la app: Ajustes > desactivar "Modo demo" > pegar la dirección del servidor (`https://…ts.net`) y el token. El móvil necesita Tailscale encendido.

## Probar solo la interfaz
    cd app
    python -m http.server 8080
y abre http://localhost:8080 (modo demo).

## Seguridad
Esto controla un PC. El token vive solo en `server/.env` (ignorado por git) y en tu móvil. No lo subas ni lo pegues en chats. Más detalles en `server/README.md`.

## Novedades de la v2

- **Escenas editables** desde el móvil: pasos de abrir webs/apps, volumen, silencio, multimedia y esperas (pestaña Control).
- **Accesos**: tus webs favoritas y las apps del PC, a un toque; barra para abrir cualquier dirección en el PC.
- **PC**: volumen, multimedia, ver la pantalla, portapapeles compartido y procesos.
- **Personalización**: color de acento, estilo del orbe (plasma, anillos, cristal), velocidad e idioma de la voz y vibración.
- Todo funciona también en modo demo (se guarda solo en el móvil). Detalles del servidor en `server/README.md`.
