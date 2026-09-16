@echo off
setlocal EnableDelayedExpansion
title Aether Console - Desktop Automation Backend
cd /d "%~dp0"

echo =====================================================================
echo   AETHER - Standalone Desktop Intelligence Application
echo =====================================================================
echo.

:: Detect Edge or Chrome executable for Standalone Desktop App Mode
set "APP_EXE="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "APP_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined APP_EXE if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "APP_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined APP_EXE if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "APP_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined APP_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "APP_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined APP_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "APP_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

:: 1. Verify virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe.
    echo Please create it first by running:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -e .
    echo.
    pause
    exit /b 1
)

:: 2. Check if local Ollama daemon is running, attempt background start if needed
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [!] Local Ollama service not detected on port 11434.
    echo [*] Starting local Ollama service in background...
    start /b "" ollama serve >nul 2>&1
    timeout /t 2 /nobreak >nul
) else (
    echo [OK] Local Ollama service is active.
)

:: 3. Ensure port 8000 is clean (only invoke PowerShell if port is actually occupied)
netstat -ano | findstr :8000 | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
    powershell -NoProfile -Command "try { Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } } catch {}; exit 0" >nul 2>&1
)


:: 4. Launch Aether backend and native desktop app window
echo [*] Starting Aether backend service...
echo [*] Launching native Desktop App Window...
echo [*] Keep this window open while using Aether. Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" main.py --portal --open %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo =====================================================================
if not "%EXIT_CODE%"=="0" (
    echo   [!] Aether encountered an unexpected error or exit (code %EXIT_CODE%).
    echo   Keep this console window open to review the error message above.
    echo =====================================================================
    pause
    exit /b %EXIT_CODE%
) else (
    echo   Aether desktop application has closed normally.
    echo =====================================================================
    exit 0
)
