# Wastewater Visit Planner

<!-- TODO: one-paragraph pitch in your own words. Keep it to what the agent does for a person, not how it is built. -->
An agent that answers "is it safe to visit?" questions from CDC wastewater
surveillance. It reads SARS-CoV-2 and influenza A wastewater data through
Zetaris, plans and writes with Meterless Nightshift (NVIDIA Nemotron routes),
checks every figure it writes against the data it queried, and remembers what
it found so later answers can refer back. A one-screen planner page turns a
trip (where, when, who) into a plan for both viruses.

| | |
|---|---|
| Event | Open Agent Hackathon 2026 (Zetaris, Meterless, NVIDIA) |
| Team | <!-- TODO: names --> |
| Demo video | <!-- TODO: link --> |
| Slides | <!-- TODO: link, or remove the row --> |
| Colab | Not used. The agent runs locally against a local Zetaris and the Nightshift runtime. |

## Contents

- [Setup](#setup) from a clean clone
- [Usage](#usage) with sample inputs
- [Dependencies](#dependencies)
- [Sample inputs and outputs](#sample-inputs-and-outputs)
- [Traces: which model handled each request](#traces-which-model-handled-each-request)
- [Meterless engine check](#meterless-engine-check)
- [Fallbacks when a service is down](#fallbacks-when-a-service-is-down)
- [Secrets](#secrets)
- [Repository layout](#repository-layout)

## Setup

Everything lives under `wastewater/`. Commands below are run from there.

### 1. Prerequisites

| Need | Why | Checked with |
|---|---|---|
| Python 3.11 or newer (developed on 3.13) | the agent, the benchmark and the frontend server | `python --version` |
| A JDK (developed with JDK 23) | the Zetaris JDBC driver runs in a JVM started by JPype | `java -version` |
| Zetaris Lightning platform running in Docker, JDBC on `localhost:10000` | all data access | `python -m wastewater_agent status` |
| The Zetaris JDBC driver jar (`ndp-jdbc-driver-*.jar`, ships with the platform) | JDBC connection | path in `.env` |
| Meterless Nightshift runtime on `http://127.0.0.1:8088/v1` | planner and writer models, judge for the benchmark | `python -m wastewater_agent status` |

Zetaris and Nightshift are installed as described in the hackathon's
getting-started repository; this project only connects to them.

### 2. Install

```bash
pip install -r requirements.txt
```

### 3. Configure

```bash
copy .env.example .env
```

Edit `.env`: the JDBC URL and jar path, `JAVA_HOME` if it is not set globally,
and either `ZETARIS_ENV_FILE` (a file holding `ZETARIS_USERNAME` and
`ZETARIS_PASSWORD`) or those two values directly. The Nightshift token is read
from the runtime's own `proxy-token` file by default, so nothing from Meterless
needs to be copied anywhere. `.env.example` lists every key with placeholders.

### 4. Load the data into Zetaris

Two CDC NWSS exports, each registered as a Lightning filestore table from a
file inside the Zetaris container:

| Table | Dataset | Download |
|---|---|---|
| `wastewater.sars_cov_2` | NWSS SARS-CoV-2 wastewater concentration (data.cdc.gov `g653-rqe2`) <!-- TODO: confirm the dataset id --> | `https://data.cdc.gov/api/views/g653-rqe2/rows.csv?accessType=DOWNLOAD` |
| `wastewater.influenza_a` | NWSS influenza A wastewater data (data.cdc.gov `ymmh-divb`) | `https://data.cdc.gov/api/views/ymmh-divb/rows.csv?accessType=DOWNLOAD` |

```bash
# 1. download both CSVs into wastewater/data/ (git-ignored; ~0.5 GB together)
curl -L -o data/CDC_Wastewater_Data_for_SARS-CoV-2_20261023.csv "https://data.cdc.gov/api/views/g653-rqe2/rows.csv?accessType=DOWNLOAD"
curl -L -o data/CDC_Wastewater_Data_for_Influenza_A_20261026.csv "https://data.cdc.gov/api/views/ymmh-divb/rows.csv?accessType=DOWNLOAD"

# 2. copy them into the Zetaris driver container (one-off)
docker exec zetaris-driver-1 mkdir -p /home/zetaris/customer-data/shared/wastewater
docker cp data/CDC_Wastewater_Data_for_SARS-CoV-2_20261023.csv zetaris-driver-1:/home/zetaris/customer-data/shared/wastewater/
docker cp data/CDC_Wastewater_Data_for_Influenza_A_20261026.csv zetaris-driver-1:/home/zetaris/customer-data/shared/wastewater/

# 3. create the tables (run each file in the Zetaris SQL editor, or with the
#    getting-started repo's scripts/run_sql.py)
#    sql/01_wastewater_create.sql
#    sql/02_influenza_a_create.sql
# 4. verify
#    sql/01_wastewater_select.sql
#    sql/02_influenza_a_select.sql
```

If the file names differ from the ones above (CDC stamps the export date into
the name), change the `PATH` in the two create scripts to match.

### 5. Check everything is reachable

```bash
python -m wastewater_agent status
```

Expected: `zetaris: ok` with a latest sample date per table, `nightshift: online`
with the `meterless/*` routes listed, and the memory counts.

## Usage

### Command line

```bash
python -m wastewater_agent ask "is sars-cov-2 rising in Virginia over the last 2 weeks?"
python -m wastewater_agent ask "is flu rising in California over the last 2 weeks?"
python -m wastewater_agent ask "was covid detected in Texas in September?"
python -m wastewater_agent ask "is sars-cov-2 rising in Virginia over the last 2 weeks?" --county "City of Richmond"
python -m wastewater_agent ask "is flu rising in Ohio last week?" --json   # adds the plan and fact sheet as JSON
```

The answer is followed by the window, the row counts, the plan (virus, intent,
state, county, which provider planned it), every SQL statement run, the
memories used and stored, and one Nightshift receipt per model call.

Other commands:

```bash
python -m wastewater_agent status               # Zetaris, Nightshift, memory
python -m wastewater_agent memory list          # stored findings
python -m wastewater_agent memory show <id>
python -m wastewater_agent feedback <id> helpful|not_helpful|wrong
python -m wastewater_agent audit <id>           # ledger entries for one memory
python -m wastewater_agent sleep [--execute]    # memory consolidation
python -m wastewater_agent benchmark            # see benchmark/README.md
```

### Planner page

```bash
python frontend/server.py --port 8765
```

Open http://127.0.0.1:8765/. Type the destination and home city, the dates and
who is travelling, then "Check the water": the page runs one check per virus and
shows a plan block for each. `frontend/README.md` documents the page and its API.

## Dependencies

| Dependency | Role | Where it is configured |
|---|---|---|
| Zetaris Lightning (Docker, JDBC port 10000) | holds the two CDC tables; every number in an answer comes from SQL run here | `ZETARIS_JDBC_URL`, `ZETARIS_JDBC_JAR`, credentials via `ZETARIS_ENV_FILE` |
| Meterless Nightshift runtime (`127.0.0.1:8088`) | plans the question and writes the answer; `meterless/judge` scores the benchmark | `NIGHTSHIFT_BASE_URL`, `NIGHTSHIFT_TOKEN_FILE`, `NIGHTSHIFT_MODELS` |
| NVIDIA Nemotron models (through Nightshift) | the routes the agent uses: `meterless/auto`, then `nvidia/nemotron-3-ultra-550b-a55b`, then `nvidia/nemotron-3.5-lightning-30b-a3b` | `NIGHTSHIFT_MODELS` |
| Python packages: `jaydebeapi`, `JPype1`, `httpx` | JDBC bridge and HTTP client | `requirements.txt` |
| A JDK | runs the JDBC driver | `JAVA_HOME` |
| Open-Meteo (no key) and Lucide icons (CDN with a local fallback) | the planner page's weather and icons; optional | none |

The NVIDIA API key is configured in Nightshift's Providers tab, not in this
project.

## Sample inputs and outputs

`wastewater/samples/README.md` holds three questions with the full CLI output
for each, including the SQL that was run and the receipts. The planner page's
demo mode (`http://127.0.0.1:8765/?demo=1`) renders two stored answers without
any service.

## Traces: which model handled each request

Every model call returns a Nightshift receipt, and the agent keeps them with
the answer:

- CLI: the `receipt:` lines at the end of every `ask` give the receipt id,
  the routed model, cache state and reclaimed losers; `--json` adds the plan
  and fact sheet.
- Planner page: `GET /api/answers/<id>` returns the stored record with
  `receipts`, `statements` (SQL), `memoriesUsed` and `notes` (every fallback
  that fired); `GET /api/answers/<id>/report.md` renders it as a report.
- Benchmark: `benchmark/results-<timestamp>.json` records, per question, the
  routed model, latency and whether the figure check passed.
- Nightshift app: calls carry `meterless-app: wastewater-agent`, so the app's
  stream shows them under that name.

`wastewater/samples/traces/` holds the JSON traces of the three sample runs.

## Meterless engine check

`python -m wastewater_agent status` is the conformance check: it lists the
routes Nightshift exposes and their availability. `wastewater/samples/conformance.md`
holds a captured run. The benchmark's plan layer is the functional check
(`python -m wastewater_agent benchmark --layers plan`): every question must be
planned by a Nightshift route, and the summary names the model that answered
each one.

## Fallbacks when a service is down

| Situation | What happens |
|---|---|
| A Nightshift route fails (for example `meterless/auto` returning 502) | the next route in `NIGHTSHIFT_MODELS` is tried; the failing one is skipped for five minutes |
| Nightshift unreachable or every route failing | the planner falls back to rules and the writer to sentence templates; the answer is prefixed `[offline]` and the notes say why |
| The model writes a number that is not in the fact sheet | the answer is rejected, retried once, then written from templates |
| No sampling site serves the requested county | the state-level answer is given with a note |
| The requested window has no samples | the most recent 7-day window with data is reported, labelled as such |
| Zetaris unreachable | `status` reports it; `ask` fails with the JDBC error. The planner page's demo mode (`?demo=1`) runs with no services at all |

<!-- TODO (recommended by the rules): a SAMPLE_MODE=true switch that lets `ask` answer from stored fact sheets when Zetaris is down. Not implemented yet; demo mode covers the page only. -->

## Secrets

Nothing secret is in the repository. `.env` is git-ignored and `.env.example`
has placeholders only. Zetaris credentials are read from a file outside the
repo (`ZETARIS_ENV_FILE`), and the Nightshift token from the Meterless runtime's
own token file.

## Repository layout

```
wastewater/
  wastewater_agent/     the agent: cli, agent/ (planner, executor, evaluator, writer, loop),
                        zetaris/ (JDBC and SQL templates), llm/ (nightshift, offline), hmem/ (memory),
                        pathogens.py (virus registry), benchmark.py
  frontend/             server.py (stdlib HTTP server and API) and static/ (the planner page)
  sql/                  create and verification scripts for the two Zetaris tables
  benchmark/            question set, results and README
  samples/              sample inputs, outputs, traces and the engine check
  docs/                 design documents
  .env.example          configuration template
  requirements.txt
```
