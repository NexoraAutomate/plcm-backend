@echo off
title PLCM System - Uninstall

echo Stopping containers...
docker compose down

echo.
echo Removing images...

docker image rm satlife-db:latest
docker image rm satlife-backend:latest
docker image rm satlife-frontend:latest

echo.
echo PLCM System has been removed.

pause