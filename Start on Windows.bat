@echo off
rem Double-click this file to start WoW Fish YOLO.
rem The first time it sets itself up, which takes a few minutes.
setlocal
title WoW Fish YOLO
cd /d "%~dp0"

rem Prefer a Python that is known to work: 3.11 to 3.14. Failing that, try a newer one rather than give up.
set "PY="
set "KNOWN="
for %%L in (14 99) do for %%C in ("py -3.13" "py -3.12" "py -3.11" "py -3.14" "python" "python3" "py -3") do if not defined PY call :try %%L %%~C
if not defined PY goto nopython

rem Set up again whenever the list of things it needs changes, not only the first time.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
    echo Setting up WoW Fish YOLO. This happens once and takes a few minutes...
    call %PY% -m venv --clear .venv
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

rem Is this Python 64-bit and between 3.11 and 3.<first argument>? If so, use it.
rem "call" is needed because some set-ups provide Python through a small .bat file.
:try
call %2 %3 -c "import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] <= (3, %1) and sys.maxsize > 2**32))" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%2 %3"
if "%1"=="14" set "KNOWN=yes"
exit /b 0

:nopython
echo.
echo WoW Fish YOLO needs Python 3.13, which is free.
echo   1. Get Python 3.13 (64-bit) from https://www.python.org/downloads/
echo   2. In its installer, tick "Add python.exe to PATH".
echo   3. Double-click this file again.
echo.
pause
exit /b 1

:failed
echo.
echo Setting up did not finish. Check your internet connection, then double-click this file again.
if defined KNOWN goto morehelp
call %PY% -c "import sys; print('It used Python {}.{}, which may be too new. Python 3.13 is known to work:'.format(*sys.version_info[:2]))"
echo install it as well, then double-click this file again.
:morehelp
echo More help: docs\help.md
echo.
pause
exit /b 1
