@echo off
REM Full setup on the machine running Zetaris: start weather Postgres, install deps, fetch weather.
REM Output is also saved to setup_log.txt in this folder.
cd /d "%~dp0"
call :main > setup_log.txt 2>&1
type setup_log.txt
echo.
echo Done. Press any key to close.
pause >nul
exit /b

:main
echo === %date% %time% ===
where docker >nul 2>&1 || (echo [FAIL] Docker not found. Start Docker Desktop, or use setup_laptop.bat instead. & exit /b 1)
docker info >nul 2>&1 || (echo [FAIL] Docker Desktop is not running. & exit /b 1)

docker network inspect zetaris_default >nul 2>&1 || (
  echo [FAIL] Zetaris network not found. Start Zetaris first:
  echo        cd ..\zetaris-platform ^&^& docker compose up -d
  exit /b 1
)

echo --- Starting weather-db ---
docker compose up -d || (echo [FAIL] docker compose failed & exit /b 1)

set PY=
where py >nul 2>&1 && set PY=py -3
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (echo [FAIL] Python not found & exit /b 1)

echo --- Python environment ---
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check --timeout 30 -r requirements.txt || (echo [FAIL] pip install failed & exit /b 1)

echo --- Waiting for Postgres ---
for /l %%i in (1,1,30) do (
  docker exec weather-db pg_isready -q && goto :ready
  timeout /t 2 >nul
)
echo [FAIL] weather-db did not become ready & exit /b 1
:ready

echo --- Fetching NWS weather ---
python ingest_weather.py || (echo [FAIL] ingest failed & exit /b 1)

echo --- Tests ---
python -m pytest -q tests
echo [OK] setup finished
exit /b 0
