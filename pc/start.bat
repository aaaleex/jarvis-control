@echo off
rem ============================================================
rem  Arranca Jarvis (vigilante + orbe) y el puente con Supabase.
rem  Si ya están en marcha no se duplican (cada uno lo comprueba).
rem  Primera vez:  instalar.bat  y  instalar_puente.bat
rem ============================================================
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "%~dp0vigilante.py"
if exist ".env" (
  start "" ".venv-puente\Scripts\pythonw.exe" "%~dp0puente_supabase.py"
) else (
  echo Falta pc\.env: copia .env.example como .env y rellena las claves de Supabase.
  pause
)
