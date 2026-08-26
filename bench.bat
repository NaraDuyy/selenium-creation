@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [X] Not set up yet on this machine.
    echo     Run setup.bat once, then come back to bench.bat.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "src\bench.py" %*
set "CODE=%ERRORLEVEL%"
echo.
pause
exit /b %CODE%
