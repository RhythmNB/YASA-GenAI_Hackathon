"""Stand-in Planner + Evaluator to show the Weather agent's hand-off working.

Your teammates' real Planner can replace plan_visit(); the Evaluator is the
part that makes this a loop rather than a pipeline: it checks the Weather
agent's hand-off against the evidence and sends it back with feedback if
anything is wrong.

Usage:
  python demo_planner.py --city "New York, NY" --days 3 --household dad \
      --remember "Dad is 85 and gets tired walking more than 20 minutes"
"""
import argparse
import json
import sys

from hmem import MemoryRetrievalService, MemoryStoreService
from llm import Generator
from tracing import Tracer
from weather_agent import WeatherAgent

REQUIRED = ["version", "from", "status", "city", "risk_level", "recommendation", "risk_evaluation",
            "travellers", "summary", "advice", "good_outdoor_windows", "risks", "official_alerts",
            "evidence", "stale", "sources", "model", "outcome_review", "confidence"]
LEVELS = ["low", "moderate", "high"]


def evaluate(msg):
    """Check a Weather hand-off against its own evidence. Returns a list of issues."""
    if msg.get("status") != "ok":
        return [f"weather agent failed: {msg.get('error')}"]
    issues = [f"missing field '{k}'" for k in REQUIRED if k not in msg]
    if issues:
        return issues
    evidence = msg.get("evidence", [])
    by_name = {e["period"]: e for e in evidence}
    for w in msg.get("good_outdoor_windows", []):
        e = by_name.get(w)
        if not e:
            issues.append(f"outdoor window '{w}' has no evidence")
        elif e["risk_level"] != "low" or not e["daytime"]:
            issues.append(f"outdoor window '{w}' is {e['risk_level']} risk or not daytime")
    # The overall level must equal the worst period, and match the summary and recommendation.
    worst = max((LEVELS.index(e["risk_level"]) for e in evidence), default=0)
    if evidence and msg["risk_level"] != LEVELS[worst]:
        issues.append(f"overall risk '{msg['risk_level']}' but worst period is '{LEVELS[worst]}'")
    if not (msg.get("summary") or "").lower().lstrip().startswith(f"weather risk: {msg['risk_level']}"):
        issues.append("summary does not state the weather risk level first")
    if msg["official_alerts"] and not any(r["type"] == "alert" for r in msg["risks"]):
        issues.append("official alerts exist but none is listed as a risk")
    review = msg.get("outcome_review") or {}
    if review.get("verdict") != "pass":
        issues += [f"outcome review: {i}" for i in review.get("issues", [])] or ["outcome review did not pass"]
    if msg.get("stale") and not any(r["type"] == "stale" for r in msg.get("risks", [])):
        issues.append("data is stale but no stale-data risk was reported")
    if len(msg.get("sources", [])) < 2:
        issues.append("no Zetaris query recorded as a source")
    if not (msg.get("summary") or "").strip():
        issues.append("empty summary")
    return issues


def plan_visit(city, days, household, remember, tracer, travellers=None, weekdays=None):
    store = MemoryStoreService(tracer=tracer)
    retriever = MemoryRetrievalService(store, tracer=tracer)
    generator = Generator(tracer=tracer)
    weather = WeatherAgent(generator, store, retriever, tracer)

    for fact in remember or []:
        store.add(fact, tier="long", source="user", confidence=1.0,
                  entities=[household, city], tags=["household"], key=None)

    feedback = None
    for round_no in range(1, 3):
        tracer.event("planner_delegate", round=round_no, to="weather_agent", city=city)
        msg = weather.run(city, days, household=household, feedback=feedback, travellers=travellers,
                          weekdays=weekdays)
        issues = evaluate(msg)
        tracer.event("evaluator_verdict", round=round_no, ok=not issues, issues=issues)
        if not issues:
            return msg, []
        if msg.get("status") != "ok":
            return msg, issues  # nothing to retry against
        feedback = issues
    return msg, issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="New York, NY", help="City id like 'Boston, MA' (see cities.py)")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--household", default="dad")
    ap.add_argument("--remember", action="append", help="household fact to store in H-MEM (repeatable)")
    ap.add_argument("--traveller", action="append", dest="travellers",
                    help="sensitive group travelling: older_adult, infant, young_child, pregnant, health_condition")
    args = ap.parse_args()

    tracer = Tracer()
    msg, issues = plan_visit(args.city, args.days, args.household, args.remember, tracer, args.travellers)
    print(json.dumps(msg, indent=2, ensure_ascii=False, default=str))
    print(f"\nEvaluator: {'PASSED' if not issues else 'ISSUES: ' + '; '.join(issues)}")
    print(f"Trace: {tracer.path}")
    sys.exit(0 if not issues else 1)


if __name__ == "__main__":
    main()
