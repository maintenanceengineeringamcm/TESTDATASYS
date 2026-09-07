@echo off
title System Alert - Security Breach
color 0C
mode con: cols=80 lines=25 >nul
cls
echo ******************************************************
echo * WARNING: UNAUTHORIZED ACTIVITY DETECTED              *
echo ******************************************************
echo.
echo Scanning system for intrusions...
echo (Press CTRL+C to abort and return to desktop)
echo.

rem simulated progress
setlocal enabledelayedexpansion
for /L %%i in (1,1,100) do (
	set /a p=%%i
	set /p="Progress: [" <nul
	for /L %%j in (1,1,%%i) do @set /p=## <nul
	for /L %%k in (%%i,1,100) do @set /p=.. <nul
	set /p="] " <nul
	set /p="!p!%%" <nul
	rem short delay
	>nul ping -n 1 -w 30 127.0.0.1
	echo.
)

echo.
echo CRITICAL: Malware signatures matched. Isolating files...
>nul ping -n 1 -w 700 127.0.0.1
echo.
echo Attempting system lockdown...
for /L %%i in (1,1,5) do (
	set /p="Lockdown in " <nul
	set /p="%%i" <nul
	set /p="..." <nul
	>nul ping -n 1 -w 400 127.0.0.1
	echo.
)

echo.
echo This is a simulated alert for demonstration purposes only.
echo No files have been harmed.
echo.
pause
endlocal
