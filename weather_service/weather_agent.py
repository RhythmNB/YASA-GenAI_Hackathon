"""Weather agent for the visit planner.

Gets weather for a city through Zetaris (via weather_tool), reads household
context from H-MEM, asks the model (Meterless Nightshift) to write advice for
an older visitor, checks its own output, saves key facts back to H-MEM, and
returns a structured hand-off message for the Planner / Evaluator.

The facts in the hand-off (outdoor windows, risks, alerts) are computed from the
data, never invented by the model. The model only writes the summary and advice,
and the agent checks that text before handing it off.
"""
import json
import os
import re
from datetime import datetime

from critic import review_outcome
from hmem import MemoryRetrievalService
from risk import _overlaps, assess, detect_travellers
from cities import get_city
from weather_tool import get_weather_briefing

HANDOFF_VERSION = "1.1"
AGENT = "weather_agent"


def _default_refresher(city_ids):
    import ingest_weather
    return ingest_weather.refresh(city_ids, quick=True, verbose=False,
                                  skip_postgres=os.getenv("WEATHER_REFRESH_POSTGRES", "1") == "0")


def _max_age_hours():
    return float(os.getenv("WEATHER_MAX_AGE_HOURS", "1"))

SYSTEM_PROMPT = (
    "You are the Weather agent in a trip planner. You summarise National Weather Service "
    "data and a pre-computed WEATHER RISK EVALUATION for the user's trip. Use ONLY the facts "
    "provided and never change the risk level. Official NWS alerts come first. Tailor advice "
    "only to the travellers listed under TRAVELLERS; if none are listed, give general advice "
    "and do not assume anyone is elderly, a child, pregnant or unwell. Keep advice practical "
    "(timing, clothing, shade, water, indoor options). Never give medical advice; for anything "
    "clinical say to check with a GP. The summary MUST start with exactly "
    "'Weather risk: <Level> (<Recommendation>).' using the given level and recommendation. "
    'Reply with JSON only: {"summary": "<2-3 sentences>", "advice": ["<short tip>", ...]}'
)


def _risks(evaluation, briefing):
    """Flatten the risk evaluation into one entry per distinct risk."""
    risks, seen = [], set()
    for p in evaluation["periods"]:
        for r in p["reasons"]:
            period = None if r["type"] == "alert" else p["period"]
            key = (r["type"], period, r["detail"])
            if key not in seen:
                seen.add(key)
                risks.append({"type": r["type"], "level": r["level"], "period": period, "detail": r["detail"]})
    if briefing["stale"]:
        risks.append({"type": "stale", "level": "low", "period": None,
                      "detail": f"Weather data is {briefing['data_age_hours']} hours old; re-run refresh_weather.bat"})
    return risks


def _filter_weekdays(periods, weekdays):
    """Keep periods that start on the given weekdays (local time of the forecast)."""
    wanted = {w.lower() for w in weekdays}
    kept = []
    for p in periods:
        try:
            day = datetime.fromisoformat(str(p["start"]).replace("Z", "+00:00")).strftime("%A").lower()
        except ValueError:
            day = p["name"].split()[0].lower()
        if day in wanted:
            kept.append(p)
    return kept


def _evidence(briefing, evaluation):
    levels = {p["period"]: p["level"] for p in evaluation["periods"]}
    return [{"period": p["name"], "start": p["start"], "daytime": p["daytime"],
             "temperature_f": p["temperature_f"], "precip_chance_pct": p["precip_chance_pct"],
             "wind": p["wind"], "summary": p["summary"], "flags": p["flags"],
             "risk_level": levels.get(p["name"], "low")} for p in briefing["periods"]]


