"""Composer agent: the verdict by rules, the prose by Nightshift (checked) or
by templates, reviewed by the Evaluator agent and revised up to MAX_REVISIONS
times, then assembled into a TravelPlan."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from wastewater_agent.agent.writer import allowed_numbers, foreign_numbers
from wastewater_agent.llm import NightshiftProvider, ProviderUnauthorized, ProviderUnavailable

from . import evaluator
from .findings import LEVEL_LABEL, LEVEL_RANK, LEVEL_TAGLINE, ORDER, Finding, TravelPlan, Verdict
from .trip import TripRequest

HEALTH = ("covid", "flu", "pertussis")
COMPOSER_ATTEMPTS = 2
MAX_TOKENS = 900
MAX_REVISIONS = 2   # evaluator rounds after the first draft: at most 3 drafts and 3 reviews

SYSTEM_PROMPT = """You are the composer for a family visit planner. You receive a fact sheet about one
planned visit: the verdict (already decided by rules), what each source found, and who is in the household.
Write for the person planning the visit.

Reply with one JSON object and nothing else: {"intro": string, "precautions": [string, ...]}.
- intro: 2 or 3 plain sentences on what drives the verdict. Do not restate the verdict label (Go, Caution, Stop),
  its tagline or the trip dates: the page already shows them above the intro. Name the destination city or state.
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
                       "None of the sources had enough recent data for this trip.", LEVEL_TAGLINE["unknown"])
    top = max(known.values(), key=lambda l: LEVEL_RANK[l])
    drivers = [f for f in findings if known.get(f.source) == top]
    # One plain sentence per driving source (the adapter's "meaning"), headline as fallback.
    parts = [(f.meaning or f"{f.title}: {f.headline}").rstrip(".") + "." for f in drivers]
    parts = [p[0].upper() + p[1:] for p in parts]
    reason = " ".join(parts)
    if top in ("moderate", "high") and sensitive and any(f.source in HEALTH and f.level == "moderate" for f in drivers):
        reason += f" Counted as {top} because the household includes {trip.household()}."
    if top == "low":
        reason = "Every source with data is at a low level. " + reason
    return Verdict(top, LEVEL_LABEL[top], reason, LEVEL_TAGLINE[top])


# -- fact sheet ------------------------------------------------------------

def render_sheet(trip: TripRequest, findings: list[Finding], verdict: Verdict) -> str:
    lines = [
        f"destination: {trip.label}" + (f" ({trip.to_county})" if trip.to_county else ""),
        f"travelling from: {trip.from_city}, {trip.from_state.upper()}",
        f"dates: {trip.start.isoformat()} to {trip.end.isoformat()}",
        f"party: {trip.adults} adults, {trip.children} children; household includes {trip.household()}",
        f"verdict: {verdict.level} ({verdict.label}: {verdict.tagline}). reason: {verdict.reason}",
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


def allowed_for(trip: TripRequest, sheet: str) -> set[float]:
    """Numbers prose may use: those in the fact sheet, plus the trip's own date parts (the sheet
    writes dates as 2026-11-17, whose day and month the figure check would not otherwise allow)."""
    parts = {trip.start.day, trip.start.month, trip.start.year, trip.end.day, trip.end.month, trip.end.year}
    return allowed_numbers(sheet) | {float(x) for x in parts}


# -- prose -----------------------------------------------------------------

def template_prose(trip: TripRequest, findings: list[Finding], verdict: Verdict) -> tuple[str, list[str]]:
    intro = verdict.reason  # the label, tagline and dates are shown above the intro already
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
        items.append("Keep hand hygiene strict around older relatives and air the rooms you share.")
    if "young_child" in trip.with_:
        items.append("Keep young children's hands washed and their routine vaccines up to date.")
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
    if not isinstance(d, dict):
        return None
    intro, prec = d.get("intro"), d.get("precautions")
    if not isinstance(intro, str) or not isinstance(prec, list) or not prec:
        return None
    prec = [str(p).strip() for p in prec if str(p).strip()]
    return (intro.strip(), prec[:8]) if len(intro.strip()) > 20 and prec else None


def write_prose(trip: TripRequest, findings: list[Finding], verdict: Verdict,
                provider: NightshiftProvider | None, previous: tuple[str, list[str]] | None = None,
                feedback: list[str] | None = None) -> tuple[str, list[str], str, list[str]]:
    """Returns (intro, precautions, model, notes). With `previous` and `feedback` this is a
    revision: the model sees its last draft and the evaluator's issues and fixes only those."""
    notes: list[str] = []
    if provider is None:
        intro, prec = template_prose(trip, findings, verdict)
        return intro, prec, "template", ["composer: Nightshift unavailable, template prose"]
    sheet = render_sheet(trip, findings, verdict)
    allowed = allowed_for(trip, sheet)
    ask = f"FACT SHEET\n{sheet}"
    if previous and feedback:
        last = json.dumps({"intro": previous[0], "precautions": previous[1]}, ensure_ascii=False, indent=1)
        ask += ("\n\nYOUR PREVIOUS DRAFT\n" + last +
                "\n\nAN EVALUATOR FOUND THESE PROBLEMS. Fix every one of them and keep the rest of the draft:\n"
                + "\n".join(f"- {i}" for i in feedback))
    for attempt in range(COMPOSER_ATTEMPTS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"{ask}\n\nrequest: {uuid.uuid4()}"}]
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

