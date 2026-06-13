#!/usr/bin/env bash
# Finter — one-shot launcher for Linux/macOS.
# Creates a venv on first run, installs deps, builds the instrument cache, starts the server.

set -e
cd "$(dirname "$0")"

VENV=".venv"

if [ ! -d "$VENV" ]; then
    echo "[Finter] Creating virtual environment..."
    python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

echo "[Finter] Installing dependencies..."
pip install -r requirements.txt

echo "[Finter] Building instrument data (uses live prices if online)..."
python -m backend.build_instruments

echo "[Finter] Starting server at http://localhost:8000"
python -m uvicorn backend.app:app --port 8000
