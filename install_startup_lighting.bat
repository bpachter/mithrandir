@echo off
:: ============================================================
:: install_startup_lighting.bat
:: Registers Mithrandir idle lighting as a Windows logon task.
:: RIGHT-CLICK -> "Run as administrator" to install.
:: ============================================================

set TASK_NAME=Mithrandir Startup Lighting
set PYTHON=C:\Python312\pythonw.exe
set SCRIPT=%~dp0startup_lighting.py

echo.
echo Registering Task: "%TASK_NAME%"
echo Python  : %PYTHON%
echo Script  : %SCRIPT%
echo.

schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

schtasks /Create ^
  /TN "%TASK_NAME%" ^
  /TR "\"%PYTHON%\" \"%SCRIPT%\"" ^
  /SC ONLOGON ^
  /DELAY 0000:30 ^
  /RL HIGHEST ^
  /F

if %ERRORLEVEL% == 0 (
    echo.
    echo SUCCESS!  Mithrandir lighting will auto-start 15 seconds after logon.
    echo.
    echo To run it right now without rebooting:
    echo   schtasks /Run /TN "Mithrandir Startup Lighting"
) else (
    echo.
    echo FAILED.  Make sure you right-clicked and chose "Run as administrator".
)

pause
