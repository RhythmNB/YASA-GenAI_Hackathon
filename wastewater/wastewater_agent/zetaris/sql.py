"""Fixed, read-only SQL templates. Inputs are validated; the model never
writes SQL. Every function returns one statement."""

from __future__ import annotations

import re
from datetime import date

TABLE = "wastewater.sars_cov_2"
TARGET = "sars-cov-2"
_STATE = re.compile(r"^[a-z]{2}$")


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


def latest_sample_date(state: str | None = None) -> str:
    return (
        f"SELECT MAX(sample_collect_date) AS latest_sample_date FROM {TABLE} "
        f"WHERE pcr_target = '{TARGET}'{_state_clause(state)}"
    )


def window_summary(start: date | str, end: date | str, state: str | None = None) -> str:
    return (
        "SELECT COUNT(*) AS samples, "
        "SUM(CASE WHEN pcr_target_detect = 'yes' THEN 1 ELSE 0 END) AS positives, "
        "COUNT(DISTINCT site) AS sites, "
        "AVG(CAST(REPLACE(pcr_target_avg_conc, ',', '') AS DOUBLE)) AS mean_conc "
        f"FROM {TABLE} WHERE pcr_target = '{TARGET}' "
        f"AND sample_collect_date >= '{_d(start)}' AND sample_collect_date <= '{_d(end)}'"
        f"{_state_clause(state)}"
    )


def window_units(start: date | str, end: date | str, state: str | None = None) -> str:
    return (
        "SELECT pcr_target_units AS units, COUNT(*) AS samples "
        f"FROM {TABLE} WHERE pcr_target = '{TARGET}' "
        f"AND sample_collect_date >= '{_d(start)}' AND sample_collect_date <= '{_d(end)}'"
        f"{_state_clause(state)} GROUP BY pcr_target_units ORDER BY samples DESC"
    )


def ping() -> str:
    return "SELECT 1 AS ok"
