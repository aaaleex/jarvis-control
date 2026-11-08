# Notas de la noche (4 de noviembre de 2026): para retomar si se corta

## Estado de partida (01:15)
- Copia completa: `C:\Users\alexa\jarvis_copias\noche-inicio-20261104-0115.zip` (3,2 GB, todo menos .venv).
- Config original: `C:\Users\alexa\jarvis_copias\config-antes-noche.yaml`. **Al acabar, restaurar `voz.activada: true` y `vigilante.sonido_activacion: true`** en el config.yaml actual. No copiar el viejo: el actual tiene las claves nuevas de la interfaz.
- Durante la noche la voz y los pitidos están en false.
- Copias por bloque (solo código): `jarvis_copias\noche-bloque1-…zip`, `noche-bloque2a-…zip`.
- Herramientas de la noche en el scratchpad de la sesión: `copia.py` (zip), `hoja.py` (hoja de contactos), `reiniciar_jarvis.ps1`.

## Bloque 1 · Duplicados: HECHO
- [x] Causa encontrada en tu log (01:09:21 y 01:09:22): dos «asistente creado» en el mismo proceso.
- [x] Arreglo en `interfaz.py` (`_lanzar_asistente` con cerrojo, `despertar` atómico) y en `vigilante.py` (cerrojo en `lanzar_jarvis` y espera al dormido que está arrancando).
- [x] `pruebas/prueba_duplicados.py`:
  - código viejo: 2 asistentes, micro abierto 2 veces, 1 orden perdida;
  - código nuevo: 12/12.

## Bloque 2 · Interfaz: EN CURSO
- [x] `orbe.js` nuevo (3 estilos, postproceso propio) y `estudio_orbe.py` para capturas. Iteraciones 1-6 hechas.
- [x] Ventana del orbe transparente (DWM), sin barra de tareas, clics que atraviesan, desvanecidos y centrada en la pantalla del ratón.
- [x] Panel aparte (`panel.html/css/js`): clic derecho o menú de la bandeja.
- [x] Bug encontrado: `SetWindowPos(hwnd, -1)` sin argtypes no ponía «encima de todo» (ni en `ventanas.traer_al_frente`). Corregido con `c_void_p(-1)`.
- [x] `pruebas/prueba_orbe_ventana.py`: 13/13.
- [x] 9 iteraciones de pulido (iteraciones 7-8 dedicadas a movimiento y ondas). Capturas en `capturas/estudio` y `capturas/panel`.
- [x] Medido en la ventana real con `pruebas/medir_orbe.ps1`:

  | Estado | fps | GPU |
  |---|---|---|
  | Reposo | 30 | 3,5 % |
  | Hablando o pensando | 60 | 6,9 % |
  | Oculto | sin dibujar | 0 % |

## Bloque 3 · Herramientas: HECHO
- [x] `pc.py` (archivos, sistema, apps, portapapeles, OCR, capturas, recordatorios, programadas, red) y `recordatorios.py` (ligero, para el vigilante).
- [x] Camino rápido en `intenciones.py` (`_orden_pc`): 105/105 en `probar_intenciones.py`.
- [x] Categorías en `cerebro.py`: el prompt base sigue con 7 herramientas.
- [x] El vigilante dispara recordatorios y rutinas (`_revisar_recordatorios`) y Jarvis tiene `/api/aviso`.
- [x] `pruebas/prueba_pc.py`: 32/32 de punta a punta.
- [x] Bug arreglado: `ctypes.cast` en el COM del micro (doble Release que acababa cerrando el proceso). Ahora `QueryInterface`.
- [!] La primera ejecución de `prueba_pc` se cortó antes de restaurar el portapapeles: lo que tenías copiado se perdió (el historial de Windows está desactivado). La prueba ya restaura siempre (`finally`).

## Verificación final: HECHA (02:56)
- Pruebas:

  | Prueba | Resultado |
  |---|---|
  | Duplicados | 12/12 |
  | Orbe | 13/13 |
  | Intenciones | 105/105 |
  | PC | 32/32 |
  | Escenas | 10/10 |
  | Ventanas | 8/10 (Chrome cerrado y pestañas cambiadas; ver informe) |

- Comprobado también: «qué tengo hoy» (con el arreglo del eco), «para», inactividad (02:54:52) y Ctrl+Alt+J (35 ms).
- README actualizado e INFORME_NOCHE.md escrito.
- `voz.activada` y `vigilante.sonido_activacion` vuelven a estar en true. Vigilante y dormido arrancados con el código final.
- 0 errores de JavaScript esta noche. No queda ningún proceso de prueba.
- Copia final: `jarvis_copias\noche-final-….zip`.
