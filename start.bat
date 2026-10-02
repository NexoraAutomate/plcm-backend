@echo off
title PLCM System - Start (Offline)
setlocal EnableExtensions
cd /d "%~dp0"

set "COMPOSE_FILE=docker-compose.prod.yml"
set "IMAGE_TAR=images\satlife-complete.tar"

echo ===========================================
echo      PLCM System Deployment (Offline)
echo ===========================================
echo.

echo Checking Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not running.
    echo Start Docker Desktop / the Docker engine and try again.
    pause
    exit /b 1
)

if not exist "%COMPOSE_FILE%" (
    echo ERROR: %COMPOSE_FILE% not found in %cd%
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        echo .env missing — copying from .env.example
        copy /Y ".env.example" ".env" >nul
    ) else (
        echo ERROR: .env is required. Copy .env.example to .env and edit secrets.
        pause
        exit /b 1
    )
)

if not exist "%IMAGE_TAR%" (
    echo ERROR: Image archive not found: %IMAGE_TAR%
    echo Place satlife-complete.tar under the images\ folder.
    pause
    exit /b 1
)

echo.
echo Loading Docker images from %IMAGE_TAR% ...
docker load -i "%IMAGE_TAR%"
if errorlevel 1 (
    echo ERROR: Failed to load Docker images.
    pause
    exit /b 1
)

echo.
echo Starting containers with %COMPOSE_FILE% ...
docker compose -f "%COMPOSE_FILE%" --env-file .env up -d --pull never
if errorlevel 1 (
    echo ERROR: Failed to start containers.
    pause
    exit /b 1
)

echo.
echo ===========================================
echo PLCM System started successfully.
echo.
echo Frontend:  http://localhost:3000
echo Backend:   http://localhost:8000/docs
echo.
echo From another PC on the LAN, use this machine's IP:
echo   http://^<host-ip^>:3000
echo ===========================================

pause
endlocal
