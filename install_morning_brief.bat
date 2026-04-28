@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  install_morning_brief.bat
REM  Registers Mithrandir's daily 7am macro brief with Windows Task Scheduler.
REM  Run once as administrator (or accept the UAC prompt).
REM  Re-running is safe — it deletes and recreates the task.
REM ─────────────────────────────────────────────────────────────────────────────

SET TASK_NAME=MithrandirMorningBrief
SET PYTHON=C:\Users\benpa\OneDrive\Desktop\Mithrandir\.venv\Scripts\python.exe
SET SCRIPT=C:\Users\benpa\OneDrive\Desktop\Mithrandir\phase5-intelligence\morning_brief.py
SET LOG_DIR=C:\Users\benpa\OneDrive\Desktop\Mithrandir\logs

REM Create log directory if it doesn't exist
IF NOT EXIST "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Remove any existing task with this name (ignore errors)
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM Create the new daily 7:00 AM task
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\" >> \"%LOG_DIR%\morning_brief.log\" 2>&1" ^
  /sc daily ^
  /st 07:00 ^
  /ru "%USERNAME%" ^
  /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo  [OK] Morning brief scheduled at 7:00 AM daily.
    echo       Task name : %TASK_NAME%
    echo       Script    : %SCRIPT%
    echo       Log       : %LOG_DIR%\morning_brief.log
    echo.
    echo  To test immediately, run:
    echo    "%PYTHON%" "%SCRIPT%"
    echo.
) ELSE (
    echo  [ERROR] Failed to create scheduled task. Try running as Administrator.
)

pause
