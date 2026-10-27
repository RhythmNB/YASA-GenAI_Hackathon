"""Evaluator agent: reviews each draft the composer writes and returns "pass" or
"revise" with specific issues the composer must fix.

Two layers:
- rule checks, in code, every round: figures must come from the fact sheet, the
  intro must not contradict the verdict, every stated household group needs a
  precaution, a source that failed must not be described as if it had data,
  and the draft must name the destination and have a sensible length;
- a Nightshift review (thinking off) for what rules cannot judge: clarity for a
  family reader, claims the sheet does not support, generic precautions,
  medical advice or certainty beyond the data.

The evaluator never changes the verdict level; that is decided by rules in the
composer. It only judges whether the prose says it faithfully and usefully.

It also reviews the agents' findings before anything is composed, and sends the
planner back for what can be fixed by asking again: a source that failed or timed
out is retried once, and a wastewater reading with no recent samples for the
destination's county is asked again at state level. That review is rules only,
so which agents are re-asked is predictable and bounded."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field

from wastewater_agent.agent.writer import foreign_numbers
from wastewater_agent.llm import NightshiftProvider, ProviderUnauthorized, ProviderUnavailable

from wastewater_agent.states import state_name

from .findings import ORDER, Finding, Verdict
from .trip import TripRequest

MAX_TOKENS = 500
MAX_MODEL_ISSUES = 4

# Words that would contradict a verdict level if they appear in the intro.
CONTRADICTS = {
    "low": ("high risk", "reconsider", "avoid the trip", "cancel the trip", "postpone the trip", "dangerous"),
    "moderate": ("no concerns", "nothing to worry", "completely safe", "no risk"),
    "high": ("low risk", "good to go", "no concerns", "safe to travel", "nothing to worry", "no risk"),
    "unknown": ("low risk", "high risk", "good to go"),
}
# A precaution must mention at least one of these for each stated household group.
GROUP_WORDS = {
    "older_adult": ("older", "elderly", "grandparent", "senior", "65"),
    "young_child": ("child", "kid", "toddler"),
    "newborn": ("baby", "newborn", "infant"),
    "pregnant": ("pregnan", "expecting"),
}
SOURCE_WORDS = {
    "covid": ("covid", "sars"), "flu": ("flu", "influenza"), "pertussis": ("whooping", "pertussis"),
    "weather": ("weather", "forecast", "temperature", "rain"), "guidance": (),
}
CALM_WORDS = ("low", "good", "safe", "clear", "fine", "minimal", "no risk", "favourable", "favorable")
MISSING_WORDS = ("unavailable", "not available", "no data", "no recent", "missing", "could not", "couldn't", "unknown", "not checked")

SYSTEM_PROMPT = """You are the evaluator for a family visit planner. You review a draft travel plan
(an intro and a list of precautions) against the fact sheet it was written from.

Check that:
1. the intro states the verdict faithfully (the verdict itself is decided by rules; do not dispute it);
2. every claim is supported by the fact sheet;
3. the precautions are specific to this trip's findings and household, practical, and not generic filler;
4. there is no medical advice beyond what the sheet says and no certainty the data cannot support;
5. sources marked "not available" are not described as if they had data.

