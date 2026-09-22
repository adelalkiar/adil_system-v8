@echo off
chcp 65001 > nul
cd /d "%~dp0\.."
title Al-Adil System - Install Requirements
echo.
echo ============================================
echo   Al-Adil System - Installing Requirements
echo ============================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Download from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH"
    pause & exit /b 1
)

echo [1/3] Installing Python packages...
python -m pip install fastapi uvicorn pandas openpyxl cryptography python-multipart aiofiles pyodbc --quiet --no-warn-script-location

echo [2/3] Checking ODBC Drivers...
python -c "import pyodbc; d=[x for x in pyodbc.drivers() if 'SQL Server' in x]; print('Found SQL Drivers:',d) if d else print('WARNING: No SQL Server ODBC Driver!')"

echo [3/3] Checking for missing ODBC Driver...
python -c "
import pyodbc
drivers = [d for d in pyodbc.drivers() if 'SQL Server' in d]
if not drivers:
    print()
    print('========================================')
    print('  ODBC Driver NOT found!')
    print('  Download ODBC Driver 18 from:')
    print('  https://aka.ms/downloadmsodbcsql')
    print('========================================')
else:
    print('OK - Using:', drivers[0])
"

echo.
echo Done! You can now run install_and_run.py
echo.
pause
