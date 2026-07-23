@echo off
REM ============================================================================
REM  Met a jour le Fading Echo Launcher sans tout reinstaller.
REM
REM  Telecharge la derniere version du code depuis GitHub et remplace les
REM  fichiers du launcher, EN GARDANT votre environnement (.venv) et vos
REM  donnees. Bien plus rapide que de retelecharger le ZIP complet et de
REM  relancer install.bat.
REM ============================================================================
setlocal
title Mise a jour - Fading Echo Launcher
cd /d "%~dp0"

if not exist "fe_launcher\app.py" (
  echo Ce fichier doit etre a la racine du launcher. Abandon.
  pause & exit /b 1
)

echo Telechargement de la derniere version...
set "ZIP=%TEMP%\fe-launcher-update.zip"
set "TMP=%TEMP%\fe-launcher-update"
powershell -NoProfile -Command ^
  "try { Invoke-WebRequest -Uri 'https://github.com/cheapmanga/FadingLauncher/archive/refs/heads/main.zip' -OutFile '%ZIP%' } catch { exit 1 }"
if not exist "%ZIP%" (
  echo Echec du telechargement. Verifiez votre connexion.
  pause & exit /b 1
)

echo Extraction...
if exist "%TMP%" rmdir /s /q "%TMP%"
powershell -NoProfile -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%TMP%' -Force"

REM Le ZIP GitHub contient un sous-dossier "FadingLauncher-main".
set "SRC=%TMP%\FadingLauncher-main"
if not exist "%SRC%\fe_launcher\app.py" (
  echo Archive inattendue. Abandon sans rien modifier.
  pause & exit /b 1
)

echo Remplacement du code ^(votre .venv et vos donnees sont conserves^)...
REM On remplace le code et les ressources, PAS le .venv ni les fichiers locaux.
robocopy "%SRC%\fe_launcher" "%~dp0fe_launcher" /MIR /NFL /NDL /NJH /NJS /NC /NS >nul
robocopy "%SRC%\tools" "%~dp0tools" /MIR /NFL /NDL /NJH /NJS /NC /NS >nul
copy /y "%SRC%\*.bat" "%~dp0" >nul 2>&1
copy /y "%SRC%\*.py" "%~dp0" >nul 2>&1
copy /y "%SRC%\*.md" "%~dp0" >nul 2>&1

rmdir /s /q "%TMP%" 2>nul
del "%ZIP%" 2>nul

echo(
echo ================================================
echo    Launcher mis a jour.
echo    Relancez-le ^(raccourci du Bureau ou lancer.bat^).
echo ================================================
echo(
pause
endlocal
