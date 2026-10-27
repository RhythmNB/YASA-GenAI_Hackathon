# Trip Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One request (destination, home, dates, who is visited) runs the wastewater, pertussis, guidance and weather agents in parallel, and a composer turns their findings into a verdict-first travel plan shown on the existing planner page.

**Architecture:** A new `planner` package (planner agent, adapters, composer) sits at the repo root and imports the wastewater agent in-process, imports the pertussis and guidance modules from the handoff folder, and calls the weather service over HTTP. The frontend server moves under `planner/` and gains a streaming `POST /api/plan`; the page's progress card and "Your plan" card render the TravelPlan. The three agent folders move under `agents/`.

**Tech Stack:** Python 3.13 standard library plus `httpx` (already a wastewater dependency); the wastewater agent's `NightshiftProvider`, figure-check helpers and JDBC client; plain HTML/CSS/JS page with no build step.

**Spec:** `docs/2026-10-27-trip-planner-design.md`. The project keeps no test suite by the user's choice; each task ends with a verification command instead of a test, and nothing is committed (the user manages git).

**Conventions:** Run Python commands from the repo root `F:\Hackathon\YASA-GenAI_Hackathon` unless a step says otherwise. In Git Bash, long Python edits go through a scratch `patch_*.py` run with `python -I`, not heredocs. Never touch the user's server on port 8765; verify on the preview (`launch.json`, lands on 8766).

---

## File map

| Path | Responsibility |
|---|---|
| `agents/wastewater/` | moved `wastewater/`, unchanged inside |
| `agents/pertussis_guidance/` | moved `visit-planner-handoff/`, unchanged inside |
| `agents/weather/` | moved `weather_service/`, venv recreated |
| `planner/__init__.py` | package marker, repo path helpers |
| `planner/findings.py` | `Finding`, `Verdict`, `TravelPlan`, level tables, JSON |
| `planner/trip.py` | `TripRequest`, toggle mappings |
| `planner/adapters/wastewater.py` | two wastewater answers → two Findings |
| `planner/adapters/pertussis.py` | pertussis briefing → Finding |
| `planner/adapters/guidance.py` | CDC guidance → Finding (quoted, no level) |
| `planner/adapters/weather.py` | weather service HTTP → Finding |
| `planner/composer.py` | verdict rules, fact sheet, Nightshift prose, template |
| `planner/planner_agent.py` | parallel fan-out, progress, timeouts, calls composer |
| `planner/cli.py`, `planner/__main__.py` | `python -m planner ...` |
| `planner/frontend/server.py` | moved; `/api/plan` stream, `/api/plans`, status weather |
| `planner/frontend/static/{index.html,app.js,styles.css}` | toggles, button, progress, plan card |
| `planner/frontend/static/sample-plan.json` | demo plan from a real run |
| `README.md`, `docs/SUBMISSION-CHECKLIST.md`, READMEs and SETUP-NOTES | path updates and planner usage |

---

### Task 1: Restructure the folders

**Files:**
- Move: `wastewater/` → `agents/wastewater/` (tracked files via `git mv`)
- Move: `wastewater/frontend/` → `planner/frontend/` (untracked, plain move)
- Move: `visit-planner-handoff/` → `agents/pertussis_guidance/` (untracked)
- Move: `weather_service/` → `agents/weather/` (untracked)
- Move: `wastewater/SUBMISSION-CHECKLIST.md` → `docs/SUBMISSION-CHECKLIST.md`
- Modify: `.claude/launch.json`, `planner/frontend/server.py:37-38`

- [ ] **Step 1: Move the tracked wastewater folder with git so history follows**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && mkdir -p agents planner docs && git mv wastewater agents/wastewater && git status --short | head -5
```

Expected: lines like `R  wastewater/wastewater_agent/cli.py -> agents/wastewater/wastewater_agent/cli.py` (renames staged, nothing committed). The untracked files inside (`frontend/`, `samples/`, `pathogens.py`, ...) move with the directory on disk.

- [ ] **Step 2: Move the untracked folders**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && mv agents/wastewater/frontend planner/frontend && mv agents/wastewater/SUBMISSION-CHECKLIST.md docs/SUBMISSION-CHECKLIST.md && mv visit-planner-handoff agents/pertussis_guidance && mv weather_service agents/weather && ls agents planner docs
```

Expected: `agents: pertussis_guidance  wastewater  weather`, `planner: frontend`, `docs: 2026-10-27-trip-planner-design.md  2026-10-27-trip-planner-plan.md  SUBMISSION-CHECKLIST.md`.

- [ ] **Step 3: Confirm the getting-started junction survived the move**

```powershell
Get-Item "F:\Hackathon\YASA-GenAI_Hackathon\agents\pertussis_guidance\getting-started" | Select-Object LinkType, Target; Test-Path "F:\Hackathon\YASA-GenAI_Hackathon\agents\pertussis_guidance\getting-started\scripts\zetaris_sql.py"
```

Expected: `Junction  F:\Hackathon\getting-started` and `True`. If the junction is missing, recreate it: `New-Item -ItemType Junction -Path "F:\Hackathon\YASA-GenAI_Hackathon\agents\pertussis_guidance\getting-started" -Target "F:\Hackathon\getting-started"`.

- [ ] **Step 4: Recreate the weather venv (its scripts embed the old absolute path)**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon/agents/weather && rm -rf .venv && python -m venv .venv && ./.venv/Scripts/python -m pip install -q --disable-pip-version-check -r requirements.txt && ./.venv/Scripts/python -m pytest -q tests 2>&1 | tail -2
```

Expected: `43 passed in ...s`.

- [ ] **Step 5: Point the frontend server at the moved wastewater package**

Replace lines 37-38 of `planner/frontend/server.py`:

```python
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
```

with:

```python
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent  # planner/frontend -> repo root
sys.path.insert(0, str(REPO))                                 # the planner package
sys.path.insert(0, str(REPO / "agents" / "wastewater"))      # the wastewater_agent package
```

- [ ] **Step 6: Update launch.json paths**

Replace the whole of `.claude/launch.json` with:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "planner-frontend",
      "runtimeExecutable": "python",
      "runtimeArgs": ["planner/frontend/server.py", "--port", "8765"],
      "port": 8765
    },
    {
      "name": "weather-service",
      "runtimeExecutable": "agents/weather/.venv/Scripts/python.exe",
      "runtimeArgs": ["agents/weather/web_app.py", "--no-browser", "--port", "8770"],
      "port": 8770
    }
  ]
}
```

