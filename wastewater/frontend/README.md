# Wastewater Visit Planner (frontend)

A one-screen planner over the wastewater agent. You say where you're going,
where from, when, and who's travelling; the page checks the CDC wastewater
data for the destination's state and shows the forecast for the trip.
`server.py` is standard-library Python; the page is plain HTML, CSS and
JavaScript with no build step. Lucide icons and Open-Meteo forecasts are
loaded from the network and degrade gracefully offline.

## Run

From `wastewater/`, with Zetaris (Docker) and Nightshift running:

```bash
python frontend/server.py --port 8765
```

Open http://127.0.0.1:8765/. The first check starts the JVM for the JDBC
driver, so it takes a few seconds longer.

**Demo mode**: http://127.0.0.1:8765/?demo=1 renders `static/sample-answer.json`
(a real Virginia COVID answer captured on 2026-10-25) and
`static/sample-answer-flu.json` (a Richmond City influenza A answer captured on
2026-10-26) without calling the agent.

## The page

Dashboard layout: a pill top bar (brand, Plan, Guidance, status dots, theme);
left column an image card carrying a floating white card with the trip title,
dates, party and a map of the destination, then the weather card; right
column the trip sentence and "Your plan", one block per virus (COVID-19, then
influenza A), each with a coverage badge, the agent's text and bullet points.
No captions or footnotes on the Plan page.

- **Hero**: the family illustration; the title becomes the destination city
  and state once chosen, with the dates and party in the crumb.
- **Plan tab**: two cards and, after a check, the answer.
  - *The trip*, written as a sentence you complete: destination city, home
    city, arrival and departure dates, number of adults and children. You type
    a city and pick it from the suggestions; the server's `/api/geocode`
    (Open-Meteo's geocoder, no key) maps it to its county, state and
    coordinates, and the page shows "county, state" under the title. The field
    and the title show the city alone. **Check the water** runs two checks in
    turn, "is sars-cov-2 rising in {state} over the last 2 weeks?" and the
    same for flu, each sent with the city's county and a `pathogen` key; the
    agent counts only the sampling sites that serve that county (the dataset's
    `counties_served` column), falling back to the whole state with a note
    when no site serves the county. A check that fails shows its error inside
    its own block and the other block still fills. **Add to calendar**
    downloads an all-day event (.ics) for the dates with the party, the route
    and both readings in the description and a reminder two days before;
    **Google Calendar** opens the same event pre-filled.
  - *Weather*: the destination for your dates (today's high and low, condition,
    rain chance, up to six day chips) and, beneath, the home city over the
    same days for comparison. Open-Meteo, up to 16 days ahead.
  - *Your plan*: a block per virus with a coverage badge, the agent's text and
    bullets for the region and period, share of samples with the virus, latest
    data date and when to check again. The map pin's popup lists both
    readings.
- **Guidance tab**: how to read the answer, pre-travel tips, sources, and the
  disclaimer. Full page without the hero.
- Theme toggle in the top bar; light and dark.

## API used

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/geocode?q=` | typed city to candidates with county, state code and coordinates (US only, cached) |
| GET | `/api/status` | Zetaris, Nightshift and memory counts |
| POST | `/api/ask` `{question, county?, pathogen?}` | run the agent; `county` (any common form, e.g. "City of Richmond") narrows to that county's sites; `pathogen` is `sars-cov-2` (default) or `flu-a` (table `wastewater.influenza_a`), unknown keys get 400 |

The server also still serves `/api/answers`, `/api/memory`, `/api/feedback`
and `/api/states` for the CLI-style views, but this page does not use them.
Static files are sent with `Cache-Control: no-cache` and the script and
stylesheet URLs carry a version query, so a reload always pairs the current
HTML with the current script. Lucide icons load from unpkg with a local copy
in `static/vendor/` as fallback.

## Notes

- One agent instance per server process (the JVM can start only once); checks
  are serialised with a lock. H-MEM records persist in `../.hmem/` as usual.
- Binds to 127.0.0.1 by default; no authentication.
- Only the city coordinates go to Open-Meteo. Nothing about the trip or the
  answer leaves the machine except the model calls Nightshift already makes.
- Adults and children are shown in the hero and written into the calendar
  event; the surveillance check itself is per state and does not use them.
