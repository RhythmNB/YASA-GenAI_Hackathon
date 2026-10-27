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
    if level == "unknown":
        meaning = f"CDC has no complete whooping cough count for {dest_name} this year, so this cannot be judged."
    else:
        meaning = f"Whooping cough in {dest_name} is {dest.get('trend')} and {dest.get('vs_national')}."
    return Finding(
        source="pertussis", title=TITLES["pertussis"], status="ok", level=level, headline=headline, meaning=meaning,
        text=res["briefing"], facts=facts, caveats=caveats,
        sources=[{"title": s["title"], "url": s["url"]} for s in res.get("sources", [])],
        model="template", trace=res.get("method"), seconds=time.perf_counter() - t0,
        raw={"facts": res["facts"], "method": res.get("method"), "destination": dest},
    )
