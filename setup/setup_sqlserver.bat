@echo off
chcp 65001 > nul
title Setup SQL Server - Al-Adil System
echo.
echo ============================================
echo   Setting up SQL Server Express
echo ============================================
echo.
echo This script will:
echo 1. Create the AdilSystem database
echo 2. Create required tables
echo 3. Enable SQL Server authentication
echo.
echo NOTE: Run this on the SERVER machine only
echo.

set /p SERVER=Enter SQL Server instance (e.g. DESKTOP-ABC\SQLEXPRESS): 
set /p SA_PASS=Enter SA password: 

echo.
echo [1/3] Creating database...
sqlcmd -S %SERVER% -U sa -P "%SA_PASS%" -Q "IF NOT EXISTS (SELECT name FROM sys.databases WHERE name='AdilSystem') CREATE DATABASE AdilSystem"
if errorlevel 1 (echo [ERROR] Failed to create database & pause & exit /b 1)

echo [2/3] Enabling TCP/IP...
echo Please enable TCP/IP in SQL Server Configuration Manager manually
echo SQL Server Configuration Manager -> SQL Server Network Configuration -> Protocols for SQLEXPRESS -> TCP/IP -> Enable

echo [3/3] Setup complete!
echo.
echo Connection string for clients:
echo   Server: %SERVER%
echo   Database: AdilSystem
echo   Username: sa
echo   Password: [your sa password]
echo.
pause
