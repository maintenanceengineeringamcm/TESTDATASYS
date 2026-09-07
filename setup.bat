@echo off
REM One-time installer for the backend and frontend dependencies.
setlocal

set ROOT=%~dp0

echo ============================================================
echo  Asset Health Index ^& DGA Analysis - setup
echo ============================================================
echo.

echo [1/3] Installing Python packages...
pushd "%ROOT%backend"
py -m pip install -r requirements.txt
if errorlevel 1 goto :fail
popd
pushd "%ROOT%config-service"
py -m pip install -r requirements.txt
if errorlevel 1 goto :fail
popd
echo.

echo [2/3] Installing Node packages...
pushd "%ROOT%frontend"
call npm install --no-fund --no-audit
if errorlevel 1 goto :fail
popd
echo.

echo [3/3] Checking the database connection...
pushd "%ROOT%backend"
py -c "import db, json; print(json.dumps(db.health(), indent=2))"
popd
echo.

echo Setup complete. Run start.bat to launch the system.
echo.
echo NEXT: schedule the daily snapshot so the dashboard loads instantly.
echo   Right-click schedule-daily-snapshot.bat and "Run as administrator".
echo   It registers a Task Scheduler job for 08:00 every day.
echo.
echo Optional: to enable the AI fault classifier, run
echo   py -m pip install -r backend\requirements-ml.txt
echo and place the training files in backend\ml_data\.
echo.
pause
exit /b 0

:fail
echo.
echo Setup FAILED. See the messages above.
pause
exit /b 1
