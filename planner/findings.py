"""The shapes the planner and composer exchange: one Finding per agent, one
Verdict, one TravelPlan. Rules live in the adapters and the composer; this
module only holds data and its JSON form."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

ORDER = ["covid", "flu", "pertussis", "weather", "guidance"]
TITLES = {
    "covid": "COVID-19 in wastewater",
    "flu": "Flu (influenza A) in wastewater",
    "pertussis": "Whooping cough",
    "weather": "Weather",
    "guidance": "CDC guidance",
}
LEVEL_RANK = {"unknown": 0, "low": 1, "moderate": 2, "high": 3}
# Traffic-light wording for the overall verdict, with a short tagline each.
LEVEL_LABEL = {
    "high": "Stop",
    "moderate": "Caution",
    "low": "Go",
    "unknown": "No signal",
}
LEVEL_TAGLINE = {
    "high": "Reconsider, or go with full precautions",
    "moderate": "Go with care",
    "low": "Good to go",
    "unknown": "Not enough data to judge",
}


@dataclass
class Finding:
    source: str
    title: str
    status: str = "ok"          # ok | error | skipped
    level: str = "unknown"      # low | moderate | high | unknown
    headline: str = ""
    meaning: str = ""           # one plain sentence: what the finding means for the visit
    text: str = ""
    facts: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    model: str | None = None
    trace: str | None = None
    seconds: float = 0.0
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def failed(source: str, error: str, seconds: float = 0.0, status: str = "error") -> Finding:
    return Finding(source=source, title=TITLES[source], status=status, level="unknown",
                   headline="Not available", error=error, caveats=[error], seconds=seconds)


@dataclass
class Verdict:
    level: str
    label: str
    reason: str
    tagline: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class TravelPlan:
    trip: dict[str, Any]
    verdict: Verdict
    intro: str
    sections: list[Finding]
    precautions: list[str]
    best_days: list[str]
    sources: list[dict[str, str]]
    models: dict[str, str | None]
    traces: dict[str, str | None]
    notes: list[str] = field(default_factory=list)
    partial: bool = False
    elapsed_seconds: float = 0.0
    evaluation: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: "plan_" + uuid.uuid4().hex[:10])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "createdAt": self.created_at,
            "elapsedSeconds": round(self.elapsed_seconds, 1),
            "partial": self.partial,
            "trip": self.trip,
            "verdict": self.verdict.to_dict(),
            "intro": self.intro,
            "sections": [s.to_dict() for s in self.sections],
            "precautions": self.precautions,
            "bestDays": self.best_days,
            "sources": self.sources,
            "models": self.models,
            "traces": self.traces,
            "notes": self.notes,
            "evaluation": self.evaluation,
        }
