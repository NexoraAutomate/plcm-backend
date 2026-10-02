@echo off
title PLCM System - Uninstall
setlocal EnableExtensions
cd /d "%~dp0"

set "COMPOSE_FILE=docker-compose.prod.yml"

echo ===========================================
echo      Uninstalling PLCM System
echo ===========================================
echo.

echo Stopping containers...
if exist ".env" (
    docker compose -f "%COMPOSE_FILE%" --env-file .env down
) else (
    docker compose -f "%COMPOSE_FILE%" down
)

echo.
echo Removing images...
docker image rm satlife-db:latest 2>nul
docker image rm satlife-backend:latest 2>nul
docker image rm satlife-frontend:latest 2>nul

echo.
echo Done. Named volumes (satlife_pgdata / satlife_uploads) were kept.
echo To remove data volumes as well, run:
echo   docker volume rm satlife_pgdata satlife_uploads
echo.
pause
endlocal
