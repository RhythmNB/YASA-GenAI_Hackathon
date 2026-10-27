import json

from critic import confidence, review_outcome, rule_review


def handoff(advice, risks=(), level="moderate", groups=(), summary="Weather risk: Moderate (Go with care).", age=0.5):
    return {"summary": summary, "advice": list(advice), "risk_level": level,
            "risks": [{"type": t, "level": "moderate", "period": "Sat", "detail": t} for t in risks],
            "travellers": {"groups": list(groups)}, "evidence": [{}, {}], "data_age_hours": age}


def test_flags_risks_the_advice_ignores():
    issues = rule_review(handoff(["Have fun!"], risks=["heat", "storm"]))
    assert any("heat" in i for i in issues) and any("storm" in i for i in issues)


def test_good_advice_passes():
    h = handoff(["Go out in the morning and bring water.", "Keep an indoor backup for storms."],
                risks=["heat", "storm"])
    assert rule_review(h) == []


def test_high_risk_needs_a_plan_b():
    h = handoff(["Bring water."], risks=["heat"], level="high")
    assert any("rescheduling" in i for i in rule_review(h))


def test_stated_travellers_must_be_addressed_and_none_invented():
    assert any("infant" in i for i in rule_review(handoff(["Bring water."], groups=["infant"])))
    assert any("no such traveller" in i for i in rule_review(handoff(["Keep your elderly dad cool."])))


def test_no_medical_advice():
    assert any("medical" in i for i in rule_review(handoff(["Take 400 mg ibuprofen if hot."])))


def test_confidence_from_data_age():
    assert confidence(handoff([], age=0.5))["level"] == "high"
    assert confidence(handoff([], age=3))["level"] == "medium"
    assert confidence(handoff([], age=30))["level"] == "low"


def test_model_reviewer_points_are_included():
    class Critic:
        def __call__(self, prompt, system_prompt=None, agent="", sample_response=None):
            return {"text": '{"verdict": "revise", "issues": ["mention sunscreen"]}', "model": "critic"}
    r = review_outcome(handoff(["Bring water."], risks=["heat"]), generator=Critic())
    assert r["verdict"] == "revise" and "(model) mention sunscreen" in r["issues"]
    assert r["reviewer_model"] == "critic"
