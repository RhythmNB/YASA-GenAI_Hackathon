# Weather agent hand-off (v1.2)

The Planner calls the Weather agent and gets back one Python dict / JSON message.

```python
from weather_agent import WeatherAgent
msg = weather_agent.run("New York, NY", days=3, household="dad", feedback=None,
                        travellers=["older_adult"])   # optional
```

`travellers` is optional. Only pass groups the user (or the traveller agent) actually stated:
`older_adult`, `infant`, `young_child`, `pregnant`, `health_condition`. With none, the agent
uses healthy-adult thresholds and assumes nothing. Facts the user asked it to remember
(e.g. "Dad is 85") also count and are reported under `travellers.from_memory`.

`feedback` is an optional list of problems (strings) from the Planner or Evaluator.
The agent fixes them and returns a new message.

## Message

| Field | Type | Meaning |
|---|---|---|
| `version` | str | `"1.2"` |
| `from` | str | `"weather_agent"` |
| `status` | str | `"ok"` or `"error"` (then see `error`) |
| `city` / `label` | str | City id `"Name, ST"`, e.g. `"Portland, ME"` (see `cities.py`) |
| `risk_level` | str | Overall weather risk: `"low"`, `"moderate"` or `"high"` (worst period in range) |
| `recommendation` | str | `"Good to go"`, `"Go with care"` or `"Avoid or reschedule outdoor plans"` |
| `risk_evaluation` | dict | `overall_level`, `recommendation`, `reasons` (e.g. `"Saturday: heat (97°F)"`), `profile` (`general`/`sensitive`), `counts` per level |
| `travellers` | dict | `groups` used, split into `stated` (passed in) and `from_memory` (remembered household facts) |
| `outcome_review` | dict | Second evaluation of the finished answer: `verdict` (`pass`/`revise`), `issues`, `rule_issues`, `model_issues`, `confidence`, `reviewer_model`, `round` (2 = passed after a revision) |
| `confidence` | str | `high` / `medium` / `low`, from data freshness and coverage |
| `summary` | str | 2-3 sentences for an older visitor (written by the model, checked by the agent) |
| `advice` | list[str] | Practical tips |
| `good_outdoor_windows` | list[str] | Daytime periods whose risk level is low (computed from data) |
| `risks` | list | `{type: alert/heat/cold/rain/wind/storm/stale, level: low/moderate/high, period, detail}` |
| `official_alerts` | list | NWS alerts that overlap the periods covered (event, severity, headline, effective, expires, instruction) |
| `other_active_alerts` | list | Active alerts for the city that end before or start after the periods covered |
| `periods_covered` | list[str] | The forecast periods the evaluation used (e.g. only Saturday and Sunday for "this weekend") |
| `evidence` | list | The forecast periods the claims are based on, each with its `risk_level` |
| `data_fetched_at` / `data_age_hours` / `stale` | | How fresh the data is |
| `sources` | list[str] | NWS + the exact Zetaris SQL that was run |
| `memories_used` | list[str] | H-MEM record ids the agent read |
| `model` | str | Which model wrote the summary (from Nightshift) |
| `run_id` | str | Matches `logs/run_<run_id>.jsonl` |
| `error` | str/null | Set when `status` is `"error"` |

## Shared memory (H-MEM)

The agent writes forecast facts under keys like `weather:New York, NY:Saturday` (short tier) and a
summary under `weather:New York, NY:summary` (working tier). Other agents can read them with
`MemoryRetrievalService.retrieve(...)` instead of re-querying.

## How the risk level is decided (`risk.py`)

Rules, not the model, set the level. Healthy adult / sensitive (stated groups only):

| Factor | Moderate | High |
|---|---|---|
| Heat | ≥95°F / ≥88°F | ≥105°F / ≥95°F |
| Cold | ≤32°F / ≤40°F | ≤10°F / ≤20°F |
| Rain chance | ≥60% / ≥50% | |
| Wind | ≥25 mph / ≥20 mph | ≥40 mph / ≥35 mph |
| Forecast words | thunderstorm, snow, sleet, freezing rain, smoke | blizzard, ice storm, heavy snow, hurricane, tornado, severe thunderstorm |
| NWS alert severity | Moderate | Severe or Extreme |

The overall level is the worst period in the requested days. The model must start its summary
with `Weather risk: <Level> (<Recommendation>).`; the agent checks this and the Evaluator checks
that the overall level matches the worst period.

## Outcome review (`critic.py`)

After the answer is written and fact-checked, the Outcome Reviewer evaluates it again as a whole:
does the advice address every risk found, does it fit the level (High must offer rescheduling or
indoor options), are the stated travellers addressed and none invented, is there no medical advice,
and how confident should the user be (data age and coverage). With Nightshift on, the model also
reviews the answer as an independent critic. On `revise`, the agent rewrites once with the points
and is reviewed again; the Evaluator rejects any hand-off whose review did not pass.
