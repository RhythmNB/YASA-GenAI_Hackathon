"""Weather risk from the weather service over HTTP (POST /api/weather)."""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

import httpx

from ..findings import TITLES, Finding, failed
from ..trip import TripRequest

DEFAULT_URL = "http://127.0.0.1:8770"
FORECAST_DAYS = 7
NWS = {"title": "National Weather Service forecast and alerts (api.weather.gov)", "url": "https://api.weather.gov"}


def service_url() -> str:
    return os.environ.get("WEATHER_SERVICE_URL", DEFAULT_URL).rstrip("/")


def run(trip: TripRequest, base_url: str | None = None, timeout: float = 180.0, today: date | None = None) -> Finding:
    base = (base_url or service_url()).rstrip("/")
    today = today or date.today()
    body = {"city": trip.label, "days": FORECAST_DAYS, "travellers": trip.weather_groups()}
    t0 = time.perf_counter()
    try:
        r = httpx.post(f"{base}/api/weather", json=body, timeout=timeout)
    except httpx.HTTPError as e:
        return failed("weather", f"weather service unreachable at {base}: {e.__class__.__name__}", time.perf_counter() - t0)
    if r.status_code == 400:
        err = r.json().get("error", "bad request") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        return failed("weather", f"the weather agent does not cover {trip.label}: {err}", time.perf_counter() - t0, status="skipped")
    if r.status_code != 200:
        return failed("weather", f"weather service returned HTTP {r.status_code}", time.perf_counter() - t0)
    data = r.json()
    h = data.get("handoff") or {}
    if h.get("status") == "error" or not data.get("ok", True):
        return failed("weather", str(h.get("error") or data.get("error") or "weather lookup failed"), time.perf_counter() - t0)

    level = h.get("risk_level") or "unknown"
    ev = h.get("risk_evaluation") or {}
    headline = f"Weather risk {level} ({h.get('recommendation', '')}) for the next {len(h.get('periods_covered') or [])} forecast periods"
    facts = [f"{r_['period']}: {r_['detail']}" for r_ in (h.get("risks") or []) if r_.get("level") in ("moderate", "high")]
    if h.get("good_outdoor_windows"):
        facts.append("Low-risk times outdoors: " + ", ".join(h["good_outdoor_windows"]))
    facts += list(h.get("advice") or [])[:4]
    caveats = [a.get("headline") or a.get("event") for a in (h.get("official_alerts") or []) if a]
    if trip.start > today + timedelta(days=FORECAST_DAYS):
        caveats.append(f"The forecast covers only the next {FORECAST_DAYS} days; your trip starts {trip.start.isoformat()}. "
                       "This is the current outlook for the city; check again nearer the date.")
    if h.get("stale"):
        caveats.append(f"Forecast data is {h.get('data_age_hours')} hours old")
    conf = h.get("confidence")
    if conf:
        facts.append(f"Confidence {conf}, data {h.get('data_age_hours')} h old")
    reasons = [str(x) for x in (ev.get("reasons") or []) if x]
    meaning = f"{h.get('recommendation', 'Weather risk ' + level)}. " + ("; ".join(reasons) + "." if reasons else "No weather risk flagged for the forecast days.")
    return Finding(
        source="weather", title=TITLES["weather"], status="ok", level=level, headline=headline, meaning=meaning,
        text=h.get("summary") or "", facts=facts, caveats=[c for c in caveats if c], sources=[NWS],
        model=h.get("model"), trace=data.get("trace"), seconds=time.perf_counter() - t0,
        raw={"goodOutdoorWindows": h.get("good_outdoor_windows") or [], "reasons": ev.get("reasons") or [],
             "profile": ev.get("profile"), "travellers": h.get("travellers"), "evaluator": data.get("evaluator"),
             "outcomeReview": h.get("outcome_review"), "periodsCovered": h.get("periods_covered") or []},
    )
