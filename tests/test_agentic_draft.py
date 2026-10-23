from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.agentic.contracts import (
    AgenticEvaluation, Dimension, Requirement, RequirementMatch, RequirementSet, RunKey, SourceCitation,
)
from pipeline.schemas import JobFacts, WorkRights
from pipeline.agentic.review import REQUIRED_CRITERIA

H = hashlib.sha256(b"Python developer").hexdigest()
EVIDENCE_HASH = "b" * 64
CONFIG_HASH = "c" * 64


def _evaluation(evidence_hash=EVIDENCE_HASH):
    key = RunKey(posting_id=41, ad_hash=H, evidence_hash=evidence_hash,
                 rubric_version="career-ops-v1", config_hash=CONFIG_HASH)
    jd = SourceCitation(source_id="ad", content_hash=H, quote="Python developer")
    candidate = SourceCitation(source_id="cv.L4", content_hash=EVIDENCE_HASH,
                               quote="Automated reporting with Python")
    requirement = Requirement(id="python", text="Python", tier="stated", importance="high", jd_signal=jd)
    return AgenticEvaluation(
        run_key=key, requirements=RequirementSet(ad_hash=H, requirements=(requirement,)),
        matches=(RequirementMatch(requirement_id="python", match="strong", evidence=(candidate,)),),
        archetype="software developer", global_score=4.2,
        dimensions={name: Dimension(score=4.0, reason="evidence supports the match")
                    for name in ("cv_match", "north_star", "compensation", "culture", "red_flags")},
        facts=JobFacts(real_job=True, role_family="software_dev", duties=["Build software"],
                       required_skills=["Python"], preferred_skills=[], seniority="entry", min_years=None,
                       hours="full_time_only", program=False,
                       work_rights=WorkRights(requirement="none_stated", quote=""), screening_questions=[]),
        location_fit="melbourne", location_evidence=None, legitimacy="verified", research_available=False,
        report={key: f"Evaluation section {key}" for key in "ABCDEFG"}, screening_questions=(),
    )


def _proposal(context, feedback=()):
    return {
        "run_key": context["evaluation"]["run_key"],
        "evaluation_hash": context["evaluation_hash"],
        "evidence_hash": context["evaluation"]["run_key"]["evidence_hash"],
        "content": {
            "cv": {"summary": [{"id": "claim-1", "text": "Automated reporting with Python",
                                 "evidence_ids": ["cv.L4"], "tier": "stated",
                                 "key_span": "Automated reporting with Python"}]},
            "letter": {"paragraphs": [[{"id": "letter-1", "text": "As a graduate student, I am applying for the Developer role at Python.",
                                          "evidence_ids": ["cv.L4"], "tier": "framing"}]]},
            "honest_gaps": [],
        },
        "screening_answers": (),
    }



def _bundle(tmp_path):
    from jobwatch.candidate.evidence import snapshot_evidence
    root = tmp_path / "private-profile"
    root.mkdir(exist_ok=True)
    (root / "cv.md").write_text("# Synthetic Candidate\n\n## Experience\n- Automated reporting with Python\n")
    return snapshot_evidence(root)

def test_drafter_review_and_pdf_package_are_verified(tmp_path, monkeypatch):
    """A passing package requires fresh review plus verified claim and both PDF bytes."""
    from pipeline.agentic import draft
    from pipeline.agentic.contracts import DraftProposal, ReviewVerdict

    bundle = _bundle(tmp_path)
    evaluation = _evaluation(bundle.bundle_hash)
    cv_pdf, letter_pdf = b"synthetic verified cv pdf", b"synthetic verified letter pdf"
    monkeypatch.setattr(draft, "render_pdf", lambda text, max_pages, letter=False:
                        (letter_pdf if letter else cv_pdf, {"pages_rendered": 1}))
    monkeypatch.setattr(draft, "verify_pdf", lambda *args: {"ok": True, "failures": []})

    calls = []
    def fake_run_role(role, context, budget, llm, **kwargs):
        calls.append((role.name, context))
        if role.name == "drafter":
            proposal = DraftProposal.model_validate(_proposal(context))
            return SimpleNamespace(output=proposal)
        proposal = DraftProposal.model_validate(context["draft"])
        verdict = ReviewVerdict(run_key=evaluation.run_key, draft_hash=proposal.draft_hash,
                                reviewer_role="independent_reviewer", verdict="approve",
                                criteria=dict.fromkeys(REQUIRED_CRITERIA, True), feedback=())
        return SimpleNamespace(output=verdict)

    monkeypatch.setattr(draft, "run_role", fake_run_role)
    from pipeline.agentic import review
    monkeypatch.setattr(review, "run_role", fake_run_role)
    manifest = draft.draft_and_review(evaluation.run_key, evaluation,
                                      budget=object(), llm_drafter=object(), llm_reviewer=object(), evidence_bundle=bundle,
                                      posting={"company": "Python", "title": "Developer"},
                                      ad_text="Python developer")

    assert manifest.run_key == evaluation.run_key
    assert manifest.pdfs == {"cv": hashlib.sha256(cv_pdf).hexdigest(),
                             "letter": hashlib.sha256(letter_pdf).hexdigest()}
    assert manifest.verification == {"cv_pdf": True, "letter_pdf": True, "claims": True, "review": True}
    assert calls[0][0] == "drafter" and calls[1][0] == "reviewer"
    assert DraftProposal.model_validate(calls[1][1]["draft"]).draft_hash == manifest.draft_hash


