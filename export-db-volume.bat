@echo off
title PLCM - Export DB volume
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "COMPOSE_FILE=docker-compose.prod.yml"
set "BACKUP_DIR=backups"
set "VOLUME_SUFFIX=satlife_pgdata"
set "HELPER_IMAGE=satlife-db:latest"

echo ===========================================
echo      Export Postgres DB volume
echo ===========================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not running.
    pause
    exit /b 1
)

if not exist "%COMPOSE_FILE%" (
    echo ERROR: %COMPOSE_FILE% not found in %cd%
    pause
    exit /b 1
)

docker image inspect "%HELPER_IMAGE%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Image %HELPER_IMAGE% not found.
    echo Load images with start.bat first, then run this script again.
    pause
    exit /b 1
)

rem Project name defaults to this folder name (Compose volume = project_satlife_pgdata)
for %%I in (".") do set "PROJECT=%%~nxI"
set "VOLUME=%PROJECT%_%VOLUME_SUFFIX%"

rem Prefer the volume actually mounted on satlife-db when the container exists
for /f "delims=" %%V in ('docker inspect -f "{{range .Mounts}}{{if eq .Destination \"/var/lib/postgresql/data\"}}{{.Name}}{{end}}{{end}}" satlife-db 2^>nul') do (
    if not "%%V"=="" set "VOLUME=%%V"
)

docker volume inspect "%VOLUME%" >nul 2>&1
if errorlevel 1 (
    echo Looking for a %VOLUME_SUFFIX% volume...
    set "VOLUME="
    for /f "delims=" %%V in ('docker volume ls -q 2^>nul ^| findstr /i "%VOLUME_SUFFIX%$"') do (
        if defined VOLUME (
            echo ERROR: Multiple DB volumes found. Refusing to guess.
            echo   !VOLUME!
            echo   %%V
            echo Stop extra stacks or set the volume name manually.
            pause
            exit /b 1
        )
        set "VOLUME=%%V"
    )
)

if not defined VOLUME (
    echo ERROR: No Postgres data volume found ^(*%VOLUME_SUFFIX%^).
    echo Start the system once with start.bat so the volume is created.
    pause
    exit /b 1
)

echo Using volume: %VOLUME%
echo.

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%" >nul 2>&1

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
set "BACKUP_FILE=%BACKUP_DIR%\satlife_pgdata_%STAMP%.tar.gz"
set "BACKUP_FILE_ABS=%cd%\%BACKUP_FILE%"

echo Stopping containers for a consistent snapshot...
if exist ".env" (
    docker compose -f "%COMPOSE_FILE%" --env-file .env stop
) else (
    docker compose -f "%COMPOSE_FILE%" stop
)

echo.
echo Exporting to %BACKUP_FILE% ...
docker run --rm --entrypoint tar ^
  -v "%VOLUME%:/data:ro" ^
  -v "%cd%\%BACKUP_DIR%:/backup" ^
  "%HELPER_IMAGE%" ^
  czf "/backup/satlife_pgdata_%STAMP%.tar.gz" -C /data .
if errorlevel 1 (
    echo ERROR: Volume export failed.
    echo Starting containers again...
    if exist ".env" (
        docker compose -f "%COMPOSE_FILE%" --env-file .env start
    ) else (
        docker compose -f "%COMPOSE_FILE%" start
    )
    pause
    exit /b 1
)

echo.
echo Restarting containers...
if exist ".env" (
    docker compose -f "%COMPOSE_FILE%" --env-file .env start
) else (
    docker compose -f "%COMPOSE_FILE%" start
)

echo.
echo ===========================================
echo Export complete.
echo File: %BACKUP_FILE_ABS%
for %%A in ("%BACKUP_FILE%") do echo Size: %%~zA bytes
echo ===========================================
pause
endlocal
