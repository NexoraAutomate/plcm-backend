@echo off
title PLCM - Package offline deploy folder
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem Output folder inside the backend repo — copy this whole folder to the client PC
set "OUT_DIR=offline-package"
set "COMPOSE_BUILD=docker-compose.yml"
set "COMPOSE_PROD=docker-compose.prod.yml"
set "TAR_NAME=satlife-complete.tar"
rem Temporary migrate stack (avoids clash with fixed compose container_name values)
set "PACK_NET=satlife-offline-pack-net"
set "PACK_DB=satlife-offline-pack-db"
set "PACK_DB_USER=postgres"
set "PACK_DB_PASSWORD=postgres"
set "PACK_DB_NAME=plcm"

echo ===========================================
echo  PLCM offline package builder
echo  (needs Docker + internet for base images)
echo ===========================================
echo.
echo Output: %cd%\%OUT_DIR%\
echo.

docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not running.
    echo Start Docker Desktop / the Docker engine and try again.
    pause
    exit /b 1
)

if not exist "%COMPOSE_BUILD%" (
    echo ERROR: %COMPOSE_BUILD% not found.
    pause
    exit /b 1
)

if not exist "%COMPOSE_PROD%" (
    echo ERROR: %COMPOSE_PROD% not found.
    pause
    exit /b 1
)

if not exist ".env.example" (
    echo ERROR: .env.example not found.
    pause
    exit /b 1
)

rem Use local .env for build-time vars if present; otherwise seed from example
if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example for this build.
)

if not exist "..\satlife-frontend-main" (
    echo ERROR: Frontend repo not found at ..\satlife-frontend-main
    echo The compose build expects the frontend next to this backend folder.
    pause
    exit /b 1
)

echo [1/5] Building images (satlife-db / satlife-backend / satlife-frontend)...
docker compose -f "%COMPOSE_BUILD%" --env-file .env build
if errorlevel 1 (
    echo ERROR: docker compose build failed.
    pause
    exit /b 1
)

echo.
echo [2/5] Applying migrations against a fresh package DB...
echo         (validates alembic upgrade head; backend image also migrates on client start)

rem Cleanup any leftover pack containers/network from a previous failed run
docker rm -f "%PACK_DB%" >nul 2>&1
docker network rm "%PACK_NET%" >nul 2>&1

docker network create "%PACK_NET%" >nul
if errorlevel 1 (
    echo ERROR: Failed to create package network %PACK_NET%.
    pause
    exit /b 1
)

docker run -d --name "%PACK_DB%" --network "%PACK_NET%" ^
  -e POSTGRES_USER=%PACK_DB_USER% ^
  -e POSTGRES_PASSWORD=%PACK_DB_PASSWORD% ^
  -e POSTGRES_DB=%PACK_DB_NAME% ^
  satlife-db:latest >nul
if errorlevel 1 (
    echo ERROR: Failed to start package database container.
    docker network rm "%PACK_NET%" >nul 2>&1
    pause
    exit /b 1
)

echo Waiting for package database...
set "DB_READY=0"
for /L %%I in (1,1,60) do (
    docker exec "%PACK_DB%" pg_isready -U %PACK_DB_USER% -d %PACK_DB_NAME% >nul 2>&1
    if not errorlevel 1 (
        set "DB_READY=1"
        goto :db_ready
    )
    timeout /t 2 /nobreak >nul
)
:db_ready
if "!DB_READY!"=="0" (
    echo ERROR: Package database did not become ready.
    docker logs "%PACK_DB%"
    docker rm -f "%PACK_DB%" >nul 2>&1
    docker network rm "%PACK_NET%" >nul 2>&1
    pause
    exit /b 1
)

rem Image ENTRYPOINT: wait DB → create_all → alembic upgrade head → then run CMD
docker run --rm --network "%PACK_NET%" ^
  -e DATABASE_URL=postgresql://%PACK_DB_USER%:%PACK_DB_PASSWORD%@%PACK_DB%:5432/%PACK_DB_NAME% ^
  satlife-backend:latest ^
  python -c "print('Package migrate OK')"