def test_drafter_rejects_unsupported_claims_before_package_creation(tmp_path, monkeypatch):
    """An unsupported generated claim must not survive into a verified package."""
    from pipeline.agentic import draft

    bundle = _bundle(tmp_path)
    evaluation = _evaluation(bundle.bundle_hash)
    monkeypatch.setattr(draft, "render_pdf", lambda *args, **kwargs: (b"pdf", {}))
    monkeypatch.setattr(draft, "verify_pdf", lambda *args: {"ok": True, "failures": []})

    def fake_run_role(role, context, budget, llm, **kwargs):
        proposal = _proposal(context)
        proposal["content"]["cv"]["summary"][0]["text"] = "Led a team of 80 engineers"
        if role.name == "drafter":
            from pipeline.agentic.contracts import DraftProposal
            return SimpleNamespace(output=DraftProposal.model_validate(proposal))
        pytest.fail("reviewer must not approve unsupported claims")

    monkeypatch.setattr(draft, "run_role", fake_run_role)
    with pytest.raises(Exception):
        draft.draft_and_review(evaluation.run_key, evaluation, object(), object(), object(), evidence_bundle=bundle, ad_text="Python developer")


def test_reviewer_gets_fresh_draft_hash_and_revision_is_bounded(tmp_path, monkeypatch):
    """Review binds each verdict to the exact draft and permits only one revision cycle."""
    from pipeline.agentic import draft
    from pipeline.agentic.contracts import DraftProposal, ReviewVerdict

    bundle = _bundle(tmp_path)
    evaluation = _evaluation(bundle.bundle_hash)
    monkeypatch.setattr(draft, "render_pdf", lambda *args, **kwargs: (b"pdf", {}))
    monkeypatch.setattr(draft, "verify_pdf", lambda *args: {"ok": True, "failures": []})
    seen = {"reviews": 0, "revisions": 0}

    def fake_run_role(role, context, budget, llm, **kwargs):
        if role.name == "drafter":
            seen["revisions"] += bool(context.get("review_feedback"))
            return SimpleNamespace(output=DraftProposal.model_validate(_proposal(context)))
        seen["reviews"] += 1
        proposal = DraftProposal.model_validate(context["draft"])
        return SimpleNamespace(output=ReviewVerdict(
            run_key=evaluation.run_key, draft_hash=proposal.draft_hash,
            reviewer_role="independent_reviewer", verdict="revise" if seen["reviews"] == 1 else "approve",
            criteria=dict.fromkeys(REQUIRED_CRITERIA, seen["reviews"] != 1),
            feedback=("Tailor the opening",) if seen["reviews"] == 1 else ()))

    monkeypatch.setattr(draft, "run_role", fake_run_role)
    from pipeline.agentic import review
    monkeypatch.setattr(review, "run_role", fake_run_role)
    result = draft.draft_and_review(evaluation.run_key, evaluation, object(), object(), object(), evidence_bundle=bundle, ad_text="Python developer", posting={"company": "Python", "title": "Developer"})
    assert result.verification["review"] is True
    assert seen == {"reviews": 2, "revisions": 1}


