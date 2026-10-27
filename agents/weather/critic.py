"""Outcome Reviewer: a second evaluation of the Weather agent's finished answer.

The self-check asks "are the facts right?". The reviewer asks "is this a good answer for
this person?":
  - does the advice actually address every risk that was found?
  - does the advice fit the risk level (High must suggest rescheduling or indoor options)?
  - are the travellers the user described addressed (and none invented)?
  - does it stay away from medical advice?
  - how much should the user trust it (confidence from data freshness and coverage)?

Rules run every time. When a model is available (Nightshift), it also reviews the answer as an
independent critic; its points are added to the rule-based ones. The verdict is "pass" or
"revise"; the Weather agent rewrites once on "revise" and is reviewed again.
"""
import json
import re

REVIEWER = "outcome_reviewer"

# What advice must mention when a risk type is present
COVERS = {
    "heat": r"water|hydrat|shade|morning|evening|cool|air.?condition|sun",
    "cold": r"layer|warm|coat|jacket|heat(ed|ing)?\b|glove|indoor",
    "rain": r"umbrella|rain|indoor|backup|wet|waterproof",
    "storm": r"indoor|shelter|storm|lightning|backup|reschedul",
    "wind": r"wind|exposed|secure|shelter|indoor",
    "alert": r"alert|official|nws|warning|advisory|instruction",
}
HIGH_RISK_ACTION = r"reschedul|postpone|indoor|avoid|another day|delay|cancel"
TRAVELLER_WORDS = {
    "older_adult": r"older|elderly|senior|dad|mum|mom|father|mother|grand|parent|rest|seat",
    "infant": r"baby|infant|newborn|pram|stroller",
    "young_child": r"child|kid|toddler",
    "pregnant": r"pregnan",
    "health_condition": r"condition|mobility|wheelchair|walking frame|walker|medical|gp|doctor|rest",
}
INVENTED_PEOPLE = r"\b(elderly|older adult|senior|baby|infant|newborn|toddler|pregnan)\w*"
MEDICAL = r"\b(dose|dosage|mg\b|medication|prescri|ibuprofen|paracetamol|aspirin|diagnos)"

REVIEW_PROMPT = (
    "You are the Outcome Reviewer for a weather trip-planning agent. Judge whether the ANSWER is "
    "useful and appropriate for the TRAVELLERS given the RISK EVALUATION and RISKS. Check: does the "
    "advice address each risk; does it fit the risk level; does it address the stated travellers "
    "without inventing others; does it avoid medical advice; is anything important missing. "
    "Do not re-judge the risk level itself. Reply with JSON only: "
    '{"verdict": "pass" or "revise", "issues": ["<short, specific problem>", ...]}'
)


def confidence(handoff):
    """How much to trust the answer, from data freshness and coverage."""
    age = handoff.get("data_age_hours")
    covered = len(handoff.get("evidence") or [])
    reasons = []
    if age is None:
        level = "low"
        reasons.append("data age unknown")
    elif age <= 1:
        level = "high"
        reasons.append(f"data {age} h old")
    elif age <= 6:
        level = "medium"
        reasons.append(f"data {age} h old")
    else:
        level = "low"
        reasons.append(f"data {age} h old (stale)")
    if covered < 2:
        level = "low"
        reasons.append(f"only {covered} forecast period(s) available")
    return {"level": level, "reasons": reasons}


def rule_review(handoff):
    """Deterministic checks of the finished answer. Returns a list of issues."""
    issues = []
    advice = " ".join(handoff.get("advice") or [])
    text = (handoff.get("summary") or "") + " " + advice
    risk_types = {r["type"] for r in handoff.get("risks") or [] if r["type"] != "stale"}

    for kind in sorted(risk_types):
        pattern = COVERS.get(kind)
        if pattern and not re.search(pattern, advice, re.I):
            issues.append(f"advice does not address the {kind} risk")

    if handoff.get("risk_level") == "high" and not re.search(HIGH_RISK_ACTION, text, re.I):
        issues.append("risk is High but nothing suggests rescheduling, postponing or indoor options")

    groups = (handoff.get("travellers") or {}).get("groups") or []
    for g in groups:
        if not re.search(TRAVELLER_WORDS.get(g, g), advice, re.I):
            issues.append(f"advice does not address the stated traveller group '{g.replace('_', ' ')}'")
    if not groups:
        m = re.search(INVENTED_PEOPLE, text, re.I)
        if m:
            issues.append(f"answer mentions '{m.group(0)}' but no such traveller was described")

    if re.search(MEDICAL, text, re.I):
        issues.append("answer contains medical advice; it should point to a GP instead")

    if not (handoff.get("advice") or []):
        issues.append("no practical advice given")
    return issues


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    data = json.loads(m.group(0)) if m else {}
    verdict = str(data.get("verdict", "pass")).lower()
    issues = [str(i) for i in data.get("issues", []) if str(i).strip()][:5]
    return ("revise" if verdict == "revise" else "pass"), issues


def review_outcome(handoff, generator=None, tracer=None, round_no=1):
    """Second evaluation of a finished hand-off. Returns the review dict."""
    rule_issues = rule_review(handoff)
    model_issues, model = [], None
    if generator is not None:
        payload = {
            "ANSWER": {"summary": handoff.get("summary"), "advice": handoff.get("advice")},
            "RISK EVALUATION": handoff.get("risk_evaluation"),
            "RISKS": handoff.get("risks"),
            "TRAVELLERS": (handoff.get("travellers") or {}).get("groups") or "not specified",
        }
        try:
            reply = generator(json.dumps(payload, indent=1, default=str), system_prompt=REVIEW_PROMPT,
                              agent=REVIEWER, sample_response='{"verdict": "pass", "issues": []}')
            model = reply["model"]
            verdict, model_issues = _parse(reply["text"])
            if verdict == "pass":
                model_issues = []
        except Exception as exc:  # reviewer problems never block the answer
            model_issues = []
            if tracer:
                tracer.event("outcome_review_error", agent=REVIEWER, error=str(exc))
    issues = rule_issues + [f"(model) {i}" for i in model_issues]
    review = {
        "verdict": "revise" if issues else "pass",
        "issues": issues,
        "rule_issues": rule_issues,
        "model_issues": model_issues,
        "confidence": confidence(handoff),
        "reviewer_model": model,
        "round": round_no,
    }
    if tracer:
        tracer.event("outcome_review", agent=REVIEWER, **review)
    return review
