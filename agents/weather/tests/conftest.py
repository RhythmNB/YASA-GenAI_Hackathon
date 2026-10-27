import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    """A small, fresh weather snapshot: one hot day, one rainy day, one heat alert."""
    db = tmp_path / "weather.db"
    conn = sqlite3.connect(db)
    conn.executescript((ROOT / "schema.sql").read_text())
    now = datetime.now(timezone.utc)
    fetched = now.isoformat(timespec="seconds")
    rows = [  # name, temp, precip, daytime
        ("Saturday", 94, 0, 1), ("Saturday Night", 70, 10, 0),
        ("Sunday", 75, 10, 1), ("Sunday Night", 60, 20, 0),
        ("Monday", 68, 70, 1), ("Monday Night", 55, 60, 0),
    ]
    for i, (name, temp, precip, day) in enumerate(rows):
        start = now + timedelta(hours=12 * i)
        end = start + timedelta(hours=12)
        conn.execute(
            "INSERT INTO forecast_periods VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("New York, NY", i + 1, name, start.isoformat(), end.isoformat(), day, temp, precip,
             "5 mph", "Sunny" if precip < 50 else "Rain", "detail", fetched, "https://api.weather.gov/x"),
        )
    conn.execute(
        "INSERT INTO weather_alerts VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("New York, NY", "a1", "Heat Advisory", "Moderate", "Expected", "Heat Advisory Saturday",
         fetched, (now + timedelta(days=1)).isoformat(), "Drink water", fetched),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("WEATHER_MODE", "sample")
    monkeypatch.setenv("SAMPLE_DB", str(db))
    monkeypatch.setenv("LLM_MODE", "sample")
    return db
