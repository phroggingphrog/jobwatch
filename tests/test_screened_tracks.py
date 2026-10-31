from types import SimpleNamespace

from pipeline import tracks
from pipeline.nodes import gate
from pipeline.schemas import JobFacts, MatchScore

CFG = SimpleNamespace(settings={"pipeline": {"screened": {"tracks": {
    "primary": ["accounts payable"], "secondary": ["barista", "chef"], "drop": ["registered nurse"]}}}})


def test_classify_order_and_defaults():
    t = tracks.settings(CFG)
    assert tracks.classify("Graduate Chef Program", t) == "undergraduate"
    assert tracks.classify("2027 Summer Vacation Internship", t) == "undergraduate"
    assert tracks.classify("Accounts Payable Officer", t) == "primary"
    assert tracks.classify("Barista (casual)", t) == "secondary"
    assert tracks.classify("Registered Nurse - Ward 4", t) == "drop"
    assert tracks.classify("Operations Coordinator", t) is None
    assert tracks.classify("Internal Auditor", t) is None          # "intern" is a whole word only


def test_no_private_lists_means_only_programs():
    t = tracks.settings(SimpleNamespace(settings={}))
    assert tracks.classify("Chef", t) is None
    assert tracks.classify("Graduate Analyst", t) == "undergraduate"


def _score():
    return MatchScore.model_validate({"technical_skills": {"score": 4, "evidence": "evidence text"},
                                      "experience": {"score": 4, "evidence": "evidence text"},
                                      "domain": {"score": 4, "evidence": "evidence text"},
                                      "wanted": "core", "justification": "a plain justification"})


def test_program_is_not_hidden_for_hours(monkeypatch):
    from jobwatch.candidate import eligibility
    monkeypatch.setattr(eligibility, "evaluate_eligibility",
                        lambda job, ad_text="": eligibility._result("excluded", "hours_exceeded"))
    facts = JobFacts.model_construct(real_job=True)
    monkeypatch.setattr(JobFacts, "model_dump", lambda self, **k: {})
    route, dec = gate.decide(facts, _score(), "full-time 38 hours per week", "Graduate Analyst",
                             posting={"track": "undergraduate"})
    assert route == "draft" and dec.reason == "eligible_check_hours"
    route, _ = gate.decide(facts, _score(), "full-time 38 hours per week", "Analyst", posting={"track": "primary"})
    assert route == "archive"
