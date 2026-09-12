@echo off
title Aether ComfyUI Local Server (RTX 5060)
set COMFY_DIR=%USERPROFILE%\ComfyUI

if not exist "%COMFY_DIR%\main.py" (
    echo [ERROR] ComfyUI was not found in %COMFY_DIR%.
    echo Please run scripts\setup_comfyui.bat first to set up ComfyUI.
    pause
    exit /b 1
)

echo =======================================================
echo Starting ComfyUI for Project Aether on port 8188...
echo Active GPU: NVIDIA GeForce RTX 5060
echo URL: http://127.0.0.1:8188
echo =======================================================

cd /d "%COMFY_DIR%"

if exist "%~dp0..\.venv\Scripts\python.exe" (
    "%~dp0..\.venv\Scripts\python.exe" main.py --listen 127.0.0.1 --port 8188
) else (
    python main.py --listen 127.0.0.1 --port 8188
)
pause
