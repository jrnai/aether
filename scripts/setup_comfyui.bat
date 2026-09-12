@echo off
title Setup ComfyUI for Project Aether
echo Starting ComfyUI + SDXL-Turbo Setup...
powershell -ExecutionPolicy Bypass -File "%~dp0setup_comfyui.ps1" %*
pause
