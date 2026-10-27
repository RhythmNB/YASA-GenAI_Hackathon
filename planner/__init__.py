"""Trip planner: a planner agent fans a visit request out to the wastewater,
pertussis, guidance and weather agents; a composer agent turns the findings
into one travel plan. See docs/2026-10-27-trip-planner-design.md."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = REPO / "agents"


def add_agent_paths() -> None:
    """Make the in-process agents importable: wastewater_agent (a package) and the
    pertussis/guidance modules (plain scripts in the handoff folder)."""
    for p in (AGENTS / "wastewater", AGENTS / "pertussis_guidance" / "agents"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


add_agent_paths()
