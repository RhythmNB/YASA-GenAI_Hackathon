@echo off
REM Runs the Weather agent through the demo Planner + Evaluator. Output also saved to agent_demo_log.txt
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python demo_planner.py --city NYC --household dad --remember "Dad is 85 and gets tired walking more than 20 minutes" > agent_demo_log.txt 2>&1
type agent_demo_log.txt
echo.
echo Done. Press any key to close.
pause >nul
