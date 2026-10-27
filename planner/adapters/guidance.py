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
    head = (res["briefing"].split("\n", 1)[0] if res.get("briefing") else "").rstrip(":")
    return Finding(
        source="guidance", title=TITLES["guidance"], status="ok", level="unknown",
        headline=f"CDC advice for visiting {str(res['facts'].get('visited', profile)).replace('_', ' ')}",
        meaning=head,
        text=res["briefing"], facts=[], caveats=list(res.get("caveats", [])),
        sources=[{"title": s["title"], "url": s["url"]} for s in res.get("sources", [])],
        model=None, trace=None, seconds=time.perf_counter() - t0,
        raw={"facts": res.get("facts"), "priority": priority},
    )
