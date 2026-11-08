# API · mensajes entre la app del móvil y el Jarvis del PC

La app y el PC no hablan directamente: se dejan mensajes en la tabla **`public.comandos`** de Supabase
(proyecto `jarvis-control`, `https://zwqpafskvzjytuujltlg.supabase.co`). Migración: `supabase/migrations/20261108000000_comandos.sql`.

```
móvil (app/nube.js) ──INSERT pendiente──▶ Supabase ──Realtime INSERT──▶ PC (pc/puente_supabase.py)
        ▲                                                                    │ POST 127.0.0.1:8765/api/movil
        └──────────Realtime UPDATE (estado, respuesta)◀──PATCH──────────────┘ (Jarvis: misma lógica que la voz)
```

## Tabla `comandos`

| Columna      | Tipo        | Quién la escribe | Qué es |
|--------------|-------------|------------------|--------|
| `id`         | uuid        | Supabase         | `gen_random_uuid()` |
| `user_id`    | uuid        | Supabase         | `auth.uid()` del que inserta (FK a `auth.users`) |
| `texto`      | text        | app              | La orden tal cual, 1-2000 caracteres: «abre Spotify», «pon la escena gaming», «sí» |
| `estado`     | text        | app → PC         | `pendiente` → `ejecutando` → `hecho` \| `error` \| `confirmar` |
| `respuesta`  | text        | PC               | Lo que contesta Jarvis. En `confirmar`, la pregunta |
| `acciones`   | jsonb       | PC               | `[{"label": "Abrir aplicacion", "detail": "Abriendo Spotify.", "status": "ok" \| "error"}]` |
| `created_at` | timestamptz | Supabase         | Hora de la orden |
| `updated_at` | timestamptz | trigger          | Último cambio |

## Estados

| Estado       | Lo pone | Significa |
|--------------|---------|-----------|
| `pendiente`  | app (INSERT) | Orden nueva. Es el único estado con el que la app puede insertar (RLS) |
| `ejecutando` | PC | El PC la ha cogido (PATCH condicionado a `estado=pendiente`: nunca se ejecuta dos veces) |
| `hecho`      | PC | Terminada. `respuesta` y `acciones` rellenas |
| `error`      | PC | No se pudo: Jarvis cerrado (modo juego), fallo interno, o **caducada** (llegó con el PC apagado hace más de 1 h) |
| `confirmar`  | PC | Jarvis pregunta «¿seguro?» (`respuesta` = pregunta). La app inserta otra orden `«sí»` o `«no»`; el PC guarda el resultado en **la fila original** (pasa a `hecho`) y marca la del «sí» como `hecho` («Respuesta enviada a Jarvis.»). Si no llega respuesta en 35 s, la original pasa a `error` |

## Permisos (RLS)

| Quién | SELECT | INSERT | UPDATE / DELETE |
|-------|--------|--------|-----------------|
| Sin sesión (`anon`) | ✗ (401) | ✗ (401) | ✗ |
| Con sesión (`authenticated`) | solo sus filas | solo con `user_id = auth.uid()`, `estado = 'pendiente'`, sin `respuesta` ni `acciones` | ✗ |
| PC (`service_role`, solo en `pc/.env`) | todo | todo | todo (se salta RLS) |

El PC además ignora cualquier fila cuyo `user_id` no sea `ALLOWED_USER_ID`.

## Realtime

- La tabla está en la publicación `supabase_realtime`.
- App: canal `mis-comandos`, `postgres_changes` `*` con filtro `user_id=eq.<mi id>` (y RLS: solo recibe las suyas).
  Además consulta la fila cada 3 s mientras espera, por si se corta Realtime.
- PC: canal `comandos-pc`, `postgres_changes` `INSERT` con filtro `user_id=eq.<ALLOWED_USER_ID>`.
  Además cada 30 s (y al arrancar) lee las `pendiente` de la tabla y caduca las de más de 1 h.

## Ejemplo

```jsonc
// 1. app inserta
{"texto": "abre Spotify"}
// 2. Realtime -> PC; el PC hace PATCH
{"estado": "ejecutando"}
// 3. PC termina
{"estado": "hecho", "respuesta": "Abriendo Spotify.",
 "acciones": [{"label": "Abrir aplicacion", "detail": "Abriendo Spotify.", "status": "ok"}]}
```

## Dentro del PC: `POST http://127.0.0.1:8765/api/movil`

Solo escucha en `127.0.0.1` (sin token: no se expone a la red).

```jsonc
// petición
{"text": "abre Spotify"}
// respuesta
{"reply": "Abriendo Spotify.", "actions": [...], "confirmar": false}
```
Pasa el texto a `Asistente.procesar(texto, origen="movil")`, lo mismo que una orden por voz (camino rápido de
`intenciones.py`, escenas, apps en pantallas, y si no, el modelo con herramientas). Si Jarvis está dormido, despierta
sin mostrar el orbe. `«para»` / `«calla»` paran lo que esté haciendo. Si pide confirmación, `confirmar: true` y la
siguiente petición se toma como la respuesta (sí/no).

## El otro camino (opcional): servidor por Tailscale

`server/` (Node) sigue existiendo para el panel del PC de la app (volumen, ver la pantalla, procesos, portapapeles,
escenas editables). Contrato en la cabecera de `app/app.js` y `app/pc.js`; instalación en `server/README.md`.
Con sesión de Supabase, el **chat del orbe siempre va por Supabase**; el panel usa el servidor si en Ajustes hay
dirección y token y el modo demo está apagado.
