# Trip planner: planner agent, four agents, composer agent

Date: 2026-10-27. Status: approved in conversation; implementation plan to follow.

## Goal

One request ("we're visiting Richmond from Austin, 10 to 17 November, with a
newborn in the house") becomes one structured travel plan. A planner agent
fans the request out to the four agents the team has, a composer agent turns
their findings into a verdict with sections and precautions, and the existing
wastewater planner page shows it with live progress.

```
Visit request -> Planner agent -> { wastewater (COVID, flu) | pertussis -> guidance | weather }
              -> Composer agent -> Travel plan (JSON) -> page / CLI
```

## Decisions already made

| Question | Decision |
|---|---|
| Plan shape | One overall verdict with a reason, then one section per source, then a precautions checklist and the best days. Sources and models at the end. |
| Who is visited | Four toggles on the trip sentence: older adults, young children, a newborn, someone pregnant. Only stated groups are passed on; nothing is inferred. |
| Weather beyond the forecast | Always call the weather agent for the days the NWS forecast covers now; when the trip starts later than that, the section says so and asks the user to check again nearer the date. |
| Wiring | One planner process. Wastewater, pertussis and guidance are called in-process; weather over HTTP on its own service. Teammates' code is imported, never modified. |
| Folders | Restructured into `planner/`, `agents/{wastewater,pertussis_guidance,weather}/`, `docs/` (below). |

## Folder layout

```
YASA-GenAI_Hackathon/
  README.md                       project README: what it is, setup for every part, usage
  .claude/launch.json             preview configs: planner-frontend (8765), weather-service (8770)
  docs/                           project-level docs: this design, SUBMISSION-CHECKLIST.md
  planner/                        Python package `planner` (the orchestration layer)
    __init__.py
    __main__.py                   python -m planner ...
    cli.py
    trip.py                       TripRequest and the toggle -> group mappings
    planner_agent.py              PlannerAgent: parallel fan-out, progress events, timeouts
    composer.py                   verdict rules, fact sheet, Nightshift prose, template fallback
    findings.py                   Finding and TravelPlan dataclasses, JSON serialisation
    adapters/
      __init__.py
      wastewater.py               calls wastewater_agent.Agent twice (sars-cov-2, flu-a)
      pertussis.py                imports pertussis_agent from agents/pertussis_guidance/agents
      guidance.py                 imports guidance_agent from the same place
      weather.py                  POST /api/weather on the weather service
    frontend/                     moved from wastewater/frontend: server.py, static/, README.md
  agents/
    wastewater/                   moved from wastewater/ (wastewater_agent/, sql/, benchmark/,
                                  samples/, docs/, data/, .env.example, requirements.txt)
    pertussis_guidance/           moved from visit-planner-handoff/ (agents/, data/, sql/,
                                  HANDOFF.md, SETUP-NOTES.md, the getting-started junction)
    weather/                      moved from weather_service/ (unchanged inside)
```

Moves: `git mv` for tracked paths so history follows; plain moves for untracked
ones. The weather service's `.venv` is recreated after the move (its scripts
embed the old absolute path). Every path reference is updated: `launch.json`,
the root README, the frontend README, both SETUP-NOTES files, the samples and
checklist, `planner/frontend/server.py` (which adds `agents/wastewater` to
`sys.path`). Nothing is committed; the user manages git.

## Inputs

`TripRequest` (`planner/trip.py`):

| Field | From the page | Notes |
|---|---|---|
| `to_city`, `to_state`, `to_county` | destination geocode | state code lowercase; county in the wastewater agent's form ("Richmond City") |
| `from_city`, `from_state` | home geocode | pertussis compares home and destination states |
| `start`, `end` | dates | ISO dates |
| `adults`, `children` | steppers | informational, passed to the composer only |
| `with` | toggles | subset of `older_adult`, `young_child`, `newborn`, `pregnant` |

Mappings, fixed in `trip.py`:

- Guidance profile: `newborn` if the newborn toggle is on, else `older_adult` if
  older adults is on, else `general`. `pregnant` is the agent's flag. `general`
  is not an agent profile: the adapter fetches the agent's `visitor_any` rows
  for `respiratory`, `influenza` and `covid` through the agent's own
  `fetch_rows` and `build` functions with an adapter-defined profile labelled
  "family and friends".
- Weather traveller groups: `older_adult` → `older_adult`; `young_child` →
  `young_child`; `newborn` → `infant`; `pregnant` → `pregnant`. Nothing else.
- Sensitive household (used by the composer): any of the four toggles on.

## Planner agent

`PlannerAgent.run(trip, progress=None) -> TravelPlan`. It starts four tasks in a
thread pool and waits for all of them, then calls the composer.

