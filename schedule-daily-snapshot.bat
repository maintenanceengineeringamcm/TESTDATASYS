@echo off
REM ---------------------------------------------------------------------------
REM Registers the daily 08:00 health-index snapshot as a Windows scheduled task.
REM Windows has no cron; Task Scheduler is the equivalent.
REM
REM Run this ONCE, as Administrator.
REM ---------------------------------------------------------------------------
setlocal

set ROOT=%~dp0
set TASKNAME=HI Daily Snapshot
set RUNTIME=08:00

echo ============================================================
echo  Scheduling: %TASKNAME%  (daily at %RUNTIME%)
echo ============================================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo This script must be run as Administrator.
    echo Right-click it and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

REM Resolve the Python launcher so the task does not depend on PATH.
for /f "delims=" %%P in ('where py 2^>nul') do set PYEXE=%%P& goto :found
:found
if "%PYEXE%"=="" (
    echo Could not find the "py" launcher on PATH.
    pause
    exit /b 1
)
echo Using Python launcher: %PYEXE%
echo.

schtasks /Query /TN "%TASKNAME%" >nul 2>&1
if not errorlevel 1 (
    echo An existing task was found - replacing it.
    schtasks /Delete /TN "%TASKNAME%" /F >nul
)

REM /RL HIGHEST so the task can read the database under Windows auth.
schtasks /Create ^
    /TN "%TASKNAME%" ^
    /TR "\"%PYEXE%\" \"%ROOT%backend\run_snapshot.py\" --quiet" ^
    /SC DAILY ^
    /ST %RUNTIME% ^
    /RL HIGHEST ^
    /F

if errorlevel 1 (
    echo.
    echo Failed to create the scheduled task.
    pause
    exit /b 1
)

echo.
echo Task created. It will run every day at %RUNTIME%.
echo.
echo   Run it now:      schtasks /Run    /TN "%TASKNAME%"
echo   Check it:        schtasks /Query  /TN "%TASKNAME%" /V /FO LIST
echo   Remove it:       schtasks /Delete /TN "%TASKNAME%" /F
echo   Job log:         %ROOT%backend\logs\snapshot.log
echo.

choice /C YN /M "Run the first snapshot now"
if errorlevel 2 goto :done
schtasks /Run /TN "%TASKNAME%"
echo.
echo Started. Watch progress in backend\logs\snapshot.log
echo.

:done
pause
