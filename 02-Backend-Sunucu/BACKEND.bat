@echo off
title MEB AI BACKEND - KAPATMA
cd /d "%~dp0"
venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001
pause
