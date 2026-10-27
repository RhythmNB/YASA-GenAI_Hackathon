# Sample inputs and outputs
Three questions run on 2026-10-27 from `wastewater/` with the CLI. Each entry
gives the command, the answer, the plan line and the Nightshift receipts; the
full console output is in `outputs/` and the JSON trace (plan and fact sheet,
printed by `--json`) in `traces/`. Every figure in an answer comes from the SQL
listed in the output; the receipts name the model that handled each call.

## Sample 1: richmond covid trend

County-level trend with no samples in the window: the agent reports the most recent 7-day window with data instead and says the trend cannot be assessed.

```bash
python -m wastewater_agent ask "is sars-cov-2 rising in Virginia over the last 2 weeks?" --county "City of Richmond" --json
```

Answer:

> In Richmond City, Virginia during 2026-10-13 to 2026-10-26, data are partial with the latest sample on 2026-09-28; the most recent 7-day window with data, 2026-09-22 to 2026-09-28, had 1 sample from 1 site, which was positive (100.0%) with a mean concentration of 39,235.0 copies/l wastewater. The requested window had 0 samples, and the preceding window 2026-09-29 to 2026-10-12 also had 0 samples, so the trend direction is unknown due to insufficient data in both windows. Earlier finding on record (mem_a52ba8701f72, 2026-10-26): No SARS-CoV-2 wastewater samples for Richmond City, Virginia 2026-10-13..2026-10-26 (latest sample 2026-09-28); most recent 7-day window 2026-09-22..2026-09-28: 1/1 positive (100.0%), 1 sites.

```
plan:     pathogen=sars-cov-2 intent=trend state=va county=Richmond City source=nightshift
receipt: rcpt_req_d2fgkaxj via nvidia/nemotron-3-ultra-550b-a55b  cache=miss reclaimed=0
receipt: rcpt_req_gqdajbcn via nvidia/nemotron-3-ultra-550b-a55b  cache=miss reclaimed=0
provider: nightshift
```

Full output: `outputs/sample-1-richmond-covid-trend.txt`. Trace: `traces/sample-1-richmond-covid-trend.json`.

## Sample 2: california flu trend

The virus is picked from the word "flu" (table wastewater.influenza_a); a state-level trend against the preceding two weeks.

```bash
python -m wastewater_agent ask "is flu rising in California over the last 2 weeks?" --json
```

Answer:

> In California during 2026-10-13 to 2026-10-26, data are partial with the latest sample on 2026-10-20. In the requested window, 133 of 146 samples were positive (91.1%) across 59 sites, with a mean concentration of 18,480.7 copies/g dry sludge (mixed units; indicative only). Compared with the preceding window 2026-09-29 to 2026-10-12 (396 samples, 87.4% positive, mean 14,144.1), the positive share was flat (+3.7 percentage points) and the mean concentration rose by 4,336.6.

```
plan:     pathogen=flu-a intent=trend state=ca source=nightshift
receipt: rcpt_req_83o2l2wl via nvidia/nemotron-3-ultra-550b-a55b  cache=miss reclaimed=0
receipt: rcpt_req_8to6p4so via nvidia/nemotron-3-ultra-550b-a55b  cache=miss reclaimed=0
provider: nightshift
```

Full output: `outputs/sample-2-california-flu-trend.txt`. Trace: `traces/sample-2-california-flu-trend.json`.

## Sample 3: texas covid september

A detection question over a named month with full coverage.

```bash
python -m wastewater_agent ask "was covid detected in Texas in September?" --json
```

Answer:

> In Texas during September 2026 (2026-09-01 to 2026-09-30), SARS-CoV-2 was detected in 290 of 297 samples (97.6% positive share) across 45 sites, with a mean concentration of 52,161.2 copies/g dry sludge (mixed units; indicative only). The data are current through 2026-10-12.

```
plan:     pathogen=sars-cov-2 intent=detect state=tx source=nightshift
receipt: rcpt_req_5jrj94l2 via nvidia/nemotron-3-ultra-550b-a55b  cache=miss reclaimed=0
receipt: rcpt_req_isjxvj4l via nvidia/nemotron-3-ultra-550b-a55b  cache=miss reclaimed=0
provider: nightshift
```

Full output: `outputs/sample-3-texas-covid-september.txt`. Trace: `traces/sample-3-texas-covid-september.json`.

## Planner page

The same checks run from the page (`python frontend/server.py --port 8765`),
which sends one request per virus to `POST /api/ask` and shows a plan block for
each. `frontend/static/sample-answer.json` and `sample-answer-flu.json` are two
stored API responses, rendered by demo mode (`?demo=1`) with no services running.

## Combined plan

`planner/frontend/static/sample-plan.json` is a complete travel plan from the
planner (all four agents and the composer) for a visit to Richmond, VA with a
newborn, captured from a real run on 2026-10-27. It lists the model behind every
section under `models` and the trace ids under `traces`.
