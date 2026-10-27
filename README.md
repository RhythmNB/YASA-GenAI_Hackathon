# Visit Planner

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

## Setup

Commands are run from the repository root unless a step says otherwise.

### 1. Prerequisites

| Need | Why | Checked with |
|---|---|---|
| Python 3.11 or newer (developed on 3.13) | the planner, the agents, the frontend server | `python --version` |
| A JDK (developed with JDK 23) | the Zetaris JDBC driver runs in a JVM started by JPype | `java -version` |
| Zetaris Lightning platform running in Docker, JDBC on `localhost:10000` | all health data access | `python -m wastewater_agent status` from `agents/wastewater/` |
| The Zetaris JDBC driver jar (`ndp-jdbc-driver-*.jar`, ships with the platform) | JDBC connection | path in `.env` files |
| Meterless Nightshift runtime on `http://127.0.0.1:8088/v1` | the models for the wastewater agent, the composer and the weather agent | `python -m wastewater_agent status` |
| The hackathon's `getting-started` repository cloned next to this one | the pertussis and guidance agents reuse its Zetaris client and `.env.local` | `agents/pertussis_guidance/getting-started` resolves |

Zetaris and Nightshift are installed as described in the getting-started
repository; this project only connects to them.

### 2. Wastewater agent (`agents/wastewater/`)

```bash
cd agents/wastewater
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: the JDBC URL and jar path, `JAVA_HOME` if it is not set globally,
and either `ZETARIS_ENV_FILE` (a file holding `ZETARIS_USERNAME` and
`ZETARIS_PASSWORD`) or those two values directly. The Nightshift token is read
from the runtime's own `proxy-token` file by default.

Load the two CDC NWSS exports, each a Lightning filestore table from a file
inside the Zetaris container:

| Table | Dataset | Download |
|---|---|---|
| `wastewater.sars_cov_2` | NWSS SARS-CoV-2 wastewater concentration (data.cdc.gov `g653-rqe2`) <!-- TODO: confirm the dataset id --> | `https://data.cdc.gov/api/views/g653-rqe2/rows.csv?accessType=DOWNLOAD` |
| `wastewater.influenza_a` | NWSS influenza A wastewater data (data.cdc.gov `ymmh-divb`) | `https://data.cdc.gov/api/views/ymmh-divb/rows.csv?accessType=DOWNLOAD` |

```bash
# from agents/wastewater/
# 1. download both CSVs into data/ (git-ignored; ~0.5 GB together)
curl -L -o data/CDC_Wastewater_Data_for_SARS-CoV-2_20261023.csv "https://data.cdc.gov/api/views/g653-rqe2/rows.csv?accessType=DOWNLOAD"
curl -L -o data/CDC_Wastewater_Data_for_Influenza_A_20261026.csv "https://data.cdc.gov/api/views/ymmh-divb/rows.csv?accessType=DOWNLOAD"
# 2. copy them into the Zetaris driver container (one-off)
docker exec zetaris-driver-1 mkdir -p /home/zetaris/customer-data/shared/wastewater
docker cp data/CDC_Wastewater_Data_for_SARS-CoV-2_20261023.csv zetaris-driver-1:/home/zetaris/customer-data/shared/wastewater/
docker cp data/CDC_Wastewater_Data_for_Influenza_A_20261026.csv zetaris-driver-1:/home/zetaris/customer-data/shared/wastewater/
# 3. create the tables: run sql/01_wastewater_create.sql and sql/02_influenza_a_create.sql
#    (Zetaris SQL editor, or the getting-started repo's scripts/run_sql.py)
# 4. verify with sql/01_wastewater_select.sql and sql/02_influenza_a_select.sql
python -m wastewater_agent status
```

If the file names differ (CDC stamps the export date into the name), change the
`PATH` in the two create scripts to match.

### 3. Pertussis and guidance agents (`agents/pertussis_guidance/`)

Follow `agents/pertussis_guidance/HANDOFF.md`, with the Windows notes in
`agents/pertussis_guidance/SETUP-NOTES.md`: link or clone `getting-started`
into that folder, add the keys from `env.example` to `getting-started/.env.local`,
copy the census and guidance CSVs into the Zetaris container, and run
`sql/setup.sql` (or `sql/run_setup_jdbc.py` over JDBC). Check:

```bash
cd agents/pertussis_guidance/agents
python pertussis_agent.py AZ CA --no-llm --channel jdbc     # Arizona at 1019 cases, 13.37 per 100k
python guidance_agent.py newborn --priority pertussis --channel jdbc
```

### 4. Weather agent (`agents/weather/`)

Follow `agents/weather/INTEGRATION.md`, with the notes in
`agents/weather/SETUP-NOTES.md`: `setup_laptop.bat` (or its steps by hand)
creates `.venv`, writes `.env`, downloads the NWS forecast for its 217 cities
and runs its 43 tests. No Zetaris is needed for it in sample mode.

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
verdict and precautions into the event. `planner/frontend/README.md` documents
the page and its API.

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

The pertussis and guidance commands are under Setup step 3; the weather
service's own page is http://127.0.0.1:8770/ and its API is `POST /api/weather`.

## Dependencies

| Dependency | Role | Where it is configured |
|---|---|---|
| Zetaris Lightning (Docker, JDBC port 10000) | holds the wastewater tables (`wastewater.*`), the pertussis REST table and views (`cdc_rest.*`, `visitplanner.*`) and the reference tables (`refdata.*`); every health figure comes from SQL run here | `agents/wastewater/.env`, `getting-started/.env.local` |
| Meterless Nightshift runtime (`127.0.0.1:8088`) | plans and writes for the wastewater agent, writes the composer's intro and precautions, writes the weather summary; `meterless/judge` scores the wastewater benchmark | `NIGHTSHIFT_MODELS` (wastewater and composer), `METERLESS_MODEL` (pertussis), `NIGHTSHIFT_MODEL` (weather) |
| NVIDIA Nemotron models (through Nightshift) | named directly, no `meterless/auto` or `meterless/fast` aliases: `nvidia/nemotron-3-ultra-550b-a55b`, then `nvidia/nemotron-3.5-lightning-30b-a3b`; the weather and pertussis agents use the lightning model | as above |
| CDC data.cdc.gov (NWSS exports, NNDSS pertussis REST), US Census populations, CDC guidance pages | the data behind every section | `agents/*/sql`, `agents/pertussis_guidance/data` |
| National Weather Service (api.weather.gov) | forecasts and alerts for the weather agent, refreshed when older than an hour | `agents/weather/.env` |
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
- `agents/pertussis_guidance/HANDOFF.md` and `agents/weather/INTEGRATION.md`:
  each agent's own sample calls and outputs.

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
`.env.example` has placeholders only. Zetaris credentials are read from the
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
  pertussis_guidance/     the pertussis and guidance agents, their data and SQL, setup notes
  weather/                the weather service: agent, risk rules, critic, web app, tests
docs/                     design and plan for the trip planner, the submission checklist
.claude/launch.json       preview configs for the two servers
```
