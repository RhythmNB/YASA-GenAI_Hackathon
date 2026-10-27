@echo off
REM Manual refresh of every city (the agent also refreshes a city by itself when its data is over an hour old).
REM Output is also saved to refresh_log.txt
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python ingest_weather.py > refresh_log.txt 2>&1
type refresh_log.txt
echo.
echo Done. Press any key to close.
pause >nul
