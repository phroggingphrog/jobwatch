from types import SimpleNamespace

import pytest

from pipeline import tracks, title_triage
from pipeline.nodes import gate
from pipeline.schemas import JobFacts, MatchScore


def cfg(categories=()):
    return SimpleNamespace(settings={"pipeline": {"screened": {"category_snapshot": {"categories": list(categories)}}}})


def category(id, phrase, priority=0, **kwargs):
    return {"id": id, "label": id, "priority": priority, "phrases": [phrase], "action": "admit",
            "promote": True, "hours": "standard", **kwargs}


def test_no_implicit_words_and_isolation():
    assert tracks.classify("Internship Engineer", tracks.settings(cfg())) is None
    a = tracks.settings(cfg([category("a", "engineer")]))
    b = tracks.settings(cfg([category("b", "engineer")]))
    assert tracks.classify("Engineer", a) == "a"
    assert tracks.classify("Engineer", b) == "b"
    assert tracks.classify("Engineer", tracks.settings(cfg())) is None


def test_config_only_order_rename_remove():
    first = category("first", "alpha", 0)
    second = category("second", "alpha", 1)
    assert tracks.classify("Alpha", tracks.settings(cfg([second, first]))) == "first"
    assert tracks.classify("Alpha", tracks.settings(cfg([{**first, "id": "renamed", "priority": 2}, second]))) == "second"
    assert tracks.classify("Alpha", tracks.settings(cfg([{**first, "id": "renamed"}]))) == "renamed"
    assert tracks.classify("Alpha", tracks.settings(cfg())) is None


def test_dynamic_schema_rejects_other_ids():
    schema = title_triage.verdict_schema(tracks.settings(cfg([category("custom", "alpha")])))
    assert schema(items=[{"id": 1, "track": "custom"}]).items[0].track == "custom"
    with pytest.raises(ValueError):
        schema(items=[{"id": 1, "track": "primary"}])


def test_hours_limit_cannot_be_bypassed_by_category_or_policy(monkeypatch):
    from jobwatch.candidate import eligibility
    monkeypatch.setattr(eligibility, "evaluate_eligibility", lambda job, ad_text="": eligibility._result("excluded", "hours_exceeded"))
    monkeypatch.setattr(JobFacts, "model_dump", lambda self, **k: {})
    facts = JobFacts.model_construct(real_job=True)
    score = MatchScore.model_validate({"technical_skills": {"score": 4, "evidence": "evidence text"},
        "experience": {"score": 4, "evidence": "evidence text"}, "domain": {"score": 4, "evidence": "evidence text"},
        "wanted": "core", "justification": "a plain justification"})
    for track, policy in [("undergraduate", "standard"), ("custom", "allow_hours_only")]:
        route, decision = gate.decide(facts, score, "text", posting={"track": track}, hours_policy=policy)
        assert route == "archive"
        assert decision.passed is False
        assert decision.reason == "hours_exceeded"
