@echo off
chcp 65001 > nul
title Adil System

echo.
echo  ============================================
echo   Al-Adil Installment Distribution System
echo  ============================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

rem لا تشغل نسخة ثانية إذا كان الخادم يعمل بالفعل على المنفذ 8765
set "ADIL_PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do set "ADIL_PORT_PID=%%P"
if defined ADIL_PORT_PID (
    echo [INFO] Adil System is already running on port 8765 (PID %ADIL_PORT_PID%).
    start "" "http://localhost:8765/app"
    exit /b 0
)

echo [1/2] Installing requirements...
python -m pip install fastapi uvicorn pandas openpyxl xlrd cryptography python-multipart aiofiles pyodbc --quiet --no-warn-script-location

if errorlevel 1 (
    echo [ERROR] Failed to install requirements
    echo Try running as Administrator
    pause
    exit /b 1
)

echo [2/2] Starting server...
echo.
echo  Open browser: http://localhost:8765
echo  Admin panel:  http://localhost:8765/admin
echo.
python app.py
pause
