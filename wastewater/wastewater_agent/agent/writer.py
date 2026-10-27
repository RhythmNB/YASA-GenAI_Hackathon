"""FactSheet + recalled memories -> answer prose. Nightshift writes from the
given numbers only; offline uses fixed sentence templates."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..llm.base import Completion, Provider, ProviderUnauthorized, ProviderUnavailable
from ..llm.offline import OfflineProvider
from ..states import state_name
from .evaluator import FactSheet

# The routed model (Nemotron) emits reasoning before its answer, so the budget must cover both. The design's 400 was exhausted by reasoning alone.
PROSE_MAX_TOKENS = 1500

SYSTEM_PROMPT = """Write an answer about wastewater surveillance of one virus for a general reader.
Hard rules:
- Use ONLY the figures in the fact sheet, exactly as written (percentages stay percentages). Never invent, estimate, re-round or compute new figures.
- Name the virus exactly as the "virus" line gives it; never mention any other virus.
- The first sentence names the region exactly as the "region" line gives it and states the window's start and end dates.
- If coverage is partial or empty, say that the data lags: give the latest sample date and, when a fallback window is given, report it clearly labelled as the most recent 7-day window with data.
- For a trend question, compare the window with the preceding window using the given direction and change figures.
- If a note about the state is present, include it.
- Describe only what the fact sheet says; do not mention earlier findings or other periods.
- Plain prose, 2 to 5 sentences, no markdown, no headings, no bullet points, no preamble."""


def prior_sentence(memories: list[dict[str, Any]]) -> str:
    """Prior findings are appended verbatim by code, never paraphrased by the
    model, so recalled numbers cannot bleed into the current answer."""
    live = [m for m in memories if not m.get("superseded")]
    if not live:
        return ""
    m = live[0]
    learned = str(m.get("learnedAt") or "")[:10]
    return f"Earlier finding on record ({m.get('id')}, {learned}): {m.get('content')}"


def render_facts(facts: FactSheet) -> str:
    """Labelled lines are read more reliably than nested JSON by small models."""
    lines = [
        f"virus: {facts.pathogen_name}",
        f"region: {facts.region or state_name(facts.state)}",
        f"question type: {'trend (compare with the preceding window)' if facts.intent == 'trend' else 'detection'}",
        f"window: {facts.window.start} to {facts.window.end} ({facts.window.label})",
        f"coverage: {facts.coverage} (latest sample date in the data: {facts.latest_sample_date})",
    ]
    if facts.coverage == "empty":
        lines.append("samples in window: 0 (no data for this window)")
    else:
        lines.append(_summary_line(facts.samples, facts.positives, facts.positive_share, facts.sites,
                                   facts.mean_conc, facts.units))
    if facts.intent == "trend" and facts.prior_window is not None:
        lines.append(f"preceding window: {facts.prior_window.start} to {facts.prior_window.end}")
        lines.append("preceding " + _summary_line(facts.prior_samples or 0, facts.prior_positives or 0,
                                                  facts.prior_positive_share, facts.prior_sites or 0,
                                                  facts.prior_mean_conc, None))
        if facts.direction and facts.direction != "unknown":
            lines.append(f"direction of positive share: {facts.direction} ({facts.delta_share:+.1f} percentage points)")
            if facts.delta_conc is not None:
                lines.append(f"change in mean concentration: {facts.delta_conc:+,.1f}")
        else:
            lines.append("direction: unknown (not enough data in one of the windows)")
    if facts.fallback_window is not None:
        lines.append(f"fallback window (most recent 7 days with data): {facts.fallback_window.start} to {facts.fallback_window.end}")
        lines.append("fallback " + _summary_line(facts.fallback_samples or 0, facts.fallback_positives or 0,
                                                 facts.fallback_positive_share, facts.fallback_sites or 0,
                                                 facts.fallback_mean_conc, facts.fallback_units))
    if facts.state_note:
        lines.append(f"note about the state: {facts.state_note}")
    for n in facts.notes:
        if "mixed units" in n:
            lines.append("note: mean concentration averages mixed units; call it indicative only")
    return "\n".join(lines)


def _summary_line(samples: int, positives: int, share: float | None, sites: int,
                  mean_conc: float | None, units: list[tuple[str, int]] | None) -> str:
    s = f"samples: {samples}; positives: {positives}"
    if share is not None:
        s += f"; positive share: {share * 100:.1f}%"
    s += f"; sites: {sites}"
    if mean_conc is not None:
        s += f"; mean concentration: {mean_conc:,.1f}"
        if units:
            s += " " + units[0][0]
            if len(units) > 1:
                s += " (mixed units: " + ", ".join(f"{u} x{n}" for u, n in units) + ")"
    return s


WRITER_ATTEMPTS = 2


def write(
    facts: FactSheet,
    memories: list[dict[str, Any]],
    provider: Provider | None,
    offline: OfflineProvider,
) -> tuple[str, list[Completion], str | None]:
    """Returns (text, completions made, fallback_reason or None).

    Model prose is accepted only if every figure in it appears in the fact
    sheet. Nightshift races routes and can reclaim a losing route's output for
    a later, similar request, which has been seen to carry numbers from an
    earlier question into a new answer; the check catches that as well as
    ordinary hallucination. One retry carries a nonce to defeat reuse."""
    payload = facts.to_dict()
    payload["region"] = facts.region or state_name(facts.state)
    prior = prior_sentence(memories)
    sheet = render_facts(facts)
    allowed = allowed_numbers(sheet)
    completions: list[Completion] = []
    if provider is not None:
        reason = None
        for attempt in range(WRITER_ATTEMPTS):
            user = f"FACT SHEET\n{sheet}\n\nrequest: {uuid.uuid4()}"
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
            try:
                completion = provider.complete(messages, json_mode=False, max_tokens=PROSE_MAX_TOKENS)
            except ProviderUnauthorized:
                raise
            except ProviderUnavailable as e:
                reason = f"writer fallback: {e}"
                break
            completions.append(completion)
            text = completion.text.strip()
            if len(text) < 20:
                reason = "writer fallback: answer too short"
                continue
            bad = foreign_numbers(text, allowed)
            if bad:
                reason = (
                    f"writer fallback: model prose contained figures not in the fact sheet "
                    f"({', '.join(bad[:6])}); rejected text began: {text[:160]!r}"
                )
                continue
            return _join(text, prior), completions, None
    else:
        reason = "writer fallback: provider offline"
    return _join(offline.write(payload, []), prior), completions, reason


def _join(text: str, prior: str) -> str:
    return f"{text.rstrip()} {prior}" if prior else text


# -- figure validation --------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ISO_DATE = re.compile(r"(\d{4})-\d{2}-\d{2}")
_ALWAYS_ALLOWED = {7.0}  # "7-day window"
_SMALL_COUNT_MAX = 12  # "2 unit types", "two windows": harmless unless they quantify a figure
_FIGURE_NOUN = re.compile(r"^\s*(?:%|percent|pp\b|percentage|samples?\b|sites?\b|positives?\b|copies\b|detections?\b)", re.I)


def _norm(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def allowed_numbers(sheet: str) -> set[float]:
    years = {float(y) for y in _ISO_DATE.findall(sheet)}
    body = _ISO_DATE.sub(" ", sheet)
    nums = {n for n in (_norm(t) for t in _NUMBER.findall(body)) if n is not None}
    return nums | years | _ALWAYS_ALLOWED


def foreign_numbers(text: str, allowed: set[float]) -> list[str]:
    body = _ISO_DATE.sub(" ", text)
    out: list[str] = []
    for m in _NUMBER.finditer(body):
        token = m.group(0)
        value = _norm(token)
        if value is None or value in allowed:
            continue
        if value.is_integer() and 0 <= value <= _SMALL_COUNT_MAX and not _FIGURE_NOUN.match(body[m.end():m.end() + 16]):
            continue
        out.append(token)
    return out
