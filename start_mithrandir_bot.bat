@echo off
title Mithrandir Telegram Bot
set "ROOT=%~dp0"
cd /d "%ROOT%phase3-agents"
if exist "%ROOT%.venv\Scripts\python.exe" (
	"%ROOT%.venv\Scripts\python.exe" telegram_interface.py
) else (
	python telegram_interface.py
)
pause
