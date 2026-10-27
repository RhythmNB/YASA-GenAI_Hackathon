"""Offline provider: a regex planner and a template writer used when
Nightshift is unreachable or returns something unusable."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..states import find_state, state_name

_TREND_WORDS = re.compile(
    r"\b(rising|rise|falling|fall|increas\w*|decreas\w*|trend\w*|go(?:es|ing|ne)?\s+(?:up|down)|went\s+(?:up|down)|"
    r"up or down|compared?|change[ds]?|changing|growing|declin\w*|surg\w*|drop\w*|higher|lower|worse|better|"
    r"improv\w*|worsen\w*|spik\w*|climb\w*)\b",
    re.I,
)


class OfflineProvider:
    name = "offline"

    # -- planner -----------------------------------------------------------

    def plan(self, question: str, hint: dict[str, str] | None, today: date) -> dict[str, Any]:
        intent = "trend" if _TREND_WORDS.search(question) else "detect"
        state = find_state(question)
        if hint is None:
            end = today.fromordinal(today.toordinal() - 1)
            start = end.fromordinal(end.toordinal() - 6)
            hint = {"start": start.isoformat(), "end": end.isoformat()}
        return {"intent": intent, "state": state, "window": dict(hint)}

    # -- writer ------------------------------------------------------------

    def write(self, facts: dict[str, Any], memories: list[dict[str, Any]]) -> str:
        where = facts.get("region") or state_name(facts.get("state"))
        virus = facts.get("pathogen_name") or "SARS-CoV-2"
        w = facts["window"]
        span = f"{w['start']} to {w['end']}"
        coverage = facts.get("coverage")
        parts: list[str] = []

        if coverage == "empty":
            parts.append(
                f"No {virus} wastewater samples are recorded for {where} between {span}; "
                f"the latest sample in the dataset is dated {facts.get('latest_sample_date')}."
            )
            fw = facts.get("fallback_window")
            if fw and facts.get("fallback_samples"):
                parts.append(
                    "Most recent 7-day window with data "
                    f"({fw['start']} to {fw['end']}): {virus} was detected in "
                    f"{facts['fallback_positives']} of {facts['fallback_samples']} samples "
                    f"({_pct(facts['fallback_positive_share'])}) across {facts['fallback_sites']} sites"
                    f"{_conc(facts.get('fallback_mean_conc'), facts.get('fallback_units'))}."
                )
        else:
            detected = "was detected" if facts["positives"] > 0 else "was not detected"
            parts.append(
                f"Between {span}, {virus} {detected} in {where}: "
                f"{facts['positives']} of {facts['samples']} samples were positive "
                f"({_pct(facts['positive_share'])}) across {facts['sites']} sites"
                f"{_conc(facts.get('mean_conc'), facts.get('units'))}."
            )
            if coverage == "partial":
                parts.append(
                    f"Coverage is partial: the latest sample is dated {facts.get('latest_sample_date')}, "
                    "so the end of the window is not yet reported."
                )

        if facts.get("intent") == "trend":
            pw = facts.get("prior_window")
            if facts.get("direction") in (None, "unknown"):
                parts.append(
                    "The trend cannot be assessed because one of the two windows has no samples"
                    + (f" (preceding window {pw['start']} to {pw['end']}: {facts.get('prior_positives')} of "
                       f"{facts.get('prior_samples')} positive)" if pw and facts.get("prior_samples") else "")
                    + "."
                )
            elif pw and facts.get("prior_samples"):
                parts.append(
                    f"Compared with the preceding window ({pw['start']} to {pw['end']}: "
                    f"{facts['prior_positives']} of {facts['prior_samples']} positive, "
                    f"{_pct(facts['prior_positive_share'])}), the positive share is "
                    f"{facts['direction']} ({_signed(facts['delta_share'])} percentage points"
                    f"{_delta_conc(facts.get('delta_conc'))})."
                )

        if facts.get("state_note"):
            parts.append(facts["state_note"])
        return " ".join(parts)


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{share * 100:.1f}%"


def _signed(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}"


def _conc(value: float | None, units: Any) -> str:
    if value is None:
        return ""
    unit = _unit_label(units)
    return f", mean concentration {value:,.0f}{unit}"


def _delta_conc(value: float | None) -> str:
    return "" if value is None else f", mean concentration {value:+,.0f}"


def _unit_label(units: Any) -> str:
    if isinstance(units, list) and units:
        first = units[0]
        if isinstance(first, (list, tuple)):
            first = first[0]
        return f" {first}" + (" (mixed units)" if len(units) > 1 else "")
    if isinstance(units, str):
        return f" {units}"
    return ""
