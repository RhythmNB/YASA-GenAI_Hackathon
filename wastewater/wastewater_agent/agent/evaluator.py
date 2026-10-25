"""QueryResults -> FactSheet: coverage, shares, deltas, direction, fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from .executor import QueryResults, Summary
from .planner import Plan
from .windows import Window

FLAT_BAND_PP = 5.0


@dataclass
class FactSheet:
    intent: str
    state: str | None
    window: Window
    samples: int
    positives: int
    positive_share: float | None
    sites: int
    mean_conc: float | None
    units: list[tuple[str, int]]
    latest_sample_date: date | None
    coverage: str  # full | partial | empty
    prior_window: Window | None = None
    prior_samples: int | None = None
    prior_positives: int | None = None
    prior_positive_share: float | None = None
    prior_sites: int | None = None
    prior_mean_conc: float | None = None
    delta_share: float | None = None  # percentage points
    delta_conc: float | None = None
    direction: str | None = None  # rising | falling | flat | unknown
    fallback_window: Window | None = None
    fallback_samples: int | None = None
    fallback_positives: int | None = None
    fallback_positive_share: float | None = None
    fallback_sites: int | None = None
    fallback_mean_conc: float | None = None
    fallback_units: list[tuple[str, int]] | None = None
    notes: list[str] = field(default_factory=list)
    state_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        def w(x: Window | None) -> dict[str, str] | None:
            return x.to_dict() if x else None

        return {
            "intent": self.intent,
            "state": self.state,
            "window": w(self.window),
            "samples": self.samples,
            "positives": self.positives,
            "positive_share": _r(self.positive_share),
            "sites": self.sites,
            "mean_conc": _r(self.mean_conc, 1),
            "units": [list(u) for u in self.units],
            "latest_sample_date": self.latest_sample_date.isoformat() if self.latest_sample_date else None,
            "coverage": self.coverage,
            "prior_window": w(self.prior_window),
            "prior_samples": self.prior_samples,
            "prior_positives": self.prior_positives,
            "prior_positive_share": _r(self.prior_positive_share),
            "prior_sites": self.prior_sites,
            "prior_mean_conc": _r(self.prior_mean_conc, 1),
            "delta_share": _r(self.delta_share, 1),
            "delta_conc": _r(self.delta_conc, 1),
            "direction": self.direction,
            "fallback_window": w(self.fallback_window),
            "fallback_samples": self.fallback_samples,
            "fallback_positives": self.fallback_positives,
            "fallback_positive_share": _r(self.fallback_positive_share),
            "fallback_sites": self.fallback_sites,
            "fallback_mean_conc": _r(self.fallback_mean_conc, 1),
            "fallback_units": [list(u) for u in self.fallback_units] if self.fallback_units else None,
            "notes": list(self.notes),
            "state_note": self.state_note,
        }


def _r(value: float | None, nd: int = 4) -> float | None:
    return None if value is None else round(value, nd)


def evaluate(
    plan: Plan,
    results: QueryResults,
    fetch_fallback: Callable[[Window, str | None], Summary] | None = None,
) -> FactSheet:
    cur = results.current
    latest = results.latest_state if plan.state else results.latest_overall
    if cur.samples == 0:
        coverage = "empty"
    elif latest is not None and latest >= plan.window.end:
        coverage = "full"
    else:
        coverage = "partial"

    facts = FactSheet(
        intent=plan.intent,
        state=plan.state,
        window=plan.window,
        samples=cur.samples,
        positives=cur.positives,
        positive_share=cur.positive_share,
        sites=cur.sites,
        mean_conc=cur.mean_conc,
        units=cur.units,
        latest_sample_date=latest,
        coverage=coverage,
        notes=list(plan.notes),
    )
    for n in plan.notes:
        if n.startswith("state ") and "not recognised" in n:
            facts.state_note = "The state in the question was not recognised, so this answer is national."
    if coverage != "full" and latest is not None:
        facts.notes.append(f"data lag: latest sample {latest.isoformat()} is before window end {plan.window.end.isoformat()}"
                           if latest < plan.window.end else "no samples in the requested window")
    if len(cur.units) > 1:
        facts.notes.append("mean concentration averages mixed units; treat as indicative only")

    if plan.intent == "trend" and results.prior is not None:
        pr = results.prior
        facts.prior_window = pr.window
        facts.prior_samples = pr.samples
        facts.prior_positives = pr.positives
        facts.prior_positive_share = pr.positive_share
        facts.prior_sites = pr.sites
        facts.prior_mean_conc = pr.mean_conc
        if cur.positive_share is not None and pr.positive_share is not None:
            facts.delta_share = (cur.positive_share - pr.positive_share) * 100.0
            if facts.delta_share > FLAT_BAND_PP:
                facts.direction = "rising"
            elif facts.delta_share < -FLAT_BAND_PP:
                facts.direction = "falling"
            else:
                facts.direction = "flat"
        else:
            facts.direction = "unknown"
        if cur.mean_conc is not None and pr.mean_conc is not None:
            facts.delta_conc = cur.mean_conc - pr.mean_conc

    if coverage == "empty" and latest is not None and fetch_fallback is not None:
        fb_window = Window(latest - timedelta(days=6), latest, "most recent 7 days with data")
        fb = fetch_fallback(fb_window, plan.state)
        facts.fallback_window = fb.window
        facts.fallback_samples = fb.samples
        facts.fallback_positives = fb.positives
        facts.fallback_positive_share = fb.positive_share
        facts.fallback_sites = fb.sites
        facts.fallback_mean_conc = fb.mean_conc
        facts.fallback_units = fb.units
    return facts
