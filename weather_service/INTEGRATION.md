# Integrating the Weather agent (for the team front end)

Brief for whoever (or whichever coding assistant) is wiring the Weather agent into the team's
app next to the Wastewater and Pertussis agents. Read this first, then `HANDOFF.md` for every field.

## What this service is

`weather_service/` is a self-contained Python agent for the visit planner (Open Agent Hackathon,
Track 3). For a US city (217 supported) and a date range it returns a **weather risk level**
(low / moderate / high) with reasons, low-risk outdoor times, practical advice, official NWS alerts,
and the evidence behind every claim.

Inside one call it:

1. checks the city's stored forecast and **refreshes it live from NWS** if older than 1 hour,
2. reads it through **Zetaris** (or the offline SQLite copy in sample mode),
3. reads household facts from **H-MEM** (Meterless engine, `hmem.py`),
4. computes the risk level with fixed rules (`risk.py`), never by the model,
5. has the model (Meterless **Nightshift**, `llm.py`) write a summary and advice, then fact-checks it,
6. runs an **Outcome Review** (`critic.py`) of the finished answer and revises once if needed,
7. is checked by an **Evaluator** (`demo_planner.py`) that sends it back with feedback if anything is wrong,
8. logs every step as JSONL in `logs/`.

## Setup

```bat
cd weather_service
setup_laptop.bat          :: no Docker/Zetaris needed; downloads weather for all cities, runs tests
```

`.env` controls modes: `LLM_MODE=sample|nightshift`, `WEATHER_MODE=sample|zetaris`. Sample mode needs
no credentials (judges use it). Nightshift must be running for `LLM_MODE=nightshift`.

## Option A (recommended): call it over HTTP

Run the service, which listens on `127.0.0.1:8766` only and sends CORS headers so a front end on
another local port can call it:

```bat
.venv\Scripts\python web_app.py --no-browser            :: or --port 8770
```

| Endpoint | Purpose |
|---|---|
| `POST /api/weather` | Structured call for other agents/front ends (below) |
| `GET /api/cities` | All 217 city ids with state and coordinates (for a picker/autocomplete) |
| `GET /api/status` | `{"mode": "nightshift"|"sample", "cities": 217}` |
| `GET /api/memory` | What H-MEM currently remembers |
| `POST /api/ask` | Free-text chat used by the built-in page (`{"question": "..."}`) |

### `POST /api/weather` request

```json
{
  "city": "Portland, ME",
  "days": 3,
  "weekdays": ["Saturday", "Sunday"],
  "travellers": ["older_adult"],
  "household": "household",
  "remember": ["Dad uses a walking frame"],
  "question": "optional free text"
}
```

Only a `city` or a `question` is required. `city` accepts an id (`"Boston, MA"`), legacy
`"NYC"`/`"LA"`, or free text (`"portland maine"`). If `question` is given, the city, days, weekend or
named days, and travellers are read from it when not passed explicitly.

`travellers` must only contain groups the user (or the traveller/location agent) actually stated:
`older_adult`, `infant`, `young_child`, `pregnant`, `health_condition`. **Do not infer them.** Empty or
missing means healthy-adult thresholds. Unknown values return HTTP 400.

### Response (abridged)

```json
{
  "ok": true,
  "note": null,
  "evaluator": {"ok": true, "issues": []},
  "trace": "run_20261027T003000Z-ab12cd.jsonl",
  "handoff": {
    "version": "1.2",
    "city": "Chicago, IL",
    "periods_covered": ["Saturday", "Saturday Night", "Sunday", "Sunday Night"],
    "risk_level": "high",
    "recommendation": "Avoid or reschedule outdoor plans",
    "risk_evaluation": {"overall_level": "high", "reasons": ["Saturday: extreme heat (97°F)"],
                        "profile": "sensitive", "counts": {"low": 2, "moderate": 1, "high": 1}},
    "travellers": {"groups": ["older_adult"], "stated": ["older_adult"], "from_memory": []},
    "outcome_review": {"verdict": "pass", "issues": [], "confidence": {"level": "high"}, "round": 1},
    "confidence": "high",
    "summary": "Weather risk: High (Avoid or reschedule outdoor plans). ...",
    "advice": ["..."],
    "good_outdoor_windows": ["Sunday"],
    "risks": [{"type": "heat", "level": "high", "period": "Saturday", "detail": "extreme heat (97°F)"}],
    "official_alerts": [], "other_active_alerts": [],
    "evidence": [{"period": "Saturday", "risk_level": "high", "temperature_f": 97, "precip_chance_pct": 0}],
    "data_age_hours": 0.2, "stale": false,
    "sources": ["National Weather Service (api.weather.gov) via Zetaris", "SELECT ..."],
    "model": "nvidia/nemotron-3.5-bolt-e4b"
  }
}
```

Errors: HTTP 400 `{"ok": false, "error": "...", "hint": "..."}` for bad input. If the weather lookup
itself fails, HTTP 200 with `handoff.status = "error"` and `handoff.error` set, so the planner can
continue with the other agents.

## Option B: import it in Python (same process)

```python
import sys; sys.path.insert(0, r"path\to\weather_service")
from web_app import weather_api
status, body = weather_api({"city": "Boston, MA", "weekdays": ["Saturday", "Sunday"]})
```

`weather_api` is exactly what the HTTP endpoint calls. For lower-level use, `WeatherAgent.run(city,
days, household=None, feedback=None, travellers=None, weekdays=None)` returns the hand-off dict directly.

## Combining with the Wastewater / Pertussis agents

- **Call the agents in parallel** with the same location, dates and travellers; each returns its own
  verdict. Keep them separate in the UI ("Weather risk: High", "Wastewater: ...") rather than
  merging into one number, so users can see why.
- **Overall trip guidance**: a reasonable rule is "worst of the parts" (any High means High), with
  each agent's reasons listed. Do not rewrite this agent's `risk_level`; if the combined planner
  disagrees, send `feedback` back instead (the Evaluator pattern).
- **Location**: weather is keyed by city id `"Name, ST"`. Each city's **county FIPS** and county name
  are in the `cities` table (Zetaris `weather_pg.cities`, or `sample_data/weather_sample.db`), so
  county-level wastewater can be joined on `county_fips` and state-level pertussis on `state`.
  Cities outside the 217 return HTTP 400; fall back to the nearest supported city if needed.
- **Travellers**: pass the same stated groups to every agent. The weather agent reports what it
  used under `handoff.travellers`.
- **Memory**: this service keeps its own H-MEM store in `weather_service/memory/`. If the team wants
  one shared memory, point every agent at the same `MemoryStoreService(path=...)` rather than copying facts.

## What the UI should show for weather

Risk level and recommendation (prominently), the reasons, low-risk outdoor times, advice, official
alerts, confidence and data age, the model that answered, and this note: "Summarises National Weather
Service data. Not medical advice; check with a GP about anything health-related." `web/index.html`
is a working reference implementation of this card.

## Please keep these intact

- Risk thresholds (`risk.py`) and review rules (`critic.py`) are deliberate; change them only with Rhythm.
- All model calls go through `llm.Generator` (Nightshift is the required provider; it logs the model).
- Sample mode must keep working without credentials, and nothing may assume who is travelling.
- Never commit `.env`. Run `python -m pytest -q tests` (43 tests) after any change here.

## Known gaps

- `WEATHER_MODE=zetaris` needs Java 11+, the Zetaris JDBC jar (`../zetaris-platform/jdbc/`) and the
  Zetaris password in `.env`; until then the agent reads the offline copy.
- The `cities` table still has to be registered in Zetaris under `weather_pg`; forecasts and alerts
  already are.