- [ ] **Step 7: Fix path mentions in docs and notes**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && grep -rln "wastewater/frontend\|visit-planner-handoff\|weather_service\|wastewater/samples\|wastewater/sql\|wastewater/\.env\|wastewater/benchmark\|wastewater/wastewater_agent\|wastewater/requirements\|wastewater/SUBMISSION" README.md docs agents/*/SETUP-NOTES.md agents/wastewater/samples agents/wastewater/benchmark/README.md planner/frontend/README.md 2>/dev/null
```

For each listed file apply, in this order, with `sed -i`:

```bash
sed -i -e 's#wastewater/frontend#planner/frontend#g' -e 's#visit-planner-handoff#agents/pertussis_guidance#g' -e 's#weather_service#agents/weather#g' -e 's#wastewater/samples#agents/wastewater/samples#g' -e 's#wastewater/sql#agents/wastewater/sql#g' -e 's#wastewater/\.env#agents/wastewater/.env#g' -e 's#wastewater/benchmark#agents/wastewater/benchmark#g' -e 's#wastewater/wastewater_agent#agents/wastewater/wastewater_agent#g' -e 's#wastewater/requirements#agents/wastewater/requirements#g' -e 's#wastewater/SUBMISSION-CHECKLIST.md#docs/SUBMISSION-CHECKLIST.md#g' <file>
```

Then re-run the grep; expected: no output. (The root README's setup section is rewritten fully in Task 9, so only the paths need to be right here.)

- [ ] **Step 8: Verify the moved parts still run**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon/agents/wastewater && python -m wastewater_agent status 2>&1 | grep -v SLF4J | head -4
cd /f/Hackathon/YASA-GenAI_Hackathon/agents/pertussis_guidance/agents && python pertussis_agent.py AZ CA --no-llm --channel jdbc 2>&1 | grep -v SLF4J | tail -1
cd /f/Hackathon/YASA-GenAI_Hackathon && python -c "import sys; sys.path.insert(0,'planner/frontend'); import server; print('server imports ok')"
```

Expected: `zetaris:` / `ok ...` lines; `(written by: template)`; `server imports ok`.

---

### Task 2: Findings and TripRequest

**Files:**
- Create: `planner/__init__.py`, `planner/findings.py`, `planner/trip.py`

- [ ] **Step 1: Create `planner/__init__.py`**

```python
"""Trip planner: a planner agent fans a visit request out to the wastewater,
pertussis, guidance and weather agents; a composer agent turns the findings
into one travel plan. See docs/2026-10-27-trip-planner-design.md."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = REPO / "agents"


def add_agent_paths() -> None:
    """Make the in-process agents importable: wastewater_agent (a package) and the
    pertussis/guidance modules (plain scripts in the handoff folder)."""
    for p in (AGENTS / "wastewater", AGENTS / "pertussis_guidance" / "agents"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


add_agent_paths()
```

- [ ] **Step 2: Create `planner/findings.py`**

```python
"""The shapes the planner and composer exchange: one Finding per agent, one
Verdict, one TravelPlan. Rules live in the adapters and the composer; this
module only holds data and its JSON form."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

ORDER = ["covid", "flu", "pertussis", "weather", "guidance"]
TITLES = {
    "covid": "COVID-19 in wastewater",
    "flu": "Flu (influenza A) in wastewater",
    "pertussis": "Whooping cough",
    "weather": "Weather",
    "guidance": "CDC guidance",
}
LEVEL_RANK = {"unknown": 0, "low": 1, "moderate": 2, "high": 3}
LEVEL_LABEL = {
    "high": "Reconsider, or go with full precautions",
    "moderate": "Go with care",
    "low": "Good to go",
    "unknown": "Not enough data to judge",
}


@dataclass
class Finding:
    source: str
    title: str
    status: str = "ok"          # ok | error | skipped
    level: str = "unknown"      # low | moderate | high | unknown
    headline: str = ""
    text: str = ""
    facts: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    model: str | None = None
    trace: str | None = None
    seconds: float = 0.0
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def failed(source: str, error: str, seconds: float = 0.0, status: str = "error") -> Finding:
    return Finding(source=source, title=TITLES[source], status=status, level="unknown",
                   headline="Not available", error=error, caveats=[error], seconds=seconds)


@dataclass
class Verdict:
    level: str
    label: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class TravelPlan:
    trip: dict[str, Any]
    verdict: Verdict
    intro: str
    sections: list[Finding]
    precautions: list[str]
    best_days: list[str]
    sources: list[dict[str, str]]
    models: dict[str, str | None]
    traces: dict[str, str | None]
    notes: list[str] = field(default_factory=list)
    partial: bool = False
    elapsed_seconds: float = 0.0
    id: str = field(default_factory=lambda: "plan_" + uuid.uuid4().hex[:10])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "createdAt": self.created_at,
            "elapsedSeconds": round(self.elapsed_seconds, 1),
            "partial": self.partial,
            "trip": self.trip,
            "verdict": self.verdict.to_dict(),
            "intro": self.intro,
            "sections": [s.to_dict() for s in self.sections],
            "precautions": self.precautions,
            "bestDays": self.best_days,
            "sources": self.sources,
            "models": self.models,
            "traces": self.traces,
            "notes": self.notes,
        }
```

- [ ] **Step 3: Create `planner/trip.py`**

```python
"""The visit request and the fixed mappings from its toggles to what each agent
understands. Only stated groups are passed on; nothing is inferred."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

GROUPS = ("older_adult", "young_child", "newborn", "pregnant")
GROUP_WORDS = {"older_adult": "older adults", "young_child": "young children",
               "newborn": "a newborn", "pregnant": "someone pregnant"}
WEATHER_GROUPS = {"older_adult": "older_adult", "young_child": "young_child",
                  "newborn": "infant", "pregnant": "pregnant"}


@dataclass
class TripRequest:
    to_city: str
    to_state: str                    # two-letter code, lowercase
    from_city: str
    from_state: str                  # two-letter code, lowercase
    start: date
    end: date
    to_county: str | None = None     # wastewater agent form, e.g. "Richmond City"
    adults: int = 2
    children: int = 0
    with_: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TripRequest":
        """Accepts the page's keys (toCity, toState, ...) or snake_case."""
        g = lambda camel, snake: d.get(camel) if d.get(camel) is not None else d.get(snake)  # noqa: E731
        groups = tuple(x for x in (d.get("with") or d.get("with_") or []) if x in GROUPS)
        try:
            start, end = date.fromisoformat(str(g("start", "start"))), date.fromisoformat(str(g("end", "end")))
        except (TypeError, ValueError) as e:
            raise ValueError("start and end must be ISO dates (YYYY-MM-DD)") from e
        to_state, from_state = str(g("toState", "to_state") or "").lower(), str(g("fromState", "from_state") or "").lower()
        if len(to_state) != 2 or len(from_state) != 2:
            raise ValueError("toState and fromState must be two-letter state codes")
        if not g("toCity", "to_city"):
            raise ValueError("toCity is required")
        return cls(
            to_city=str(g("toCity", "to_city")).strip(), to_state=to_state,
            from_city=str(g("fromCity", "from_city") or "").strip(), from_state=from_state,
            start=min(start, end), end=max(start, end),
            to_county=(str(g("toCounty", "to_county")).strip() or None) if g("toCounty", "to_county") else None,
            adults=max(1, int(g("adults", "adults") or 1)), children=max(0, int(g("children", "children") or 0)),
            with_=groups,
        )

    # -- mappings ---------------------------------------------------------

    @property
    def label(self) -> str:
        return f"{self.to_city}, {self.to_state.upper()}"

    @property
    def sensitive(self) -> bool:
        return bool(self.with_)

    def guidance_profile(self) -> tuple[str, bool]:
        """(profile, pregnant): newborn wins over older_adult; 'general' when neither."""
        pregnant = "pregnant" in self.with_
        if "newborn" in self.with_:
            return "newborn", pregnant
        if "older_adult" in self.with_:
            return "older_adult", pregnant
        return "general", pregnant

    def weather_groups(self) -> list[str]:
        return [WEATHER_GROUPS[g] for g in self.with_]

    def household(self) -> str:
        words = [GROUP_WORDS[g] for g in self.with_]
        return ", ".join(words) if words else "no stated higher-risk group"

    def to_dict(self) -> dict[str, Any]:
        return {"toCity": self.to_city, "toState": self.to_state, "toCounty": self.to_county,
                "fromCity": self.from_city, "fromState": self.from_state,
                "start": self.start.isoformat(), "end": self.end.isoformat(),
                "adults": self.adults, "children": self.children, "with": list(self.with_)}
```

- [ ] **Step 4: Verify the two modules**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python -c "
from planner.trip import TripRequest
from planner.findings import Finding, TravelPlan, Verdict, failed
t = TripRequest.from_dict({'toCity':'Richmond','toState':'VA','toCounty':'Richmond City','fromCity':'Austin','fromState':'tx','start':'2026-11-10','end':'2026-11-17','with':['newborn','pregnant','bogus']})
print(t.label, t.guidance_profile(), t.weather_groups(), t.sensitive, t.household())
print(failed('weather','down').to_dict()['status'])
"
```

Expected: `Richmond, VA ('newborn', True) ['infant', 'pregnant'] True a newborn, someone pregnant` and `error`.

---

### Task 3: Adapters

**Files:**
- Create: `planner/adapters/__init__.py`, `planner/adapters/wastewater.py`, `planner/adapters/pertussis.py`, `planner/adapters/guidance.py`, `planner/adapters/weather.py`

- [ ] **Step 1: Create `planner/adapters/__init__.py`**

```python
"""One adapter per agent. Each turns an agent's own result into a Finding and
assigns its level by fixed rules; none of them changes the agent's output."""
```

- [ ] **Step 2: Create `planner/adapters/wastewater.py`**

```python
"""COVID-19 and influenza A from the wastewater agent (in-process)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from wastewater_agent.agent import Agent
from wastewater_agent.agent.writer import render_facts
from wastewater_agent.states import state_name

from ..findings import TITLES, Finding, failed
from ..trip import TripRequest

SOURCE_BY_KEY = {"sars-cov-2": "covid", "flu-a": "flu"}
WORD_BY_KEY = {"sars-cov-2": "sars-cov-2", "flu-a": "flu"}
NWSS = {"title": "CDC National Wastewater Surveillance System (via Zetaris)", "url": "https://www.cdc.gov/nwss/"}


def level_for(share: float | None, direction: str | None, coverage: str) -> str:
    if coverage == "empty" or share is None:
        return "unknown"
    if share >= 0.8 and direction == "rising":
        return "high"
    if share >= 0.5 or direction == "rising":
        return "moderate"
    return "low"


def run(agent: Agent, trip: TripRequest, pathogen_key: str,
        progress: Callable[[dict[str, Any]], None] | None = None) -> Finding:
    source = SOURCE_BY_KEY[pathogen_key]
    question = f"is {WORD_BY_KEY[pathogen_key]} rising in {state_name(trip.to_state)} over the last 2 weeks?"
    t0 = time.perf_counter()

    def forward(e: dict[str, Any]) -> None:  # only the route events, tagged with the source
        if progress and e.get("stage") == "route":
            progress({"stage": source, "state": "route", "route_state": e.get("state"), "model": e.get("model")})

    try:
        answer = agent.ask(question, county=trip.to_county, pathogen=pathogen_key, progress=forward)
    except Exception as e:  # noqa: BLE001  (ZetarisError, ProviderError, ...)
        return failed(source, f"{e.__class__.__name__}: {str(e)[:200]}", time.perf_counter() - t0)

    f = answer.facts
    empty = f.coverage == "empty"
    share = f.fallback_positive_share if empty else f.positive_share
    samples = (f.fallback_samples or 0) if empty else f.samples
    sites = (f.fallback_sites or 0) if empty else f.sites
    window = f.fallback_window if empty and f.fallback_window else f.window
    level = level_for(share, f.direction, f.coverage)
    pct = "n/a" if share is None else f"{share * 100:.0f}%"
    trend = f", {f.direction}" if f.direction and f.direction != "unknown" else ""
    headline = (f"{pct} of {samples} samples positive{trend} in {f.region}"
                if samples else f"No samples for {f.region} in the period")
    facts = [f"Period {window.start} to {window.end}" + (" (most recent window with data)" if empty else ""),
             f"{samples} samples from {sites} sites; latest sample {f.latest_sample_date or 'unknown'}"]
    if f.prior_positive_share is not None and f.delta_share is not None:
        facts.append(f"Preceding window {f.prior_positive_share * 100:.0f}% positive ({f.delta_share:+.1f} points)")
    caveats = list(f.notes) + ([f.state_note] if f.state_note else []) + list(answer.fallback_reasons)
    model = (answer.completions[-1].routed_model if answer.provider == "nightshift" and answer.completions else "template")
    return Finding(
        source=source, title=TITLES[source], status="ok", level=level, headline=headline,
        text=answer.text, facts=facts, caveats=caveats, sources=[NWSS], model=model,
        trace=answer.memory.id if answer.memory else None, seconds=time.perf_counter() - t0,
        raw={"question": question, "facts": f.to_dict(), "factSheet": render_facts(f),
             "statements": list(answer.statements),
             "receipts": [{"receiptId": c.receipt_id, "routedModel": c.routed_model} for c in answer.completions],
             "coverage": f.coverage, "positiveShare": share, "direction": f.direction},
    )
```

- [ ] **Step 3: Create `planner/adapters/pertussis.py`**

```python
"""Whooping cough counts from the handoff's pertussis agent (in-process, JDBC,
no model call: the composer writes the prose)."""

from __future__ import annotations

import time
from typing import Any

from ..findings import TITLES, Finding, failed
from ..trip import TripRequest


def level_for(state: dict[str, Any]) -> str:
    if not state.get("data_ok") or state.get("trend") == "unknown":
        return "unknown"
    higher = str(state.get("trend", "")).startswith("higher")
    above = str(state.get("vs_national", "")).startswith("above")
    if higher and above:
        return "high"
    if higher or above:
        return "moderate"
    return "low"


def run(trip: TripRequest) -> Finding:
    import pertussis_agent  # from agents/pertussis_guidance/agents (sys.path set in planner/__init__)

    t0 = time.perf_counter()
    try:
        res = pertussis_agent.pertussis_activity([trip.from_state.upper(), trip.to_state.upper()],
                                                 use_llm=False, channel="jdbc")
        dest_name = pertussis_agent.resolve_state(trip.to_state.upper())
    except Exception as e:  # noqa: BLE001
        return failed("pertussis", f"{e.__class__.__name__}: {str(e)[:200]}", time.perf_counter() - t0)

    states = res["facts"]["states"]
    dest = next((s for s in states if s["state"] == dest_name), None) or {"state": dest_name, "trend": "unknown", "data_ok": False, "notes": []}
    level = level_for(dest)
    cases = dest.get("ytd_cases")
    rate = dest.get("ytd_rate_per_100k")
    if cases is not None and rate is not None:
        headline = f"{int(cases)} cases this year in {dest_name} ({rate} per 100,000), {dest.get('trend')}; {dest.get('vs_national')}"
    else:
        headline = f"No complete 2026 count for {dest_name}"
    facts = []
    for s in states:
        if s.get("ytd_cases") is not None:
            facts.append(f"{s['state']}: {int(s['ytd_cases'])} cases so far this year ({s.get('ytd_rate_per_100k')} per 100,000), "
                         f"{s.get('trend')}, {s.get('vs_national')}")
        else:
            facts.append(f"{s['state']}: no complete count this year")
    nat = res["facts"].get("national") or {}
    if nat.get("ytd_rate_per_100k") is not None:
        facts.append(f"National rate {nat['ytd_rate_per_100k']} per 100,000, data to CDC week {res['facts'].get('as_of_mmwr_week')}")
    caveats = list(dest.get("notes", [])) + list(res["facts"].get("general_caveats", []))
    return Finding(
        source="pertussis", title=TITLES["pertussis"], status="ok", level=level, headline=headline,
        text=res["briefing"], facts=facts, caveats=caveats,
        sources=[{"title": s["title"], "url": s["url"]} for s in res.get("sources", [])],
        model="template", trace=res.get("method"), seconds=time.perf_counter() - t0,
        raw={"facts": res["facts"], "method": res.get("method"), "destination": dest},
    )
```

Note: `national(rows)` in the pertussis agent returns `{"ytd_cases", "prev_ytd_cases", "ytd_rate_per_100k", "ratio_vs_last_year", "states_included"}`; the code above uses `ytd_rate_per_100k`.

- [ ] **Step 4: Create `planner/adapters/guidance.py`**

```python
"""CDC guidance from the handoff's guidance agent. Quoted as returned; never
given a risk level and never passed through a model."""

from __future__ import annotations

import time

from ..findings import TITLES, Finding, failed
from ..trip import TripRequest

GENERAL_PROFILE = {
    "label": "family and friends",
    "audiences": ["visitor_any"],
    "pathogens": ["respiratory", "influenza", "covid"],
}


def run(trip: TripRequest, pertussis_rising: bool) -> Finding:
    import guidance_agent  # from agents/pertussis_guidance/agents

    t0 = time.perf_counter()
    profile, pregnant = trip.guidance_profile()
    priority = ["pertussis"] if pertussis_rising else []
    try:
        if profile == "general":
            p = {k: (list(v) if isinstance(v, list) else v) for k, v in GENERAL_PROFILE.items()}
            if pregnant:
                p["audiences"].insert(0, "pregnant")
                p["pathogens"] = ["pertussis", "rsv"] + p["pathogens"]
            rows = guidance_agent.fetch_rows(p["audiences"], p["pathogens"], "jdbc")
            res = guidance_agent.build("general", rows, p, priority)
        else:
            res = guidance_agent.guidance_for_visit(profile, priority=priority, pregnant=pregnant, channel="jdbc")
    except Exception as e:  # noqa: BLE001
        return failed("guidance", f"{e.__class__.__name__}: {str(e)[:200]}", time.perf_counter() - t0)
    return Finding(
        source="guidance", title=TITLES["guidance"], status="ok", level="unknown",
        headline=f"CDC advice for visiting {res['facts'].get('visited', profile).replace('_', ' ')}",
        text=res["briefing"], facts=[], caveats=list(res.get("caveats", [])),
        sources=[{"title": s["title"], "url": s["url"]} for s in res.get("sources", [])],
        model=None, trace=None, seconds=time.perf_counter() - t0,
        raw={"facts": res.get("facts"), "priority": priority},
    )
```

- [ ] **Step 5: Create `planner/adapters/weather.py`**

```python
"""Weather risk from the weather service over HTTP (POST /api/weather)."""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

import httpx

from ..findings import TITLES, Finding, failed
from ..trip import TripRequest

DEFAULT_URL = "http://127.0.0.1:8770"
FORECAST_DAYS = 7
NWS = {"title": "National Weather Service forecast and alerts (api.weather.gov)", "url": "https://api.weather.gov"}


def service_url() -> str:
    return os.environ.get("WEATHER_SERVICE_URL", DEFAULT_URL).rstrip("/")


def run(trip: TripRequest, base_url: str | None = None, timeout: float = 180.0, today: date | None = None) -> Finding:
    base = (base_url or service_url())
    today = today or date.today()
    body = {"city": trip.label, "days": FORECAST_DAYS, "travellers": trip.weather_groups()}
    t0 = time.perf_counter()
    try:
        r = httpx.post(f"{base}/api/weather", json=body, timeout=timeout)
    except httpx.HTTPError as e:
        return failed("weather", f"weather service unreachable at {base}: {e.__class__.__name__}", time.perf_counter() - t0)
    if r.status_code == 400:
        err = r.json().get("error", "bad request") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        return failed("weather", f"the weather agent does not cover {trip.label}: {err}", time.perf_counter() - t0, status="skipped")
    if r.status_code != 200:
        return failed("weather", f"weather service returned HTTP {r.status_code}", time.perf_counter() - t0)
    data = r.json()
    h = data.get("handoff") or {}
    if h.get("status") == "error" or not data.get("ok", True):
        return failed("weather", str(h.get("error") or data.get("error") or "weather lookup failed"), time.perf_counter() - t0)

    level = h.get("risk_level") or "unknown"
    ev = h.get("risk_evaluation") or {}
    headline = f"Weather risk {level} ({h.get('recommendation', '')}) for the next {len(h.get('periods_covered') or [])} forecast periods"
    facts = [f"{r_['period']}: {r_['detail']}" for r_ in (h.get("risks") or []) if r_.get("level") in ("moderate", "high")]
    if h.get("good_outdoor_windows"):
        facts.append("Low-risk times outdoors: " + ", ".join(h["good_outdoor_windows"]))
    facts += list(h.get("advice") or [])[:4]
    caveats = [a.get("headline") or a.get("event") for a in (h.get("official_alerts") or []) if a]
    if trip.start > today + timedelta(days=FORECAST_DAYS):
        caveats.append(f"The forecast covers only the next {FORECAST_DAYS} days; your trip starts {trip.start.isoformat()}. "
                       "This is the current outlook for the city; check again nearer the date.")
    if h.get("stale"):
        caveats.append(f"Forecast data is {h.get('data_age_hours')} hours old")
    conf = h.get("confidence")
    if conf:
        facts.append(f"Confidence {conf}, data {h.get('data_age_hours')} h old")
    return Finding(
        source="weather", title=TITLES["weather"], status="ok", level=level, headline=headline,
        text=h.get("summary") or "", facts=facts, caveats=[c for c in caveats if c], sources=[NWS],
        model=h.get("model"), trace=data.get("trace"), seconds=time.perf_counter() - t0,
        raw={"goodOutdoorWindows": h.get("good_outdoor_windows") or [], "reasons": ev.get("reasons") or [],
             "profile": ev.get("profile"), "travellers": h.get("travellers"), "evaluator": data.get("evaluator"),
             "outcomeReview": h.get("outcome_review"), "periodsCovered": h.get("periods_covered") or []},
    )
```

- [ ] **Step 6: Verify the adapters one by one (services up: Zetaris, Nightshift, weather on 8770)**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python - <<'EOF' 2>&1 | grep -v SLF4J
from datetime import date
from planner.trip import TripRequest
from planner.adapters import pertussis, guidance, weather
t = TripRequest.from_dict({'toCity':'Richmond','toState':'va','toCounty':'Richmond City','fromCity':'Austin','fromState':'tx','start':'2026-11-10','end':'2026-11-17','with':['newborn']})
p = pertussis.run(t); print('pertussis', p.status, p.level, p.headline, round(p.seconds,1))
g = guidance.run(t, p.level in ('moderate','high')); print('guidance', g.status, g.headline, len(g.sources), 'sources')
w = weather.run(t); print('weather', w.status, w.level, w.headline, w.model, round(w.seconds))
EOF
```

Expected: `pertussis ok <level> <N> cases this year in Virginia ...`, `guidance ok CDC advice for visiting newborn 5 sources`, `weather ok low ... nvidia/nemotron-3.5-lightning-30b-a3b 6x`. Then the wastewater adapter:

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python - <<'EOF' 2>&1 | grep -v SLF4J
from planner.trip import TripRequest
from planner.adapters import wastewater
from wastewater_agent.agent import Agent
from wastewater_agent.config import load_settings
t = TripRequest.from_dict({'toCity':'Richmond','toState':'va','toCounty':'Richmond City','fromCity':'Austin','fromState':'tx','start':'2026-11-10','end':'2026-11-17'})
a = Agent(load_settings())
for k in ('sars-cov-2', 'flu-a'):
    f = wastewater.run(a, t, k, progress=lambda e: print('  event', e)); print(k, f.status, f.level, f.headline, f.model, round(f.seconds))
EOF
```

Expected: route events printed, then `sars-cov-2 ok unknown ...` (Richmond's window is empty right now) and `flu-a ok ...` with a Nemotron model name.

---

### Task 4: Composer

**Files:**
- Create: `planner/composer.py`

- [ ] **Step 1: Create `planner/composer.py`**

```python
"""Composer agent: the verdict by rules, the prose by Nightshift (checked) or
by templates, assembled into a TravelPlan."""

from __future__ import annotations

import json
import uuid
from typing import Any

from wastewater_agent.agent.writer import allowed_numbers, foreign_numbers
from wastewater_agent.llm import NightshiftProvider, ProviderUnauthorized, ProviderUnavailable
from wastewater_agent.states import state_name

from .findings import LEVEL_LABEL, LEVEL_RANK, ORDER, Finding, TravelPlan, Verdict
from .trip import TripRequest

HEALTH = ("covid", "flu", "pertussis")
COMPOSER_ATTEMPTS = 2
MAX_TOKENS = 900

SYSTEM_PROMPT = """You are the composer for a family visit planner. You receive a fact sheet about one
planned visit: the verdict (already decided by rules), what each source found, and who is in the household.
Write for the person planning the visit.

Reply with one JSON object and nothing else: {"intro": string, "precautions": [string, ...]}.
- intro: 2 or 3 plain sentences. Start from the verdict, then say what drives it. Name the destination.
- precautions: 5 to 8 short, practical, imperative items that follow from the findings and the household.
Use only facts and numbers from the fact sheet; never invent figures or quote guidance text that is not there.
Do not give medical advice beyond what the sheet says; say "check with a healthcare provider" where the sheet does."""


# -- verdict ---------------------------------------------------------------

def effective_level(f: Finding, sensitive: bool) -> str:
    if f.status != "ok" or f.source == "guidance":
        return "unknown"
    if sensitive and f.source in HEALTH and f.level == "moderate":
        return "high"
    return f.level


def verdict_for(trip: TripRequest, findings: list[Finding]) -> Verdict:
    sensitive = trip.sensitive
    levels = {f.source: effective_level(f, sensitive) for f in findings}
    known = {s: l for s, l in levels.items() if l != "unknown"}
    if not known:
        return Verdict("unknown", LEVEL_LABEL["unknown"],
                       "None of the sources had enough recent data for this trip.")
    top = max(known.values(), key=lambda l: LEVEL_RANK[l])
    drivers = [f for f in findings if known.get(f.source) == top]
    parts = [f"{f.title.lower()}: {f.headline}" for f in drivers]
    reason = "; ".join(parts) + "."
    if top in ("moderate", "high") and sensitive and any(f.source in HEALTH and f.level == "moderate" for f in drivers):
        reason += f" Counted as {top} because the household includes {trip.household()}."
    if top == "low":
        reason = "Every source with data is at a low level: " + reason
    return Verdict(top, LEVEL_LABEL[top], reason)


# -- fact sheet ------------------------------------------------------------

def render_sheet(trip: TripRequest, findings: list[Finding], verdict: Verdict) -> str:
    lines = [
        f"destination: {trip.label}" + (f" ({trip.to_county})" if trip.to_county else ""),
        f"travelling from: {trip.from_city}, {trip.from_state.upper()}",
        f"dates: {trip.start.isoformat()} to {trip.end.isoformat()}",
        f"party: {trip.adults} adults, {trip.children} children; household includes {trip.household()}",
        f"verdict: {verdict.level} ({verdict.label}). reason: {verdict.reason}",
        "",
    ]
    for f in findings:
        lines.append(f"[{f.title}] status: {f.status}; level: {f.level}")
        if f.status != "ok":
            lines.append(f"  not available: {f.error}")
            continue
        lines.append(f"  headline: {f.headline}")
        for x in f.facts:
            lines.append(f"  - {x}")
        for c in f.caveats:
            lines.append(f"  caveat: {c}")
        if f.source == "guidance":
            lines.append("  (the guidance text itself is shown to the user separately; do not rewrite it)")
    return "\n".join(lines)


# -- prose -----------------------------------------------------------------

def template_prose(trip: TripRequest, findings: list[Finding], verdict: Verdict) -> tuple[str, list[str]]:
    intro = f"{verdict.label} for {trip.label}, {trip.start.strftime('%d %b')} to {trip.end.strftime('%d %b')}. {verdict.reason}"
    by = {f.source: f for f in findings}
    items: list[str] = []
    if any(by.get(s) and by[s].level in ("moderate", "high") for s in ("covid", "flu")):
        items.append("Check the wastewater readings again a few days before you travel.")
        items.append("Wear a well-fitted mask on the journey and in crowded indoor places.")
    if by.get("pertussis") and by["pertussis"].level in ("moderate", "high"):
        items.append("Make sure everyone visiting is up to date with whooping cough (Tdap) vaccination, at least two weeks before the visit.")
    if "newborn" in trip.with_:
        items.append("Anyone with a cough, fever or runny nose should postpone meeting the baby.")
    if "older_adult" in trip.with_:
        items.append("Keep hand hygiene strict and air the rooms you share.")
    if "pregnant" in trip.with_:
        items.append("Ask the person who is pregnant what their healthcare provider has advised for visitors.")
    w = by.get("weather")
    if w and w.status == "ok":
        items += [a for a in w.facts if a and not a.startswith(("Low-risk", "Confidence"))][:2]
    items.append("Stay home if you have symptoms, and read the CDC guidance section below.")
    out: list[str] = []
    for i in items:
        if i not in out:
            out.append(i)
    return intro, out[:8]


def _parse(text: str) -> tuple[str, list[str]] | None:
    try:
        d = json.loads(text)
    except ValueError:
        return None
    intro, prec = d.get("intro"), d.get("precautions")
    if not isinstance(intro, str) or not isinstance(prec, list) or not prec:
        return None
    prec = [str(p).strip() for p in prec if str(p).strip()]
    return (intro.strip(), prec[:8]) if len(intro.strip()) > 20 and prec else None


def write_prose(trip: TripRequest, findings: list[Finding], verdict: Verdict,
                provider: NightshiftProvider | None) -> tuple[str, list[str], str, list[str]]:
    """Returns (intro, precautions, model, notes)."""
    notes: list[str] = []
    if provider is None:
        intro, prec = template_prose(trip, findings, verdict)
        return intro, prec, "template", ["composer: Nightshift unavailable, template prose"]
    sheet = render_sheet(trip, findings, verdict)
    allowed = allowed_numbers(sheet)
    for attempt in range(COMPOSER_ATTEMPTS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"FACT SHEET\n{sheet}\n\nrequest: {uuid.uuid4()}"}]
        try:
            c = provider.complete(messages, json_mode=True, max_tokens=MAX_TOKENS)
        except ProviderUnauthorized:
            raise
        except ProviderUnavailable as e:
            notes.append(f"composer fallback: {e}")
            break
        parsed = _parse(c.text)
        if parsed is None:
            notes.append(f"composer attempt {attempt + 1}: reply was not the expected JSON")
            continue
        intro, prec = parsed
        bad = foreign_numbers(intro + "\n" + "\n".join(prec), allowed)
        if bad:
            notes.append(f"composer attempt {attempt + 1}: figures not in the fact sheet ({', '.join(bad[:5])})")
            continue
        return intro, prec, c.routed_model or provider.model, notes
    intro, prec = template_prose(trip, findings, verdict)
    return intro, prec, "template", notes + ["composer: template prose used"]


# -- assembly --------------------------------------------------------------

def compose(trip: TripRequest, findings: dict[str, Finding], provider: NightshiftProvider | None,
            elapsed: float = 0.0, notes: list[str] | None = None) -> TravelPlan:
    ordered = [findings[s] for s in ORDER if s in findings]
    verdict = verdict_for(trip, ordered)
    intro, precautions, model, prose_notes = write_prose(trip, ordered, verdict, provider)
    weather = findings.get("weather")
    best_days = [w for w in (weather.raw.get("goodOutdoorWindows", []) if weather and weather.status == "ok" else [])
                 if "night" not in w.lower()]
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for f in ordered:
        for s in f.sources:
            if s.get("url") and s["url"] not in seen:
                seen.add(s["url"])
                sources.append({"title": s.get("title", s["url"]), "url": s["url"]})
    return TravelPlan(
        trip=trip.to_dict(), verdict=verdict, intro=intro, sections=ordered, precautions=precautions,
        best_days=best_days, sources=sources,
        models={"composer": model, **{f.source: f.model for f in ordered}},
        traces={f.source: f.trace for f in ordered},
        notes=list(notes or []) + prose_notes,
        partial=any(f.status != "ok" for f in ordered),
        elapsed_seconds=elapsed,
    )
```

- [ ] **Step 2: Verify the rules and the template path without any service**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python - <<'EOF'
from planner.trip import TripRequest
from planner.findings import Finding, TITLES, failed
from planner.composer import compose, verdict_for
t = TripRequest.from_dict({'toCity':'Richmond','toState':'va','fromCity':'Austin','fromState':'tx','start':'2026-11-10','end':'2026-11-17','with':['newborn']})
fs = {'covid': Finding('covid', TITLES['covid'], level='low', headline='20% of 10 samples positive, flat in Virginia'),
      'flu': Finding('flu', TITLES['flu'], level='moderate', headline='60% of 50 samples positive, rising in Virginia'),
      'pertussis': Finding('pertussis', TITLES['pertussis'], level='moderate', headline='300 cases this year in Virginia (3.5 per 100,000), higher than at this point last year; close to the national rate'),
      'weather': failed('weather', 'weather service unreachable'),
      'guidance': Finding('guidance', TITLES['guidance'], text='What CDC recommends ...', sources=[{'title':'CDC','url':'https://www.cdc.gov/pertussis/'}])}
v = verdict_for(t, list(fs.values())); print(v.level, '|', v.label, '|', v.reason)
p = compose(t, fs, provider=None, elapsed=1.0)
d = p.to_dict(); print(d['partial'], d['models']['composer'], len(d['precautions']), d['sections'][0]['source'], d['sources'])
print(d['intro'])
EOF
```

Expected: `high | Reconsider, or go with full precautions | ... Counted as high because the household includes a newborn.`, then `True template 6..8 covid [{'title': 'CDC', ...}]` and an intro beginning "Reconsider, or go with full precautions for Richmond, VA".

---

### Task 5: Planner agent

**Files:**
- Create: `planner/planner_agent.py`

- [ ] **Step 1: Create `planner/planner_agent.py`**

```python
"""Planner agent: runs the four agents in parallel, reports progress, then hands
the findings to the composer."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from wastewater_agent.agent import Agent
from wastewater_agent.config import Settings, load_settings
from wastewater_agent.llm import ProviderUnauthorized

from .adapters import guidance, pertussis, wastewater, weather
from .composer import compose
from .findings import Finding, TravelPlan, failed
from .trip import TripRequest

Progress = Callable[[dict[str, Any]], None]
TIMEOUTS = {"wastewater": 240.0, "pertussis_guidance": 120.0, "weather": 180.0}


class PlannerAgent:
    def __init__(self, settings: Settings | None = None, *, agent: Agent | None = None,
                 weather_url: str | None = None) -> None:
        self.settings = settings or load_settings()
        self.agent = agent or Agent(self.settings)
        self.weather_url = weather_url

    def run(self, trip: TripRequest, progress: Progress | None = None) -> TravelPlan:
        emit: Progress = progress or (lambda e: None)
        t0 = time.perf_counter()
        findings: dict[str, Finding] = {}
        notes: list[str] = []

        # One JVM per process: open the JDBC connection here, before any thread
        # could race to start it (the pertussis agent uses the same driver).
        self.agent.client.connect()

        def done(f: Finding) -> None:
            findings[f.source] = f
            if f.status == "ok":
                emit({"stage": f.source, "state": "done", "level": f.level, "model": f.model, "seconds": round(f.seconds, 1)})
            else:
                notes.append(f"{f.source}: {f.error}")
                emit({"stage": f.source, "state": "failed", "error": f.error, "seconds": round(f.seconds, 1)})

        def task_wastewater() -> None:
            for key, source in (("sars-cov-2", "covid"), ("flu-a", "flu")):
                emit({"stage": source, "state": "start"})
                done(wastewater.run(self.agent, trip, key, progress=emit))

        def task_pertussis_guidance() -> None:
            emit({"stage": "pertussis", "state": "start"})
            p = pertussis.run(trip)
            done(p)
            emit({"stage": "guidance", "state": "start"})
            done(guidance.run(trip, pertussis_rising=p.status == "ok" and p.level in ("moderate", "high")))

        def task_weather() -> None:
            emit({"stage": "weather", "state": "start"})
            done(weather.run(trip, base_url=self.weather_url, timeout=TIMEOUTS["weather"]))

        tasks = {"wastewater": task_wastewater, "pertussis_guidance": task_pertussis_guidance, "weather": task_weather}
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = {name: pool.submit(fn) for name, fn in tasks.items()}
            for name, fut in futures.items():
                try:
                    fut.result(timeout=TIMEOUTS[name])
                except TimeoutError:
                    for source in {"wastewater": ("covid", "flu"), "pertussis_guidance": ("pertussis", "guidance"), "weather": ("weather",)}[name]:
                        if source not in findings:
                            done(failed(source, f"timed out after {TIMEOUTS[name]:.0f} s"))
                except ProviderUnauthorized:
                    raise
                except Exception as e:  # noqa: BLE001  a bug in a task must not lose the other findings
                    for source in {"wastewater": ("covid", "flu"), "pertussis_guidance": ("pertussis", "guidance"), "weather": ("weather",)}[name]:
                        if source not in findings:
                            done(failed(source, f"{e.__class__.__name__}: {str(e)[:200]}"))

        state, _ = self.agent.nightshift.readiness()
        if state == "unauthorized":
            raise ProviderUnauthorized("Nightshift rejected the token; check the token file")
        provider = self.agent.nightshift if state == "online" else None
        emit({"stage": "composer", "state": "start", "model": provider.model if provider else "template"})
        plan = compose(trip, findings, provider, elapsed=time.perf_counter() - t0, notes=notes)
        plan.elapsed_seconds = time.perf_counter() - t0
        emit({"stage": "composer", "state": "done", "model": plan.models["composer"], "level": plan.verdict.level,
              "seconds": round(plan.elapsed_seconds, 1)})
        return plan

    def close(self) -> None:
        self.agent.close()
```

Note on `fut.result(timeout=...)`: the timeout only stops waiting; the thread finishes in the background and its late result is ignored. `JdbcClient.connect()` (`wastewater_agent/zetaris/client.py:27`) returns at once when a connection already exists, so calling it here and again inside `Agent.ask` is harmless.

- [ ] **Step 2: Verify with all services up (prints the events as they arrive)**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python - <<'EOF' 2>&1 | grep -v SLF4J
import json, time
from planner.planner_agent import PlannerAgent
from planner.trip import TripRequest
t = TripRequest.from_dict({'toCity':'Richmond','toState':'va','toCounty':'Richmond City','fromCity':'Austin','fromState':'tx','start':'2026-11-10','end':'2026-11-17','with':['newborn']})
t0 = time.time()
plan = PlannerAgent().run(t, progress=lambda e: print(f"{time.time()-t0:5.1f}s", e))
d = plan.to_dict()
print(d['verdict']); print(d['intro']); print('partial', d['partial'], 'models', d['models']); print('precautions', len(d['precautions']), 'bestDays', d['bestDays'])
EOF
```

Expected: events for covid, flu, pertussis, guidance and weather (start, routes, done with models and seconds), then composer start/done; `partial False`; `models.composer` a Nemotron model; total under about 90 s.

---

### Task 6: CLI

**Files:**
- Create: `planner/cli.py`, `planner/__main__.py`

- [ ] **Step 1: Create `planner/cli.py`**

```python
"""python -m planner "Richmond, VA" --from "Austin, TX" --start 2026-11-10 --end 2026-11-17 --with older_adult,newborn"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from .planner_agent import PlannerAgent
from .trip import GROUPS, TripRequest


def parse_place(text: str) -> tuple[str, str]:
    if "," not in text:
        raise SystemExit(f'place must be "City, ST": {text!r}')
    city, st = (p.strip() for p in text.rsplit(",", 1))
    if len(st) != 2:
        raise SystemExit(f"state must be a two-letter code: {st!r}")
    return city, st.lower()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="planner", description="Compose a travel plan from the four agents")
    p.add_argument("to", help='destination, "City, ST"')
    p.add_argument("--from", dest="from_", required=True, help='home, "City, ST"')
    p.add_argument("--county", help="destination county in the wastewater agent's form, e.g. 'Richmond City'")
    p.add_argument("--start", default=(date.today() + timedelta(days=14)).isoformat())
    p.add_argument("--end", default=(date.today() + timedelta(days=21)).isoformat())
    p.add_argument("--adults", type=int, default=2)
    p.add_argument("--children", type=int, default=0)
    p.add_argument("--with", dest="with_", default="", help="comma list of " + ",".join(GROUPS))
    p.add_argument("--weather-url", help="weather service base URL (default http://127.0.0.1:8770)")
    p.add_argument("--json", action="store_true", help="print the plan as JSON")
    p.add_argument("--quiet", action="store_true", help="no progress lines")
    a = p.parse_args(argv)

    to_city, to_state = parse_place(a.to)
    from_city, from_state = parse_place(a.from_)
    groups = [g.strip() for g in a.with_.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        raise SystemExit(f"unknown group(s) {unknown}; use {', '.join(GROUPS)}")
    trip = TripRequest.from_dict({"toCity": to_city, "toState": to_state, "toCounty": a.county, "fromCity": from_city,
                                  "fromState": from_state, "start": a.start, "end": a.end, "adults": a.adults,
                                  "children": a.children, "with": groups})

    def progress(e: dict) -> None:
        if a.quiet or a.json:
            return
        if e.get("state") == "route":
            print(f"  {e['stage']}: route {e.get('model')} {e.get('route_state')}", file=sys.stderr)
        elif e.get("state") == "done":
            print(f"  {e['stage']}: {e.get('level', '')} via {e.get('model') or '-'} ({e.get('seconds')} s)", file=sys.stderr)
        elif e.get("state") == "failed":
            print(f"  {e['stage']}: FAILED {e.get('error')}", file=sys.stderr)
        else:
            print(f"  {e['stage']}: {e['state']}", file=sys.stderr)

    agent = PlannerAgent(weather_url=a.weather_url)
    try:
        plan = agent.run(trip, progress=progress)
    finally:
        agent.close()
    d = plan.to_dict()
    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0
    v = d["verdict"]
    print(f"\n{v['label'].upper()}  ({v['level']})\n{v['reason']}\n\n{d['intro']}\n")
    for s in d["sections"]:
        print(f"== {s['title']}  [{s['level']}{'' if s['status'] == 'ok' else ', ' + s['status']}]")
        print(f"   {s['headline']}")
        for x in s["facts"]:
            print(f"   - {x}")
        if s["source"] == "guidance" and s["text"]:
            print("   " + s["text"].replace("\n", "\n   "))
        for c in s["caveats"]:
            print(f"   ! {c}")
    print("\nBefore you go:")
    for x in d["precautions"]:
        print(f"  [ ] {x}")
    if d["bestDays"]:
        print("\nBest days outdoors: " + ", ".join(d["bestDays"]))
    print("\nmodels: " + ", ".join(f"{k}={v}" for k, v in d["models"].items()))
    print(f"elapsed: {d['elapsedSeconds']} s" + ("  (partial)" if d["partial"] else ""))
    for n in d["notes"]:
        print(f"note: {n}")
    return 0
```

- [ ] **Step 2: Create `planner/__main__.py`**

```python
import sys

from .cli import main

sys.exit(main())
```

- [ ] **Step 3: Verify the CLI, full and partial**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python -m planner "Richmond, VA" --from "Austin, TX" --county "Richmond City" --start 2026-11-10 --end 2026-11-17 --with newborn 2>&1 | grep -v SLF4J
```

Expected: progress lines on stderr, then the verdict block, five sections, "Before you go" list, best days, models and elapsed. Then with the weather service stopped (`preview_stop` it, or point at a dead port):

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python -m planner "Richmond, VA" --from "Austin, TX" --county "Richmond City" --with older_adult --weather-url http://127.0.0.1:8799 2>&1 | grep -v SLF4J | grep -i "weather\|partial"
```

Expected: `weather: FAILED weather service unreachable ...`, a Weather section `[unknown, error]`, and `elapsed: ... (partial)`.

---

### Task 7: Server: `/api/plan` stream, `/api/plans`, status weather

**Files:**
- Modify: `planner/frontend/server.py` (imports, `AgentService`, `Handler._ask_stream` → generic `_stream`, `do_POST`, `do_GET`, `status`)

- [ ] **Step 1: Import the planner after the wastewater imports (after line 46)**

```python
from planner.planner_agent import PlannerAgent  # noqa: E402
from planner.trip import TripRequest  # noqa: E402
```

- [ ] **Step 2: Add plan storage and a `plan` method to `AgentService`**

In `__init__`, after `self.order: list[str] = []`:

```python
        self.plans: dict[str, dict[str, Any]] = {}
        self.plan_order: list[str] = []
        self._planner: PlannerAgent | None = None
```

After the `agent` property:

```python
    @property
    def planner(self) -> PlannerAgent:
        if self._planner is None:
            self._planner = PlannerAgent(self.settings, agent=self.agent)
        return self._planner

    def plan(self, trip: dict[str, Any], progress: Any = None) -> dict[str, Any]:
        request = TripRequest.from_dict(trip)  # ValueError on bad input
        with self._lock:
            record = self.planner.run(request, progress=progress).to_dict()
        self.plans[record["id"]] = record
        self.plan_order.insert(0, record["id"])
        return record
```

- [ ] **Step 3: Add the weather service to `status()`**

At the end of `status()`, before `return out`:

```python
        weather_url = (os.environ.get("WEATHER_SERVICE_URL") or "http://127.0.0.1:8770").rstrip("/")
        try:
            r = httpx.get(f"{weather_url}/api/status", timeout=5.0)
            out["weather"] = {"ok": r.status_code == 200, "url": weather_url, **(r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"})}
        except (httpx.HTTPError, ValueError) as e:
            out["weather"] = {"ok": False, "url": weather_url, "error": e.__class__.__name__}
```

and add `import os` to the imports.

- [ ] **Step 4: Generalise the stream helper**

Replace the whole `_ask_stream` method with:

```python
    def _ask_stream(self, question: str, county: str | None, pathogen: str | None) -> None:
        self._stream(lambda send: SERVICE.ask(question, county, pathogen, progress=send), "answer")

    def _plan_stream(self, trip: dict[str, Any]) -> None:
        self._stream(lambda send: SERVICE.plan(trip, progress=send), "plan")

    def _stream(self, run: Any, final_stage: str) -> None:
        """Newline-delimited JSON: one progress event per line while `run` works, then
        {"stage": final_stage, "record"/"plan": ...} or {"stage": "error", ...}. The
        connection closes when the body ends (no Content-Length), which fetch() handles."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        alive = True

        def send(event: dict[str, Any]) -> None:
            nonlocal alive
            if not alive:
                return
            try:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                alive = False  # the page went away; let the run finish and be stored

        try:
            result = run(send)
            send({"stage": final_stage, ("record" if final_stage == "answer" else "plan"): result})
        except (KeyError, ValueError) as e:
            send({"stage": "error", "status": 400, "error": str(e)})
        except ProviderUnauthorized as e:
            send({"stage": "error", "status": 401, "error": str(e)})
        except ZetarisError as e:
            send({"stage": "error", "status": 502, "error": f"zetaris: {e}"})
        except ProviderError as e:
            send({"stage": "error", "status": 502, "error": f"nightshift: {e}"})
```

- [ ] **Step 5: Route `POST /api/plan` and `GET /api/plans`**

In `do_POST`, before `if parts == ["api", "feedback"]:`:

```python
            if parts == ["api", "plan"]:
                if data.get("stream"):
                    return self._plan_stream(data)
                try:
                    return self._json(200, SERVICE.plan(data))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
```

In `do_GET`, before `if parts[1:] == ["memory"]:`:

```python
            if parts[1:] == ["plans"]:
                return self._json(200, {"plans": [{"id": p["id"], "createdAt": p["createdAt"], "trip": p["trip"], "verdict": p["verdict"],
                                                   "partial": p["partial"], "elapsedSeconds": p["elapsedSeconds"]}
                                                  for p in (SERVICE.plans[i] for i in SERVICE.plan_order)]})
            if len(parts) >= 3 and parts[1] == "plans":
                rec = SERVICE.plans.get(parts[2])
                if rec is None:
                    return self._json(404, {"error": "no such plan"})
                if parts[3:] == ["report.md"]:
                    return self._file(200, plan_report_markdown(rec), "text/markdown; charset=utf-8", f"{rec['id']}.md")
                return self._json(200, rec)
```

- [ ] **Step 6: Add `plan_report_markdown` next to `report_markdown`**

```python
def plan_report_markdown(rec: dict[str, Any]) -> str:
    t, v = rec["trip"], rec["verdict"]
    lines = [f"# Travel plan: {t['toCity']}, {t['toState'].upper()}", "",
             f"{t['start']} to {t['end']}, from {t['fromCity']}, {t['fromState'].upper()}; "
             f"{t['adults']} adults, {t['children']} children; with: {', '.join(t['with']) or 'none stated'}.",
             "", f"## {v['label']} ({v['level']})", "", v["reason"], "", rec["intro"], ""]
    for s in rec["sections"]:
        lines += [f"## {s['title']}  ({s['level']}{'' if s['status'] == 'ok' else ', ' + s['status']})", "", s["headline"], ""]
        if s["text"]:
            lines += [s["text"], ""]
        lines += [f"- {x}" for x in s["facts"]]
        lines += [f"- Caveat: {c}" for c in s["caveats"]]
        lines.append("")
    lines += ["## Before you go", ""] + [f"- [ ] {x}" for x in rec["precautions"]] + [""]
    if rec["bestDays"]:
        lines += ["## Best days outdoors", "", ", ".join(rec["bestDays"]), ""]
    lines += ["## Sources", ""] + [f"- [{s['title']}]({s['url']})" for s in rec["sources"]] + [""]
    lines += ["## Models", ""] + [f"- {k}: {v or 'none'}" for k, v in rec["models"].items()] + [""]
    if rec["notes"]:
        lines += ["## Notes", ""] + [f"- {n}" for n in rec["notes"]] + [""]
    lines += [f"Generated {rec['createdAt']} in {rec['elapsedSeconds']} s" + (" (partial)" if rec["partial"] else ""), "", DISCLAIMER]
    return "\n".join(lines)
```

- [ ] **Step 7: Verify the server on the preview port**

Start it with `preview_start` (`planner-frontend`, lands on 8766), then:

```bash
curl -s -m 10 http://127.0.0.1:8766/api/status | python -I -c "import sys,json; d=json.load(sys.stdin); print('weather:', d.get('weather'))"
curl -s -m 300 -N -X POST http://127.0.0.1:8766/api/plan -H "Content-Type: application/json" -d '{"toCity":"Richmond","toState":"va","toCounty":"Richmond City","fromCity":"Austin","fromState":"tx","start":"2026-11-10","end":"2026-11-17","adults":2,"children":1,"with":["newborn"],"stream":true}' | python -I -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    if e['stage'] == 'plan': print('PLAN', e['plan']['verdict'], 'partial', e['plan']['partial'], 'id', e['plan']['id'])
    else: print(e)
"
curl -s -m 10 http://127.0.0.1:8766/api/plans | head -c 300; echo
curl -s -m 10 -o /dev/null -w "report http %{http_code}\n" "http://127.0.0.1:8766/api/plans/$(curl -s http://127.0.0.1:8766/api/plans | python -I -c 'import sys,json; print(json.load(sys.stdin)["plans"][0]["id"])')/report.md"
curl -s -m 10 -X POST http://127.0.0.1:8766/api/plan -H "Content-Type: application/json" -d '{"toCity":"Richmond"}' ; echo
```

Expected: `weather: {'ok': True, ...}`; a stream of events ending in `PLAN {...} partial False id plan_...`; a plans listing; `report http 200`; and `{"error": "start and end must be ISO dates (YYYY-MM-DD)"}` for the bad request.

---

### Task 8: Page: toggles, button, progress, plan card

**Files:**
- Modify: `planner/frontend/static/index.html` (toggles, button text, plan card, asset versions v=12)
- Modify: `planner/frontend/static/styles.css` (verdict banner, level badges, checklist, disclosure)
- Modify: `planner/frontend/static/app.js` (trip groups, planVisit, progress events, renderPlan, calendar, demo)

- [ ] **Step 1: index.html, the toggles**

Replace the `who` group:

```html
            <span class="who" role="group" aria-label="Who you will be with">
              <button type="button" class="tog" id="who-elderly" aria-pressed="false"><i data-lucide="check"></i> older adults</button>
              <button type="button" class="tog" id="who-kids" aria-pressed="false"><i data-lucide="check"></i> young children</button>
            </span><span class="w p">.</span>
```

with:

```html
            <span class="who" role="group" aria-label="Who you will be with">
              <button type="button" class="tog" id="who-elderly" data-group="older_adult" aria-pressed="false"><i data-lucide="check"></i> older adults</button>
              <button type="button" class="tog" id="who-kids" data-group="young_child" aria-pressed="false"><i data-lucide="check"></i> young children</button>
              <button type="button" class="tog" id="who-newborn" data-group="newborn" aria-pressed="false"><i data-lucide="check"></i> a newborn</button>
              <button type="button" class="tog" id="who-pregnant" data-group="pregnant" aria-pressed="false"><i data-lucide="check"></i> someone pregnant</button>
            </span><span class="w p">.</span>
```

- [ ] **Step 2: index.html, the button and the plan card**

Change the button to `<button type="button" class="btn-primary" id="visit-submit"><i data-lucide="route"></i> Plan this visit</button>`.

Replace everything inside `<section class="card plan-card" id="plan-card">` with:

```html
        <div class="card-head"><span class="tile-ic"><i data-lucide="clipboard-list"></i></span><h2>Your plan</h2></div>
        <p class="plan-empty" id="plan-empty">Plan this visit to get a recommendation for the trip.</p>
        <div class="verdict hidden" id="plan-verdict">
          <div class="verdict-head"><span class="verdict-dot"></span><strong id="verdict-label"></strong></div>
          <p class="verdict-reason" id="verdict-reason"></p>
        </div>
        <p class="plan-text hidden" id="plan-intro"></p>
        <div id="plan-sections"></div>
        <div class="plan-block hidden" id="plan-precautions">
          <div class="plan-block-head"><span class="virus"><i data-lucide="list-checks"></i> Before you go</span></div>
          <ul class="checklist" id="precautions-list"></ul>
        </div>
        <div class="plan-block hidden" id="plan-best">
          <div class="plan-block-head"><span class="virus"><i data-lucide="sun"></i> Best days outdoors</span></div>
          <p class="plan-text" id="best-days"></p>
        </div>
        <details class="plan-sources hidden" id="plan-sources">
          <summary>Sources and models</summary>
          <ul class="plain" id="sources-list"></ul>
          <p class="muted" id="models-line"></p>
        </details>
        <div class="plan-error hidden" id="plan-error" role="alert"></div>
```

Bump both asset versions to `styles.css?v=12` and `app.js?v=12`.

- [ ] **Step 3: styles.css additions (append after the `.plan-block-head .badge` rule)**

```css
.verdict { border-radius: var(--r-md); padding: .9rem 1rem; background: var(--paper-2); border-left: 5px solid var(--ink-2); }
.verdict-head { display: flex; align-items: center; gap: .55rem; font-size: var(--fs-2); }
.verdict-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--ink-2); flex: none; }
.verdict-reason { margin: .35rem 0 0; color: var(--ink-2); }
.verdict.low { border-left-color: var(--sage); } .verdict.low .verdict-dot { background: var(--sage); }
.verdict.moderate { border-left-color: var(--mustard); } .verdict.moderate .verdict-dot { background: var(--mustard); }
.verdict.high { border-left-color: var(--brick); } .verdict.high .verdict-dot { background: var(--brick); }
.badge.low { background: var(--sage-2); color: var(--sage); }
.badge.moderate { background: var(--mustard-2); color: var(--mustard); }
.badge.high { background: var(--brick-2); color: var(--brick); }
.badge.unknown, .badge.error, .badge.skipped { background: var(--paper-2); color: var(--ink-2); }
.plan-block .headline { font-weight: 600; margin: 0; }
.plan-block .caveat { font-size: var(--fs-0); color: var(--ink-2); margin: 0; }
.plan-block .quote { white-space: pre-line; }
.checklist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .35rem; }
.checklist li { display: flex; gap: .5rem; align-items: flex-start; }
.checklist li::before { content: ""; flex: none; width: 16px; height: 16px; margin-top: .2rem; border: 1.5px solid var(--teal); border-radius: 4px; }
.plan-sources { padding-top: .9rem; border-top: 1px solid var(--rule); font-size: var(--fs-0); }
.plan-sources summary { cursor: pointer; color: var(--ink-2); }
.plan-sources ul { margin: .5rem 0 0; }
```

Check that `--paper-2`, `--sage-2`, `--mustard-2`, `--brick-2` exist in both the light `:root` and the dark block (they do, lines 9-34); if a light-mode tint is missing, add it next to `--teal-2`.

- [ ] **Step 4: app.js, trip groups**

In `trip()`, replace the two `elderly`/`kids` lines and `with_` with:

```js
    const groups = [...document.querySelectorAll(".tog[aria-pressed=\"true\"]")].map((b) => b.dataset.group);
    const WORDS = { older_adult: "older adults", young_child: "young children", newborn: "a newborn", pregnant: "someone pregnant" };
    const with_ = groups.map((g) => WORDS[g]).join(", ").replace(/, ([^,]*)$/, " and $1");
```

and in the returned object replace `elderly, kids, with_,` with `groups, with_,`.

- [ ] **Step 5: app.js, replace the check/answer code with the plan code**

Delete from the line `  const PATHOGENS = [` through the end of `function render(rec) { ... }` (the block that ends just before `/* ---------- weather: destination for the dates ...`), and delete `const block = ...`, `const part = ...`, `async function check()`, `$("visit-submit").addEventListener("click", check);` and `async function demoAnswer(...)` (they live inside that range or right after the progress object). Keep `askStream` and the `progress` object. Insert in place of the deleted `PATHOGENS` block:

```js
  /* ---------- the plan: one request, four agents, one composer ---------- */
  let currentPlan = null;
  const setGoogleLink = () => { const a = $("cal-google"); if (a) a.href = googleCalendarUrl(); };
  const LEVEL_WORD = { low: "low", moderate: "moderate", high: "high", unknown: "no data" };
  const SECTION_ICON = { covid: "biohazard", flu: "thermometer", pertussis: "baby", weather: "cloud-sun", guidance: "book-open" };
  function tripBody() {
    const t = trip();
    if (!t.to) throw new Error("Pick a destination city first");
    return { toCity: t.to.name, toState: t.to.stateCode, toCounty: t.to.county || null,
      fromCity: t.from ? t.from.name : "", fromState: t.from ? t.from.stateCode : t.to.stateCode,
      start: t.start, end: t.end, adults: t.adults, children: t.children, with: t.groups };
  }
  async function planStream(body, onEvent) {
    const res = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, stream: true }) });
    if (!res.ok || !(res.headers.get("content-type") || "").includes("ndjson")) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `${res.status} ${res.statusText}`);
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "", plan = null;
    for (;;) {
      const { value, done } = await reader.read();
      buf += done ? dec.decode() : dec.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = done ? "" : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const e = JSON.parse(line);
        if (e.stage === "plan") plan = e.plan;
        else if (e.stage === "error") throw new Error(e.error);
        else onEvent(e);
      }
      if (done) break;
    }
    if (!plan) throw new Error("the connection closed before the plan arrived");
    return plan;
  }
  async function planVisit() {
    let body;
    try { body = tripBody(); } catch (e) { $("plan-error").textContent = e.message; $("plan-error").classList.remove("hidden"); return; }
    $("visit-submit").disabled = true;
    $("plan-error").classList.add("hidden");
    progress.begin(`Planning the visit to ${body.toCity}`);
    try {
      const plan = DEMO ? await demoPlan(body) : await planStream(body, (e) => progress.event(e));
      renderPlan(plan);
      progress.finish();
    } catch (e) {
      $("plan-error").textContent = `The plan didn't complete: ${e.message.split("\n")[0]}. Try again in a moment.`;
      $("plan-error").classList.remove("hidden");
      $("answer-progress").classList.add("hidden");
    } finally {
      $("visit-submit").disabled = false;
      if (!DEMO) loadStatus();
    }
  }
  $("visit-submit").addEventListener("click", planVisit);
  function renderSection(s) {
    const level = s.status === "ok" ? s.level : s.status;
    const div = document.createElement("div");
    div.className = "plan-block";
    div.id = `ps-${s.source}`;
    const quote = s.source === "guidance";
    div.innerHTML = `
      <div class="plan-block-head"><span class="virus">${ic(SECTION_ICON[s.source] || "info")} ${esc(s.title)}</span><span class="badge ${esc(level)}">${esc(LEVEL_WORD[level] || level)}</span></div>
      <p class="headline">${esc(s.headline)}</p>
      ${s.status === "ok" && s.text ? `<p class="plan-text${quote ? " quote" : ""}">${esc(s.text)}</p>` : ""}
      ${s.facts.length ? `<ul class="plan-points">${s.facts.map((x) => `<li>${ic("dot")}<span>${esc(x)}</span></li>`).join("")}</ul>` : ""}
      ${s.caveats.map((c) => `<p class="caveat">${esc(c)}</p>`).join("")}
      ${s.status !== "ok" ? `<div class="plan-error" role="alert">${esc(s.error || "not available")}</div>` : ""}`;
    return div;
  }
  function renderPlan(plan) {
    currentPlan = plan;
    const v = plan.verdict;
    $("plan-empty").classList.add("hidden");
    const banner = $("plan-verdict"); banner.className = `verdict ${v.level}`;
    $("verdict-label").textContent = v.label; $("verdict-reason").textContent = v.reason;
    $("plan-intro").textContent = plan.intro; $("plan-intro").classList.remove("hidden");
    const box = $("plan-sections"); box.innerHTML = "";
    plan.sections.forEach((s) => box.appendChild(renderSection(s)));
    $("precautions-list").innerHTML = plan.precautions.map((x) => `<li><span>${esc(x)}</span></li>`).join("");
    $("plan-precautions").classList.toggle("hidden", !plan.precautions.length);
    $("best-days").textContent = plan.bestDays.join(", ");
    $("plan-best").classList.toggle("hidden", !plan.bestDays.length);
    $("sources-list").innerHTML = plan.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("");
    $("models-line").textContent = "Written by " + Object.entries(plan.models).filter(([, m]) => m).map(([k, m]) => `${k}: ${m}`).join("; ") + (plan.partial ? ". Some sources were unavailable." : "");
    $("plan-sources").classList.remove("hidden");
    setGoogleLink();
    drawMap(trip());
    icons();
  }
  async function demoPlan(body) {
    const plan = await (await fetch("sample-plan.json")).json();
    plan.id = "plan_demo_" + Date.now().toString(36); plan.createdAt = new Date().toISOString();
    const pause = (ms) => new Promise((r) => setTimeout(r, ms));
    for (const s of plan.sections) { progress.event({ stage: s.source, state: "start" }); await pause(250); progress.event({ stage: s.source, state: s.status === "ok" ? "done" : "failed", level: s.level, model: s.model, seconds: s.seconds, error: s.error }); }
    progress.event({ stage: "composer", state: "start", model: plan.models.composer }); await pause(400);
    progress.event({ stage: "composer", state: "done", model: plan.models.composer, level: plan.verdict.level, seconds: plan.elapsedSeconds });
    return plan;
  }
