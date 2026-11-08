"""
Comprueba qué entiende el camino rápido SIN ejecutar nada:
    .venv\\Scripts\\python.exe pruebas\\probar_intenciones.py
Cada línea: frase -> intención (o «-> modelo» si se la deja al modelo). Al final, fallos respecto a lo esperado.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import escenas  # noqa: E402
import intenciones  # noqa: E402

escenas.crear_ejemplos()

# (frase, acción esperada o None si debe ir al modelo, argumentos que deben aparecer)
CASOS = [
    ("Abre YouTube", "abrir", {"tipo": "web"}),
    ("abre youtube en la pantalla de la izquierda", "abrir", {"pantalla": "izquierda"}),
    ("Ponme Spotify en la tercera", "abrir", {"valor": "spotify", "pantalla": "tercera"}),
    ("abre discord en la pantalla 2 maximizado", "abrir", {"pantalla": "2", "modo": "maximizar"}),
    ("Abre VS Code en la mitad izquierda de la principal", "abrir", {"pantalla": "principal", "modo": "mitad_izquierda"}),
    ("abre el navegador", "abrir", {}),
    ("Enséñame Discord", "traer", {"nombre": "discord"}),
    ("pon Spotify delante", "traer", {"nombre": "spotify"}),
    ("Muéstrame Spotify en la pantalla 2", "traer", {"pantalla": "2"}),
    ("trae chrome a la pantalla principal", "traer", {"pantalla": "principal"}),
    ("Pasa Discord a la pantalla 3", "ventana_mover", {"pantalla": "3"}),
    ("mueve spotify a la otra pantalla", "ventana_mover", {"pantalla": "otra"}),
    ("pon chrome en la mitad derecha", "abrir", {"modo": "mitad_derecha"}),
    ("minimiza Discord", "ventana_minimizar", {}),
    ("maximiza spotify", "ventana_maximizar", {}),
    ("cierra el bloc de notas", "ventana_cerrar", {}),
    ("Muéstrame el escritorio", "escritorio", {}),
    ("enséñame la pestaña de la clasificación", "pestana", {}),
    ("¿Qué hora es?", "hora", {}),
    ("Jarvis, ¿qué día es hoy?", "fecha", {}),
    ("¿Qué tiempo hace?", "clima", {"cuando": "hoy"}),
    ("qué tiempo va a hacer mañana", "clima", {"cuando": "manana"}),
    ("Sube el volumen", "volumen", {"accion": "subir"}),
    ("baja el volumen un poco", "volumen", {"accion": "bajar"}),
    ("pon el volumen al 30", "volumen", {"accion": "fijar", "cantidad": 30}),
    ("volumen al cincuenta por ciento", "volumen", {"accion": "fijar", "cantidad": 50}),
    ("silencia el pc", "volumen", {"accion": "silenciar"}),
    ("pausa la música", "musica", {"accion": "play_pausa"}),
    ("siguiente canción", "musica", {"accion": "siguiente"}),
    ("pon la anterior", "musica", {"accion": "anterior"}),
    ("Pon un temporizador de 5 minutos", "temporizador", {"minutos": 5}),
    ("temporizador de media hora para la pasta", "temporizador", {"minutos": 30, "etiqueta": "pasta"}),
    ("avísame en diez minutos", "temporizador", {"minutos": 10}),
    ("pon una alarma a las siete y media", "alarma", {"hora": "07:30"}),
    ("despiértame a las 8 menos cuarto", "alarma", {"hora": "07:45"}),
    ("alarma a las 6 de la tarde", "alarma", {"hora": "18:00"}),
    ("cancela los temporizadores", "cancelar_temporizadores", {}),
    ("Apunta en mi inbox comprar leche", "inbox", {"texto": "comprar leche"}),
    ("anota que mañana llamo a Marta", "inbox", {"texto": "mañana llamo a Marta"}),
    ("busca recetas de pasta en YouTube", "youtube", {"consulta": "recetas de pasta"}),
    ("Vamos a jugar", "escena", {"clave": "vamos_a_jugar"}),
    ("modo estudio", "escena", {"clave": "modo_estudio"}),
    ("he terminado", "escena", {"clave": "he_terminado"}),
    ("guarda esta disposición como trabajo", "guardar_escena", {"nombre": "trabajo"}),
    ("activa el modo juego", "modo_juego", {"activar": True}),
    ("abre Spotify y sube el volumen", "abrir+volumen", {}),
    ("abre spotify y discord", "abrir+abrir", {}),
    # --- Bloque 3: PC ---
    ("busca el pdf de la factura", "buscar_archivos", {"tipo": "pdf", "texto": "factura"}),
    ("busca las fotos de hoy", "buscar_archivos", {"tipo": "imagen", "dias": 1}),
    ("encuentra los archivos que se llaman informe en descargas", "buscar_archivos", {"texto": "informe", "carpeta": "descargas"}),
    ("busca los vídeos de esta semana", "buscar_archivos", {"tipo": "video", "dias": 7}),
    ("¿qué he descargado hoy?", "descargas_recientes", {}),
    ("abre la carpeta de descargas", "abrir_carpeta", {"cual": "descargas"}),
    ("abre el segundo", "abrir_archivo", {"cual": "segundo"}),
    ("abre la carpeta del primero", "abrir_carpeta", {"cual": "primero"}),
    ("copia el primero a documentos", "copiar_archivo", {"cual": "primero", "destino": "documentos"}),
    ("mueve el 2 a la carpeta de escritorio", "mover_archivo", {"cual": "2"}),
    ("¿cuánto espacio me queda en el disco?", "discos", {}),
    ("¿cuánta batería me queda?", "bateria", {}),
    ("¿qué programa está consumiendo más memoria?", "procesos", {"por": "ram"}),
    ("qué está consumiendo tanta cpu", "procesos", {"por": "cpu"}),
    ("mata el proceso de notepad", "cerrar_proceso", {"nombre": "notepad"}),
    ("cierra a la fuerza chrome", "cerrar_proceso", {"nombre": "chrome"}),
    ("silencia el micro", "microfono", {"accion": "silenciar"}),
    ("activa el micrófono", "microfono", {"accion": "activar"}),
    ("baja el volumen de Spotify", "volumen_app", {"app": "spotify", "accion": "bajar"}),
    ("pon el volumen de discord al 30", "volumen_app", {"app": "discord", "accion": "fijar", "cantidad": 30}),
    ("silencia discord", "volumen_app", {"accion": "silenciar"}),
    ("baja el brillo un poco", "brillo", {"accion": "bajar"}),
    ("pon el brillo al 70", "brillo", {"accion": "fijar", "cantidad": 70}),
    ("activa el ahorro de energía", "plan_energia", {"plan": "ahorro"}),
    ("bloquea el ordenador", "bloquear", {}),
    ("¿qué apps tengo abiertas?", "apps_abiertas", {}),
    ("resume lo que he copiado", "resumir_portapapeles", {}),
    ("traduce lo que he copiado al inglés", "traducir_portapapeles", {"idioma": "ingles"}),
    ("guarda lo que he copiado en Obsidian", "portapapeles_a_obsidian", {}),
    ("dicta hola qué tal", "escribir_texto", {"texto": "hola qué tal"}),
    ("lee la pantalla", "leer_texto_pantalla", {"zona": "pantalla"}),
    ("¿qué pone aquí?", "leer_texto_pantalla", {"zona": "ventana"}),
    ("abre la última captura", "abrir_ultima_captura", {}),
    ("recuérdame mañana a las 10 llamar al médico", "recordatorio", {"texto": "llamar al médico", "cuando": "manana a las 10"}),
    ("recuérdame el viernes a las nueve y media que tengo dentista", "recordatorio", {"texto": "tengo dentista"}),
    ("recuérdame comprar pan mañana", "recordatorio", {"texto": "comprar pan"}),
    ("¿qué recordatorios tengo?", "listar_recordatorios", {}),
    ("cada día a las 9 lee mi agenda", "programar_rutina", {"hora": "09:00", "orden": "lee mi agenda"}),
    ("de lunes a viernes a las siete y media dime el tiempo", "programar_rutina", {"hora": "07:30", "orden": "dime el tiempo"}),
    ("todos los lunes a las 8 dime qué tengo", "programar_rutina", {"hora": "08:00"}),
    ("¿qué rutinas programadas tengo?", "listar_rutinas_programadas", {}),
    ("¿tengo internet?", "estado_red", {}),
    ("¿cuál es mi IP?", "estado_red", {}),
    ("haz un test de velocidad", "velocidad_internet", {}),
    ("conecta la vpn", "vpn", {"accion": "conectar"}),
    ("recuérdame en 5 minutos sacar la ropa", "temporizador", {"minutos": 5, "etiqueta": "sacar la ropa"}),
    # Lo que NO debe coger el camino rápido (va al modelo)
    ("¿Qué tengo hoy?", None, {}),
    ("busca un buen restaurante cerca", None, {}),
    ("escribe un correo a mi jefe diciendo que llego tarde", None, {}),
    ("cuéntame un chiste", None, {}),
    ("pon música relajante", None, {}),
    ("abre el archivo de apuntes", None, {}),
    ("apunta en la nota diaria que he ido al gimnasio", None, {}),
    ("busca información sobre la segunda guerra mundial", None, {}),
    ("qué es mejor, Spotify o YouTube Music", None, {}),
    ("abre fortnite", None, {}),
    ("pon un temporizador", None, {}),
    ("cierra todo", None, {}),
]

fallos = 0
t0 = time.time()
for frase, esperada, args in CASOS:
    r = intenciones.entender(frase)
    obtenida = "+".join(i.accion for i in r) if r else None
    ok = obtenida == esperada
    if ok and r and len(r) == 1:
        for k, v in args.items():
            if r[0].argumentos.get(k) != v:
                ok = False
    fallos += not ok
    print(f"{'OK ' if ok else 'MAL'} {frase!r:58} -> {r if r else 'modelo'}")
print(f"\n{len(CASOS) - fallos}/{len(CASOS)} correctas · {(time.time() - t0) * 1000 / len(CASOS):.1f} ms por frase de media")

