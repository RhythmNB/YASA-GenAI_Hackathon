"""The pathogens the agent can answer about, and where each one's data lives.

This registry is the only place that knows a pathogen's table, `pcr_target`
value and display name. Adding a dataset means adding one entry here; the
SQL templates, plan, fact sheet and memory tags read everything from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pathogen:
    key: str          # stable id used in plans, memory tags, API fields
    table: str        # Zetaris table, schema-qualified
    target: str       # exact `pcr_target` value in that table
    name: str         # display name in prose
    words: tuple[str, ...] = field(default_factory=tuple)  # question words that select it

    def mentioned_in(self, text: str) -> bool:
        low = text.lower()
        return any(re.search(rf"\b{re.escape(w)}\b", low) for w in self.words)


PATHOGENS: dict[str, Pathogen] = {
    "sars-cov-2": Pathogen(
        key="sars-cov-2",
        table="wastewater.sars_cov_2",
        target="sars-cov-2",
        name="SARS-CoV-2",
        words=("sars-cov-2", "sars cov 2", "covid", "covid-19", "coronavirus", "sars"),
    ),
    "flu-a": Pathogen(
        key="flu-a",
        table="wastewater.influenza_a",
        target="fluav",  # the only pcr_target value in the loaded table (338,192 rows, 2021-09-15 to 2026-10-20)
        name="influenza A",
        words=("flu", "influenza", "influenza a", "flu a"),
    ),
}
DEFAULT_KEY = "sars-cov-2"


def default() -> Pathogen:
    return PATHOGENS[DEFAULT_KEY]


def get(key: str | None) -> Pathogen:
    """A registry entry by key; None or unknown -> the default. Keys are case-insensitive."""
    if not key:
        return default()
    k = key.strip().lower()
    if k not in PATHOGENS:
        raise KeyError(f"unknown pathogen {key!r}; known: {', '.join(PATHOGENS)}")
    return PATHOGENS[k]


def from_question(text: str) -> Pathogen:
    """The pathogen a question names, by its words; the default when none is named.
    Registry order decides ties, so a question naming both picks the first."""
    for p in PATHOGENS.values():
        if p.mentioned_in(text):
            return p
    return default()
