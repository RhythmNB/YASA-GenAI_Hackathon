# Visit Planner (frontend)

A one-screen planner over the four agents. You say where you're going, where
from, when, who's travelling and who you'll be with; the page asks the planner
agent, shows each agent reporting in as it runs, and renders the composed
travel plan. `server.py` is standard-library Python; the page is plain HTML,
CSS and JavaScript with no build step. Lucide icons and Open-Meteo forecasts
are loaded from the network and degrade gracefully offline.

## Run

From the repository root, with Zetaris (Docker) and Nightshift running:

```bash
python planner/frontend/server.py --port 8765
```

The server starts the weather service on port 8770 when nothing answers there
(`weather_service.py`, using `agents/weather/.venv`), checks it before each plan
and restarts it if it has stopped, and stops it on exit; a weather service you
started yourself is reused and left alone. `--no-weather` turns this off.

Open http://127.0.0.1:8765/. The first plan starts the JVM for the JDBC
driver, so it takes a few seconds longer; a full plan takes one to two
minutes, most of it the weather agent's model calls.

**Demo mode**: http://127.0.0.1:8765/?demo=1 renders `static/sample-plan.json`
(a real plan for Richmond, VA with a newborn, captured on 2026-10-27) with a
replayed progress card and no services.

## The page

Layout: a top bar with the brand and the theme toggle; a 340px sidebar on the
left that sticks while you scroll, holding, in order, the trip form with its
buttons, the destination (the title, dates, party and a small map) and the
weather; and "Your plan" filling the rest of the width as the main display.
The family illustration sits behind the whole page at low opacity (`hero.jpg`,
22% in light mode, 14% in dark). Below about 960px the sidebar stacks above the
plan. No captions or footnotes on the Plan page.

- **Destination**: the title becomes the destination city once chosen, with
  the dates and party beneath and the map under that.
- **The trip**, four labelled rows: Location (home city to destination city),
  Dates (arrival to departure), Travellers (adults and children steppers) and
  Visiting, four small toggles for who you will be with: elderly, kids,
  newborn, pregnant. Only the toggles you switch on are passed to the agents.
  You type a city and pick it from the suggestions; the server's `/api/geocode`
  (Open-Meteo's geocoder, no key) maps it to its county, state and coordinates.
- **Plan this visit** sends one request to `POST /api/plan` and reads the
  streamed progress. The progress card (bottom right) shows the current step
  and a trail: each agent with its level, the model that handled it and the
  seconds it took, every Nightshift route the wastewater agent tried, then the
  composer's model.
- **Your plan**: the verdict as a large label and tagline in the level's
  colour, Go (good to go), Caution (go with care) or Stop (reconsider, or go
  with full precautions), or No signal when no source had data; the header
  turns the same solid green, amber or red once a plan exists. The reason
  sentence is kept in the report and the calendar event. Then the intro, then one collapsed row per source (COVID-19 in
  wastewater, flu in wastewater, whooping cough, weather, CDC guidance) with
  an icon and a risk word: low risk, moderate risk, high risk, no recent data,
  unavailable, or advice. Each row expands to a one-sentence meaning, bullet
  facts, caveats and, for the health and weather sources, a further "Full
  answer from the agent" disclosure with the agent's own text; guidance shows
  CDC's bullets directly. A source that failed shows its error in its row.
  Before anything is composed, the Evaluator agent reviews what the agents
  returned and can send the planner back once (`MAX_REPLANS = 1`): a failed
  agent is asked again, and a county with no recent wastewater samples is
  asked again at state level. A new answer replaces the first only when it
  says more, and a state-wide reading carries a caveat saying so. The
  progress card shows the request and each re-ask, and "Sources and models"
  lists them.
  Before it is shown, every draft goes to the Evaluator agent (rule checks
  plus a Nightshift review); on "revise" the composer rewrites with the
  issues listed, at most twice. The progress card shows each review round,
  and "Sources and models" says which draft passed.
  Then "Before you go" (the precautions as a checklist, always in full),
  "Best days outdoors", and a collapsed "Sources and models" disclosure. The
  map pin's popup lists the wastewater and weather levels.
- **Add to calendar** downloads an all-day event (.ics) with the party, the
  route, the verdict, the intro and the precautions in the description and a
  reminder two days before; a Google Calendar button, when present in the
  markup, opens the same event pre-filled.
- **Download**, a menu at the top right of "Your plan" once a plan exists,
  offers the report as Markdown (.md) or plain text (.txt), the plan's data
  as JSON, or a PDF through the browser's print dialog (the print stylesheet
  shows only the plan with every section expanded). Files are named
  `visit-plan-<city>-<start>.<ext>` and built on the page, so they work in
  demo mode too; the server's `/api/plans/<id>/report.md` renders the same
  Markdown server-side.
- **The last plan survives a refresh.** After a plan renders, the page keeps
  it with the trip fields in the browser's local storage and restores both on
  load, so the plan and its report stay available until the next plan replaces
  them. Demo mode never stores anything.
- **Weather card**: the destination for your dates and the home city beneath,
  from Open-Meteo, up to 16 days ahead. Independent of the weather agent.
- Theme toggle in the top bar; light and dark.

## API used

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/geocode?q=` | typed city to candidates with county, state code and coordinates (US only, cached) |
| GET | `/api/status` | Zetaris (both tables), Nightshift, the weather service and memory counts |
| POST | `/api/plan` `{toCity, toState, toCounty?, fromCity, fromState, start, end, adults, children, with[], stream?}` | run the planner; with `stream: true` the reply is newline-delimited JSON progress events ending in `{"stage": "plan", "plan": ...}`; bad input gets 400 |
| GET | `/api/plans`, `/api/plans/<id>`, `/api/plans/<id>/report.md` | plans made by this server process, one record, a Markdown report |
| POST | `/api/ask` `{question, county?, pathogen?, stream?}` | the wastewater agent alone (not used by the page any more) |

The server also serves `/api/answers`, `/api/memory`, `/api/feedback` and
`/api/states` for the wastewater agent's CLI-style views. Static files are
sent with `Cache-Control: no-cache` and the script and stylesheet URLs carry a
version query, so a reload always pairs the current HTML with the current
script. Lucide icons load from unpkg with a local copy in `static/vendor/` as
fallback.

## Notes

- One wastewater agent and one planner per server process (the JVM can start
  only once); plans are serialised with a lock. H-MEM records persist in
  `agents/wastewater/.hmem/` as usual.
- The weather service URL is `WEATHER_SERVICE_URL` (default
  `http://127.0.0.1:8770`).
- Binds to 127.0.0.1 by default; no authentication.
- Only the city coordinates go to Open-Meteo. Nothing about the trip or the
  plan leaves the machine except the model calls Nightshift already makes and
  the weather service's NWS refresh.
