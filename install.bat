@echo off
REM ============================================================================
REM  Installeur du Fading Echo Launcher (Windows)
REM
REM  Double-cliquez sur ce fichier. Il verifie que tout est present et installe
REM  ce qui manque : Python, l'environnement, la dependance PySide6, et un
REM  raccourci sur le Bureau. On peut le relancer sans risque : il ne refait
REM  que ce qui n'est pas deja en place.
REM ============================================================================
setlocal enabledelayedexpansion
title Installation - Fading Echo Launcher
cd /d "%~dp0"

echo(
echo ================================================
echo    Fading Echo Launcher - installation
echo ================================================
echo(

REM --- Verification : le code du launcher est-il bien la ? -------------------
if not exist "fe_launcher\app.py" (
  echo ERREUR : ce fichier doit etre place a la racine du launcher,
  echo a cote du dossier "fe_launcher". Il n'y est pas.
  echo(
  echo Telechargez le projet complet depuis :
  echo   https://github.com/cheapmanga/FadingLauncher
  echo puis relancez install.bat depuis le dossier extrait.
  echo(
  pause
  exit /b 1
)

REM --- Etape 1/4 : Python ----------------------------------------------------
echo [1/4] Recherche de Python...
set "PYCMD="
py -3 --version >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD (
  python --version >nul 2>&1 && set "PYCMD=python"
)

if not defined PYCMD (
  echo       Python n'est pas installe. Telechargement de la version officielle...
  set "PYURL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
  set "PYEXE=%TEMP%\fe-python-installer.exe"
  powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '!PYURL!' -OutFile '!PYEXE!' } catch { exit 1 }"
  if not exist "!PYEXE!" (
    echo       Echec du telechargement. Installez Python a la main depuis
    echo       https://www.python.org/downloads/ ^(cochez "Add Python to PATH"^),
    echo       puis relancez install.bat.
    pause
    exit /b 1
  )
  echo       Installation de Python en cours ^(patientez une minute^)...
  "!PYEXE!" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
  del "!PYEXE!" >nul 2>&1
  REM  Le PATH modifie n'est pas encore actif dans cette fenetre : on cherche
  REM  l'executable a son emplacement d'installation par utilisateur.
  set "PYCMD="
  for /f "delims=" %%i in ('dir /b /s "%LocalAppData%\Programs\Python\python.exe" 2^>nul') do set "PYCMD=%%i"
  if not defined PYCMD (
    py -3 --version >nul 2>&1 && set "PYCMD=py -3"
  )
  if not defined PYCMD (
    echo       Python a ete installe, mais il faut rouvrir cette fenetre.
    echo       Fermez-la et relancez install.bat : ce sera pris en compte.
    pause
    exit /b 0
  )
  echo       Python installe.
) else (
  echo       Python : OK
)

REM --- Etape 2/4 : environnement isole (venv) --------------------------------
echo [2/4] Preparation de l'environnement...
if exist ".venv\Scripts\python.exe" (
  echo       Environnement : deja present
) else (
  %PYCMD% -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo       ERREUR : impossible de creer l'environnement Python.
    pause
    exit /b 1
  )
  echo       Environnement cree.
)
set "VENV_PY=.venv\Scripts\python.exe"

REM --- Etape 3/4 : dependance PySide6 ----------------------------------------
echo [3/4] Verification de la dependance graphique ^(PySide6^)...
"%VENV_PY%" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo       Installation de PySide6 ^(gros telechargement, patientez^)...
  "%VENV_PY%" -m pip install --quiet --upgrade pip
  "%VENV_PY%" -m pip install --quiet PySide6
  "%VENV_PY%" -c "import PySide6" >nul 2>&1
  if errorlevel 1 (
    echo       ERREUR : l'installation de PySide6 a echoue. Verifiez votre
    echo       connexion internet et relancez install.bat.
    pause
    exit /b 1
  )
  echo       PySide6 installe.
) else (
  echo       PySide6 : OK
)

REM --- Etape 4/4 : raccourci sur le Bureau -----------------------------------
echo [4/4] Creation du raccourci sur le Bureau...
set "TARGET=%~dp0.venv\Scripts\pythonw.exe"
set "LNK=%USERPROFILE%\Desktop\Fading Echo Launcher.lnk"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.Arguments='-m fe_launcher.app';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.Description='Fading Echo Launcher';" ^
  "$s.Save()"
if exist "%LNK%" (
  echo       Raccourci cree sur le Bureau.
) else (
  echo       Raccourci non cree ^(sans gravite^). Utilisez lancer.bat a la place.
)

echo(
echo ================================================
echo    Installation terminee.
echo(
echo    Pour lancer : double-cliquez sur le raccourci
echo    "Fading Echo Launcher" sur votre Bureau,
echo    ou sur "lancer.bat" dans ce dossier.
echo ================================================
echo(
pause
endlocal
