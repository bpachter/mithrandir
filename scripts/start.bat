@echo off
:: Enkidu one-command launcher
:: Usage: scripts\start.bat [--no-browser] [--backend-only] [--port 8080]
::
:: This batch file is a thin wrapper around scripts/start.py.
:: It ensures the .env is loaded and Python is on PATH before launching.

setlocal

:: Move to project root so relative paths work
cd /d "%~dp0.."

:: Check Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   ERROR: Python not found on PATH.
    echo   Install Python 3.11+ from https://python.org/downloads
    echo.
    pause
    exit /b 1
)

:: Run the Python launcher, passing through any arguments
python scripts\start.py %*
