"""The visit request and the fixed mappings from its toggles to what each agent
understands. Only stated groups are passed on; nothing is inferred."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

GROUPS = ("older_adult", "young_child", "newborn", "pregnant")
GROUP_WORDS = {"older_adult": "older adults", "young_child": "young children",
               "newborn": "a newborn", "pregnant": "someone pregnant"}
WEATHER_GROUPS = {"older_adult": "older_adult", "young_child": "young_child",
                  "newborn": "infant", "pregnant": "pregnant"}


@dataclass
class TripRequest:
    to_city: str
    to_state: str                    # two-letter code, lowercase
    from_city: str
    from_state: str                  # two-letter code, lowercase
    start: date
    end: date
    to_county: str | None = None     # wastewater agent form, e.g. "Richmond City"
    adults: int = 2
    children: int = 0
    with_: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TripRequest":
        """Accepts the page's keys (toCity, toState, ...) or snake_case."""
        g = lambda camel, snake: d.get(camel) if d.get(camel) is not None else d.get(snake)  # noqa: E731
        groups = tuple(x for x in (d.get("with") or d.get("with_") or []) if x in GROUPS)
        try:
            start, end = date.fromisoformat(str(g("start", "start"))), date.fromisoformat(str(g("end", "end")))
        except (TypeError, ValueError) as e:
            raise ValueError("start and end must be ISO dates (YYYY-MM-DD)") from e
        to_state, from_state = str(g("toState", "to_state") or "").lower(), str(g("fromState", "from_state") or "").lower()
        if len(to_state) != 2 or len(from_state) != 2:
            raise ValueError("toState and fromState must be two-letter state codes")
        if not g("toCity", "to_city"):
            raise ValueError("toCity is required")
        county = g("toCounty", "to_county")
        return cls(
            to_city=str(g("toCity", "to_city")).strip(), to_state=to_state,
            from_city=str(g("fromCity", "from_city") or "").strip(), from_state=from_state,
            start=min(start, end), end=max(start, end),
            to_county=(str(county).strip() or None) if county else None,
            adults=max(1, int(g("adults", "adults") or 1)), children=max(0, int(g("children", "children") or 0)),
            with_=groups,
        )

    # -- mappings ---------------------------------------------------------

    @property
    def label(self) -> str:
        return f"{self.to_city}, {self.to_state.upper()}"

    @property
    def sensitive(self) -> bool:
        return bool(self.with_)

    def guidance_profile(self) -> tuple[str, bool]:
        """(profile, pregnant): newborn wins over older_adult; 'general' when neither."""
        pregnant = "pregnant" in self.with_
        if "newborn" in self.with_:
            return "newborn", pregnant
        if "older_adult" in self.with_:
            return "older_adult", pregnant
        return "general", pregnant

    def weather_groups(self) -> list[str]:
        return [WEATHER_GROUPS[g] for g in self.with_]

    def household(self) -> str:
        words = [GROUP_WORDS[g] for g in self.with_]
        return ", ".join(words) if words else "no stated higher-risk group"

    def to_dict(self) -> dict[str, Any]:
        return {"toCity": self.to_city, "toState": self.to_state, "toCounty": self.to_county,
                "fromCity": self.from_city, "fromState": self.from_state,
                "start": self.start.isoformat(), "end": self.end.isoformat(),
                "adults": self.adults, "children": self.children, "with": list(self.with_)}
