# Setup notes for this machine (Windows, 2026-10-27)

What `INTEGRATION.md` and `setup_laptop.bat` do, as run here, and the two
local settings that differ from the defaults.

## What was done

- Copied `agents/weather.zip` into the hackathon repo next to `wastewater/`
  and `agents/pertussis_guidance/`. The folder's own `.gitignore` keeps `.env`,
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
| `SAMPLE_DB` | absolute path to `agents/weather/sample_data/weather_sample.db` | The example's relative path resolves against the working directory, so launching `web_app.py` from the repo root (as `.claude/launch.json` does) created a second, empty database at the repo root. |
| `NWS_USER_AGENT` | unchanged placeholder | NWS asks for an app name and contact email; put a team contact address in before the demo. |

`NIGHTSHIFT_API_KEY` is empty on purpose: the service reads the token from the
Nightshift runtime's own file.

## One code change (2026-10-27)

`llm.py` now passes `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`
on every Nightshift call. Without it the Nemotron routes reason at length before
answering: the critic's 33-character verdict took 17 to 79 s, a full run 50 to
215 s, and the planner's 180 s limit was often exceeded. With it the same
Richmond run takes 5 to 25 s (the upper end when the critic asks for one
revision). Prompts, rules and the review are unchanged; the 43 tests pass.

## Running it

From the repo root, the Claude preview config `weather-service` starts it
(`.claude/launch.json`), or from this folder:

```bat
.venv\Scripts\python web_app.py --no-browser
```

Then `http://127.0.0.1:8770/` is the built-in page and `POST /api/weather`
the call for the planner, as described in `INTEGRATION.md`.