def _parse_json(text):
    """Pull the JSON object out of a model reply (models often wrap it in ``` fences)."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("no JSON object in reply")
    data = json.loads(match.group(0))
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("missing 'summary'")
    advice = data.get("advice", [])
    if not isinstance(advice, list):
        raise ValueError("'advice' must be a list")
    return {"summary": data["summary"].strip(), "advice": [str(a) for a in advice][:6]}


def _sample_reply(label, windows, risks, evaluation, travellers, memories):
    """Deterministic stand-in for the model in sample mode."""
    lvl = evaluation["overall_level"]
    summary = f"Weather risk: {lvl.capitalize()} ({evaluation['recommendation']})."
    if windows:
        summary += f" Best times to be outside in {label}: {', '.join(windows)}."
    else:
        summary += f" No low-risk daytime windows in {label} over this period."
    if evaluation["reasons"]:
        summary += " Main reasons: " + "; ".join(evaluation["reasons"][:3]) + "."
    types = {r["type"] for r in risks}
    advice = []
    if "alert" in types:
        advice.append("Follow the official NWS alert instructions first.")
    if "heat" in types:
        advice.append("Plan outdoor time for the morning and bring water and shade.")
    if "cold" in types:
        advice.append("Pack warm layers.")
    if "rain" in types or "storm" in types:
        advice.append("Have an indoor backup plan for wet or stormy periods.")
    if "wind" in types:
        advice.append("Secure loose items and avoid exposed areas in strong wind.")
    if lvl == "high":
        advice.append("Consider rescheduling outdoor plans or choosing indoor options on the high-risk days.")
    if travellers:
        advice.append("Advice uses stricter thresholds for: " + ", ".join(t.replace("_", " ") for t in travellers)
                      + "; plan extra rest and shelter for them.")
    if memories:
        advice.append("Household notes considered: " + memories[0][1].content)
    if not advice:
        advice.append("Conditions look comfortable; normal precautions are enough.")
    return json.dumps({"summary": summary, "advice": advice})


def _self_check(parsed, briefing, windows, evaluation):
    """Return problems with the model's text, judged against the data."""
    problems = []
    lvl = evaluation["overall_level"]
    if not re.match(rf"\s*weather risk:\s*{lvl}\b", parsed["summary"], re.I):
        problems.append(f"summary must start with 'Weather risk: {lvl.capitalize()} "
                        f"({evaluation['recommendation']}).'")
    if lvl == "high" and re.search(r"\b(safe|perfect|ideal|great|no concerns)\b", parsed["summary"], re.I):
        problems.append("summary sounds reassuring but the weather risk is high")
    known = {p["name"].lower() for p in briefing["periods"]}
    for name in re.findall(r"\b((?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day(?: Night)?|Tonight|Today|This Afternoon)\b",
                           parsed["summary"]):
        if name.lower() not in known:
            problems.append(f"summary mentions '{name}', which is not in the forecast data")
    for a in briefing["active_alerts"]:
        event = (a.get("event") or "").lower()
        if event and event not in (parsed["summary"] + " ".join(parsed["advice"])).lower():
            problems.append(f"official alert '{a.get('event')}' is not mentioned")
    if not windows and re.search(r"\b(perfect|ideal|great) (day|weather)\b", parsed["summary"], re.I):
        problems.append("summary sounds positive but no comfortable windows exist")
    return problems