| Task | Call | Timeout |
|---|---|---|
| wastewater | `Agent.ask(question, county, pathogen)` for `sars-cov-2`, then `flu-a`, question "is {virus} rising in {state} over the last 2 weeks?" | 120 s each |
| pertussis then guidance | `pertussis_activity([from_state, to_state], use_llm=False, channel="jdbc")`, then `guidance_for_visit(profile, priority, pregnant, channel="jdbc")` with `priority=["pertussis"]` when the destination's trend starts with "higher" | 120 s together |
| weather | `POST http://127.0.0.1:{WEATHER_PORT}/api/weather` with `city="{to_city}, {TO_ST}"`, `days=7`, `travellers=<mapped groups>` | 180 s |

The wastewater calls share one `Agent` instance and the frontend server's lock,
as today. The pertussis and guidance modules are imported by adding
`agents/pertussis_guidance/agents` to `sys.path`; they load Zetaris settings
from the linked `getting-started/.env.local` themselves. The weather service
URL comes from `WEATHER_SERVICE_URL` (default `http://127.0.0.1:8770`).

Progress events, as dicts, in this order per task: `{"stage": "<source>",
"state": "start"}`, then `{"stage": "<source>", "state": "done", "model": ...,
"level": ..., "seconds": ...}` or `{"state": "failed", "error": ...}`; the
wastewater task also forwards the wastewater agent's own route events as
`{"stage": "covid" | "flu", "state": "route", "route_state": "start" | "failed" | "done", "model": ...}`. Then `{"stage": "composer", "state": "start"}` and
`"done"` with the model, then the caller receives the plan.

## Findings

Every adapter returns a `Finding` (`planner/findings.py`):

| Field | Meaning |
|---|---|
| `source` | `covid`, `flu`, `pertussis`, `weather`, `guidance` |
| `title` | "COVID-19 in wastewater", "Flu (influenza A) in wastewater", "Whooping cough", "Weather", "CDC guidance" |
| `status` | `ok`, `error`, `skipped` |
| `level` | `low`, `moderate`, `high`, `unknown`; guidance always `unknown` (it carries no risk) |
| `headline` | one line, e.g. "100% of 2 samples positive, rising" |
| `text` | the agent's own prose (wastewater answer, pertussis briefing, weather summary, guidance briefing) |
| `facts` | bullet facts for the section (strings) |
| `caveats` | the agent's caveats and any planner note (beyond-forecast, partial data, fallback) |
| `sources` | `[{"title", "url"}]` from the agent |
| `model` | model that wrote `text`, or `template`, or none |
| `trace` | wastewater answer id, pertussis `method`, weather `trace` file name |
| `raw` | the agent's full result, kept for the page's trace view and the JSON output |

Level rules per adapter (rules, never the model):

- wastewater: `unknown` when the window is empty (fallback window is reported
  in `facts`); `high` when positive share is 0.8 or more and direction is
  rising; `moderate` when share is 0.5 or more, or direction is rising; else `low`.
- pertussis (destination state): `unknown` when `data_ok` is false or the
  state is missing; `high` when trend starts with "higher" and `vs_national`
  is "above"; `moderate` when one of those holds; else `low`.
- weather: the agent's `risk_level`; `unknown` when its status is `error`.
- guidance: `unknown`.

## Composer agent

`compose(trip, findings, provider, offline) -> TravelPlan`.

1. Verdict, by rules. For a sensitive household, a `moderate` health finding
   (covid, flu, pertussis) counts as `high`. Overall is the worst level among
   findings that are not `unknown`:

   | Overall | Label |
   |---|---|
   | high | Reconsider, or go with full precautions |
   | moderate | Go with care |
   | low | Good to go |
   | none known | Not enough data to judge |

   `reason` is one sentence built from the findings that set the level, e.g.
   "Whooping cough in Virginia is higher than last year and above the national
   rate, and the household includes a newborn."

