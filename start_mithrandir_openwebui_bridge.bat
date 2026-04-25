@echo off
title Mithrandir Open WebUI Bridge
set "ROOT=%~dp0"
cd /d "%ROOT%phase3-agents"
if exist "%ROOT%.venv\Scripts\python.exe" (
	"%ROOT%.venv\Scripts\python.exe" mithrandir_openwebui_bridge.py
) else (
	python mithrandir_openwebui_bridge.py
)
pause
