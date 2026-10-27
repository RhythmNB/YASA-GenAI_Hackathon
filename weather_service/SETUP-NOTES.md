# Setup notes for this machine (Windows, 2026-10-27)

What `INTEGRATION.md` and `setup_laptop.bat` do, as run here, and the two
local settings that differ from the defaults.

## What was done

- Copied `weather_service.zip` into the hackathon repo next to `wastewater/`
  and `visit-planner-handoff/`. The folder's own `.gitignore` keeps `.env`,
  `.venv/`, `logs/` and `memory/` out of git.
- Ran the `setup_laptop.bat` steps by hand (the script ends with `pause`, which
  blocks a non-interactive shell): `.venv` created, requirements installed,
  `.env` created from `.env.example`, weather downloaded from NWS for all 217
  cities (3038 forecast periods, 21 alerts, 18 s), and `python -m pytest -q tests`
  passed 43 of 43.
- Verified `weather_api(...)` in-process in sample mode for Boston, Richmond
  and free text ("richmond virginia"), and in Nightshift mode for Richmond
  with stated travellers: model-written summary and advice, outcome review
  `pass`, about 65 s per call.

## Settings that differ from the defaults (`.env`)

| Key | Value here | Why |
|---|---|---|
| `WEATHER_PORT` | `8770` | 8766 is taken on this machine by the wastewater preview server. `web_app.py` reads this, so `run_web_app.bat` also lands on 8770. |
| `LLM_MODE` | `nightshift` | Nightshift is installed here. Set back to `sample` for a run with no model (what judges use). |
| `NIGHTSHIFT_MODEL` | `nvidia/nemotron-3.5-lightning-30b-a3b` | The default `meterless/fast`, like `meterless/auto` and `meterless/cheap`, currently returns HTTP 502 (the NVIDIA function behind those aliases no longer exists for the account). Naming the model directly works; `check_nightshift.py` passes with it. |
| `WEATHER_MODE` | `sample` | Reads the offline SQLite copy, refreshed live from NWS when older than an hour. The Zetaris path needs the `weather_pg` tables registered first (see "Known gaps" in INTEGRATION.md). |
| `WEATHER_REFRESH_POSTGRES` | `0` | No local Postgres for the weather data on this machine. |
| `NWS_USER_AGENT` | unchanged placeholder | NWS asks for an app name and contact email; put a team contact address in before the demo. |

`NIGHTSHIFT_API_KEY` is empty on purpose: the service reads the token from the
Nightshift runtime's own file.

## Running it

From the repo root, the Claude preview config `weather-service` starts it
(`.claude/launch.json`), or from this folder:

```bat
.venv\Scripts\python web_app.py --no-browser
```

Then `http://127.0.0.1:8770/` is the built-in page and `POST /api/weather`
the call for the planner, as described in `INTEGRATION.md`.
