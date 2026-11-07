# Jarvis · mando móvil

App web (PWA) para hablar con Jarvis y controlar el PC desde el móvil: un orbe que se toca para hablar, un panel de control y una terminal. Sin servidor funciona en modo demo (datos simulados).

```
móvil (app) ──https · Tailscale──▶ servidor (server/, en el PC de Jarvis) ──▶ Ollama / tu Jarvis / comandos del sistema
```

## Qué hay en el repo
- `index.html`, `styles.css`, `app.js`, `sw.js`, `manifest.webmanifest`, `icon.svg` · la app. `app.js` lleva arriba el contrato con el servidor.
- `server/` · servidor Node sin dependencias que corre en el PC. Instalación paso a paso en [`server/README.md`](server/README.md).

## Dos formas de usarla
1. **Servida por el propio servidor** (la más simple): abres el link de Tailscale del PC y la app detecta el servidor sola.
2. **Alojada en Vercel** (u otro sitio): en `server/.env` pon `ALLOWED_ORIGIN=https://tu-app.vercel.app`. Luego, en la app: Ajustes > desactivar "Modo demo" > pegar la dirección del servidor (`https://…ts.net`) y el token. El móvil necesita Tailscale encendido.

## Probar solo la interfaz
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
