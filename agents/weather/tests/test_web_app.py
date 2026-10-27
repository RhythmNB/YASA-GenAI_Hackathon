from web_app import answer, parse_question


def test_parse_question():
    assert parse_question("Visiting Dad in NYC this weekend")[:2] == ("New York, NY", 7)
    assert parse_question("Visiting Dad in NYC this weekend")[3] == ["Saturday", "Sunday"]
    assert parse_question("Boston on Friday")[3] == ["Friday"]
    assert parse_question("Is LA too hot tomorrow?")[:2] == ("Los Angeles, CA", 2)
    assert parse_question("Boise for 4 days")[:2] == ("Boise, ID", 4)
    assert parse_question("Brooklyn next week")[:2] == ("New York, NY", 7)
    assert parse_question("Paris")[0] is None


def test_unknown_city_asks_back():
    assert answer("weather in Paris?")["kind"] == "clarify"


def test_weather_api_structured_call(fixture_db, tmp_path, monkeypatch):
    import hmem, tracing
    monkeypatch.setattr(hmem, "HERE", tmp_path)
    monkeypatch.setattr(tracing, "HERE", tmp_path)
    monkeypatch.setenv("WEATHER_AUTO_REFRESH", "0")
    from web_app import weather_api
    status, body = weather_api({"city": "NYC", "days": 3, "travellers": ["older_adult"]})
    assert status == 200 and body["ok"] and body["evaluator"]["ok"]
    h = body["handoff"]
    assert h["city"] == "New York, NY" and h["risk_evaluation"]["profile"] == "sensitive"
    assert h["outcome_review"]["verdict"] == "pass"


def test_weather_api_reads_free_text_and_validates(fixture_db, tmp_path, monkeypatch):
    import hmem, tracing
    monkeypatch.setattr(hmem, "HERE", tmp_path)
    monkeypatch.setattr(tracing, "HERE", tmp_path)
    monkeypatch.setenv("WEATHER_AUTO_REFRESH", "0")
    from web_app import weather_api
    status, body = weather_api({"question": "with our newborn in new york"})
    assert status == 200 and body["handoff"]["travellers"]["stated"] == ["infant"]
    assert weather_api({"city": "Paris"})[0] == 400
    assert weather_api({"city": "NYC", "travellers": ["grumpy"]})[0] == 400
