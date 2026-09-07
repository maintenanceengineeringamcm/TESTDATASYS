@echo off
REM Launches the Flask API and the Vite dev server in separate windows.
setlocal

set ROOT=%~dp0

echo ============================================================
echo  Asset Health Index ^& DGA Analysis
echo ============================================================
echo.

if not exist "%ROOT%frontend\node_modules" (
    echo [setup] Installing frontend packages, this runs once...
    pushd "%ROOT%frontend"
    call npm install --no-fund --no-audit
    popd
    echo.
)

echo [1/3] Starting Configuration service on http://127.0.0.1:5001 ...
start "HI Config Service" cmd /k "cd /d "%ROOT%config-service" && py app.py"

REM The API reads scoring overrides from the configuration service at startup.
timeout /t 3 /nobreak >nul

echo [2/3] Starting API on http://127.0.0.1:5000 ...
start "HI API" cmd /k "cd /d "%ROOT%backend" && py app.py"

echo [3/3] Starting UI on http://127.0.0.1:5180 ...
start "HI UI" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo.
echo All three services are starting in their own windows.
echo Open http://127.0.0.1:5180 once the UI window reports "ready".
echo Close those windows to stop the services.
echo.
pause
