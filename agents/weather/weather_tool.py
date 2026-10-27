"""Weather tool for the visit-planner agents.

Queries forecast and alert tables through Zetaris (WEATHER_MODE=zetaris) or a
local SQLite snapshot (WEATHER_MODE=sample), and returns a structured briefing
the Weather agent can reason over. Every briefing includes the SQL it ran and
the data age, so the agent's output is traceable.

Usage:
  python weather_tool.py            # both cities
  python weather_tool.py LA 2       # LA, next 2 days
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).resolve().parent
from cities import CITIES, get_city  # noqa: E402

# Kept for backwards compatibility: id -> label
VALID_CITIES = {cid: cid for cid in CITIES}

# Simple screening thresholds for an older visitor. Official NWS alerts
# (e.g. Heat Advisory) always take priority over these heuristics.
HEAT_F = 90
COLD_F = 40
WET_PCT = 50
STALE_HOURS = 6

TOOL_SPEC = {
    "name": "get_weather_briefing",
    "description": (
        "Get the National Weather Service forecast and active alerts for a US city, "
        "with heat, cold and rain flags and good outdoor windows for an older visitor."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string",
                     "description": "City id as 'Name, ST', e.g. 'Portland, ME' or 'New York, NY'"},
            "days": {"type": "integer", "minimum": 1, "maximum": 7, "default": 3},
        },
        "required": ["city"],
    },
}


def _mode():
    return os.getenv("WEATHER_MODE", "sample").strip().lower()


def _tables():
    if _mode() == "zetaris":
        return (
            os.getenv("ZETARIS_FORECAST_TABLE", "forecast_periods"),
            os.getenv("ZETARIS_ALERTS_TABLE", "weather_alerts"),
        )
    return "forecast_periods", "weather_alerts"


def _connect():
    if _mode() == "zetaris":
        import jaydebeapi

        return jaydebeapi.connect(
            "com.zetaris.lightning.jdbc.LightningDriver",
            os.environ["ZETARIS_JDBC_URL"],
            [os.environ["ZETARIS_USER"], os.environ["ZETARIS_PASSWORD"]],
            str((HERE / os.environ["ZETARIS_JDBC_JAR"]).resolve()),
        )
    path = Path(os.getenv("SAMPLE_DB", HERE / "sample_data" / "weather_sample.db"))
    if not path.is_absolute():
        path = HERE / path
    if not path.exists():
        raise FileNotFoundError(
            f"Sample DB not found at {path}. Run: python ingest_weather.py --skip-postgres"
        )
    return sqlite3.connect(path)


def run_sql(sql):
    """Run a query and return rows as dicts with lower-case column names."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0].split(".")[-1].lower() for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def _hours_since(ts):
    if ts is None:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)


def _flags(period):
    flags = []
    temp = period.get("temperature_f")
    precip = period.get("precip_chance") or 0
    if temp is not None and bool(period.get("is_daytime")) and temp >= HEAT_F:
        flags.append("heat")
    if temp is not None and temp <= COLD_F:
        flags.append("cold")
    if precip >= WET_PCT:
        flags.append("rain")
    return flags


def get_weather_briefing(city, days=3):
    info = get_city(city)
    if not info:
        raise ValueError(f"Unsupported city '{city}'. Use an id like 'Boston, MA' (see cities.py)")
    city = info["id"]
    sql_city = city.replace("'", "''")
    days = max(1, min(int(days), 7))

    forecast_table, alerts_table = _tables()
    # City is whitelisted above, so inlining it is safe and works across JDBC drivers.
    forecast_sql = (
        "SELECT period_name, start_time, end_time, is_daytime, temperature_f, precip_chance, "
        "wind_speed, short_forecast, fetched_at "
        f"FROM {forecast_table} WHERE city = '{sql_city}' ORDER BY start_time"
    )
    alerts_sql = (
        "SELECT event, severity, urgency, headline, effective, expires, instruction "
        f"FROM {alerts_table} WHERE city = '{sql_city}'"
    )

    all_periods = run_sql(forecast_sql)
    # Drop periods that have already ended (snapshots age); keep all if none remain.
    upcoming = [p for p in all_periods if (_hours_since(p.get("end_time")) or -1) < 0]
    raw_periods = (upcoming or all_periods)[: days * 2]
    alerts = run_sql(alerts_sql)

    periods = []
    for p in raw_periods:
        flags = _flags(p)
        periods.append({
            "name": p["period_name"],
            "start": str(p["start_time"]),
            "end": str(p["end_time"]),
            "daytime": bool(p["is_daytime"]),
            "temperature_f": p["temperature_f"],
            "precip_chance_pct": p["precip_chance"],
            "wind": p["wind_speed"],
            "summary": p["short_forecast"],
            "flags": flags,
        })

    fetched_at = raw_periods[0]["fetched_at"] if raw_periods else None
    age = _hours_since(fetched_at)

    return {
        "city": city,
        "label": city,
        "state": info["state"],
        "mode": _mode(),
        "data_fetched_at": str(fetched_at) if fetched_at else None,
        "data_age_hours": age,
        "stale": age is None or age > STALE_HOURS,
        "active_alerts": [
            {k: (str(v) if v is not None else None) for k, v in a.items()} for a in alerts
        ],
        "periods": periods,
        "good_outdoor_windows": [
            p["name"] for p in periods if p["daytime"] and not p["flags"]
        ],
        "thresholds": {"heat_f": HEAT_F, "cold_f": COLD_F, "rain_pct": WET_PCT},
        "trace": {
            "source": "National Weather Service (api.weather.gov)",
            "queries": [forecast_sql, alerts_sql],
        },
    }


if __name__ == "__main__":
    cities = [sys.argv[1]] if len(sys.argv) > 1 else ["New York, NY", "Los Angeles, CA"]
    n_days = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for c in cities:
        print(json.dumps(get_weather_briefing(c, n_days), indent=2, default=str))
