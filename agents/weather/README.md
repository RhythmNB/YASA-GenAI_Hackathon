# Weather service (217 US cities)

## Quick start on a laptop (no Docker or Zetaris)

Double-click `setup_laptop.bat`, then `run_web_app.bat`. This uses the offline copy of the weather
(`sample_data/weather_sample.db`); the agent refreshes a city live from NWS whenever its data is
more than an hour old. Set `LLM_MODE=nightshift` in `.env` once Nightshift is installed.


Pulls National Weather Service forecasts and active alerts for 217 US cities (the 50 largest
plus at least the 4 largest in every state, and DC, listed in `cities.py`),
stores them in Postgres, and exposes them to the agents **through Zetaris**. A SQLite
snapshot of the same tables powers sample mode, so judges can run it with no credentials.

```
api.weather.gov ──> ingest_weather.py ──> Postgres (weather-db) ──> Zetaris ──> weather_tool.py ──> Weather agent
                                     └──> sample_data/weather_sample.db (sample mode)
```

## 1. Install

```bash
cd agents/weather
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set NWS_USER_AGENT to your real email
```

## 2. Start Postgres

```bash
docker compose up -d   # Zetaris must already be running
```

Tables are created automatically from `schema.sql`. Postgres listens on host port **5433**
so it won't clash with anything else you have running.

## 3. Fetch weather

```bash
python ingest_weather.py
```

This writes forecasts, alerts and a `cities` table (state, county FIPS, NWS zones) to Postgres
and refreshes the sample DB. The first run takes a few minutes (it looks up every city once and
caches it in `sample_data/nws_points_cache.json`); later runs take about a minute.
Run it on a schedule (e.g. every 2 hours) during the demo window; NWS forecasts update often.

## 4. Register Postgres in Zetaris

Start Zetaris first (`cd ../zetaris-platform && docker compose up -d`). The weather database
joins Zetaris's Docker network, so Zetaris reaches it by container name.

In the Zetaris UI at http://localhost:3000, add a new **PostgreSQL** data source:

| Field    | Value |
|----------|-------|
| Name     | `weather_pg` |
| Host     | `weather-db` |
| Port     | `5432` |
| Database | `weather` |
| User / password | values from your `.env` |

Check it in the Zetaris SQL Editor:

```sql
SELECT city, period_name, temperature_f, precip_chance FROM weather_pg.forecast_periods
WHERE city = 'Chicago, IL';
```

If Zetaris shows the table under a different name (e.g. `weather_pg.public.forecast_periods`),
copy that exact name into `ZETARIS_FORECAST_TABLE` and `ZETARIS_ALERTS_TABLE` in `.env`.

## 5. Query through Zetaris

`.env.example` already points `ZETARIS_JDBC_JAR` at the jar in `../zetaris-platform/jdbc/`.
Install Java 11+ if you don't have it (JayDeBeApi needs it), set your Zetaris password in `.env`, then:

```bash
WEATHER_MODE=zetaris python weather_tool.py "Chicago, IL" 3
```

## Sample mode (no credentials)

```bash
python ingest_weather.py --skip-postgres   # only needs internet
WEATHER_MODE=sample python weather_tool.py
```

Commit `sample_data/weather_sample.db` so judges get a working snapshot.

## Tests

```bash
python -m pytest -q tests
```

## Using it from the agent

`weather_tool.TOOL_SPEC` is a JSON tool schema; register it with your agent framework and call
`get_weather_briefing(city, days)`. Each briefing returns flagged forecast periods, official
alerts, good outdoor windows, data age, and the exact SQL it ran (for your traces).

Official NWS alerts (e.g. Heat Advisory) should always outrank the simple heat/cold/rain
thresholds in the tool.

## Weather agent (Meterless)

`weather_agent.py` is the Weather agent from the visit-planner architecture. It:

1. reads household context from **H-MEM** (`hmem.py`, Meterless engine: tiered store + retrieval),
2. queries weather **through Zetaris** with `weather_tool.py`,
3. asks the model through **Meterless Nightshift** (`llm.py`, the one shared generator) for a summary and advice,
4. checks the model's text against the data and retries once, falling back to a deterministic summary,
5. writes forecast facts back to H-MEM, and
6. returns a hand-off message for the Planner (format in `HANDOFF.md`).

`demo_planner.py` is a stand-in Planner + Evaluator that shows the loop: the Evaluator checks the
hand-off and sends it back with feedback if anything is unsupported.

```bash
python demo_planner.py --city "Boston, MA" --household dad --remember "Dad is 85 and uses a walking frame"
```

Every step is logged as JSONL in `logs/` (memory lookups, Zetaris queries, model calls with the model
name, self-checks, hand-offs, evaluator verdicts). Memory lives in `memory/`.

Set `LLM_MODE=nightshift` plus the `NIGHTSHIFT_*` values in `.env` to use Nightshift;
`LLM_MODE=sample` runs without any model.

## Web app

`web_app.py` serves a chat page at http://127.0.0.1:8766 (only on this computer). Ask things like
"Visiting Dad in NYC this weekend"; say "remember Dad is 85 and uses a walking frame" to save a
household fact to H-MEM. Each answer shows the summary, good outdoor windows, risks, advice, the
Evaluator verdict, data freshness, the forecast rows and Zetaris queries it used, and the model.

On Windows double-click `run_web_app.bat`, or run `python web_app.py`.

## For the team app

Other agents and front ends call `POST /api/weather` (JSON in, hand-off out) on
`python web_app.py --no-browser`. See `INTEGRATION.md`.

## Weather risk evaluation

`risk.py` gives every forecast period a level (low / moderate / high) from fixed rules: heat, cold,
rain chance, wind, storm or snow wording and official NWS alerts. The overall level is the worst
period in the days asked about. Healthy-adult thresholds are used unless the user states a
sensitive traveller (older adult, infant, young child, pregnant, health condition). Thresholds are
listed in `HANDOFF.md`.

## Outcome review

`critic.py` is a second evaluation of the agent's finished answer (does the advice address every
risk, fit the risk level and the stated travellers, avoid medical advice; plus a confidence
rating). With Nightshift on, the model also reviews the answer as a critic. If the review fails,
the agent revises once and is reviewed again. See `HANDOFF.md`.

## Live refresh

Before answering, the agent checks how old the city's data is. If it is older than
`WEATHER_MAX_AGE_HOURS` (default 1), it re-downloads just that city from NWS (about a second),
stores it, and reads it again (through Zetaris in `zetaris` mode). If NWS cannot be reached it
answers from the stored data and flags its age.
