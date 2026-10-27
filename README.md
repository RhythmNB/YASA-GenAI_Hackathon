<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="planner/frontend/static/pin-dark.png">
    <img src="planner/frontend/static/pin.png" alt="Insightor logo" width="80">
  </picture>
</p>

<h1 align="center">Insightor</h1>

<p align="center"><em>Decide before you go</em></p>

Should I visit my Grandma in New York? This planner can help you.

| | |
|---|---|
| Event | Open Agent Hackathon 2026 (Zetaris, Meterless, NVIDIA) |
| Team | YASA |
| Demo video | <!-- TODO: link --> |

## Contents

- [Sponsor technology](#sponsor-technology)
- [Setup](#setup) from a clean clone
  - [1. Before you start (once, by hand)](#1-before-you-start-once-by-hand)
  - [2. Run the setup script](#2-run-the-setup-script)
- [Run](#run)
- [The page's API](#the-pages-api)
- [Dependencies](#dependencies)
- [Samples](#samples)
- [Benchmarks and tests](#benchmarks-and-tests)
- [Data sources](#data-sources)
- [Future directions](#future-directions)
- [Repository layout](#repository-layout)

## Sponsor technology

- **Zetaris is the data layer.** Every figure in a plan comes from SQL run
  through Zetaris Lightning over JDBC; no agent calls a data source directly.
  Zetaris holds the CDC wastewater exports for COVID-19 and influenza A as file
  tables (`wastewater.*`), live CDC whooping cough counts as a REST table joined
  with Census populations in views (`cdc_rest.*`, `visitplanner.*`,
  `refdata.*`), the CDC guidance text (`refdata.cdc_guidance`), the National
  Weather Service forecasts in a Postgres registered as a datasource
  (`weather_pg`), and city lookup as REST tables (`geocoding.*`).
  `install.py` registers all of them.
- **Meterless H-MEM is the memory engine.** Each finding is stored as a
  memory record with its place, virus and dates, kept in short-term, working,
  long-term and archived tiers, with a ledger of every action. A newer finding
  supersedes an older one, and a sleep cycle decays and archives what is no
  longer used. H-MEM powers the "Earlier finding on record" line in wastewater
  answers, recalled only for the same place and virus. It also lets the weather
  agent remember household facts such as "Dad uses a walking frame". Test
  result: the memory benchmark found the stored finding in 11 of 11 fresh
  sessions, with the live record ranked first 11 of 11 (25 Oct). The weather
  service's H-MEM tests pass as part of its 43 of 43.
- **Meterless Nightshift is the AI provider.** Every model call goes to
  Nightshift's OpenAI-compatible endpoint on `127.0.0.1:8088`, tagged with
  the app name so its stream groups them. Each answer keeps Nightshift's
  receipt, which names the model that handled it. A route that fails is
  skipped and the next one answers, and `meterless/judge` scores the wastewater
  benchmark.
- **NVIDIA Nemotron does the language work, through Nightshift.**
  `nemotron-3-ultra-550b-a55b` reads the question, writes the wastewater
  answers, writes the plan's intro and checklist, and reviews each draft as the
  evaluator. `nemotron-3.5-lightning-30b-a3b` writes the weather summary and is
  the fallback route. Rules decide the verdict and every risk level, and every
  figure the models write is checked against the data. Results: question
  reading 14 of 14, judge fidelity 9.91 of 10, and Nemotron-written plans
  passed the evaluator 3 of 3.

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

**You need an NVIDIA API key in Nightshift to get the same output as ours** (and as in [samples.md](samples.md)).
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
`--getting-started <folder>`.

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

## The page's API

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
| NVIDIA Nemotron models (through Nightshift) | aliases: `nvidia/nemotron-3-ultra-550b-a55b`, then `nvidia/nemotron-3.5-lightning-30b-a3b`; the weather and pertussis agents use the lightning model | as above |
| CDC data.cdc.gov (NWSS exports, NNDSS pertussis REST), US Census populations, CDC guidance pages | the data behind every section | `agents/*/sql`, `agents/pertussis_guidance/data` |
| National Weather Service (api.weather.gov) | forecasts and alerts for the weather agent, loaded into the `weather-db` Postgres and read through Zetaris; refreshed when older than an hour | `agents/weather/.env`, `agents/weather/docker-compose.yml` |
| Python packages: `jaydebeapi`, `JPype1`, `httpx` (planner and wastewater); the weather service's own `requirements.txt` in its venv | JDBC bridge, HTTP clients | `agents/wastewater/requirements.txt`, `agents/weather/requirements.txt` |
| A JDK | runs the JDBC driver | `JAVA_HOME` |
| Open-Meteo (no key) and Lucide icons (CDN with a local fallback) | the page's weather card and icons; optional | none |

## Samples

- [samples.md](samples.md): three trips from the planner page, one per
  verdict (Stop, Caution, Go), with the inputs and each plan's verdict,
  findings, checklist and best days.
- `planner/frontend/static/sample-plan.json`: a complete travel plan for a
  visit to Richmond, VA with a newborn, captured from a real run on
  2026-10-27; the page's demo mode (`http://127.0.0.1:8765/?demo=1`) renders it
  with no services.

## Benchmarks and tests

| Agent | How it is checked | Latest result |
|---|---|---|
| Planner (verdict rules, composer, evaluator) | `python -m planner.benchmark` | 26/26 rule cases (verdicts, evaluator rule checks, replanning). On the three sample trips: verdict 3/3; Nemotron-written prose 3/3, evaluator passed 3/3; median 48 s (27 Oct) |
| Wastewater (COVID-19, flu) | `python -m wastewater_agent benchmark`, from `agents/wastewater/` | Question reading 14/14 exact (27 Oct, `nemotron-3-ultra-550b-a55b`). Answers 10/11 passed the figure check first time, judge fidelity 9.91/10 and clarity 10/10; memory recall 11/11 with the live record first 11/11 (25 Oct, `nemotron-3.5-lightning-30b-a3b`) |
| Pertussis | Its own evaluator: every rewrite must pass rule checks (numbers, citations, no risk scores) and a second Nemotron reviewer, up to 3 tries, or the template is used | No separate benchmark. The planner takes its counts and labels, not its prose |
| Guidance | Rules only, no model: CDC text quoted word for word | Nothing to score |
| Weather | `pytest`, from `agents/weather/` with its `.venv` | 43/43 tests pass (27 Oct) |

The planner benchmark has three layers:
- `rules`: hand-written cases, no services.
- `compose`: the composer and evaluator on the findings saved from the [samples.md](samples.md) trips (`planner/benchmark/fixtures/`). Needs Nightshift.
- `e2e`: full plans for the same trips. Needs Zetaris, Nightshift and the weather service; about 10 minutes. Opt-in: `--layers rules,compose,e2e`.

## Data sources

- Wastewater exports are CDC's weekly NWSS files; a county with no recent samples is answered at state level and labelled so.
- Pertussis counts are state level only (New York City is the exception), provisional and often revised.
- CDC guidance rows are a snapshot from 2026-10-26.
- Weather covers the 217 US cities and the 7-day NWS forecast.

## Future directions

- Alerts before a saved visit when activity changes.
- Forecasts of where activity is heading, using past seasons' flu, RSV and
  COVID-19 trends and temperature changes.
- Clinician review of the guidance wording.
- More pathogens, such as RSV and measles.
- Immunocompromised people as a household group, alongside elderly, newborn and
  pregnant visitors.

## Repository layout

```
planner/                  the orchestration layer (Python package `planner`)
  planner_agent.py        fan-out to the four agents in parallel, progress events, timeouts
  composer.py             verdict rules, fact sheet, Nightshift prose with figure check, template fallback
  adapters/               wastewater.py, pertussis.py, guidance.py, weather.py: agent result -> Finding
  findings.py, trip.py    the Finding, Verdict, TravelPlan and TripRequest shapes
  cli.py                  python -m planner
  geocode.py              locate each city through Zetaris via API
  benchmark/              python -m planner.benchmark: rule cases, composer and evaluator runs, fixtures, results
  frontend/               server.py (stdlib HTTP server and API) and static/ (the planner page)
agents/
  wastewater/             wastewater_agent/ (cli, planner, executor, evaluator, writer, memory), sql/, benchmark/, samples/, docs/
  pertussis_guidance/     the pertussis and guidance agents, their data and SQL
  weather/                the weather service: agent, risk rules, critic, web app, tests
install.py                one-command setup (see Setup)
```
