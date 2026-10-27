from risk import assess, assess_period, detect_travellers, profile_for


def period(name="Saturday", temp=70, rain=0, wind="5 mph", summary="Sunny", daytime=True):
    return {"name": name, "temperature_f": temp, "precip_chance_pct": rain, "wind": wind,
            "summary": summary, "daytime": daytime, "start": None, "end": None}


def test_levels_for_a_healthy_adult():
    assert assess_period(period())["level"] == "low"
    assert assess_period(period(temp=96))["level"] == "moderate"
    assert assess_period(period(temp=106))["level"] == "high"
    assert assess_period(period(temp=8))["level"] == "high"
    assert assess_period(period(rain=70))["level"] == "moderate"
    assert assess_period(period(wind="20 to 45 mph"))["level"] == "high"
    assert assess_period(period(summary="Blizzard Conditions"))["level"] == "high"
    assert assess_period(period(summary="Chance Showers And Thunderstorms"))["level"] == "moderate"


def test_sensitive_profile_only_when_stated():
    assert profile_for(None) == "general" and profile_for(["older_adult"]) == "sensitive"
    assert assess_period(period(temp=90))["level"] == "low"
    assert assess_period(period(temp=90), profile="sensitive")["level"] == "moderate"


def test_alerts_set_the_level():
    alert = {"event": "Excessive Heat Warning", "severity": "Extreme"}
    ev = assess([period(), period("Sunday")], [alert])
    assert ev["overall_level"] == "high" and ev["recommendation"].startswith("Avoid")
    assert any("Excessive Heat Warning" in r for r in ev["reasons"])


def test_overall_is_worst_period():
    ev = assess([period(), period("Sunday", rain=80)])
    assert ev["overall_level"] == "moderate" and ev["counts"] == {"low": 1, "moderate": 1, "high": 0}


def test_detects_only_what_the_user_said():
    assert detect_travellers("Visiting Dad in NYC") == []
    assert detect_travellers("Visiting my mum") == []
    assert detect_travellers("with my 85-year-old dad") == ["older_adult"]
    assert detect_travellers("taking our newborn") == ["infant"]
    assert detect_travellers("with a 6 month old") == ["infant"]
    assert detect_travellers("Dad is 85") == ["older_adult"]


def test_reasons_that_set_the_level_come_first():
    alert = {"event": "Rip Current Statement", "severity": "Severe"}
    ev = assess([period(rain=70)], [alert])
    assert ev["overall_level"] == "high" and "Rip Current" in ev["reasons"][0]
