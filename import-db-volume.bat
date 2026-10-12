@echo off
title PLCM - Import DB volume
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "COMPOSE_FILE=docker-compose.prod.yml"
set "BACKUP_DIR=backups"
set "VOLUME_SUFFIX=satlife_pgdata"
set "HELPER_IMAGE=satlife-db:latest"
set "BACKUP_FILE=%~1"

echo ===========================================
echo      Import Postgres DB volume
echo ===========================================
echo.
echo WARNING: This OVERWRITES the current database volume.
echo Make an export first if you need a safety copy.
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

if "%BACKUP_FILE%"=="" (
    if not exist "%BACKUP_DIR%" (
        echo ERROR: No backups folder and no file argument given.
        echo Usage: import-db-volume.bat [path-to-backup.tar.gz]
        pause
        exit /b 1
    )
    set "LATEST="
    for /f "delims=" %%F in ('dir /b /a-d /o-d "%BACKUP_DIR%\satlife_pgdata_*.tar.gz" 2^>nul') do (
        if not defined LATEST set "LATEST=%BACKUP_DIR%\%%F"
    )
    if not defined LATEST (
        echo ERROR: No satlife_pgdata_*.tar.gz files in %BACKUP_DIR%\
        echo Usage: import-db-volume.bat [path-to-backup.tar.gz]
        pause
        exit /b 1
    )
    set "BACKUP_FILE=!LATEST!"
    echo Using latest backup: !BACKUP_FILE!
) else (
    echo Using backup: %BACKUP_FILE%
)

if not exist "%BACKUP_FILE%" (
    echo ERROR: Backup file not found: %BACKUP_FILE%
    pause
    exit /b 1
)

rem Project name defaults to this folder name (Compose volume = project_satlife_pgdata)
for %%I in (".") do set "PROJECT=%%~nxI"
set "VOLUME=%PROJECT%_%VOLUME_SUFFIX%"

for /f "delims=" %%V in ('docker inspect -f "{{range .Mounts}}{{if eq .Destination \"/var/lib/postgresql/data\"}}{{.Name}}{{end}}{{end}}" satlife-db 2^>nul') do (
    if not "%%V"=="" set "VOLUME=%%V"
)

docker volume inspect "%VOLUME%" >nul 2>&1
if errorlevel 1 (
    echo Volume %VOLUME% does not exist yet — creating it...
    docker volume create "%VOLUME%" >nul
    if errorlevel 1 (
        echo ERROR: Failed to create volume %VOLUME%.
        pause
        exit /b 1
    )
)

echo Target volume: %VOLUME%
echo.
set /p "CONFIRM=Type YES to overwrite the database volume: "
if /I not "%CONFIRM%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo Stopping containers...
if exist ".env" (
    docker compose -f "%COMPOSE_FILE%" --env-file .env stop
) else (
    docker compose -f "%COMPOSE_FILE%" stop
)

rem Resolve absolute path + parent for a reliable Docker bind mount on Windows
for %%F in ("%BACKUP_FILE%") do (
    set "BACKUP_ABS=%%~fF"
    set "BACKUP_NAME=%%~nxF"
    set "BACKUP_PARENT=%%~dpF"
)
rem Strip trailing backslash from parent for docker -v
if "!BACKUP_PARENT:~-1!"=="\" set "BACKUP_PARENT=!BACKUP_PARENT:~0,-1!"

echo.
echo Restoring into %VOLUME% ...
docker run --rm --entrypoint sh ^
  -v "%VOLUME%:/data" ^
  -v "!BACKUP_PARENT!:/backup" ^
  "%HELPER_IMAGE%" ^
  -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; tar xzf \"/backup/!BACKUP_NAME!\" -C /data"
if errorlevel 1 (
    echo ERROR: Volume import failed.
    echo Starting containers again (database may be incomplete^)...
    if exist ".env" (
        docker compose -f "%COMPOSE_FILE%" --env-file .env start
    ) else (
        docker compose -f "%COMPOSE_FILE%" start
    )
    pause
    exit /b 1
)

echo.
echo Starting containers...
if exist ".env" (
    docker compose -f "%COMPOSE_FILE%" --env-file .env up -d --pull never
) else (
    docker compose -f "%COMPOSE_FILE%" up -d --pull never
)
if errorlevel 1 (
    echo ERROR: Restore finished but containers failed to start.
    pause
    exit /b 1
)

echo.
echo ===========================================
echo Import complete.
echo Restored from: %BACKUP_ABS%
echo Volume:        %VOLUME%
echo ===========================================
pause
endlocal
