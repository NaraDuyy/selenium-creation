@echo off
setlocal
cd /d "%~dp0"

echo ==============================================================
echo   selenium-creation  ^|  one-time setup
echo ==============================================================
echo.

rem Ask each candidate to print something. Windows ships a "python.exe" stub
rem that only advertises the Microsoft Store, so a name on PATH proves nothing.
set "PY="
call :try_python "py -3"
call :try_python "python"
call :try_python "python3"
if not defined PY (
    echo [X] No working Python on this machine.
    echo     Windows may list python.exe without installing it - that stub only
    echo     opens the Microsoft Store.
    echo.
    echo     Install Python 3.9 or newer from
    echo       https://www.python.org/downloads/windows/
    echo     and tick "Add python.exe to PATH", then run setup.bat again.
    echo.
    echo     If it still fails, turn off the stub in
    echo       Settings ^> Apps ^> Advanced app settings ^> App execution aliases
    goto :fail
)

echo [1/4] Using Python:
%PY% --version
echo.

echo [2/4] Creating the virtual environment in .venv ...
if exist ".venv\Scripts\python.exe" (
    echo       .venv already exists - reusing it.
) else (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [X] Could not create the virtual environment.
        goto :fail
    )
)
echo.

echo [3/4] Installing dependencies ^(CloakBrowser + its ~200 MB browser, takes a minute^) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] Dependency install failed. Scroll up for the pip error.
    goto :fail
)
".venv\Scripts\python.exe" -m cloakbrowser install
if errorlevel 1 (
    echo [X] Could not download the CloakBrowser binary. Scroll up for the error.
    goto :fail
)
echo.

echo [4/4] Checking your rotating-proxy key ...
if not exist "proxykey.txt" (
    echo.
    echo       proxykey.txt is missing. Paste the key you received when you
    echo       bought the proxyxoay.shop rotating plan.
    echo.
    set /p "PROXYKEY=      Key: "
    if not defined PROXYKEY (
        echo [X] No key entered. Create proxykey.txt yourself and paste the key in.
        goto :fail
    )
    > "proxykey.txt" echo %PROXYKEY%
    echo       Saved to proxykey.txt
) else (
    echo       proxykey.txt found.
)
echo.

echo ==============================================================
echo   Setup complete. Launch a browser with:   run.bat
echo ==============================================================
echo.
pause
exit /b 0

:try_python
if defined PY goto :eof
for /f "delims=" %%v in ('%~1 -c "print(42)" 2^>nul') do (
    if "%%v"=="42" set "PY=%~1"
)
goto :eof

:fail
echo.
pause
exit /b 1
