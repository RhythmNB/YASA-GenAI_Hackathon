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
VIRUS_WORD = {"covid": "COVID-19", "flu": "flu"}


def _day(d) -> str:
    return d.strftime("%d %b") if d else "unknown"


def meaning_for(level: str, virus: str, region: str, direction: str | None, latest, empty: bool, samples: int) -> str:
    if empty:
        if samples:
            return f"No {virus} wastewater samples for {region} in the last two weeks; the most recent reading, from {_day(latest)}, is shown below."
        return f"No {virus} wastewater data for {region} in this period."
    if level == "high":
        return f"A lot of {virus} in {region}'s wastewater, and it is rising."
    if level == "moderate":
        return f"{virus} is showing up in a fair share of samples in {region}" + (", and the trend is rising." if direction == "rising" else ".")
    return f"Little {virus} in {region}'s wastewater recently."
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
    virus = VIRUS_WORD[source]
    plural = "sample" if samples == 1 else "samples"
    site_s = "site" if sites == 1 else "sites"
    if empty:
        facts = [f"No samples in the two weeks you asked about; latest sample {_day(f.latest_sample_date)}"]
        if samples:
            facts.append(f"Most recent reading ({_day(window.start)} to {_day(window.end)}): {pct} of {samples} {plural} positive, from {sites} {site_s}")
    else:
        facts = [f"{pct} of {samples} {plural} were positive between {_day(window.start)} and {_day(window.end)}, from {sites} {site_s}",
                 f"Latest sample {_day(f.latest_sample_date)}" + (" (the data lags the end of the period)" if f.coverage == "partial" else "")]
        if f.prior_positive_share is not None and f.delta_share is not None:
            facts.append(f"Two weeks before: {f.prior_positive_share * 100:.0f}% positive, so the share is {f.direction or 'unchanged'} ({f.delta_share:+.0f} points)")
    meaning = meaning_for(level, virus, f.region, f.direction, f.latest_sample_date, empty, samples)
    caveats = list(f.notes) + ([f.state_note] if f.state_note else []) + list(answer.fallback_reasons)
    model = (answer.completions[-1].routed_model if answer.provider == "nightshift" and answer.completions else "template")
    return Finding(
        source=source, title=TITLES[source], status="ok", level=level, headline=headline, meaning=meaning,
        text=answer.text, facts=facts, caveats=caveats, sources=[NWSS], model=model,
        trace=answer.memory.id if answer.memory else None, seconds=time.perf_counter() - t0,
        raw={"question": question, "facts": f.to_dict(), "factSheet": render_facts(f),
             "statements": list(answer.statements),
             "receipts": [{"receiptId": c.receipt_id, "routedModel": c.routed_model} for c in answer.completions],
             "coverage": f.coverage, "positiveShare": share, "direction": f.direction},
    )
