@echo off
REM Builds Tomms_CEBT_HI (the small CMMS copy the HI system needs) and backs it
REM up to the backup\ folder next to this file.
REM
REM Run it ON the machine that hosts the SQL Server instance holding Tomms_CEBT:
REM SQL Server itself writes the .bak, so the folder must be local to it.
setlocal

REM --- the instance that holds Tomms_CEBT (default instance = machine name) ---
set SERVER=DESKTOP-E3R1QOH

set OUTDIR=%~dp0backup
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

REM SQL Server writes the backup under its own service account, which cannot
REM write to a user's folder until it is given permission.
set SVC=
for /f "usebackq delims=" %%A in (`sqlcmd -S "%SERVER%" -E -C -h -1 -W -Q "SET NOCOUNT ON; SELECT TOP 1 service_account FROM sys.dm_server_services WHERE servicename LIKE 'SQL Server (%%'"`) do set SVC=%%A
if not defined SVC (
    echo Could not connect to %SERVER% - check the SERVER name at the top of this file.
    pause
    exit /b 1
)
icacls "%OUTDIR%" /grant "%SVC%":(OI)(CI)M >nul
if errorlevel 1 echo WARNING: could not grant %SVC% access to %OUTDIR% - the backup step may fail.

echo Building Tomms_CEBT_HI on %SERVER% ...
echo.
REM -E  Windows login   -b  stop on error   -C  trust the server certificate
sqlcmd -S "%SERVER%" -E -C -b -W -s " | " -i "%~dp0create_tomms_slim.sql" -v BackupDir="%OUTDIR%"
if errorlevel 1 (
    echo.
    echo FAILED - see the message above.
    pause
    exit /b 1
)
echo.
echo Backup file: %OUTDIR%\Tomms_CEBT_HI.bak
pause
