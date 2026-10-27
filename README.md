# Insightor

<!-- TODO: one-paragraph pitch in your own words. Keep it to what the planner does for a person, not how it is built. -->
Planning a family visit? Say where you are going, where from, when, and who is
in the household. A planner agent asks four agents at once, all reading
through Zetaris: COVID-19 and influenza A in wastewater, whooping cough counts,
CDC guidance for the people you will be with, and the weather risk at the
destination. A composer agent turns their findings into one travel plan: a
verdict with its reason, a section per source, a precautions checklist and the
best days to be outdoors. Rules decide the verdict and every risk level; the
Meterless Nightshift models (NVIDIA Nemotron routes) write the prose, and every
figure they write is checked against the data.

| | |
|---|---|
| Event | Open Agent Hackathon 2026 (Zetaris, Meterless, NVIDIA) |
| Team | <!-- TODO: names --> |
| Demo video | <!-- TODO: link --> |
| Slides | <!-- TODO: link, or remove the row --> |
| Colab | Not used. Everything runs locally against a local Zetaris and the Nightshift runtime. |

## Contents

- [How it fits together](#how-it-fits-together)
- [Setup](#setup) from a clean clone
- [Run](#run)
- [Usage](#usage) with sample inputs
- [Dependencies](#dependencies)
- [Sample inputs and outputs](#sample-inputs-and-outputs)
- [Traces: which model handled each request](#traces-which-model-handled-each-request)
- [Meterless engine check](#meterless-engine-check)
- [Fallbacks when a service is down](#fallbacks-when-a-service-is-down)
- [Secrets](#secrets)
- [Repository layout](#repository-layout)

## How it fits together

```
Visit request (who, where from and to, dates, household)
        |
   Planner agent  (planner/planner_agent.py, runs the four in parallel)
        |-- wastewater agent   COVID-19 then influenza A, county level   (agents/wastewater, in-process)
        |-- pertussis agent    whooping cough, home and destination state (agents/pertussis_guidance, in-process)
        |-- guidance agent     CDC advice for the stated household         (agents/pertussis_guidance, in-process)
        '-- weather agent      NWS risk level for the destination          (agents/weather, HTTP on port 8770)
        |    ^
        v    |  ask again: retry a failed agent, or a county reading with no
   Evaluator     recent samples at state level (one round, MAX_REPLANS = 1)
   (findings review, rules only)
        |
   Composer agent  (planner/composer.py: verdict by rules, prose by Nightshift)
        |    ^
        v    |  revise, with the issues to fix (at most 2 rounds)
   Evaluator agent (planner/evaluator.py: rule checks + a Nightshift review, pass or revise)
        |
   Travel plan  ->  planner page (planner/frontend) or `python -m planner`
```

Each agent keeps its own data, rules and memory; the planner only normalises
what they return. The design is in `docs/2026-10-27-trip-planner-design.md`.

- **Location**: the destination city to its county and state, through the
  Open-Meteo geocoding API registered in Zetaris as REST tables (`geocoding.*`).
- **Wastewater agent**: COVID-19 and influenza A levels and trends from the CDC
  NWSS exports, county level with a state fallback. It plans its SQL with a
  Nightshift model, checks the answer against the rows, and keeps H-MEM memory
  of earlier findings (`agents/wastewater/.hmem/`).
- **Pertussis agent**: whooping cough cases this year against last year and the
  national rate, per state, from CDC NNDSS through a Zetaris REST table joined
  with Census populations.
- **Guidance agent**: picks the CDC advice that fits who you will be with and
  quotes it word for word with its source and date. Rules only, so medical
  advice is never rewritten.
- **Weather agent**: a separate service (port 8770) that reads NWS forecasts
  and alerts from the `weather_pg` Postgres through Zetaris, rates each period
  low, moderate or high with fixed rules (heat, cold, rain, wind, storms,
  official alerts; stricter for older adults, infants, young children and
  pregnancy), writes a summary with a Nightshift model and has it reviewed by a
  critic. Data older than an hour is downloaded again before it answers.

## Setup

Two parts: install four things by hand, then run one script that does the rest.

### 1. Before you start (once, by hand)

| Install | Notes |
|---|---|
| **Python 3.11 or newer** | [python.org](https://www.python.org/downloads/); on Windows tick "Add python.exe to PATH". Developed on 3.13. |
| **A JDK, 17 or newer** | For example [Eclipse Temurin](https://adoptium.net/). The Zetaris JDBC driver runs in it. `install.py` finds it through `JAVA_HOME` or `java` on the PATH; developed with JDK 23. |
| **Docker Desktop**, running | [docker.com](https://www.docker.com/products/docker-desktop/). |
| **The Zetaris Lightning platform** | The hackathon's Docker bundle from Zetaris Cloud. In the bundle folder: `docker login`, `docker compose pull`, `docker compose up -d`, then sign in once at http://localhost:3000 and note the admin password. Put the bundle folder (it holds `jdbc/ndp-jdbc-driver-*.jar`) next to this repository, or pass `--jdbc-jar` to the script. |
| **Meterless Nightshift** (recommended) | Install the app, add an NVIDIA API key from [build.nvidia.com](https://build.nvidia.com/) under Setup > Providers, and keep it open. Without it everything still runs, but the prose comes from templates instead of the Nemotron models. |
| **git** | To clone this repository and `zetaris/getting-started`. |

### 2. Run the setup script

```bash
git clone <this repository's URL> YASA-GenAI_Hackathon
cd YASA-GenAI_Hackathon
python install.py
```

It asks once for your Zetaris username (Enter keeps `admin@zetaris.com`)
and password, the ones you sign in to http://localhost:3000 with, and saves
them in the git-ignored `getting-started/.env.local`. It takes about 10 minutes the first
time, most of it downloading the two CDC wastewater exports (about 0.5 GB).
It is safe to run again: every step skips what is already in place, and
values already in a `.env` file are kept. What it does:

| Step | What happens |
|---|---|
| 1. Look around | finds Python, the JDK, the JDBC jar, the running Zetaris driver container and Nightshift's token; stops with a clear message if something is missing |
| 2. Packages | `pip install` of the planner's packages (`jaydebeapi`, `JPype1`, `httpx`) and a separate `.venv` for the weather service |
| 3. Sign in | signs in to Zetaris with your username and password; if Zetaris rejects them it asks again (three tries), and nothing is saved until a sign-in works |
| 4. getting-started | clones [zetaris/getting-started](https://github.com/zetaris/getting-started) next to this repository (the pertussis and guidance agents use its Zetaris client) and links it into `agents/pertussis_guidance/` |
| 5. Settings | writes `getting-started/.env.local`, `agents/wastewater/.env` and `agents/weather/.env` (all git-ignored; secrets are never printed) |
| 6. Data in Zetaris | downloads the CDC NWSS SARS-CoV-2 and influenza A exports and creates `wastewater.sars_cov_2` and `wastewater.influenza_a`; creates the pertussis REST table, the census and CDC guidance tables and the `visitplanner` views; starts the weather Postgres (`weather-db`), loads the NWS forecasts and alerts, and registers it as the datasource `weather_pg` |
| 7. Check | queries every table through Zetaris and prints the command to start the planner |

`python install.py --check` reports what is in place without changing
anything. `python install.py --reset` forgets the saved Zetaris sign-in and
paths, asks and detects them again, and rewrites the settings (use it after
changing your Zetaris password or moving the JDK or the bundle). Other options: `--java-home`, `--jdbc-jar`, `--zetaris-user`,
`--getting-started <folder>`, and `--no-weather-db` (no weather Postgres; the
weather service then reads an offline SQLite copy instead of Zetaris).

If a step fails, the script names it and what to do; fix that and run it
again (stopping it with Ctrl+C is fine too). Finished steps are skipped and
broken tables are rebuilt. The usual causes: Docker or the Zetaris platform not started, the
JDBC jar not beside the repository (`--jdbc-jar`), or a wrong Zetaris
username or password (it asks again; `--reset` if it changed after setup).

## Run

One command, from the repository root:

```bash
python planner/frontend/server.py --port 8765
```

The planner server starts the weather service on port 8770 itself, from
`agents/weather/.venv`, when nothing answers there; it checks again before each
plan and restarts it if it has stopped, and stops it on exit. A weather service
you start by hand is reused and left running. Its output goes to
`agents/weather/logs/service.log`. Pass `--no-weather` to turn this off.

Open http://127.0.0.1:8765/. The first plan starts the JVM for the JDBC driver,
so it takes a few seconds longer.

## Usage

### The planner page

Type the destination and home city, the dates, the party, and switch on who
you will be with (older adults, young children, a newborn, someone pregnant),
then **Plan this visit**. The progress card names each agent and the model
that handled it as they report; "Your plan" then shows the verdict, the intro,
one section per source, the "Before you go" checklist and the best days, with
sources and models in a disclosure at the end. **Add to calendar** writes the
verdict and precautions into the event. **Download** saves the plan as
Markdown, text, JSON or PDF. The last plan survives a page refresh, and the
"Before you go" boxes you tick are remembered per plan.

### The planner on the command line

```bash
python -m planner "Richmond, VA" --from "Austin, TX" --county "Richmond City" --start 2026-11-10 --end 2026-11-17 --with newborn
python -m planner "Chicago, IL" --from "Boston, MA" --with older_adult,pregnant --json
python -m planner "Richmond, VA" --from "Austin, TX" --weather-url http://127.0.0.1:8799   # weather down: a partial plan
```

Progress lines go to stderr (each agent with its level, model and seconds),
then the plan: verdict, intro, sections, checklist, best days, models, elapsed.
`--json` prints the same TravelPlan JSON the page receives.

### Single agents

```bash
cd agents/wastewater
python -m wastewater_agent ask "is sars-cov-2 rising in Virginia over the last 2 weeks?" --county "City of Richmond"
python -m wastewater_agent ask "is flu rising in California over the last 2 weeks?"
python -m wastewater_agent ask "was covid detected in Texas in September?" --json
python -m wastewater_agent status | memory list | memory show <id> | feedback <id> helpful | audit <id> | sleep | benchmark
```

```bash
cd agents/pertussis_guidance
python agents/pertussis_agent.py AZ CA --no-llm --channel jdbc     # whooping cough, two states
python agents/guidance_agent.py newborn --priority pertussis --channel jdbc
```

The weather service's own page is http://127.0.0.1:8770/ and its API is
`POST /api/weather` (the planner server starts it; see Run).

### The page's API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/plan` `{toCity, toState, fromCity, fromState, start, end, adults, children, with[], stream?}` | run the planner; with `stream: true` the reply is one JSON line per progress event, ending in `{"stage": "plan", "plan": ...}` |
| GET | `/api/plans`, `/api/plans/<id>`, `/api/plans/<id>/report.md` | plans made by this server process, one record, a Markdown report |
| GET | `/api/geocode?q=` | a typed city to candidates with county, state and coordinates (the page's type-ahead) |
| GET | `/api/status` | Zetaris, Nightshift, the weather service and memory counts |
| POST | `/api/ask` `{question, county?, pathogen?}` | the wastewater agent alone |

The server binds to 127.0.0.1 with no authentication. One planner runs per
server process (the JVM starts once), and plans are run one at a time.

## Dependencies

| Dependency | Role | Where it is configured |
|---|---|---|
| Zetaris Lightning (Docker, JDBC port 10000) | holds the wastewater tables (`wastewater.*`), the pertussis REST table and views (`cdc_rest.*`, `visitplanner.*`) and the reference tables (`refdata.*`), the geocoding REST tables (`geocoding.*`) and the weather datasource (`weather_pg`, the weather Postgres); every health and weather figure comes from SQL run here | `agents/wastewater/.env`, `getting-started/.env.local` |
| Meterless Nightshift runtime (`127.0.0.1:8088`) | plans and writes for the wastewater agent, writes the composer's intro and precautions, writes the weather summary; `meterless/judge` scores the wastewater benchmark | `NIGHTSHIFT_MODELS` (wastewater and composer), `METERLESS_MODEL` (pertussis), `NIGHTSHIFT_MODEL` (weather) |
| NVIDIA Nemotron models (through Nightshift) | named directly, no `meterless/auto` or `meterless/fast` aliases: `nvidia/nemotron-3-ultra-550b-a55b`, then `nvidia/nemotron-3.5-lightning-30b-a3b`; the weather and pertussis agents use the lightning model | as above |
| CDC data.cdc.gov (NWSS exports, NNDSS pertussis REST), US Census populations, CDC guidance pages | the data behind every section | `agents/*/sql`, `agents/pertussis_guidance/data` |
| National Weather Service (api.weather.gov) | forecasts and alerts for the weather agent, loaded into the `weather-db` Postgres and read through Zetaris; refreshed when older than an hour | `agents/weather/.env`, `agents/weather/docker-compose.yml` |
| Python packages: `jaydebeapi`, `JPype1`, `httpx` (planner and wastewater); the weather service's own `requirements.txt` in its venv | JDBC bridge, HTTP clients | `agents/wastewater/requirements.txt`, `agents/weather/requirements.txt` |
| A JDK | runs the JDBC driver | `JAVA_HOME` |
| Open-Meteo (no key) and Lucide icons (CDN with a local fallback) | the page's weather card and icons; optional | none |

The NVIDIA API key is configured in Nightshift's Providers tab, not in this
project.

## Sample inputs and outputs

- `planner/frontend/static/sample-plan.json`: a complete travel plan for a
  visit to Richmond, VA with a newborn, captured from a real run on
  2026-10-27; the page's demo mode (`http://127.0.0.1:8765/?demo=1`) renders it
  with no services.
- `agents/wastewater/samples/README.md`: three wastewater questions with the
  full CLI output, SQL and receipts, plus the JSON traces in `samples/traces/`.
- The single-agent commands under Usage, each with the output it prints.

## Traces: which model handled each request

- Every plan records `models` (composer and each agent) and `traces` (the
  wastewater memory ids, the pertussis method, the weather run's trace file).
  `GET /api/plans` lists the plans this server made; `GET /api/plans/<id>` is
  the full record and `/report.md` a Markdown report.
- While a plan runs, `POST /api/plan` with `"stream": true` sends one JSON line
  per stage: each agent's start, done (level, model, seconds) or failure, every
  Nightshift route the wastewater agent tried, and the composer's model.
- Wastewater: `receipt:` lines in every `ask`, `GET /api/answers/<id>`, and the
  benchmark's `results-<timestamp>.json` per question.
- Weather: `agents/weather/logs/run_<id>.jsonl`, one event per step, with the
  model on each `llm_call`.
- Nightshift app: calls carry `meterless-app` (`wastewater-agent`,
  `visit-planner-cloud`, `visit-planner`), so the app's stream groups them.

## Meterless engine check

`python -m wastewater_agent status` (from `agents/wastewater/`) lists the routes
Nightshift exposes and their availability; `agents/wastewater/samples/conformance.md`
holds a captured run. `agents/weather/check_nightshift.py` does the same from
the weather service's venv. The wastewater benchmark's plan layer
(`python -m wastewater_agent benchmark --layers plan`) is the functional check:
every question must be planned by a Nightshift route.

## Data notes

- Wastewater exports are CDC's weekly NWSS files; a county with no recent
  samples is answered at state level and labelled so.
- Pertussis counts are state level only (New York City is the exception),
  provisional and often revised. Missouri, Delaware and DC have no complete
  2026 count: a reporting gap, not zero.
- CDC guidance rows are a snapshot from 2026-10-26. Infant RSV immunization is
  no longer routine since the 5 January 2026 schedule change, but CDC's RSV page
  predates it, so that advice carries a "check with a healthcare provider"
  caveat; the COVID rows cover the 2025-26 vaccine.
- Weather covers the 217 US cities in `agents/weather/cities.py` and the
  7-day NWS forecast.

## Fallbacks when a service is down

| Situation | What happens |
|---|---|
| A Nightshift model fails (for example a 502 from the provider) | the next route in `NIGHTSHIFT_MODELS` is tried; the failing one is skipped for five minutes |
| Nightshift unreachable or every route failing | the wastewater planner falls back to rules and its writer to templates (answer prefixed `[offline]`); the composer writes template prose and says so in `models.composer` |
| A model writes a number that is not in its fact sheet | the output is rejected, retried once, then written from templates |
| The evaluator never passes a draft | after 2 revisions the plan ships the best draft (the last that passed, else the one with fewest rule problems) and lists the open points under `evaluation.unresolved` |
| One agent fails or times out | the evaluator has the planner ask it once more; if that also fails, its section says so, the plan is marked `partial` and the verdict comes from the other sources |
| The destination county has no recent wastewater samples | the evaluator has the planner ask again for the state-wide reading, which is used if it says more and is labelled as state-wide; recorded under `evaluation.replans` |
| The weather service is down or the city is not among its 217 | the weather section says so; no best days |
| The trip starts beyond the 7-day forecast | the weather section gives the current outlook with a caveat to check again nearer the date |
| No sampling site serves the requested county | the wastewater agent answers for the state with a note |
| Zetaris unreachable | `status` reports it; the health sections fail and the plan is partial. Demo mode (`?demo=1`) runs with no services at all |

<!-- TODO (recommended by the rules): a SAMPLE_MODE=true switch that lets the agents answer from stored data when Zetaris is down. Not implemented; demo mode covers the page only, and the weather agent has its own sample mode. -->

## Secrets

Nothing secret is in the repository. Every `.env` is git-ignored and every
`.env.example` has placeholders only; `install.py` writes the real values into
the git-ignored files and never prints them. Zetaris credentials are read from the
getting-started checkout's `.env.local`, and the Nightshift token from the
Meterless runtime's own token file.

## Repository layout

```
planner/                  the orchestration layer (Python package `planner`)
  planner_agent.py        fan-out to the four agents in parallel, progress events, timeouts
  composer.py             verdict rules, fact sheet, Nightshift prose with figure check, template fallback
  adapters/               wastewater.py, pertussis.py, guidance.py, weather.py: agent result -> Finding
  findings.py, trip.py    the Finding, Verdict, TravelPlan and TripRequest shapes
  cli.py                  python -m planner
  frontend/               server.py (stdlib HTTP server and API) and static/ (the planner page)
agents/
  wastewater/             wastewater_agent/ (cli, planner, executor, evaluator, writer, memory), sql/, benchmark/, samples/, docs/
  pertussis_guidance/     the pertussis and guidance agents, their data and SQL
  weather/                the weather service: agent, risk rules, critic, web app, tests
install.py                one-command setup (see Setup)
docs/                     design and plan for the trip planner, the submission checklist
.claude/launch.json       preview configs for the two servers
```
