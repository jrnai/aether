#!/usr/bin/env bash
# Project Aether - Desktop Application Launcher for Linux / macOS / WSL
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "====================================================================="
echo "  AETHER - Standalone Desktop Intelligence Application"
echo "====================================================================="
echo

# 1. Resolve Python in virtual environment
PYTHON_BIN=""
if [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON_BIN=".venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "[ERROR] Python virtual environment not found at .venv/bin/python."
    echo "Please create it first by running:"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate && pip install -e ."
    exit 1
fi

# 2. Check local Ollama daemon
if curl -s -f http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "[OK] Local Ollama service is active."
else
    echo "[!] Local Ollama service not detected on port 11434."
    if command -v ollama >/dev/null 2>&1; then
        echo "[*] Starting local Ollama service in background..."
        ollama serve >/dev/null 2>&1 &
        sleep 2
    else
        echo "[WARN] Ollama command not found in PATH. Ensure Ollama is running if using local LLMs."
    fi
fi

# 3. Check Google Calendar credentials if present
if [ -f "credentials.json" ]; then
    if ! "$PYTHON_BIN" -c "from src.servers.google_calendar_client import GoogleCalendarManager; mgr = GoogleCalendarManager(); exit(0 if mgr.is_logged_in() else 1)" >/dev/null 2>&1; then
        echo "[!] Google Calendar authorization is expired or disconnected."
        echo "[*] Launching browser to re-authenticate Google Calendar..."
        "$PYTHON_BIN" -m src.tools.login_google_calendar || true
    fi
fi

# 4. Launch Aether portal server
echo "[*] Starting Aether backend service..."
echo "[*] Keep this terminal open while using Aether. Press Ctrl+C to stop."
echo

exec "$PYTHON_BIN" main.py --portal --open "$@"
