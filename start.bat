@echo off
rem Windows: double-click this file to start the bot. The first run sets things up (a few minutes).
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (set "PY=python") else (set "PY=py -3")

rem Set up again whenever the requirements change, not only the first time.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
    echo Setting up. The first time takes a few minutes.
    if not exist ".venv\Scripts\python.exe" (
        %PY% -m venv .venv
        if errorlevel 1 goto nopython
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

".venv\Scripts\python.exe" bot.py %*
if errorlevel 1 pause
exit /b

:nopython
echo.
echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup. Then run this file again.
pause
exit /b 1

:failed
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
