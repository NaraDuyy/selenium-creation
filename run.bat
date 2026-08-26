@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [X] Not set up yet on this machine.
    echo     Run setup.bat once, then come back to run.bat.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "src\main.py" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo Exited with code %CODE%.
    pause
)
exit /b %CODE%
