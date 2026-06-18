@echo off
REM Komment Qiroli — web-panelni venv ichida ishga tushiradi
cd /d "%~dp0"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
