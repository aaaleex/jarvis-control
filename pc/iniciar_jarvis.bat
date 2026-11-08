@echo off
REM ============================================================
REM  Arranca el VIGILANTE de Jarvis (icono en la bandeja) y abre Jarvis.
REM  Si el vigilante ya estaba en marcha, solo abre Jarvis.
REM ============================================================
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo  [!] No encuentro el entorno de Python de Jarvis.
    echo      Ejecuta primero instalar.bat
    echo.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" vigilante.py --abrir
