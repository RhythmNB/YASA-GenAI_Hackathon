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
        elif e.get("stage") == "evaluator" and e.get("state") == "done":
            print(f"  evaluator round {e['round']}: {e['verdict']}" + (f", {e['issues']} issues" if e.get("issues") else "")
                  + f" via {e.get('model') or 'rules only'}", file=sys.stderr)
        elif e.get("stage") == "location" and e.get("state") == "done":
            print(f"  location: {e['place']}, county {e.get('county') or '-'} via Zetaris {e['table']} ({e['seconds']} s)", file=sys.stderr)
        elif e.get("stage") == "location" and e.get("state") == "failed":
            print(f"  location: Zetaris lookup unavailable ({e.get('error')}); using the given county", file=sys.stderr)
        elif e.get("stage") == "location":
            return
        elif e.get("stage") == "evaluator" and e.get("state") == "findings":
            reqs = e.get("requests") or []
            print("  evaluator: findings complete, nothing to ask again" if not reqs else
                  "  evaluator: sending the planner back: " + "; ".join(f"{r['source']} ({r['action']})" for r in reqs), file=sys.stderr)
        elif e.get("retry") and e.get("state") in ("done", "failed"):
            print(f"  {e['stage']} (asked again, {e.get('action')}): {e.get('level')}, keeping the {e.get('kept')} answer", file=sys.stderr)
        elif e.get("retry"):
            return
        elif e.get("state") == "revise":
            print(f"  composer: revising (draft {e['round']})", file=sys.stderr)
        elif e.get("stage") == "evaluator":
            return
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
        # The plan carries non-ASCII text (degree signs, dashes); write it as UTF-8
        # whatever the console code page, so a redirect to a file stays valid JSON.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0
    v = d["verdict"]
    print(f"\n{v['label'].upper()}: {v.get('tagline', '')}  ({v['level']})\n{v['reason']}\n\n{d['intro']}\n")
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
    ev = d.get("evaluation") or {}
    for rp in ev.get("replans") or []:
        for r in rp["requests"]:
            print(f"\nre-check: {r['source']} ({r['action']}): {r['reason']}; {r['before']['level']} -> {r['after']['level']}, kept the {r['kept']} answer")
    if ev:
        print(f"\nevaluation: {ev['final']} after {len(ev['rounds'])} review(s); kept draft {ev['chosenRound']}")
        for r in ev["rounds"]:
            print(f"  round {r['round']}: {r['verdict']}" + "".join(f"\n    - {i}" for i in r["issues"]))
    print("\nmodels: " + ", ".join(f"{k}={v}" for k, v in d["models"].items()))
    print(f"elapsed: {d['elapsedSeconds']} s" + ("  (partial)" if d["partial"] else ""))
    for n in d["notes"]:
        print(f"note: {n}")
    return 0
