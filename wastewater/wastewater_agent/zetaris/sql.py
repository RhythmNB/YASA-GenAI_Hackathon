"""Fixed, read-only SQL templates. Inputs are validated; the model never
writes SQL. Every function returns one statement."""

from __future__ import annotations

import re
from datetime import date

from ..pathogens import Pathogen, default as default_pathogen

# Kept for callers that still import them; the templates read table and target
# from the pathogen registry entry they are given.
TABLE = default_pathogen().table
TARGET = default_pathogen().target
_STATE = re.compile(r"^[a-z]{2}$")


def _src(p: Pathogen | None) -> tuple[str, str]:
    p = p or default_pathogen()
    return p.table, p.target


def _d(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


def _state_clause(state: str | None) -> str:
    if state is None:
        return ""
    if not _STATE.match(state):
        raise ValueError(f"invalid state code: {state!r}")
    return f" AND state_territory = '{state}'"


_COUNTY = re.compile(r"^[a-z][a-z .'\-]{0,60}$", re.I)


def _county_clause(county: str | None) -> str:
    """`counties_served` is a ', '-separated list of county names (independent
    cities as 'Richmond City'); match one whole name, case-insensitively."""
    if county is None:
        return ""
    if not _COUNTY.match(county):
        raise ValueError(f"invalid county name: {county!r}")
    needle = county.lower().replace("'", "''")
    return f" AND LOWER(CONCAT(', ', counties_served, ', ')) LIKE '%, {needle}, %'"


def latest_sample_date(state: str | None = None, county: str | None = None, pathogen: Pathogen | None = None) -> str:
    table, target = _src(pathogen)
    return (
        f"SELECT MAX(sample_collect_date) AS latest_sample_date FROM {table} "
        f"WHERE pcr_target = '{target}'{_state_clause(state)}{_county_clause(county)}"
    )


def county_sites(state: str, county: str, pathogen: Pathogen | None = None) -> str:
    """How many sampling sites have ever served this county (0 = no coverage)."""
    table, target = _src(pathogen)
    return (
        f"SELECT COUNT(DISTINCT site) AS sites FROM {table} "
        f"WHERE pcr_target = '{target}'{_state_clause(state)}{_county_clause(county)}"
    )


def window_summary(start: date | str, end: date | str, state: str | None = None, county: str | None = None,
                   pathogen: Pathogen | None = None) -> str:
    table, target = _src(pathogen)
    return (
        "SELECT COUNT(*) AS samples, "
        "SUM(CASE WHEN pcr_target_detect = 'yes' THEN 1 ELSE 0 END) AS positives, "
        "COUNT(DISTINCT site) AS sites, "
        "AVG(CAST(REPLACE(pcr_target_avg_conc, ',', '') AS DOUBLE)) AS mean_conc "
        f"FROM {table} WHERE pcr_target = '{target}' "
        f"AND sample_collect_date >= '{_d(start)}' AND sample_collect_date <= '{_d(end)}'"
        f"{_state_clause(state)}{_county_clause(county)}"
    )


def window_units(start: date | str, end: date | str, state: str | None = None, county: str | None = None,
                 pathogen: Pathogen | None = None) -> str:
    table, target = _src(pathogen)
    return (
        "SELECT pcr_target_units AS units, COUNT(*) AS samples "
        f"FROM {table} WHERE pcr_target = '{target}' "
        f"AND sample_collect_date >= '{_d(start)}' AND sample_collect_date <= '{_d(end)}'"
        f"{_state_clause(state)}{_county_clause(county)} GROUP BY pcr_target_units ORDER BY samples DESC"
    )


def ping() -> str:
    return "SELECT 1 AS ok"
