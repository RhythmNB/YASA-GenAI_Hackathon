"""Plan -> QueryResults. Runs the fixed templates, one statement per call."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..zetaris import JdbcClient, sql
from .planner import Plan
from .windows import Window


@dataclass
class Summary:
    window: Window
    samples: int
    positives: int
    sites: int
    mean_conc: float | None
    units: list[tuple[str, int]]

    @property
    def positive_share(self) -> float | None:
        return (self.positives / self.samples) if self.samples else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window.to_dict(),
            "samples": self.samples,
            "positives": self.positives,
            "positive_share": self.positive_share,
            "sites": self.sites,
            "mean_conc": self.mean_conc,
            "units": [list(u) for u in self.units],
        }


@dataclass
class QueryResults:
    latest_overall: date | None
    latest_state: date | None
    current: Summary
    prior: Summary | None = None
    fallback: Summary | None = None
    statements: list[str] = field(default_factory=list)


class Executor:
    def __init__(self, client: JdbcClient) -> None:
        self.client = client
        self.statements: list[str] = []

    def _run(self, statement: str) -> list[dict[str, Any]]:
        self.statements.append(statement)
        return self.client.query(statement)

    def latest(self, state: str | None) -> date | None:
        rows = self._run(sql.latest_sample_date(state))
        value = rows[0].get("latest_sample_date") if rows else None
        return date.fromisoformat(str(value)) if value else None

    def summary(self, window: Window, state: str | None) -> Summary:
        rows = self._run(sql.window_summary(window.start, window.end, state))
        row = rows[0] if rows else {}
        units_rows = self._run(sql.window_units(window.start, window.end, state))
        units = [(str(r.get("units")), int(r.get("samples") or 0)) for r in units_rows if r.get("units")]
        mean = row.get("mean_conc")
        return Summary(
            window=window,
            samples=int(row.get("samples") or 0),
            positives=int(row.get("positives") or 0),
            sites=int(row.get("sites") or 0),
            mean_conc=float(mean) if mean is not None else None,
            units=units,
        )

    def run(self, plan: Plan) -> QueryResults:
        self.statements = []
        latest_overall = self.latest(None)
        latest_state = self.latest(plan.state) if plan.state else None
        current = self.summary(plan.window, plan.state)
        prior = self.summary(plan.window.prior(), plan.state) if plan.intent == "trend" else None
        return QueryResults(
            latest_overall=latest_overall,
            latest_state=latest_state,
            current=current,
            prior=prior,
            statements=self.statements,
        )
