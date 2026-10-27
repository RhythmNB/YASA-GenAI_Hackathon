"""Weather agent tests in sample mode (no Nightshift, no Zetaris)."""
import json

from demo_planner import evaluate, plan_visit
from hmem import MemoryRetrievalService, MemoryStoreService
from llm import Generator
from tracing import Tracer
from weather_agent import WeatherAgent


def make_agent(tmp_path, generator=None):
    tracer = Tracer(log_dir=tmp_path / "logs")
    store = MemoryStoreService(path=tmp_path / "mem" / "hmem.jsonl", tracer=tracer)
    retriever = MemoryRetrievalService(store, tracer=tracer)
    return WeatherAgent(generator or Generator(tracer), store, retriever, tracer, refresher=None), store, tracer


def test_handoff_is_grounded_in_data(fixture_db, tmp_path):
    agent, store, tracer = make_agent(tmp_path)
    msg = agent.run("NYC", days=3, household="dad")
    assert msg["status"] == "ok" and msg["from"] == "weather_agent"
    assert msg["good_outdoor_windows"] == ["Sunday"]          # Saturday has an alert, Monday is wet
    types = {r["type"] for r in msg["risks"]}
    assert {"alert", "rain"} <= types
    assert "heat" not in types            # 94°F is not a risk for a healthy adult; nothing assumed
    assert msg["risk_level"] == "moderate" and msg["recommendation"] == "Go with care"
    assert msg["summary"].startswith("Weather risk: Moderate")
    assert msg["travellers"]["groups"] == [] and msg["risk_evaluation"]["profile"] == "general"
    assert "Heat Advisory" in json.dumps(msg)
    assert msg["model"] == "sample/deterministic"
    assert evaluate(msg) == []
    # Facts were written to H-MEM for other agents.
    assert any(r.key == "weather:New York, NY:Saturday" for r in store.active())
    kinds = [json.loads(l)["kind"] for l in tracer.path.read_text().splitlines()]
    for k in ["agent_start", "hmem_retrieve", "tool_call", "risk_evaluation", "llm_call", "self_check", "handoff"]:
        assert k in kinds


def test_bad_model_reply_is_caught_and_falls_back(fixture_db, tmp_path):
    class LyingModel:
        """Invents a day that isn't in the data and ignores the heat alert."""
        def __call__(self, prompt, system_prompt=None, agent="", sample_response=None):
            return {"text": '{"summary": "Thursday is a perfect day.", "advice": []}', "model": "fake"}

    agent, _, tracer = make_agent(tmp_path, generator=LyingModel())
    msg = agent.run("NYC", days=3)
    log = [json.loads(l) for l in tracer.path.read_text().splitlines()]
    checks = [e for e in log if e["kind"] == "self_check"]
    assert len(checks) == 2 and all(c["problems"] for c in checks)   # caught, retried once
    assert any(e["kind"] == "fallback" for e in log)
    assert "Thursday" not in msg["summary"] and evaluate(msg) == []


def test_tool_failure_returns_error_handoff(tmp_path, monkeypatch):
    def broken(city, days):
        raise RuntimeError("Zetaris unreachable")
    tracer = Tracer(log_dir=tmp_path / "logs")
    store = MemoryStoreService(path=tmp_path / "hmem.jsonl")
    monkeypatch.setenv("LLM_MODE", "sample")
    agent = WeatherAgent(Generator(tracer), store, MemoryRetrievalService(store), tracer, briefing_fn=broken)
    msg = agent.run("LA")
    assert msg["status"] == "error" and "Zetaris" in msg["error"]
    assert evaluate(msg)


def test_stated_travellers_tighten_thresholds(fixture_db, tmp_path):
    agent, _, _ = make_agent(tmp_path)
    msg = agent.run("NYC", days=3, travellers=["older_adult"])
    assert msg["risk_evaluation"]["profile"] == "sensitive"
    assert any(r["type"] == "heat" and r["period"] == "Saturday" for r in msg["risks"])
    assert msg["travellers"]["stated"] == ["older_adult"]
    assert evaluate(msg) == []


def test_model_must_state_the_risk_level(fixture_db, tmp_path):
    class NoLevelModel:
        def __call__(self, prompt, system_prompt=None, agent="", sample_response=None):
            return {"text": '{"summary": "Sunday looks fine. Heat Advisory Saturday.", "advice": []}',
                    "model": "fake"}
    agent, _, tracer = make_agent(tmp_path, generator=NoLevelModel())
    msg = agent.run("NYC", days=3)
    checks = [json.loads(l) for l in tracer.path.read_text().splitlines() if '"self_check"' in l]
    assert any("Weather risk" in p for c in checks for p in c["problems"])
    assert msg["summary"].startswith("Weather risk: Moderate") and evaluate(msg) == []


def test_evaluator_rejects_wrong_overall_level(fixture_db, tmp_path):
    agent, _, _ = make_agent(tmp_path)
    msg = agent.run("NYC", days=3)
    msg["risk_level"] = "low"
    assert any("overall risk" in i for i in evaluate(msg))


