"""Offline test of the ingest logic with a fake NWS API."""
import sqlite3

import ingest_weather as ing


def fake_nws(url, params=None, retries=5):
    if "/points/" in url:
        return {"properties": {"forecast": "https://api.weather.gov/gridpoints/X/1,1/forecast",
                               "county": "https://api.weather.gov/zones/county/NYC061",
                               "forecastZone": "https://api.weather.gov/zones/forecast/NYZ072",
                               "gridId": "OKX"}}
    if "/zones/county/" in url:
        return {"properties": {"name": "New York"}}
    if url.endswith("/forecast"):
        return {"properties": {"periods": [
            {"number": 1, "name": "Today", "startTime": "2026-10-26T06:00:00-04:00",
             "endTime": "2026-10-26T18:00:00-04:00", "isDaytime": True, "temperature": 20,
             "temperatureUnit": "C", "probabilityOfPrecipitation": {"value": None},
             "windSpeed": "5 mph", "shortForecast": "Sunny", "detailedForecast": "Sunny."}]}}
    if url.endswith("/alerts/active"):
        return {"features": [{"properties": {
            "id": "a1", "event": "Heat Advisory", "severity": "Moderate", "urgency": "Expected",
            "headline": "Heat", "geocode": {"UGC": ["NYZ072"]}, "affectedZones": []}}]}
    raise AssertionError(url)


def test_ingest_writes_cities_forecasts_and_matched_alerts(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    monkeypatch.setattr(ing, "nws_get", fake_nws)
    monkeypatch.setattr(ing, "SAMPLE_DB", db)
    monkeypatch.setattr(ing, "POINTS_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr("sys.argv", ["x", "--skip-postgres", "--cities", "New York, NY"])
    ing.main()
    con = sqlite3.connect(db)
    assert con.execute("SELECT temperature_f, precip_chance FROM forecast_periods").fetchall() == [(68, 0)]
    assert con.execute("SELECT county_fips, county_name FROM cities").fetchall() == [("36061", "New York")]
    assert con.execute("SELECT city, event FROM weather_alerts").fetchall() == [("New York, NY", "Heat Advisory")]
    assert (tmp_path / "cache.json").exists()


def test_single_city_refresh_keeps_other_cities_alerts(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    monkeypatch.setattr(ing, "nws_get", fake_nws)
    monkeypatch.setattr(ing, "SAMPLE_DB", db)
    monkeypatch.setattr(ing, "POINTS_CACHE", tmp_path / "cache.json")
    con = sqlite3.connect(db)
    con.executescript(ing.SCHEMA_PATH.read_text())
    con.execute("INSERT INTO weather_alerts (city, alert_id, event, fetched_at) VALUES ('Boston, MA','b1','Frost','x')")
    con.commit()
    monkeypatch.setattr("sys.argv", ["x", "--skip-postgres", "--cities", "New York, NY"])
    ing.main()
    rows = sorted(sqlite3.connect(db).execute("SELECT city FROM weather_alerts").fetchall())
    assert rows == [("Boston, MA",), ("New York, NY",)]