```

- [ ] **Step 6: app.js, progress events for the planner**

Replace the body of `progress.event(e)` (the `switch`) with:

```js
    event(e) {
      const AGENT = { covid: "COVID-19 wastewater", flu: "Flu wastewater", pertussis: "Whooping cough", weather: "Weather", guidance: "CDC guidance" };
      const name = AGENT[e.stage] || e.stage;
      if (e.state === "route") {
        if (e.route_state === "start") this.step(`${name}: trying ${modelHtml(e.model)}`);
        else if (e.route_state === "failed") this.trail(`${name}: ${esc(shortModel(e.model))} failed, trying the next route`, true);
        return;
      }
      if (e.stage === "composer") {
        if (e.state === "start") this.step(`Composing the plan with ${modelHtml(e.model)}`);
        else { this.trail(`Plan composed by ${modelHtml(e.model)}`); this.step("Done"); }
        return;
      }
      if (e.state === "start") this.step(`${name}: running`);
      else if (e.state === "done") this.trail(`${name}: ${esc(LEVEL_WORD[e.level] || e.level)}${e.model ? ` via ${modelHtml(e.model)}` : ""}${e.seconds != null ? `, ${e.seconds} s` : ""}`);
      else if (e.state === "failed") this.trail(`${name}: not available (${esc(String(e.error || "").slice(0, 80))})`, true);
    },
