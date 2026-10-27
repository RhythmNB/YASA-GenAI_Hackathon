"""Fetch National Weather Service forecasts and active alerts for every city in cities.py.

Loads the results into:
  1. Postgres, which is registered in Zetaris as a data source
  2. A local SQLite file, used by sample mode so judges can run without credentials

Tables: forecast_periods (14 half-day periods per city, 7 days), weather_alerts
(active NWS alerts matched to each city's county/zone) and cities (one row per
city with state, county FIPS and NWS zone codes, for joins with other datasets).

Speed: the NWS "points" lookup for each city is cached in sample_data/nws_points_cache.json,
forecasts are fetched in parallel, and alerts come from ONE nationwide request.

Usage:
  python ingest_weather.py                       # all cities, Postgres + sample DB
  python ingest_weather.py --skip-postgres       # only the sample DB
  python ingest_weather.py --cities "Boston, MA" "Portland, ME"
"""
import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from cities import CITIES

load_dotenv()

BASE = "https://api.weather.gov"
HEADERS = {
    "User-Agent": os.getenv(
        "NWS_USER_AGENT", "visit-planner-hackathon/0.1 (contact@example.com)"
    ),
    "Accept": "application/geo+json",
}
RETRYABLE = {429, 500, 502, 503, 504}
WORKERS = int(os.getenv("NWS_WORKERS", "6"))
HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.sql"
SAMPLE_DB = Path(os.getenv("SAMPLE_DB", HERE / "sample_data" / "weather_sample.db"))
POINTS_CACHE = HERE / "sample_data" / "nws_points_cache.json"
_cache_lock = threading.Lock()

FORECAST_COLS = [
    "city", "period_number", "period_name", "start_time", "end_time",
    "is_daytime", "temperature_f", "precip_chance", "wind_speed",
    "short_forecast", "detailed_forecast", "fetched_at", "source_url",
]
ALERT_COLS = [
    "city", "alert_id", "event", "severity", "urgency", "headline",
    "effective", "expires", "instruction", "fetched_at",
]
CITY_COLS = [
    "city", "name", "state", "state_name", "latitude", "longitude",
    "county_fips", "county_name", "county_zone", "forecast_zone", "nws_office", "fetched_at",
]

_session = threading.local()
# Retry policy: patient for manual refreshes, quick for live refreshes inside the agent.
_policy = {"retries": 5, "timeout": 30}


def _http():
    if not hasattr(_session, "s"):
        _session.s = requests.Session()
        _session.s.headers.update(HEADERS)
    return _session.s


def nws_get(url, params=None, retries=None):
    """GET a NWS endpoint with retries on rate limits and server errors."""
    retries = retries or _policy["retries"]
    last_error = None
    for attempt in range(retries):
        try:
            resp = _http().get(url, params=params, timeout=_policy["timeout"])
        except requests.RequestException as exc:
            last_error = str(exc)
        else:
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in RETRYABLE:
                resp.raise_for_status()
            last_error = f"HTTP {resp.status_code} from {url}"
        if attempt < retries - 1:
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"NWS request failed after {retries} attempts: {last_error}")


