@echo off
:: Install the daily QV pipeline refresh as a Windows Scheduled Task.
:: Runs at 6:30 PM weekdays (after US market close).
:: Requires elevated (Administrator) prompt.

set TASK_NAME=Mithrandir QV Daily Refresh
set SCRIPT=%~dp0phase2-tool-use\quant-value\daily_refresh.py
set PYTHON=C:\Users\benpa\AppData\Local\Programs\Python\Python312\pythonw.exe

:: Fall back to system Python if above path doesn't exist
if not exist "%PYTHON%" set PYTHON=pythonw.exe

echo Installing scheduled task: "%TASK_NAME%"
echo Script : %SCRIPT%
echo Python : %PYTHON%
echo Schedule: Mon-Fri at 18:30

schtasks /Create /TN "%TASK_NAME%" ^
  /TR "\"%PYTHON%\" \"%SCRIPT%\"" ^
  /SC WEEKLY ^
  /D MON,TUE,WED,THU,FRI ^
  /ST 18:30 ^
  /RL HIGHEST ^
  /F

if %ERRORLEVEL% == 0 (
    echo.
    echo SUCCESS: Task scheduled. First run: next weekday at 18:30.
    echo To run immediately: schtasks /Run /TN "%TASK_NAME%"
    echo To view logs: check output directory in QV config settings.json
) else (
    echo.
    echo FAILED. Run this script as Administrator.
)
pause
