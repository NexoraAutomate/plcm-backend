@echo off
title PLCM System - Update (Offline)
setlocal EnableExtensions
cd /d "%~dp0"

set "COMPOSE_FILE=docker-compose.prod.yml"
set "IMAGE_TAR=images\satlife-complete.tar"

echo ===========================================
echo      Updating PLCM System (Offline)
echo ===========================================
echo.

if not exist "%IMAGE_TAR%" (
    echo ERROR: Image archive not found: %IMAGE_TAR%
    pause
    exit /b 1
)

if not exist ".env" (
    echo ERROR: .env is required.
    pause
    exit /b 1
)

echo Stopping existing containers...
docker compose -f "%COMPOSE_FILE%" --env-file .env down

echo.
echo Loading updated images from %IMAGE_TAR% ...
docker load -i "%IMAGE_TAR%"
if errorlevel 1 (
    echo ERROR: Failed to load Docker images.
    pause
    exit /b 1
)

echo.
echo Starting updated containers...
docker compose -f "%COMPOSE_FILE%" --env-file .env up -d --pull never
if errorlevel 1 (
    echo ERROR: Failed to start containers.
    pause
    exit /b 1
)

echo.
echo Update completed successfully.
pause
endlocal