def load_cache():
    if POINTS_CACHE.exists():
        return json.loads(POINTS_CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    POINTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    POINTS_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")


def point_info(city, cache):
    """Forecast URL, county and zone codes for a city (cached after the first run)."""
    with _cache_lock:
        if city["id"] in cache:
            return cache[city["id"]]
    p = nws_get(f"{BASE}/points/{city['lat']},{city['lon']}")["properties"]
    county_zone = (p.get("county") or "").rsplit("/", 1)[-1]          # e.g. CAC037
    forecast_zone = (p.get("forecastZone") or "").rsplit("/", 1)[-1]  # e.g. CAZ368
    county_name = None
    if county_zone:
        try:
            county_name = nws_get(f"{BASE}/zones/county/{county_zone}")["properties"].get("name")
        except Exception:
            county_name = None
    info = {
        "forecast_url": p["forecast"],
        "county_zone": county_zone,
        "forecast_zone": forecast_zone,
        "county_name": county_name,
        "nws_office": p.get("gridId"),
        # County zone CAC037 -> FIPS 06037 (state FIPS + 3-digit county code)
        "county_fips": (city["state_fips"] + county_zone[3:]) if len(county_zone) == 6 else None,
    }
    with _cache_lock:
        cache[city["id"]] = info
    return info


def fetch_city(city, cache, fetched_at):
    """Return (forecast_rows, city_row) for one city."""
    info = point_info(city, cache)
    forecast = nws_get(info["forecast_url"])
    periods = []
    for p in forecast["properties"]["periods"]:
        temp = p.get("temperature")
        if temp is not None and p.get("temperatureUnit") == "C":
            temp = round(temp * 9 / 5 + 32)
        precip = (p.get("probabilityOfPrecipitation") or {}).get("value")
        periods.append({
            "city": city["id"],
            "period_number": p["number"],
            "period_name": p["name"],
            "start_time": p["startTime"],
            "end_time": p["endTime"],
            "is_daytime": bool(p["isDaytime"]),
            "temperature_f": temp,
            "precip_chance": precip if precip is not None else 0,
            "wind_speed": p.get("windSpeed"),
            "short_forecast": p.get("shortForecast"),
            "detailed_forecast": p.get("detailedForecast"),
            "fetched_at": fetched_at,
            "source_url": info["forecast_url"],
        })
    city_row = {
        "city": city["id"], "name": city["name"], "state": city["state"],
        "state_name": city["state_name"], "latitude": city["lat"], "longitude": city["lon"],
        "county_fips": info["county_fips"], "county_name": info["county_name"],
        "county_zone": info["county_zone"], "forecast_zone": info["forecast_zone"],
        "nws_office": info["nws_office"], "fetched_at": fetched_at,
    }
    return periods, city_row


def fetch_alerts(city_rows, fetched_at):
    """Alerts matched to cities by county/forecast zone. One nationwide request for big
    refreshes; for a handful of cities, one small request per city instead."""
    if len(city_rows) <= 5:
        features = []
        for c in city_rows:
            features += nws_get(f"{BASE}/alerts/active", params={
                "status": "actual", "point": f"{c['latitude']},{c['longitude']}"}).get("features", [])
        data = {"features": features}
    else:
        data = nws_get(f"{BASE}/alerts/active", params={"status": "actual"})
    by_zone = {}
    for c in city_rows:
        for z in (c["county_zone"], c["forecast_zone"]):
            if z:
                by_zone.setdefault(z, set()).add(c["city"])
    alerts = []
    for feature in data.get("features", []):
        a = feature["properties"]
        zones = set((a.get("geocode") or {}).get("UGC") or [])
        zones |= {u.rsplit("/", 1)[-1] for u in a.get("affectedZones") or []}
        hit = set().union(*(by_zone.get(z, set()) for z in zones)) if zones else set()
        for city_id in sorted(hit):
            if any(x["city"] == city_id and x["alert_id"] == (a.get("id") or feature.get("id")) for x in alerts):
                continue
            alerts.append({
                "city": city_id,
                "alert_id": a.get("id") or feature.get("id"),
                "event": a.get("event"),
                "severity": a.get("severity"),
                "urgency": a.get("urgency"),
                "headline": a.get("headline"),
                "effective": a.get("effective"),
                "expires": a.get("expires"),
                "instruction": a.get("instruction"),
                "fetched_at": fetched_at,
            })
    return alerts


def insert_sql(table, cols, placeholder):
    values = ", ".join([placeholder] * len(cols))
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({values})"


def as_tuples(rows, cols):
    return [tuple(r[c] for c in cols) for r in rows]


def _write(cur, ph, periods, alerts, city_rows, ok_ids, all_ids, alerts_ok):
    """Replace rows for refreshed cities and drop cities no longer in the list."""
    in_ok = ", ".join([ph] * len(ok_ids))
    in_all = ", ".join([ph] * len(all_ids))
    for table in ("forecast_periods", "cities"):
        cur.execute(f"DELETE FROM {table} WHERE city IN ({in_ok})", ok_ids)
        cur.execute(f"DELETE FROM {table} WHERE city NOT IN ({in_all})", all_ids)
    if alerts_ok:  # fresh alerts for the refreshed cities replace their old ones
        cur.execute(f"DELETE FROM weather_alerts WHERE city IN ({in_ok})", ok_ids)
    cur.execute(f"DELETE FROM weather_alerts WHERE city NOT IN ({in_all})", all_ids)
    cur.executemany(insert_sql("forecast_periods", FORECAST_COLS, ph), as_tuples(periods, FORECAST_COLS))
    cur.executemany(insert_sql("cities", CITY_COLS, ph), as_tuples(city_rows, CITY_COLS))
    if alerts:
        cur.executemany(insert_sql("weather_alerts", ALERT_COLS, ph), as_tuples(alerts, ALERT_COLS))


def write_postgres(*args, verbose=True):
    import psycopg

    with psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5433")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text())
            _write(cur, "%s", *args)
    if verbose:
        print(f"Postgres: wrote {len(args[0])} forecast periods, {len(args[1])} alerts, {len(args[2])} cities")


def write_sqlite(*args, verbose=True):
    SAMPLE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SAMPLE_DB)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        _write(conn.cursor(), "?", *args)
        conn.commit()
    finally:
        conn.close()
    if verbose:
        print(f"Sample DB: wrote {len(args[0])} forecast periods, {len(args[1])} alerts, "
              f"{len(args[2])} cities -> {SAMPLE_DB}")


