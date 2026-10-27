"""Weather risk evaluation: rule-based, so every level can be explained and checked.

Each forecast period gets a level (low / moderate / high) with reasons, and a trip
gets an overall level (the worst period in the requested range) plus a
recommendation. The model never decides the level; it only writes it up.

Thresholds are for a healthy adult by default. Stricter thresholds apply ONLY when
the travellers are explicitly described as sensitive (older adult, infant, young
child, pregnant, or a health condition). Nothing is assumed about who is travelling.
"""
import re
from datetime import datetime

LEVELS = ["low", "moderate", "high"]
RECOMMENDATION = {
    "low": "Good to go",
    "moderate": "Go with care",
    "high": "Avoid or reschedule outdoor plans",
}
SENSITIVE_GROUPS = {"older_adult", "infant", "young_child", "pregnant", "health_condition"}

# value at or beyond which a factor becomes (moderate, high)
PROFILES = {
    "general": {"heat_f": (95, 105), "cold_f": (32, 10), "rain_pct": (60, None), "wind_mph": (25, 40)},
    "sensitive": {"heat_f": (88, 95), "cold_f": (40, 20), "rain_pct": (50, None), "wind_mph": (20, 35)},
}

# Forecast wording -> level
KEYWORDS = [
    (r"blizzard|ice storm|heavy snow|hurricane|tropical storm|tornado|severe thunderstorm", "high"),
    (r"thunderstorm|t-storm|freezing rain|freezing drizzle|sleet|snow|smoke|blowing dust", "moderate"),
]
ALERT_LEVEL = {"extreme": "high", "severe": "high", "moderate": "moderate", "minor": "low"}


def _worse(a, b):
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def profile_for(travellers):
    """'sensitive' only if a traveller group is explicitly given as sensitive."""
    groups = {str(t).strip().lower() for t in (travellers or [])}
    return "sensitive" if groups & SENSITIVE_GROUPS else "general"


def max_wind_mph(text):
    nums = [int(n) for n in re.findall(r"\d+", text or "")]
    return max(nums) if nums else None


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _overlaps(period, alert):
    """True if the alert covers this period (or if times are unknown)."""
    p_start, p_end = _parse(period.get("start")), _parse(period.get("end"))
    a_start, a_end = _parse(alert.get("effective")), _parse(alert.get("expires"))
    if not (p_start and p_end and a_end):
        return True
    return (a_start or p_start) < p_end and a_end > p_start


def assess_period(period, alerts=(), profile="general"):
    t = PROFILES[profile]
    level, reasons = "low", []

    def bump(new_level, kind, detail):
        nonlocal level
        level = _worse(level, new_level)
        reasons.append({"type": kind, "level": new_level, "detail": detail})

    temp = period.get("temperature_f")
    if temp is not None:
        mod, high = t["heat_f"]
        if temp >= high:
            bump("high", "heat", f"extreme heat ({temp}°F)")
        elif temp >= mod:
            bump("moderate", "heat", f"heat ({temp}°F)")
        mod, high = t["cold_f"]
        if temp <= high:
            bump("high", "cold", f"extreme cold ({temp}°F)")
        elif temp <= mod:
            bump("moderate", "cold", f"cold ({temp}°F)")

    rain = period.get("precip_chance_pct") or 0
    if rain >= t["rain_pct"][0]:
        bump("moderate", "rain", f"{rain}% chance of rain")

    wind = max_wind_mph(period.get("wind"))
    if wind is not None:
        mod, high = t["wind_mph"]
        if wind >= high:
            bump("high", "wind", f"strong winds (up to {wind} mph)")
        elif wind >= mod:
            bump("moderate", "wind", f"wind (up to {wind} mph)")

    summary = (period.get("summary") or "").lower()
    for pattern, kw_level in KEYWORDS:
        m = re.search(pattern, summary)
        if m:
            bump(kw_level, "storm", f"forecast mentions {m.group(0)}")
            break

    for a in alerts:
        if _overlaps(period, a):
            a_level = ALERT_LEVEL.get((a.get("severity") or "").lower(), "moderate")
            bump(a_level, "alert", f"official NWS {a.get('event')} ({a.get('severity') or 'unknown severity'})")

    return {"level": level, "reasons": reasons}


def assess(periods, alerts=(), travellers=None):
    """Assess a list of weather_tool periods. Returns the trip-level evaluation."""
    profile = profile_for(travellers)
    per_period = []
    overall = "low"
    for p in periods:
        r = assess_period(p, alerts, profile)
        per_period.append({"period": p["name"], "daytime": p.get("daytime"), **r})
        overall = _worse(overall, r["level"])
    # Alerts with no overlap info still count toward the overall level.
    if alerts and not periods:
        for a in alerts:
            overall = _worse(overall, ALERT_LEVEL.get((a.get("severity") or "").lower(), "moderate"))
    # Reasons that set the overall level come first, then the rest, most serious first.
    reasons = []
    for want in reversed(LEVELS):
        for p in per_period:
            for r in p["reasons"]:
                text = f"{p['period']}: {r['detail']}"
                if r["level"] == want and text not in reasons:
                    reasons.append(text)
    return {
        "overall_level": overall,
        "recommendation": RECOMMENDATION[overall],
        "reasons": reasons[:6],
        "profile": profile,
        "periods": per_period,
        "counts": {lvl: sum(1 for p in per_period if p["level"] == lvl) for lvl in LEVELS},
    }


_AGE = re.compile(r"(\d{1,3})[- ]?(year|yr|month|week)s?[- ]?old", re.I)
_GROUP_WORDS = [
    ("older_adult", r"elderly|senior|grand(?:ma|pa|mother|father|parent)s?|nana|aged (?:mum|mom|dad|father|mother)|retiree"),
    ("infant", r"newborn|new-born|\bbaby\b|\bbabies\b|infant"),
    ("young_child", r"toddler|young (?:kid|child)|little ones|preschooler"),
    ("pregnant", r"pregnan|expecting a baby"),
    ("health_condition", r"asthma|copd|heart condition|immunocompromised|chemo|dementia|uses a (?:wheelchair|walking frame|walker)|mobility"),
]


def detect_travellers(text):
    """Sensitive groups the user explicitly described (never inferred from 'Dad' or 'Mum' alone)."""
    found = set()
    t = text or ""
    for num, unit in _AGE.findall(t):
        n, unit = int(num), unit.lower()
        if unit in ("month", "week") or n <= 1:
            found.add("infant")
        elif n <= 5:
            found.add("young_child")
        elif n >= 65:
            found.add("older_adult")
    for num in re.findall(r"\b(?:is|aged|age)\s+(\d{2,3})\b", t, re.I):
        if int(num) >= 65:
            found.add("older_adult")
    for group, pattern in _GROUP_WORDS:
        if re.search(pattern, t, re.I):
            found.add(group)
    return sorted(found)
