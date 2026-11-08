@echo off
REM ============================================================
REM  Instalación de JARVIS: entorno virtual + librerías + modelos
REM  Solo hace falta ejecutarlo una vez (o si algo se rompe).
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  === Instalando J.A.R.V.I.S. ===
echo.

where py >nul 2>nul || (echo  [!] No encuentro Python. Instala Python 3.12 desde https://www.python.org & pause & exit /b 1)
py -3.12 --version >nul 2>nul || (echo  [!] Necesito Python 3.12. Descargalo de https://www.python.org/downloads/release/python-31210/ & pause & exit /b 1)

if not exist ".venv" (
    echo  [1/3] Creando entorno virtual con Python 3.12...
    py -3.12 -m venv .venv || (echo  [!] No pude crear el entorno virtual & pause & exit /b 1)
)

echo  [2/3] Instalando librerias (puede tardar varios minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo  [!] Fallo instalando librerias & pause & exit /b 1)

if not exist "modelos\vosk\vosk-model-small-es-0.42" (
    echo  Descargando el detector de la palabra «Jarvis» ^(Vosk, 40 MB^)...
    powershell -NoProfile -Command "New-Item -ItemType Directory -Force modelos\vosk | Out-Null; Invoke-WebRequest https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip -OutFile modelos\vosk\es.zip; Expand-Archive modelos\vosk\es.zip -DestinationPath modelos\vosk -Force; Remove-Item modelos\vosk\es.zip"
)

echo  [3/3] Descargando modelos de IA en Ollama...
where ollama >nul 2>nul || (echo  [!] No encuentro Ollama. Instalalo desde https://ollama.com y vuelve a ejecutar este archivo. & pause & exit /b 1)
ollama pull qwen3:4b-instruct
ollama pull bge-m3
ollama pull qwen2.5vl:3b

echo.
echo  === Listo. Arranca Jarvis con iniciar_jarvis.bat ===
pause
