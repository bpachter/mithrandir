@echo off
echo Starting Enkidu Phase 7 UI...

:: Start FastAPI backend
:: --reload is intentionally OFF: the server writes server.log, test_tts.wav and
:: touches voices/ during TTS which would trigger watchfiles restarts mid-stream,
:: killing in-flight WebSocket TTS chunks before the browser plays them.
:: (The /api/test-audio path still works under --reload because it's a single
:: fast HTTP response, which is why that one was hearable and chat TTS wasn't.)
start "Enkidu Backend" cmd /k "cd /d %~dp0server && python -m uvicorn main:app --host 0.0.0.0 --port 8000"

:: Brief pause to let backend initialize
timeout /t 2 /nobreak >nul

:: Start Vite dev server
start "Enkidu Frontend" cmd /k "cd /d %~dp0client && npm run dev"

echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo Both servers running. Close their windows to stop.
