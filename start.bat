@echo off
title PLCM System - Start

echo ===========================================
echo      PLCM System Deployment
echo ===========================================
echo.

echo Checking Docker...
docker info >nul 2>&1

if errorlevel 1 (
    echo ERROR: Docker Desktop is not running.
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo.
echo Loading Docker images...
docker load -i images\satlife-complete.tar

if errorlevel 1 (
    echo ERROR: Failed to load Docker images.
    pause
    exit /b 1
)

echo.
echo Starting PLCM containers...
docker compose up -d

if errorlevel 1 (
    echo ERROR: Failed to start containers.
    pause
    exit /b 1
)

echo.
echo ===========================================
echo PLCM System started successfully.
echo.
echo Frontend:
echo http://localhost:3000
echo.
echo Backend API:
echo http://localhost:8000/docs
echo ===========================================

pause