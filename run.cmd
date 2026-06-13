@echo off
REM Finter — one-shot launcher for Windows.
REM Installs deps (first run), builds the instrument cache, starts the server.

setlocal
cd /d "%~dp0"

echo [Finter] Installing dependencies...
python -m pip install -r requirements.txt || goto :err

echo [Finter] Building instrument data (uses live prices if online)...
python -m backend.build_instruments

echo [Finter] Starting server at http://localhost:8000
python -m uvicorn backend.app:app --port 8000
goto :eof

:err
echo [Finter] Setup failed. Is Python on your PATH?
exit /b 1
