@echo off
REM ============================================================================
REM  Fabrique un vrai .exe autonome du launcher (Windows).
REM
REM  A lancer UNE FOIS sur le PC de jeu. Produit "FadingEchoLauncher.exe" dans
REM  le dossier "dist" : un seul fichier, qui ne necessite PLUS Python ni rien
REM  d'autre pour tourner. Vous pouvez ensuite le copier ou vous voulez.
REM
REM  Prerequis : Python installe (lancez install.bat s'il ne l'est pas).
REM ============================================================================
setlocal
title Compilation - Fading Echo Launcher
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo L'environnement n'est pas pret. Lancez d'abord install.bat.
  pause
  exit /b 1
)
set "VENV_PY=.venv\Scripts\python.exe"

echo Installation de l'outil de compilation ^(PyInstaller^)...
"%VENV_PY%" -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 (
  echo Echec de l'installation de PyInstaller. Verifiez votre connexion.
  pause
  exit /b 1
)

echo Compilation en cours ^(cela peut prendre quelques minutes^)...
"%VENV_PY%" -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "FadingEchoLauncher" ^
  --add-data "fe_launcher\resources;fe_launcher\resources" ^
  --collect-submodules PySide6 ^
  run.py 2>build_exe.log

if exist "dist\FadingEchoLauncher.exe" (
  echo(
  echo ================================================
  echo    Termine : dist\FadingEchoLauncher.exe
  echo    Ce fichier est autonome, copiez-le ou vous voulez.
  echo ================================================
) else (
  echo(
  echo La compilation a echoue. Details dans build_exe.log.
)
echo(
pause
endlocal
