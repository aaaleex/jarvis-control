@echo off
rem ============================================================
rem  Instala el puente con Supabase en su propio entorno (.venv-puente)
rem  para no cambiar las librerías de Jarvis (supabase trae otra versión de websockets).
rem  Y lo deja arrancando solo al iniciar sesión en Windows.
rem ============================================================
cd /d "%~dp0"
if not exist ".venv-puente\Scripts\python.exe" py -3.12 -m venv .venv-puente || python -m venv .venv-puente
".venv-puente\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-puente.txt || goto :error
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Jarvis puente Supabase.lnk'); $s.TargetPath='%~dp0.venv-puente\Scripts\pythonw.exe'; $s.Arguments='\"%~dp0puente_supabase.py\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo.
echo Listo. Rellena pc\.env (mira .env.example) y ejecuta start.bat
pause
exit /b 0
:error
echo Fallo instalando dependencias.
pause
exit /b 1