```

`LEVEL_WORD` is defined in Step 5 above the progress object's first use at runtime (the object is only called after the page loads), so keep both inside the same IIFE.

- [ ] **Step 7: app.js, map popup, trip change, calendar, boot**

- In `drawMap`, replace the `lines`/`bindPopup` pair with:

```js
    const lines = currentPlan ? currentPlan.sections.filter((s) => ["covid", "flu", "weather"].includes(s.source) && s.status === "ok").map((s) => `${s.title}: ${LEVEL_WORD[s.level] || s.level}`) : [];
    marker.bindPopup(lines.length ? `<b>${esc(t.to.name)}</b><br>${lines.map(esc).join("<br>")}` : t.to.name);
```

- In `onTripChange`, replace `if (current) { setGoogleLink(current); Object.values(answers).forEach((rec) => renderPoints(rec, t)); }` with `if (currentPlan) setGoogleLink();`.

- Replace `function eventFor(rec)` with:

```js
  function eventFor() {
    const t = trip(), p = currentPlan;
    const endExclusive = new Date(Date.parse(t.end) + 864e5).toISOString().slice(0, 10);
    const title = `Visit to ${t.to ? t.to.name : t.stateName}`;
    const lines = [`${t.party}, travelling from ${t.from ? t.from.label : "home"} to ${t.to ? t.to.label : t.stateName}${t.with_ ? `, to be with ${t.with_}` : ""}.`];
    if (p) {
      lines.push("", `${p.verdict.label}: ${p.verdict.reason}`, "", p.intro, "", "Before you go:");
      lines.push(...p.precautions.map((x) => `- ${x}`));
      if (p.bestDays.length) lines.push("", "Best days outdoors: " + p.bestDays.join(", "));
    } else lines.push("No plan yet. Press \"Plan this visit\" on the planner before you go.");
    lines.push("", "Re-check before travelling: health data lags the calendar by about two weeks.", "Summarises CDC and NWS data through the team's agents. Not medical advice; check with a healthcare provider about anything health-related.");
    return { start: t.start, end: endExclusive, title, description: lines.join("\n"), location: t.to ? t.to.label : t.stateName };
  }
