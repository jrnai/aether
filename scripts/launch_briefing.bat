@echo off
title Aether - Morning Briefing
cd /d "%~dp0\.."

:: Check if local Ollama is reachable, attempt background start if needed
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama not detected. Starting local Ollama service...
    start /b "" ollama serve >nul 2>&1
    timeout /t 3 /nobreak >nul
)

:: Run Aether once-per-day startup briefing
".venv\Scripts\python.exe" -m src.daemon.main --on-startup

if errorlevel 1 (
    echo.
    echo [!] Aether startup briefing exited with an error.
    pause
)
