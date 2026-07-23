@echo off
REM Lance le Fading Echo Launcher. Double-cliquez sur ce fichier.
REM Si rien ne se passe, lancez d'abord install.bat.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Le launcher n'est pas installe. Lancez d'abord install.bat.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m fe_launcher.app