def test_draft_refuses_missing_or_changed_snapshot_before_model(tmp_path):
    from pipeline.agentic.draft import draft_and_review
    from pipeline.agentic.contracts import AgenticError
    with pytest.raises(AgenticError, match="invalid_draft_evidence"):
        draft_and_review(_evaluation().run_key, _evaluation(), object(), object(), object())
    bundle = _bundle(tmp_path)
    with pytest.raises(AgenticError, match="invalid_draft_evidence"):
        draft_and_review(_evaluation().run_key, _evaluation(), object(), object(), object(), evidence_bundle=bundle, ad_text="Python developer")


def test_independent_reviewer_cannot_choose_its_own_passing_criteria(tmp_path):
    from pipeline.agentic.review import review_proposal
    from pipeline.agentic.contracts import AgenticError, DraftProposal, ReviewVerdict
    ev = _evaluation()
    proposal = DraftProposal.model_validate(_proposal({"evaluation": ev.model_dump(), "evaluation_hash": H}))
    def incomplete(*args, **kwargs):
        return SimpleNamespace(output=ReviewVerdict(run_key=ev.run_key, draft_hash=proposal.draft_hash,
                               verdict="approve", reviewer_role="independent_reviewer",
                               criteria={"tailored": True}, feedback=()))
    with pytest.raises(AgenticError):
        review_proposal(ev.run_key, proposal, {}, object(), object(), runner=incomplete)


def test_real_deepagent_writer_reads_checks_then_submits(tmp_path, monkeypatch):
    import json
    from jobwatch.llm import LLM
    from pipeline.agentic import draft
    from pipeline.agentic.runtime import BatchBudget, JobBudget
    bundle = _bundle(tmp_path)
    ev = _evaluation(bundle.bundle_hash)
    payload = _proposal({"evaluation": ev.model_dump(), "evaluation_hash": draft._evaluation_hash(ev)})
    messages = iter([
        {"tool": "read_candidate_evidence", "arguments": {"ids": ["cv.L4"]}},
        {"tool": "read_primary_sources", "arguments": {"filenames": ["cv.md"]}},
        {"tool": "check_draft_claims", "arguments": {"content": payload["content"]}},
        {"tool": "submit_draft", "arguments": {"proposal": payload}},
        {"tool": "read_primary_sources", "arguments": {"filenames": ["cv.md"]}},
        {"tool": "read_candidate_evidence", "arguments": {"ids": ["cv.L4"]}},
        {"tool": "submit_review", "arguments": {"verdict": "approve",
         "criteria": dict.fromkeys(REQUIRED_CRITERIA, True), "feedback": []}},
    ])
    calls = []
    def transport(url, headers, body, timeout):
        calls.append(body)
        return 200, {"choices": [{"message": {"content": json.dumps(next(messages))}}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 100}}
    llm = LLM(transport=transport, keys=["synthetic"])
    monkeypatch.setattr(draft, "render_pdf", lambda *a, **k: (b"verified synthetic PDF", {}))
    monkeypatch.setattr(draft, "verify_pdf", lambda *a: {"ok": True, "failures": []})
    budget = JobBudget(ev.run_key.value, BatchBudget("synthetic"))
    result = draft.draft_and_review(ev.run_key, ev, budget, llm, llm, evidence_bundle=bundle,
                                   posting={"company": "Python", "title": "Developer"},
                                   ad_text="Python developer", return_bundle=True)
    assert "Python" in result.letter_markdown
    assert len(calls) == 7 and budget.charged_tokens == 1400
    initial_writer = json.loads(calls[0]["messages"][-1]["content"])
    assert "evidence" not in initial_writer and "screening_sources" not in initial_writer
    assert initial_writer["evidence_inventory"] == [{"id": "cv.L4", "kind": "achievement", "text": "Automated reporting with Python"}]
    initial_reviewer = json.loads(calls[4]["messages"][-1]["content"])
    assert initial_reviewer["candidate_evidence"][0]["text"] == "Automated reporting with Python"
    assert set(initial_reviewer["required_criteria"]) == set(REQUIRED_CRITERIA)
    assert result.manifest.verification["review"] is True