if errorlevel 1 (
    echo ERROR: alembic upgrade head failed during packaging.
    docker rm -f "%PACK_DB%" >nul 2>&1
    docker network rm "%PACK_NET%" >nul 2>&1
    pause
    exit /b 1
)

echo Cleaning up package DB...
docker rm -f "%PACK_DB%" >nul 2>&1
docker network rm "%PACK_NET%" >nul 2>&1

echo.
echo [3/5] Preparing %OUT_DIR%\ ...
if exist "%OUT_DIR%" (
    echo Removing previous package folder...
    rmdir /S /Q "%OUT_DIR%" 2>nul
)
mkdir "%OUT_DIR%" 2>nul
mkdir "%OUT_DIR%\images" 2>nul

echo.
echo [4/5] Saving images to %OUT_DIR%\images\%TAR_NAME% ...
echo This may take several minutes...
docker save -o "%OUT_DIR%\images\%TAR_NAME%" ^
  satlife-db:latest ^
  satlife-backend:latest ^
  satlife-frontend:latest
if errorlevel 1 (
    echo ERROR: docker save failed.
    pause
    exit /b 1
)

echo.
echo [5/5] Copying client files into %OUT_DIR%\ ...
copy /Y "%COMPOSE_PROD%" "%OUT_DIR%\docker-compose.prod.yml" >nul
copy /Y "start.bat" "%OUT_DIR%\start.bat" >nul
copy /Y "stop.bat" "%OUT_DIR%\stop.bat" >nul
copy /Y "update.bat" "%OUT_DIR%\update.bat" >nul
copy /Y "uninstall.bat" "%OUT_DIR%\uninstall.bat" >nul
copy /Y "export-db-volume.bat" "%OUT_DIR%\export-db-volume.bat" >nul
copy /Y "import-db-volume.bat" "%OUT_DIR%\import-db-volume.bat" >nul
copy /Y ".env.example" "%OUT_DIR%\.env.example" >nul
rem Client gets a ready .env from the example (not your local secrets)
copy /Y ".env.example" "%OUT_DIR%\.env" >nul

(
echo PLCM / SatLife — offline client package
echo ========================================
echo.
echo Contents:
echo   images\%TAR_NAME%     Prebuilt Docker images
echo   docker-compose.prod.yml
echo   .env / .env.example
echo   start.bat / stop.bat / update.bat / uninstall.bat
echo   export-db-volume.bat / import-db-volume.bat
echo.
echo On the CLIENT PC (Docker required, internet NOT required^):
echo   1. Copy this entire folder anywhere on the machine
echo   2. Edit .env if you need different passwords / secrets
echo   3. Double-click start.bat
echo.
echo App URLs after start:
echo   Frontend:  http://localhost:3000
echo   API docs:  http://localhost:8000/docs
echo   LAN:       http://^<this-pc-ip^>:3000
echo.
echo Database volume backup:
echo   export-db-volume.bat   Snapshot satlife_pgdata into backups\
echo   import-db-volume.bat   Restore latest ^(or given^) backup into the volume
echo.
echo Notes:
echo   - start.bat loads images only if missing, then runs compose with --pull never
echo   - Backend applies Alembic migrations automatically on every start
echo   - No source code or /db folder is required on the client
echo   - To update later: replace images\%TAR_NAME% and run update.bat
echo   - Export/import use the satlife-db image ^(no extra Alpine pull needed^)
) > "%OUT_DIR%\README.txt"

echo.
echo ===========================================
echo Package ready:
echo   %cd%\%OUT_DIR%\
echo.
for %%A in ("%OUT_DIR%\images\%TAR_NAME%") do echo Tar size: %%~zA bytes
echo.
echo Copy the whole "%OUT_DIR%" folder to the client PC,
echo then run start.bat there.
echo ===========================================
pause
endlocal