def refresh(city_ids=None, skip_postgres=False, quick=False, verbose=True):
    """Download forecasts and alerts for the given city ids (default: all) and store them.

    quick=True is for live refreshes from the agent: fewer retries and shorter timeouts,
    and a Postgres problem is reported instead of raised (the sample DB is still updated).
    Returns a summary dict.
    """
    say = print if verbose else (lambda *a, **k: None)
    targets = [CITIES[c] for c in (city_ids or CITIES)]
    old_policy = dict(_policy)
    if quick:
        _policy.update(retries=2, timeout=10)
    try:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache = load_cache()
        started = time.time()
        all_periods, city_rows, failed = [], [], []

        with ThreadPoolExecutor(max_workers=min(WORKERS, len(targets))) as pool:
            futures = {pool.submit(fetch_city, c, cache, fetched_at): c for c in targets}
            for i, fut in enumerate(as_completed(futures), start=1):
                c = futures[fut]
                try:
                    periods, row = fut.result()
                except Exception as exc:  # one city's outage doesn't block the rest
                    failed.append(c["id"])
                    say(f"[WARN] {c['id']}: {exc}", file=sys.stderr)
                    continue
                all_periods += periods
                city_rows.append(row)
                if len(targets) > 5 and (i % 25 == 0 or i == len(targets)):
                    say(f"  {i}/{len(targets)} cities fetched ({time.time() - started:.0f}s)")
        save_cache(cache)

        if not city_rows:
            raise RuntimeError("No city could be fetched from NWS; existing data left untouched.")

        try:
            alerts, alerts_ok = fetch_alerts(city_rows, fetched_at), True
            say(f"Alerts: {len(alerts)} city matches from active NWS alerts")
        except Exception as exc:
            alerts, alerts_ok = [], False
            say(f"[WARN] alerts: {exc}; keeping previous alerts", file=sys.stderr)

        ok_ids = [r["city"] for r in city_rows]
        payload = (all_periods, alerts, city_rows, ok_ids, list(CITIES), alerts_ok)
        write_sqlite(*payload, verbose=verbose)
        postgres_ok, postgres_error = None, None
        if not skip_postgres:
            try:
                write_postgres(*payload, verbose=verbose)
                postgres_ok = True
            except Exception as exc:  # e.g. a laptop without Docker: the offline copy is still updated
                postgres_ok, postgres_error = False, str(exc) or exc.__class__.__name__
                say(f"[WARN] Postgres not updated ({postgres_error}). Offline copy is up to date; "
                    "use --skip-postgres if you don't run Docker on this machine.", file=sys.stderr)
        seconds = round(time.time() - started, 1)
        say(f"Done: {len(ok_ids)} cities OK, {len(failed)} failed in {seconds:.0f}s"
            + (f" (failed: {', '.join(failed)})" if failed else ""))
        return {"ok": ok_ids, "failed": failed, "alerts": len(alerts), "seconds": seconds,
                "fetched_at": fetched_at, "postgres_ok": postgres_ok, "postgres_error": postgres_error}
    finally:
        _policy.clear()
        _policy.update(old_policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-postgres", action="store_true", help="Only refresh the local sample DB")
    parser.add_argument("--cities", nargs="+", help='Only these city ids, e.g. "Boston, MA"')
    args = parser.parse_args()
    try:
        refresh(args.cities, skip_postgres=args.skip_postgres)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