```

- `icsFor(rec)` → `icsFor()` using `eventFor()` and `UID:${(currentPlan && currentPlan.id) || "trip"}-...`; `googleCalendarUrl(rec)` → `googleCalendarUrl()` using `eventFor()`; the `cal-ics` click handler calls `icsFor()` and `eventFor()` without arguments; the `cal-google` handler and boot call `setGoogleLink()`.
- Boot: `if (DEMO) planVisit();`.
- Remove any remaining reference to `answers`, `current`, `renderPoints`, `render(`, `check(`, `demoAnswer`, `PATHOGENS`, `block(`, `part(`:

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon/planner/frontend/static && node -e "new Function(require('fs').readFileSync('app.js','utf8')); console.log('parses')" && grep -n "answers\b\|\bcurrent\b\|renderPoints\|render(\|check(\|demoAnswer\|PATHOGENS\|block(\|part(" app.js
```

Expected: `parses` and no matches (apart from `currentPlan`).

- [ ] **Step 8: Verify on the preview (restart `planner-frontend` so the server has Task 7; keep `weather-service` running)**

Open `http://localhost:8766/?r=1`, set the destination to Richmond and home to Austin, switch on "a newborn", click "Plan this visit". While it runs, read the progress card:

```js
({title: document.getElementById('progress-title').innerText, step: document.getElementById('progress-step').innerText, trail: [...document.querySelectorAll('#progress-trail li')].map(l => l.innerText)})
```

Expected: lines for the five agents with levels and models, then "Plan composed by ...". After it finishes: the verdict banner with the level colour, the intro, five section blocks, the checklist, best days, the sources disclosure; no console errors (`read_console_messages` with pattern `v=12`). Also check the calendar description (`googleCalendarUrl()` via the button's `href`) contains the verdict.

---

### Task 9: Demo sample and docs

**Files:**
- Create: `planner/frontend/static/sample-plan.json`
- Modify: `README.md`, `planner/frontend/README.md`, `docs/SUBMISSION-CHECKLIST.md`, `agents/wastewater/samples/README.md`

- [ ] **Step 1: Capture the demo plan from a real run**

```bash
cd /f/Hackathon/YASA-GenAI_Hackathon && python -m planner "Richmond, VA" --from "Austin, TX" --county "Richmond City" --start 2026-11-10 --end 2026-11-17 --with newborn --json 2>/dev/null > planner/frontend/static/sample-plan.json && python -I -c "import json; d=json.load(open('planner/frontend/static/sample-plan.json', encoding='utf-8')); d['id']='plan_sample'; d['notes'].append('Sample plan for demo mode, captured from a real run on 2026-10-27.'); json.dump(d, open('planner/frontend/static/sample-plan.json','w', encoding='utf-8'), indent=2, ensure_ascii=False); print(d['verdict'], d['partial'])"
```

Expected: a verdict dict and `False`. Then `http://localhost:8766/?demo=1` renders it with the replayed progress.

- [ ] **Step 2: Root README**

Rewrite these parts of `README.md` (keep the rest):

- Title and pitch: "Visit Planner" (not "Wastewater Visit Planner"); the pitch names the four agents and the composer, as in the spec's goal.
- Setup: add a numbered step per part with its folder: `agents/wastewater` (existing steps), `agents/pertussis_guidance` (point to its `SETUP-NOTES.md`), `agents/weather` (point to its `SETUP-NOTES.md`; `setup_laptop.bat` steps), then "Run" with the two processes:

```bash
agents/weather/.venv/Scripts/python agents/weather/web_app.py --no-browser --port 8770
python planner/frontend/server.py --port 8765
```

- Usage: the planner CLI example from Task 6 and the page ("Plan this visit"); keep the wastewater CLI examples under a "Single agents" heading.
- Dependencies table: add rows for the pertussis/guidance agents (Zetaris tables `cdc_rest.nndss_pertussis_2026`, `refdata.*`, `visitplanner.*`) and the weather service (NWS, its own `.env`).
- Repository layout: the new tree from the spec.
- Traces: add `GET /api/plans/<id>` and `/report.md`, and that every plan lists its models and trace ids.

- [ ] **Step 3: Frontend README**

In `planner/frontend/README.md`: the run command path; "Plan this visit" replaces "Check the water" (one request, five sections, verdict); the API table gains `POST /api/plan {toCity, toState, toCounty?, fromCity, fromState, start, end, adults, children, with[], stream?}`, `GET /api/plans`, `GET /api/plans/<id>[/report.md]`; demo mode renders `sample-plan.json`; the four toggles.

- [ ] **Step 4: Checklist and samples**

In `docs/SUBMISSION-CHECKLIST.md` add a row "Combined travel plan (planner + composer)" pointing at `python -m planner ...` and `/api/plan`, and update the sample paths. In `agents/wastewater/samples/README.md` add a short "Combined plan" section pointing at `planner/frontend/static/sample-plan.json` as a captured full plan.

- [ ] **Step 5: Final verification list (from the spec)**

1. `python -m planner "Richmond, VA" --from "Austin, TX" --county "Richmond City" --with newborn` with all services up: every section `ok`, composer model from Nightshift.
2. Same with `--weather-url http://127.0.0.1:8799`: `(partial)`, weather `[unknown, error]`.
3. Page on 8766 with everything running: progress card lists four agents and the composer with models; the card renders every part; the Google Calendar link's `details` contains the verdict label.
4. `?demo=1` renders `sample-plan.json` with no services.
5. `cd agents/wastewater && python -m wastewater_agent benchmark --layers plan` still passes.

Then tell the user: restart their 8765 server with the new path, hard-refresh, and that nothing is committed.
