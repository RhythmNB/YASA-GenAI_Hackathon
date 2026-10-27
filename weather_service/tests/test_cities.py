from cities import CITIES, STATES, get_city, resolve_city


def test_coverage():
    assert len(CITIES) >= 150
    assert {c["state"] for c in CITIES.values()} == set(STATES)   # all 50 states + DC
    for c in CITIES.values():
        assert 18 < c["lat"] < 72 and -170 < c["lon"] < -66


def test_resolver_handles_shared_names_and_states():
    assert resolve_city("Portland, Maine")[0] == "Portland, ME"
    city, note = resolve_city("portland this weekend")
    assert city == "Portland, OR" and "Portland, ME" in note
    assert resolve_city("Kansas City, Kansas")[0] == "Kansas City, KS"
    assert resolve_city("Kansas City")[0] == "Kansas City, MO"
    assert resolve_city("Buffalo, New York")[0] == "Buffalo, NY"
    assert resolve_city("New Orleans, LA")[0] == "New Orleans, LA"
    assert resolve_city("Seattle, Washington")[0] == "Seattle, WA"
    assert resolve_city("DC tomorrow")[0] == "Washington, DC"
    assert resolve_city("me and Dad")[0] is None


def test_legacy_ids():
    assert get_city("NYC")["id"] == "New York, NY"
    assert get_city("LA")["id"] == "Los Angeles, CA"


def test_each_states_top_four_is_covered():
    # 4 largest cities per state (Wikipedia, largest cities of U.S. states by population)
    top4 = {
        "AL": "Huntsville Mobile Birmingham Montgomery", "AK": "Anchorage Juneau Fairbanks Wasilla",
        "AZ": "Phoenix Tucson Mesa Gilbert", "HI": "Honolulu|East Honolulu|Pearl City|Hilo",
        "ID": "Boise Meridian Nampa Caldwell", "IN": "Indianapolis|Fort Wayne|Evansville|Carmel",
        "MN": "Minneapolis|Saint Paul|Rochester|Bloomington", "NJ": "Newark|Jersey City|Paterson|Lakewood",
        "NH": "Manchester Nashua Concord Dover", "RI": "Providence Cranston Warwick Pawtucket",
        "VT": "Burlington|South Burlington|Colchester|Rutland", "SD": "Sioux Falls|Rapid City|Aberdeen|Brookings",
        "ME": "Portland|Lewiston|Bangor|South Portland", "DE": "Wilmington Dover Newark Middletown",
        "GA": "Atlanta Columbus Augusta Macon",
    }
    for st, names in top4.items():
        for name in (names.split("|") if "|" in names else names.split()):
            assert f"{name}, {st}" in CITIES, f"{name}, {st} missing"
    from collections import Counter
    per_state = Counter(c["state"] for c in CITIES.values())
    assert all(n >= 4 for st, n in per_state.items() if st != "DC"), per_state