def compose_loop(trip: TripRequest, ordered: list[Finding], verdict: Verdict, provider: NightshiftProvider | None,
                 emit: Callable[[dict[str, Any]], None]) -> tuple[str, list[str], str, list[str], dict[str, Any]]:
    """Composer and Evaluator in a bounded loop. Returns (intro, precautions, composer model, notes, evaluation)."""
    sheet = render_sheet(trip, ordered, verdict)
    allowed = allowed_for(trip, sheet)
    drafts: list[tuple[str, list[str], str]] = []
    reviews: list[evaluator.Review] = []
    notes: list[str] = []
    intro, prec, model, n = write_prose(trip, ordered, verdict, provider)
    notes += n
    for rnd in range(1, MAX_REVISIONS + 2):
        emit({"stage": "evaluator", "state": "start", "round": rnd})
        rv = evaluator.review(trip, ordered, verdict, intro, prec, model, provider, sheet, allowed, rnd)
        drafts.append((intro, prec, model)); reviews.append(rv)
        emit({"stage": "evaluator", "state": "done", "round": rnd, "verdict": rv.verdict,
              "issues": len(rv.issues), "model": rv.model})
        if rv.verdict == "pass" or rnd > MAX_REVISIONS or provider is None:
            break
        emit({"stage": "composer", "state": "revise", "round": rnd + 1, "model": provider.model})
        intro, prec, model, n = write_prose(trip, ordered, verdict, provider, previous=(intro, prec), feedback=rv.issues)
        notes += n
    # The last draft that passed; otherwise the one with the fewest rule problems (latest on a tie).
    passed = [i for i, r in enumerate(reviews) if r.verdict == "pass"]
    chosen = passed[-1] if passed else min(range(len(reviews)), key=lambda i: (len(reviews[i].rule_issues), -i))
    if not passed:
        notes.append(f"evaluator: no draft passed after {len(reviews)} reviews; kept draft {chosen + 1}")
    intro, prec, model = drafts[chosen]
    evaluation = {
        "final": reviews[chosen].verdict,
        "rounds": [r.to_dict() for r in reviews],
        "chosenRound": chosen + 1,
        "unresolved": [] if reviews[chosen].verdict == "pass" else reviews[chosen].issues,
        "model": next((r.model for r in reviews if r.model), None),
        "maxRevisions": MAX_REVISIONS,
    }
    return intro, prec, model, notes, evaluation


def compose(trip: TripRequest, findings: dict[str, Finding], provider: NightshiftProvider | None,
            elapsed: float = 0.0, notes: list[str] | None = None,
            emit: Callable[[dict[str, Any]], None] | None = None) -> TravelPlan:
    ordered = [findings[s] for s in ORDER if s in findings]
    verdict = verdict_for(trip, ordered)
    intro, precautions, model, prose_notes, evaluation = compose_loop(trip, ordered, verdict, provider, emit or (lambda e: None))
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
        models={"composer": model, "evaluator": evaluation["model"], **{f.source: f.model for f in ordered}},
        traces={f.source: f.trace for f in ordered},
        notes=list(notes or []) + prose_notes,
        partial=any(f.status != "ok" for f in ordered),
        elapsed_seconds=elapsed,
        evaluation=evaluation,
    )
