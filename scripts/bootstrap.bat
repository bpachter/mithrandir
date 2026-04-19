@echo off
:: Enkidu guided setup script for Windows
:: Run this ONCE before first launch on a fresh machine.
:: Usage: scripts\bootstrap.bat [--check] [--yes] [--skip-ollama]

setlocal

:: Move to project root
cd /d "%~dp0.."

echo.
echo   =============================================
echo    Enkidu Bootstrap — First-Time Setup
echo   =============================================
echo.

:: Check Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Python not found on PATH.
    echo   Install Python 3.11+ from https://python.org/downloads
    echo   Then re-run this script.
    echo.
    pause
    exit /b 1
)

:: Run the Python bootstrap, forwarding arguments
python scripts\bootstrap.py %*

echo.
pause
