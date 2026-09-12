@echo off
title Register Aether Morning Briefing Task
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_scheduled_briefing.ps1" %*
pause