2. Prose, by Nightshift. A fact sheet lists the verdict, each finding's
   headline and facts, the household, and the dates. The model writes a 2 to
   3 sentence intro and 5 to 8 precautions as a JSON object `{"intro": str,
   "precautions": [str]}`. The request goes through `NightshiftProvider` with
   the same route chain as the wastewater agent and `enable_thinking: false`.
   Every number in the output must appear in the fact sheet (the wastewater
   writer's `allowed_numbers`/`foreign_numbers` check, reused); one retry with
   a nonce, then the template. Guidance text is quoted as the agent returned
   it and never sent to the model.

3. Template fallback (`provider` None, every route failing, or two rejected
   drafts): intro from the verdict label and reason; precautions assembled
   from fixed sentences per finding level and household group. The plan's
   `models.composer` is then `"template"` and a caveat says so.

`TravelPlan` JSON:

```json
{
  "id": "plan_...", "createdAt": "...", "elapsedSeconds": 71.2, "partial": false,
  "trip": { "...": "the request as received" },
  "verdict": { "level": "moderate", "label": "Go with care", "reason": "..." },
  "intro": "...",
  "sections": [ "Finding objects in order: covid, flu, pertussis, weather, guidance" ],
  "precautions": ["..."],
  "bestDays": ["Tuesday", "Wednesday"],
  "sources": [ {"title": "...", "url": "..."} ],
  "models": { "composer": "nvidia/...", "covid": "...", "flu": "...", "pertussis": "template", "weather": "...", "guidance": null },
  "traces": { "covid": "ans_...", "flu": "ans_...", "weather": "run_....jsonl" },
  "notes": ["weather service unreachable: ..."]
}
```

`bestDays` comes from the weather finding's `good_outdoor_windows`, filtered
to day periods. `sources` is the union of the findings' sources, de-duplicated
by URL, in section order.

## Server and page

`planner/frontend/server.py` keeps every existing endpoint and adds
`POST /api/plan`. Body: the TripRequest fields plus `"stream": true`. With
`stream`, the reply is newline-delimited JSON: the progress events above, then
`{"stage": "plan", "plan": {...}}`, or `{"stage": "error", "status", "error"}`.
Without `stream`, a plain JSON plan. Plans are kept in memory like answers:
`GET /api/plans`, `GET /api/plans/<id>`, `GET /api/plans/<id>/report.md`.
`/api/status` adds `weather: {ok, url, mode, cities}` from the weather
service's `/api/status`.

Page changes (same dashboard, same styles):

- Trip sentence: "to be with (older adults) (young children) (a newborn)
  (someone pregnant)."
- Button: "Plan this visit". One request instead of two.
- Progress card: the title names the trip; the trail gains one line per agent
  as it reports ("Whooping cough: moderate, 4 s", "Weather: low,
  nemotron-3.5-lightning, 62 s"), route lines from the wastewater agent as
  today, then "Composing the plan with <model>".
- "Your plan" card: a verdict banner (level colour from the existing badge
  palette, label, reason), the intro, then one block per section with its
  level badge, headline, text, facts as bullets and caveats in smaller type;
  a failed section shows its error in the same block. Then "Before you go"
  (the precautions as a checklist) and "Best days outdoors". A collapsed
  "Sources and models" disclosure closes the card. No captions or footnotes
  outside that disclosure.
- Calendar: the event description carries the verdict, the reason and the
  precautions. Map popup unchanged (COVID and flu shares).
- Demo mode: `static/sample-plan.json`, captured from a real run, replayed
  with simulated progress events.

CLI: `python -m planner "Richmond, VA" --from "Austin, TX" --start 2026-11-10
--end 2026-11-17 --with older_adult,newborn [--json]`, run from the repo root.
Prints the verdict, intro, sections, precautions, best days, models and
elapsed time; `--json` prints the plan.

## Error handling

| Situation | Behaviour |
|---|---|
| An agent raises or times out | its Finding has `status: error` with the message; the plan is `partial: true` and `notes` records it; the composer runs on the rest |
| Weather service down or city not in its 217 | weather Finding `error` / `skipped` with the reason; no best days |
| Trip start beyond the forecast | weather Finding `ok` with a caveat; `bestDays` still from the current forecast |
| No wastewater site serves the county | the wastewater agent's state-level fallback, surfaced as a caveat |
| Nightshift down for the composer | template prose, `models.composer: "template"` |
| Nightshift rejects the token | `ProviderUnauthorized` surfaces as HTTP 401 / CLI error, as today |
| Page request aborted | the server finishes the run and stores the plan; the stream write fails silently |

## Verification

1. `python -m planner "Richmond, VA" --from "Austin, TX" --start ... --with newborn` with all services up: a full plan, every section `ok`, composer model from Nightshift.
2. The same with the weather service stopped: `partial: true`, weather section `error`, verdict from the other findings.
3. The page: trip with a newborn, "Plan this visit", progress card shows four agents and the composer with models, "Your plan" renders every part; calendar description carries the verdict.
4. Demo mode (`?demo=1`) renders `sample-plan.json` with no services.
5. The wastewater benchmark still runs from `agents/wastewater/` (paths only).

## Out of scope

- Changing any teammate agent's rules, thresholds or prompts.
- A shared H-MEM store across agents (each keeps its own).
- Zetaris-backed weather (`WEATHER_MODE=zetaris`); the service reads its offline copy refreshed from NWS.
- Nearest-city fallback for destinations outside the weather agent's 217 cities.
- Tests for the planner package (the project keeps no test suite; verification is the list above).