Reply with one JSON object and nothing else: {"verdict": "pass" or "revise", "issues": [string, ...]}.
Use "revise" only for a problem a reader would notice. At most 4 issues. Each issue is one short
instruction that says what to change, for example "Say the flu reading is from 6 Oct, not this week"."""


@dataclass
class Review:
    round: int
    verdict: str                      # pass | revise
    rule_issues: list[str] = field(default_factory=list)
    model_issues: list[str] = field(default_factory=list)
    model: str | None = None          # the evaluator's model, or None when its review was skipped
    draft_model: str = ""             # who wrote the draft under review
    note: str | None = None           # why the model review was skipped, if it was

    @property
    def issues(self) -> list[str]:
        return self.rule_issues + self.model_issues

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issues"] = self.issues
        return d


@dataclass
class ReplanRequest:
    source: str        # covid | flu | pertussis | guidance | weather
    action: str        # retry | state_level
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def review_findings(trip: TripRequest, findings: dict[str, Finding]) -> list[ReplanRequest]:
    """What the planner should ask again. A skipped source (for example a city the weather
    agent does not cover) is left alone: asking again would get the same answer."""
    out: list[ReplanRequest] = []
    for src in ORDER:
        f = findings.get(src)
        if f is None:
            continue
        if f.status == "error":
            out.append(ReplanRequest(src, "retry", f"{f.title} did not answer ({(f.error or 'error')[:100]}); ask again"))
        elif src in ("covid", "flu") and f.status == "ok" and f.raw.get("coverage") == "empty" \
                and (f.raw.get("facts") or {}).get("county"):
            county = f.raw["facts"]["county"]
            out.append(ReplanRequest(src, "state_level",
                                     f"no recent {f.title.split(' in ')[0]} samples for {county}; ask for the state-level reading"))
    return out


def usefulness(f: Finding) -> int:
    """How much a finding can tell the reader: answered, and with a usable level."""
    return (2 if f.status == "ok" else 0) + (1 if f.level != "unknown" else 0)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def rule_checks(trip: TripRequest, findings: list[Finding], verdict: Verdict,
                intro: str, precautions: list[str], allowed: set[float]) -> list[str]:
    issues: list[str] = []
    text = intro + "\n" + "\n".join(precautions)
    low_intro, low_prec = intro.lower(), " ".join(precautions).lower()

    bad = foreign_numbers(text, allowed)
    if bad:
        issues.append(f"Remove or correct figures that are not in the fact sheet: {', '.join(bad[:5])}.")

    if trip.to_city.lower() not in low_intro and state_name(trip.to_state).lower() not in low_intro:
        issues.append(f"Name the destination, {trip.to_city} or {state_name(trip.to_state)}, in the intro.")

    clash = [w for w in CONTRADICTS.get(verdict.level, ()) if w in low_intro]
    if clash:
        issues.append(f"The verdict is {verdict.label} ({verdict.tagline.lower()}); the intro says \"{clash[0]}\", which contradicts it.")

    for g in trip.with_:
        if not any(w in low_prec for w in GROUP_WORDS[g]):
            who = {"older_adult": "the older adults", "young_child": "the young children",
                   "newborn": "the newborn", "pregnant": "the person who is pregnant"}[g]
            issues.append(f"Add a precaution specifically for {who} in the household.")

    for f in findings:
        if f.status == "ok" or not SOURCE_WORDS.get(f.source):
            continue
        for s in _sentences(text):
            ls = s.lower()
            if any(w in ls for w in SOURCE_WORDS[f.source]) and any(w in ls for w in CALM_WORDS) \
                    and not any(w in ls for w in MISSING_WORDS):
                issues.append(f"{f.title} was not available for this plan; do not describe it as low or fine (\"{s[:70]}\").")
                break

    if not 3 <= len(precautions) <= 8:
        issues.append(f"Give between 5 and 8 precautions (there are {len(precautions)}).")
    if len(_sentences(intro)) > 5:
        issues.append("Shorten the intro to 2 or 3 sentences.")
    return issues


def _parse(text: str) -> tuple[str, list[str]] | None:
    try:
        d = json.loads(text)
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("verdict") not in ("pass", "revise"):
        return None
    issues = [str(i).strip() for i in (d.get("issues") or []) if str(i).strip()][:MAX_MODEL_ISSUES]
    # "revise" without a concrete issue gives the composer nothing to fix; treat it as a pass.
    return ("revise" if d["verdict"] == "revise" and issues else "pass"), (issues if d["verdict"] == "revise" else [])


def review(trip: TripRequest, findings: list[Finding], verdict: Verdict, intro: str, precautions: list[str],
           draft_model: str, provider: NightshiftProvider | None, sheet: str, allowed: set[float],
           round_no: int) -> Review:
    rules = rule_checks(trip, findings, verdict, intro, precautions, allowed)
    r = Review(round=round_no, verdict="revise" if rules else "pass", rule_issues=rules, draft_model=draft_model)
    if provider is None:
        r.note = "model review skipped: Nightshift unavailable"
        return r
    draft = json.dumps({"intro": intro, "precautions": precautions}, ensure_ascii=False, indent=1)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"FACT SHEET\n{sheet}\n\nDRAFT\n{draft}\n\nrequest: {uuid.uuid4()}"}]
    try:
        c = provider.complete(messages, json_mode=True, max_tokens=MAX_TOKENS)
    except ProviderUnauthorized:
        raise
    except ProviderUnavailable as e:
        r.note = f"model review skipped: {str(e)[:120]}"
        return r
    parsed = _parse(c.text)
    if parsed is None:
        r.note = "model review skipped: reply was not the expected JSON"
        r.model = c.routed_model or provider.model
        return r
    verdict_word, model_issues = parsed
    r.model = c.routed_model or provider.model
    r.model_issues = model_issues
    if verdict_word == "revise":
        r.verdict = "revise"
    return r
