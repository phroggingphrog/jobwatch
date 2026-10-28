from types import SimpleNamespace

import pipeline.agentic.jev_skills as J
from pipeline.agentic.draft import drop_claims


def test_only_career_facts_reach_jev_and_name_is_masked():
    profile = SimpleNamespace(evidence=[
        {"id": "pf.experience.0.title", "text": "Graduate Accountant"},
        {"id": "pf.experience.0.highlights.0", "text": "Ann Lee reviewed individual tax returns"},
        {"id": "pf.candidate.work_rights.visa", "text": "Student visa (subclass 500)"},
        {"id": "cv.L5", "text": "ann@example.com | 0412 345 678"},
        {"id": "cv.L7", "text": "Full working rights for part-time work"},
    ])
    facts = J.safe_facts(profile, "Ann Lee")
    assert set(facts) == {"pf.experience.0.title", "pf.experience.0.highlights.0"}
    assert "Ann" not in facts["pf.experience.0.highlights.0"]


def test_claim_check_drops_only_unsupported_lines(monkeypatch):
    monkeypatch.setattr(J, "_post", lambda cfg, path, body: {"answers": {"c0": {"noul": 0.9}, "c1": {"noul": 0.1}}})
    claims = [{"id": "a", "text": "Reviewed tax returns", "evidence_ids": ["e1"]},
              {"id": "b", "text": "Led a team of 12", "evidence_ids": ["e1"]},
              {"id": "c", "text": "Student visa holder", "evidence_ids": ["private"]}]
    assert J.unsupported_claims(claims, {"e1": "Reviewed individual tax returns"}) == {"b"}
    draft = {"cv": {"summary": claims[:2], "experience": [{"bullets": claims[:2]}]}, "letter": {"paragraphs": [claims[:2]]}}
    clean = drop_claims(draft, {"b"})
    assert [c["id"] for c in clean["cv"]["summary"]] == ["a"]
    assert [c["id"] for c in clean["letter"]["paragraphs"][0]] == ["a"]
    assert len(draft["cv"]["summary"]) == 2  # original untouched


def test_work_rights_requirements_are_not_mapped(tmp_path):
    assert J.requirement_map([{"id": "r1", "text": "Employer screening question asks about right to work in Australia"}],
                             {"e1": "Graduate Accountant"}, tmp_path / "v.sqlite") == []
