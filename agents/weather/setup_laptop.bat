@echo off
REM Laptop setup: no Docker or Zetaris needed. Uses the offline copy of the weather,
REM which the agent refreshes live from the National Weather Service when it is over an hour old.
REM Output is also saved to setup_log.txt
cd /d "%~dp0"
call :main > setup_log.txt 2>&1
type setup_log.txt
echo.
echo Done. Press any key to close.
pause >nul
exit /b

:main
echo === %date% %time% ===
set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (echo [FAIL] Python not found. Install Python 3.11+ from python.org and tick "Add to PATH". & exit /b 1)

echo --- Python environment ---
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check --timeout 30 -r requirements.txt || (echo [FAIL] pip install failed & exit /b 1)

echo --- Settings (.env) ---
if not exist .env (
  copy .env.example .env >nul
  powershell -NoProfile -Command "(Get-Content .env) -replace '^WEATHER_MODE=.*','WEATHER_MODE=sample' -replace '^LLM_MODE=.*','LLM_MODE=sample' | Set-Content .env"
  echo WEATHER_REFRESH_POSTGRES=0>> .env
  echo Created .env: offline weather, no AI model. Set LLM_MODE=nightshift once Nightshift is installed.
) else (
  echo .env already exists, left unchanged.
)

echo --- Downloading weather for all cities (first run about 1-2 minutes) ---
python ingest_weather.py --skip-postgres || (echo [FAIL] download failed, check your internet & exit /b 1)

echo --- Tests ---
python -m pytest -q tests
echo [OK] laptop setup finished. Double-click run_web_app.bat to open the chat page.
exit /b 0