class WeatherAgent:
    name = AGENT

    def __init__(self, generator, store, retriever, tracer, briefing_fn=get_weather_briefing,
                 refresher=_default_refresher):
        self.generate = generator
        self.store = store
        self.retriever = retriever
        self.tracer = tracer
        self.briefing_fn = briefing_fn
        self.refresher = refresher  # None disables live refresh

    def _fresh_briefing(self, city, days):
        """Get the briefing; if this city's data is too old, re-download just this city
        from NWS first, then read it again (through Zetaris in zetaris mode)."""
        briefing = self.briefing_fn(city, days)
        age = briefing.get("data_age_hours")
        limit = _max_age_hours()
        if self.refresher is None or os.getenv("WEATHER_AUTO_REFRESH", "1") == "0":
            return briefing
        if age is not None and age <= limit:
            self.tracer.event("freshness_check", agent=AGENT, city=city, data_age_hours=age,
                              max_age_hours=limit, action="use stored data")
            return briefing
        self.tracer.event("freshness_check", agent=AGENT, city=city, data_age_hours=age,
                          max_age_hours=limit, action="refresh from NWS")
        try:
            result = self.refresher([city])
        except Exception as exc:  # offline or NWS down: answer with what we have, and say so
            self.tracer.event("live_refresh", agent=AGENT, city=city, ok=False, error=str(exc))
            return briefing
        ok = city in (result or {}).get("ok", [])
        self.tracer.event("live_refresh", agent=AGENT, city=city, ok=ok,
                          seconds=(result or {}).get("seconds"),
                          postgres_ok=(result or {}).get("postgres_ok"),
                          postgres_error=(result or {}).get("postgres_error"))
        return self.briefing_fn(city, days) if ok else briefing

    def run(self, city, days=3, household=None, feedback=None, travellers=None, weekdays=None,
            max_attempts=2):
        """travellers: sensitive groups stated by the user or another agent, e.g. ["older_adult"].
        Nothing is assumed: without them the general (healthy adult) thresholds are used.
        weekdays: optional day names to keep, e.g. ["Saturday", "Sunday"] for "this weekend"."""
        info = get_city(city)
        city = info["id"] if info else str(city).strip()
        self.tracer.event("agent_start", agent=AGENT, city=city, days=days,
                          household=household, feedback=feedback, travellers=travellers)

        # 1. Memory: what do we already know about this household and city?
        memories = self.retriever.retrieve(
            f"{city} weather outdoor visit heat cold rain walk {household or ''}",
            entities=[city, household] if household else [city],
            tags=["household", "weather"], top_n=5, agent=AGENT,
        )

        # 2. Tool: weather through Zetaris (or the sample snapshot).
        try:
            briefing = self._fresh_briefing(city, days)
        except Exception as exc:  # hand the failure to the Planner instead of crashing
            self.tracer.event("tool_error", agent=AGENT, tool="get_weather_briefing", error=str(exc))
            return self._handoff(city, status="error", error=str(exc))
        if weekdays:
            kept = _filter_weekdays(briefing["periods"], weekdays)
            if kept:
                briefing = {**briefing, "periods": kept}
        # Only alerts that overlap the periods asked about count; the rest are reported separately.
        relevant = [a for a in briefing["active_alerts"]
                    if not briefing["periods"] or any(_overlaps(p, a) for p in briefing["periods"])]
        other = [a for a in briefing["active_alerts"] if a not in relevant]
        briefing = {**briefing, "active_alerts": relevant, "other_alerts": other}
        self.tracer.event("tool_call", agent=AGENT, tool="get_weather_briefing", mode=briefing["mode"],
                          queries=briefing["trace"]["queries"], periods=len(briefing["periods"]),
                          alerts=len(briefing["active_alerts"]), stale=briefing["stale"])

        # 3. Who is travelling: only what was stated (by the caller, or in remembered household facts).
        stated = sorted(set(travellers or []))
        from_memory = sorted(set(g for _, r in memories if "household" in r.tags
                                 for g in detect_travellers(r.content)) - set(stated))
        groups = sorted(set(stated) | set(from_memory))
        traveller_info = {"groups": groups, "stated": stated, "from_memory": from_memory}

        # 4. Risk evaluation and facts computed from the data (never from the model).
        evaluation = assess(briefing["periods"], briefing["active_alerts"], groups)
        self.tracer.event("risk_evaluation", agent=AGENT, overall=evaluation["overall_level"],
                          profile=evaluation["profile"], counts=evaluation["counts"],
                          reasons=evaluation["reasons"], travellers=traveller_info)
        windows = [p["period"] for p in evaluation["periods"] if p["daytime"] and p["level"] == "low"]
        risks = _risks(evaluation, briefing)
        evidence = _evidence(briefing, evaluation)

        # 5. Model writes the summary and advice; the agent checks it and retries once.
        prompt = "\n\n".join([
            MemoryRetrievalService.format_context(memories),
            f"CITY: {briefing['label']}",
            "FORECAST (NWS, via Zetaris):\n" + json.dumps(evidence, indent=1),
            "OFFICIAL ALERTS:\n" + json.dumps(briefing["active_alerts"], indent=1),
            "TRAVELLERS: " + (", ".join(groups) if groups else "not specified (give general advice)"),
            "WEATHER RISK EVALUATION (computed, do not change):\n" + json.dumps(
                {k: evaluation[k] for k in ("overall_level", "recommendation", "reasons", "counts")}, indent=1),
            f"LOW-RISK DAYTIME WINDOWS (computed): {windows}",
            "RISKS (computed):\n" + json.dumps(risks, indent=1),
            ("PLANNER FEEDBACK TO FIX:\n" + "\n".join(feedback)) if feedback else "",
        ])
        sample = lambda: _sample_reply(briefing["label"], windows, risks, evaluation, groups, memories)  # noqa: E731
        parsed, model, problems = None, None, []
        for attempt in range(1, max_attempts + 1):
            ask = prompt if attempt == 1 else (
                prompt + "\n\nYOUR LAST REPLY HAD THESE PROBLEMS, FIX THEM:\n" + "\n".join(problems))
            reply = self.generate(ask, system_prompt=SYSTEM_PROMPT, agent=AGENT, sample_response=sample)
            model = reply["model"]
            try:
                parsed = _parse_json(reply["text"])
                problems = _self_check(parsed, briefing, windows, evaluation)
            except (ValueError, json.JSONDecodeError) as exc:
                parsed, problems = None, [f"reply was not valid JSON: {exc}"]
            self.tracer.event("self_check", agent=AGENT, attempt=attempt, problems=problems)
            if parsed and not problems:
                break
        if not parsed or problems:
            # Fall back to the deterministic text so the hand-off is always usable.
            parsed = _parse_json(sample())
            self.tracer.event("fallback", agent=AGENT, reason=problems)

        # 6. Outcome review: a second evaluation of the finished answer. On "revise" the agent
        #    rewrites once with the reviewer's points, passes the self-check again, and is re-reviewed.
        def draft(text):
            return {"summary": text["summary"], "advice": text["advice"], "risks": risks,
                    "risk_level": evaluation["overall_level"], "evidence": evidence,
                    "risk_evaluation": {k: evaluation[k] for k in ("overall_level", "recommendation", "reasons")},
                    "travellers": traveller_info, "data_age_hours": briefing["data_age_hours"]}

        review = review_outcome(draft(parsed), self.generate, self.tracer, round_no=1)
        if review["verdict"] == "revise":
            ask = (prompt + "\n\nYOUR ANSWER WAS REVIEWED. REVISE THE ADVICE TO FIX THESE POINTS, "
                   "KEEPING THE SAME RISK LEVEL:\n" + "\n".join(review["issues"])
                   + "\n\nPREVIOUS ANSWER:\n" + json.dumps(parsed))
            reply = self.generate(ask, system_prompt=SYSTEM_PROMPT, agent=AGENT, sample_response=sample)
            try:
                revised = _parse_json(reply["text"])
                rev_problems = _self_check(revised, briefing, windows, evaluation)
            except (ValueError, json.JSONDecodeError) as exc:
                revised, rev_problems = None, [f"revision was not valid JSON: {exc}"]
            self.tracer.event("revision", agent=AGENT, problems=rev_problems)
            if revised and not rev_problems:
                second = review_outcome(draft(revised), self.generate, self.tracer, round_no=2)
                if len(second["issues"]) <= len(review["issues"]):
                    parsed, model, review = revised, reply["model"], second

        # 7. Save what other agents should know into H-MEM.
        levels = {p["period"]: p["level"] for p in evaluation["periods"]}
        for p in briefing["periods"]:
            self.store.add(
                f"{city} {p['name']}: {p['temperature_f']}°F, {p['precip_chance_pct']}% rain, "
                f"{p['summary']}, weather risk {levels.get(p['name'], 'low')}",
                tier="short", source=f"{AGENT}/nws", confidence=0.9,
                entities=[city], tags=["weather", "forecast"], key=f"weather:{city}:{p['name']}",
            )
        self.store.add(f"{city} weather summary: {parsed['summary']}", tier="working",
                       source=AGENT, confidence=0.8, entities=[city] + ([household] if household else []),
                       tags=["weather", "summary"], key=f"weather:{city}:summary")

        return self._handoff(city, status="ok", briefing=briefing, windows=windows, risks=risks,
                             evidence=evidence, parsed=parsed, model=model, memories=memories,
                             evaluation=evaluation, traveller_info=traveller_info, review=review)

    def _handoff(self, city, status, error=None, briefing=None, windows=None, risks=None,
                 evidence=None, parsed=None, model=None, memories=None, evaluation=None,
                 traveller_info=None, review=None):
        msg = {
            "version": HANDOFF_VERSION,
            "from": AGENT,
            "status": status,
            "city": city,
            "label": city,
            "periods_covered": [e["period"] for e in (evidence or [])],
            "risk_level": evaluation["overall_level"] if evaluation else None,
            "recommendation": evaluation["recommendation"] if evaluation else None,
            "risk_evaluation": ({k: evaluation[k] for k in
                                 ("overall_level", "recommendation", "reasons", "profile", "counts")}
                                if evaluation else None),
            "travellers": traveller_info or {"groups": [], "stated": [], "from_memory": []},
            "outcome_review": review,
            "confidence": review["confidence"]["level"] if review else None,
            "summary": parsed["summary"] if parsed else None,
            "advice": parsed["advice"] if parsed else [],
            "good_outdoor_windows": windows or [],
            "risks": risks or [],
            "official_alerts": briefing["active_alerts"] if briefing else [],
            "other_active_alerts": briefing.get("other_alerts", []) if briefing else [],
            "evidence": evidence or [],
            "data_fetched_at": briefing["data_fetched_at"] if briefing else None,
            "data_age_hours": briefing["data_age_hours"] if briefing else None,
            "stale": briefing["stale"] if briefing else None,
            "sources": (["National Weather Service (api.weather.gov) via Zetaris"]
                        + briefing["trace"]["queries"]) if briefing else [],
            "memories_used": [r.id for _, r in (memories or [])],
            "model": model,
            "run_id": self.tracer.run_id,
            "error": error,
        }
        self.tracer.event("handoff", agent=AGENT, to="planner", message=msg)
        return msg

