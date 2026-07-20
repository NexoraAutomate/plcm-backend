@echo off
title PLCM System - Stop

echo ===========================================
echo      Stopping PLCM System
echo ===========================================
echo.

docker compose down

if errorlevel 1 (
    echo ERROR: Failed to stop containers.
    pause
    exit /b 1
)

echo.
echo PLCM System has been stopped successfully.

pause