"""Question -> Plan. Nightshift returns a JSON plan that is validated; any
failure falls back to the offline regex planner. SQL is never generated here."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..llm.base import Completion, Provider, ProviderUnauthorized, ProviderUnavailable
from ..llm.offline import OfflineProvider
from ..states import US_STATES, find_state
from .windows import Window, default_window, has_explicit_dates

INTENTS = ("detect", "trend")
PLAN_MAX_TOKENS = 1200
PLAN_ATTEMPTS = 2  # one retry on a transient route error or unparsable plan
_STATE_RE = re.compile(r"^[a-z]{2}$")

SYSTEM_PROMPT = """You plan a query over CDC wastewater surveillance data for SARS-CoV-2.
Reply with ONLY a JSON object, no prose, matching exactly:
{"intent": "detect" | "trend", "state": null | "<two lowercase letters>", "window": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}

Rules:
- intent is "trend" when the question asks whether levels are rising, falling, changing, or compares with an earlier period; otherwise "detect".
- state is the lowercase two-letter US postal code if the question names one state or territory (e.g. "virginia" -> "va"); otherwise null. Never guess a state that is not named.
- window: if a hint window is given, copy it unless the question itself contains explicit dates or a month/year; then use those. Dates must satisfy start <= end <= today.
- Do not add any other keys."""


@dataclass
class Plan:
    intent: str
    state: str | None
    window: Window
    source: str  # nightshift | offline
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "state": self.state, "window": self.window.to_dict(),
                "source": self.source, "notes": list(self.notes)}


class PlanError(ValueError):
    pass


def plan(
    question: str,
    hint: Window | None,
    today: date,
    provider: Provider | None,
    offline: OfflineProvider,
) -> tuple[Plan, Completion | None, str | None]:
    """Returns (plan, completion or None, fallback_reason or None)."""
    hint_dict = {"start": hint.start.isoformat(), "end": hint.end.isoformat()} if hint else None
    if provider is not None:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "today": today.isoformat(),
                "question": question,
                "hintWindow": hint_dict,
            })},
        ]
        reason = None
        for attempt in range(PLAN_ATTEMPTS):
            try:
                completion = provider.complete(messages, json_mode=True, max_tokens=PLAN_MAX_TOKENS)
                raw = json.loads(completion.text)
                p = _validate(raw, question, hint, today)
                p.source = provider.name
                return p, completion, None
            except ProviderUnauthorized:
                raise
            except (ProviderUnavailable, ValueError, PlanError, TypeError) as e:
                # A transient route error (Nightshift 502 "empty_response") is retried once.
                reason = f"planner fallback: {e}"
    else:
        reason = "planner fallback: provider offline"
    raw = offline.plan(question, hint_dict, today)
    p = _validate(raw, question, hint, today)
    p.source = "offline"
    return p, None, reason


def _validate(raw: dict[str, Any], question: str, hint: Window | None, today: date) -> Plan:
    if not isinstance(raw, dict):
        raise PlanError("plan is not an object")
    intent = raw.get("intent")
    if intent not in INTENTS:
        raise PlanError(f"intent must be one of {INTENTS}")
    notes: list[str] = []
    state = raw.get("state")
    if state is not None:
        state = str(state).strip().lower()
        if not _STATE_RE.match(state) or state not in US_STATES.values():
            mapped = US_STATES.get(state) or find_state(question)
            if mapped:
                state = mapped
            else:
                notes.append(f"state {state!r} not recognised; answered nationally")
                state = None
    if state is not None and not _question_names_state(question, state):
        # The model may not guess a state the question does not name.
        notes.append(f"planner proposed state {state!r} that the question does not name; answered nationally")
        state = None
    window = _window_from(raw.get("window"), today)
    if hint is not None:
        if window is None or window == (hint.start, hint.end) or not has_explicit_dates(question):
            chosen = hint
        else:
            chosen = Window(window[0], window[1], f"{window[0]} to {window[1]}")
    elif window is not None:
        chosen = Window(window[0], window[1], f"{window[0]} to {window[1]}")
    else:
        chosen = default_window(today)
        notes.append("no window given; defaulted to last week")
    return Plan(intent=intent, state=state, window=chosen, source="", notes=notes)


def _question_names_state(question: str, code: str) -> bool:
    if find_state(question) == code:
        return True
    low = question.lower()
    names = [name for name, c in US_STATES.items() if c == code]
    if any(re.search(rf"\b{re.escape(n)}\b", low) for n in names):
        return True
    return bool(re.search(rf"\b{code.upper()}\b", question))


def _window_from(raw: Any, today: date) -> tuple[date, date] | None:
    if not isinstance(raw, dict):
        return None
    try:
        start = date.fromisoformat(str(raw.get("start")))
        end = date.fromisoformat(str(raw.get("end")))
    except (TypeError, ValueError):
        raise PlanError("window dates are not ISO dates")
    if end > today:
        end = today
    if start > end:
        raise PlanError("window start is after end")
    return start, end