def test_snapshot_readers_preserve_full_sources_and_refuse_unknown_names(tmp_path):
    from pipeline.agentic import draft, review
    from pipeline.agentic.contracts import AgenticError, DraftProposal
    bundle = _bundle(tmp_path)
    profile = draft.profile_from_snapshot(bundle)
    ev = _evaluation(bundle.bundle_hash)
    sources = {name: raw.decode() for name, raw in bundle.contents.items()}
    spec = draft._role(profile, ev, "Python developer", primary_sources=sources)
    captured = []
    def capture(role, context, *args, **kwargs):
        captured.append((role, context))
        raise AgenticError("measurement_complete")
    proposal = DraftProposal.model_validate(_proposal({"evaluation": ev.model_dump(), "evaluation_hash": H}))
    with pytest.raises(AgenticError, match="measurement_complete"):
        review.review_proposal(ev.run_key, proposal, {}, object(), object(), runner=capture,
                              evidence=profile.evidence, screening_sources=sources, source_hashes=bundle.sources)
    # Changing the original file or caller mapping after role construction cannot
    # change what either role reads from the already captured snapshot.
    (tmp_path / "private-profile" / "cv.md").write_text("changed after snapshot")
    original = sources["cv.md"]
    sources["cv.md"] = "changed caller mapping"
    for role in (spec, captured[0][0]):
        tools = {tool.name: tool for tool in role.tools}
        reader = tools["read_primary_sources"]
        value = reader.handler(reader.arguments_model(filenames=["cv.md"]), {})
        assert value == [{"source_file": "cv.md", "source_hash": bundle.sources["cv.md"], "text": original}]
        evidence = tools["read_candidate_evidence"]
        assert evidence.handler(evidence.arguments_model(ids=["cv.L4"]), {}) == profile.evidence




def test_screening_answer_is_never_taken_by_position_when_its_question_is_missing(tmp_path):
    from pipeline.agentic import draft
    from pipeline.agentic.contracts import AgenticScreeningAnswer, DraftProposal
    bundle = _bundle(tmp_path)
    questions = ("Are you an Australian citizen?", "Describe your reporting experience")
    evaluation = _evaluation(bundle.bundle_hash).model_copy(update={"screening_questions": questions})
    cited = AgenticScreeningAnswer(
        question=questions[1], answer="I automated reporting with Python.", source="evidence",
        citations=(SourceCitation(source_id="cv.md", content_hash=bundle.sources["cv.md"], quote="Automated reporting with Python"),))
    content = _proposal({"evaluation": {"run_key": evaluation.run_key.model_dump(mode="json")},
                         "evaluation_hash": draft._evaluation_hash(evaluation)})["content"]
    # The model skipped the citizenship question and answered only the second one.
    proposal = DraftProposal(run_key=evaluation.run_key, evaluation_hash=draft._evaluation_hash(evaluation),
                             evidence_hash=bundle.bundle_hash, content=content, screening_answers=(cited,))
    out = draft._proposal(SimpleNamespace(output=proposal), evaluation.run_key, draft._evaluation_hash(evaluation), evaluation, bundle)
    first, second = out.screening_answers
    assert (first.question, first.source, first.answer) == (questions[0], "owner_to_answer", "")  # not cross-wired
    assert (second.question, second.source) == (questions[1], "evidence") and second.answer == cited.answer


def _failure_captures(run_key):
    from pipeline.agentic import draft, review
    verdict = SimpleNamespace(verdict="reject", criteria={"claims_supported": False}, feedback=("quotes the private letter",))
    draft._save_pdf_failure(run_key, b"%PDF cv", b"%PDF letter", {"ok": False})
    draft._save_rejection(run_key, verdict, {"letter": "Dear private employer", "removed": []})
    review._log_review_failure(run_key, {"verdict": "approve", "feedback": ["private reviewer words"]})


def _written(root):
    return [p for p in root.rglob("*") if p.is_file()]


def test_private_failure_capture_is_off_unless_opted_in(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JOBWATCH_CAPTURE_PRIVATE_FAILURES", raising=False)
    _failure_captures(_evaluation().run_key)
    assert _written(tmp_path) == []  # CV/letter PDFs, letter text and reviewer replies stay out of the data dir


def test_opted_in_private_failure_capture_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_CAPTURE_PRIVATE_FAILURES", "true")
    _failure_captures(_evaluation().run_key)
    files = _written(tmp_path)
    assert {p.name for p in files} >= {"cv.pdf", "letter.pdf", "report.json"} and len(files) == 5
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in files), [oct(p.stat().st_mode) for p in files]
    assert all(p.parent.stat().st_mode & 0o077 == 0 for p in files)
