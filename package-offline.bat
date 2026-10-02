@echo off
title PLCM - Package offline deploy folder
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem Output folder inside the backend repo — copy this whole folder to the client PC
set "OUT_DIR=offline-package"
set "COMPOSE_BUILD=docker-compose.yml"
set "COMPOSE_PROD=docker-compose.prod.yml"
set "TAR_NAME=satlife-complete.tar"

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

echo [1/4] Building images (satlife-db / satlife-backend / satlife-frontend)...
docker compose -f "%COMPOSE_BUILD%" --env-file .env build
if errorlevel 1 (
    echo ERROR: docker compose build failed.
    pause
    exit /b 1
)

echo.
echo [2/4] Preparing %OUT_DIR%\ ...
if exist "%OUT_DIR%" (
    echo Removing previous package folder...
    rmdir /S /Q "%OUT_DIR%" 2>nul
)
mkdir "%OUT_DIR%" 2>nul
mkdir "%OUT_DIR%\images" 2>nul

echo.
echo [3/4] Saving images to %OUT_DIR%\images\%TAR_NAME% ...
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
echo [4/4] Copying client files into %OUT_DIR%\ ...
copy /Y "%COMPOSE_PROD%" "%OUT_DIR%\docker-compose.prod.yml" >nul
copy /Y "start.bat" "%OUT_DIR%\start.bat" >nul
copy /Y "stop.bat" "%OUT_DIR%\stop.bat" >nul
copy /Y "update.bat" "%OUT_DIR%\update.bat" >nul
copy /Y "uninstall.bat" "%OUT_DIR%\uninstall.bat" >nul
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
echo Notes:
echo   - start.bat loads images then runs compose with --pull never
echo   - No source code or /db folder is required on the client
echo   - To update later: replace images\%TAR_NAME% and run update.bat
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
