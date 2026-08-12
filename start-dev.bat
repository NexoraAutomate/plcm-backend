@echo off
title PLCM Dev Launcher

echo ========================================
echo   Starting PLCM development stack
echo ========================================
echo.

REM --- 1. PostgreSQL ---
echo [1/3] Starting PostgreSQL...
cd /d C:\Postgresql\pgsql
bin\pg_ctl.exe -D data -l logfile start >nul 2>&1
if errorlevel 1 (
  echo       Already running or failed to start - continuing...
) else (
  echo       PostgreSQL started.
)
echo.

REM --- 2. FastAPI backend (new window) ---
echo [2/3] Starting FastAPI backend...
start "PLCM Backend" cmd /k "cd /d C:\VSCode\plcm\backend\plcm-backend && call .venv\Scripts\activate.bat && echo Backend: http://127.0.0.1:8000 && uvicorn app.main:app --reload"
echo       Window opened.
echo.

REM --- 3. Next.js frontend (new window) ---
echo [3/3] Starting Next.js frontend...
start "PLCM Frontend" cmd /k "cd /d C:\VSCode\plcm\frontend\plcm-frontend && echo Frontend: http://localhost:3000 && npm run dev"
echo       Window opened.
echo.

echo ========================================
echo   Stack is starting up
echo   Backend:  http://127.0.0.1:8000
echo   Frontend: http://localhost:3000
echo ========================================
echo.
echo You can close this launcher window.
echo Close the Backend / Frontend windows to stop those services.
echo.
timeout /t 5 >nul
