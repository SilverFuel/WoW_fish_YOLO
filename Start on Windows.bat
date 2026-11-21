@echo off
rem Double-click this file to start WoW Fish YOLO.
rem The first time it sets itself up, which takes a few minutes.
setlocal
title WoW Fish YOLO
cd /d "%~dp0"

rem Use the first Python that is new enough.
set "PY="
call :try py -3
if not defined PY call :try python
if not defined PY goto nopython

rem Set up again whenever the list of things it needs changes, not only the first time.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
    echo Setting up WoW Fish YOLO. This happens once and takes a few minutes...
    if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
    if not exist ".venv\Scripts\python.exe" goto failed
    ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto failed
    copy /y requirements.txt ".venv\requirements.installed" >nul
    echo Done.
    echo.
)

".venv\Scripts\python.exe" bot.py %*
if errorlevel 1 pause
exit /b

:try
%* -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b 0

:nopython
echo.
echo WoW Fish YOLO needs Python 3.11 or newer, which is free.
echo   1. Get it from https://www.python.org/downloads/
echo   2. In its installer, tick "Add python.exe to PATH".
echo   3. Double-click this file again.
echo.
pause
exit /b 1

:failed
echo.
echo Setting up did not finish. Check your internet connection, then double-click this file again.
echo If it keeps happening, see docs\help.md.
echo.
pause
exit /b 1
