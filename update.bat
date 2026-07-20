@echo off
title PLCM System - Update

echo Stopping existing containers...
docker compose down

echo.
echo Loading updated images...
docker load -i images\satlife-complete.tar

echo.
echo Starting updated containers...
docker compose up -d

echo.
echo Update completed successfully.

pause