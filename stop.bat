@echo off
title PLCM System - Stop
setlocal EnableExtensions
cd /d "%~dp0"

set "COMPOSE_FILE=docker-compose.prod.yml"

echo ===========================================
echo      Stopping PLCM System
echo ===========================================
echo.

docker compose -f "%COMPOSE_FILE%" --env-file .env down
if errorlevel 1 (
    echo ERROR: Failed to stop containers.
    pause
    exit /b 1
)

echo.
echo PLCM System has been stopped successfully.
pause
endlocal
