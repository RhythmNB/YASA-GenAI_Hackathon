import pytest

from weather_tool import get_weather_briefing


@pytest.mark.parametrize("days", [1, 2, 3])
def test_briefing_has_periods_and_trace(fixture_db, days):
    b = get_weather_briefing("NYC", days=days)
    assert b["city"] == "New York, NY"
    assert len(b["periods"]) == days * 2
    assert b["trace"]["queries"]
    assert not b["stale"]
    for p in b["periods"]:
        assert set(p["flags"]) <= {"heat", "cold", "rain"}


def test_flags_and_outdoor_windows(fixture_db):
    b = get_weather_briefing("NYC", days=3)
    flags = {p["name"]: p["flags"] for p in b["periods"]}
    assert flags["Saturday"] == ["heat"] and "rain" in flags["Monday"]
    assert b["good_outdoor_windows"] == ["Sunday"]
    assert b["active_alerts"][0]["event"] == "Heat Advisory"


def test_rejects_unknown_city():
    with pytest.raises(ValueError):
        get_weather_briefing("Sydney")