def test_planner_uses_household_memory(fixture_db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import hmem, tracing
    monkeypatch.setattr(hmem, "HERE", tmp_path)
    monkeypatch.setattr(tracing, "HERE", tmp_path)
    tracer = tracing.Tracer()
    msg, issues = plan_visit("NYC", 3, "dad", ["Dad is 85 and uses a walking frame"], tracer)
    assert not issues
    assert msg["memories_used"]
    assert any("walking frame" in a for a in msg["advice"])
    # A remembered, user-stated fact counts; it was not assumed.
    assert set(msg["travellers"]["from_memory"]) == {"older_adult", "health_condition"}


def test_weekday_filter(fixture_db, tmp_path):
    from datetime import datetime
    agent, _, _ = make_agent(tmp_path)
    full = agent.run("NYC", days=3)
    first_day = datetime.fromisoformat(full["evidence"][2]["start"]).strftime("%A")
    msg = agent.run("NYC", days=3, weekdays=[first_day])
    assert msg["periods_covered"] and all(
        datetime.fromisoformat(e["start"]).strftime("%A") == first_day for e in msg["evidence"])


def test_alerts_outside_the_requested_days_are_reported_separately(fixture_db, tmp_path):
    from datetime import datetime
    agent, _, _ = make_agent(tmp_path)
    full = agent.run("NYC", days=3)
    later_day = datetime.fromisoformat(full["evidence"][4]["start"]).strftime("%A")  # after the alert ends
    msg = agent.run("NYC", days=3, weekdays=[later_day])
    assert msg["official_alerts"] == [] and msg["other_active_alerts"]
    assert evaluate(msg) == []


def test_stale_data_triggers_a_live_refresh(fixture_db, tmp_path, monkeypatch):
    import sqlite3
    con = sqlite3.connect(fixture_db)
    con.execute("UPDATE forecast_periods SET fetched_at = '2020-01-01T00:00:00+00:00'")
    con.commit(); con.close()
    calls = []

    def fake_refresh(city_ids):
        calls.append(city_ids)
        c = sqlite3.connect(fixture_db)
        c.execute("UPDATE forecast_periods SET fetched_at = datetime('now') || '+00:00'")
        c.commit(); c.close()
        return {"ok": city_ids, "seconds": 0.4, "postgres_ok": True}

    tracer = Tracer(log_dir=tmp_path / "logs")
    store = MemoryStoreService(path=tmp_path / "hmem.jsonl")
    agent = WeatherAgent(Generator(tracer), store, MemoryRetrievalService(store), tracer, refresher=fake_refresh)
    msg = agent.run("NYC", days=3)
    assert calls == [["New York, NY"]]
    assert msg["stale"] is False and msg["data_age_hours"] < 1
    log = [json.loads(l) for l in tracer.path.read_text().splitlines()]
    assert any(e["kind"] == "live_refresh" and e["ok"] for e in log)


def test_fresh_data_is_not_refreshed(fixture_db, tmp_path):
    calls = []
    tracer = Tracer(log_dir=tmp_path / "logs")
    store = MemoryStoreService(path=tmp_path / "hmem.jsonl")
    agent = WeatherAgent(Generator(tracer), store, MemoryRetrievalService(store), tracer,
                         refresher=lambda ids: calls.append(ids))
    agent.run("NYC", days=3)
    assert calls == []


def test_refresh_failure_falls_back_to_stored_data(fixture_db, tmp_path):
    import sqlite3
    con = sqlite3.connect(fixture_db)
    con.execute("UPDATE forecast_periods SET fetched_at = '2020-01-01T00:00:00+00:00'")
    con.commit(); con.close()

    def offline(city_ids):
        raise RuntimeError("no internet")

    tracer = Tracer(log_dir=tmp_path / "logs")
    store = MemoryStoreService(path=tmp_path / "hmem.jsonl")
    agent = WeatherAgent(Generator(tracer), store, MemoryRetrievalService(store), tracer, refresher=offline)
    msg = agent.run("NYC", days=3)
    assert msg["status"] == "ok" and msg["stale"] is True
    assert any(r["type"] == "stale" for r in msg["risks"])


def test_outcome_review_triggers_a_revision(fixture_db, tmp_path):
    class WeakThenGood:
        """First answer ignores the rain and alert; the revision fixes it after the review."""
        def __init__(self):
            self.calls = []

        def __call__(self, prompt, system_prompt=None, agent="", sample_response=None):
            self.calls.append(agent)
            if agent == "outcome_reviewer":
                return {"text": '{"verdict": "pass", "issues": []}', "model": "fake"}
            writes = self.calls.count("weather_agent")
            advice = ["Have a nice trip."] if writes == 1 else [
                "Follow the official Heat Advisory instructions.", "Keep an indoor backup for rainy Monday."]
            return {"text": json.dumps({"summary": "Weather risk: Moderate (Go with care). Heat Advisory Saturday.",
                                        "advice": advice}), "model": "fake"}

    gen = WeakThenGood()
    agent, _, tracer = make_agent(tmp_path, generator=gen)
    msg = agent.run("NYC", days=3)
    log = [json.loads(l) for l in tracer.path.read_text().splitlines()]
    reviews = [e for e in log if e["kind"] == "outcome_review"]
    assert reviews[0]["verdict"] == "revise" and reviews[-1]["verdict"] == "pass"
    assert any(e["kind"] == "revision" for e in log)
    assert msg["outcome_review"]["verdict"] == "pass" and "indoor backup" in " ".join(msg["advice"])
    assert evaluate(msg) == []
