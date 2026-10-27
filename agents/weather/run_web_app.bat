@echo off
REM Starts the Weather Visit Planner web app at http://127.0.0.1:8766 (close this window to stop it)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python web_app.py
pause
