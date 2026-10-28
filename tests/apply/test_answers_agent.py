"""Application answers are grounded, complete, private, and separate from submission."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobwatch.apply.answers_agent import (
    AnswerRefused, answer_application, load_answer_sources, save_owner_answer,
)


def test_answer_sources_reuse_only_exact_canonical_cv_alias(tmp_path):
    text = "# Synthetic candidate\nEmail: applicant@example.test\n"
    (tmp_path / "master_resume.md").write_text(text)
    expected = load_answer_sources(tmp_path)
    (tmp_path / "cv.md").symlink_to("master_resume.md")
    actual = load_answer_sources(tmp_path)
    assert actual == expected
    assert set(actual.texts) == {"master_resume.md"}


@pytest.mark.parametrize("target", ["../outside.md", "./master_resume.md", "other.md"])
def test_answer_sources_refuse_noncanonical_cv_alias(tmp_path, target):
    (tmp_path / "master_resume.md").write_text("# Synthetic candidate\n")
    (tmp_path / "cv.md").symlink_to(target)
    with pytest.raises(AnswerRefused, match="answer_sources_unavailable"):
        load_answer_sources(tmp_path)


def test_answer_sources_refuse_canonical_alias_to_another_symlink(tmp_path):
    (tmp_path / "cv.md").symlink_to("master_resume.md")
    (tmp_path / "master_resume.md").symlink_to("../outside.md")
    with pytest.raises(AnswerRefused, match="answer_sources_unavailable"):
        load_answer_sources(tmp_path)


def test_personal_facts_and_written_answers_are_filled_without_manual_fields(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    text = "# Example Candidate\nEmail: applicant@example.test\n## Experience\nReconciled invoices in Excel.\n"
    (profile / "cv.md").write_text(text)
    sources = load_answer_sources(profile, saved_path=tmp_path / "saved.json")
    digest = hashlib.sha256(text.encode()).hexdigest()
    questions = [
        {"key": "email", "question": "Email address", "type": "email", "required": True, "options": []},
        {"key": "motivation", "question": "Why are you suitable?", "type": "textarea", "required": True, "options": []},
    ]
    calls = []

    def runner(role, context, budget, llm):
        calls.append(role.name)
        if role.name == "prefill_answers":
            payload = {"answers": [
                {"key": "email", "value": "applicant@example.test", "source": "profile",
                 "citations": [{"source_id": "cv.md", "content_hash": digest, "quote": "applicant@example.test"}],
                 "question_to_owner": ""},
                {"key": "motivation", "value": "My invoice reconciliation experience in Excel fits this accounts role.",
                 "source": "agent_draft", "citations": [{"source_id": "cv.md", "content_hash": digest,
                 "quote": "Reconciled invoices in Excel."}], "question_to_owner": ""},
            ]}
        else:
            payload = {"approved": True, "checks": {"coverage": True, "factual_support": True,
                       "no_invented_personal_facts": True, "answers_job_questions": True}, "feedback": []}
        args = role.tools[-1].arguments_model.model_validate(payload)
        return SimpleNamespace(output=args)

    result = answer_application(questions, sources, job={"title": "Accounts Assistant", "company": "Example"},
                                budget=object(), llm=object(), reviewer=object(), runner=runner)
    assert result.complete
    assert result.fields["email"]["value"] == "applicant@example.test"
    assert result.fields["motivation"]["source"] == "agent_draft"
    assert calls == ["prefill_answers", "reviewer"]
    assert result.missing == ()
    assert all(len(row["source_hash"]) == 64 for row in result.fields.values())


def test_missing_fact_is_asked_once_and_reused(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "cv.md").write_text("# Example\n## Skills\nExcel\n")
    saved = tmp_path / "saved.json"
    save_owner_answer(saved, question="What is your earliest start date?", value="2026-11-02")
    sources = load_answer_sources(profile, saved_path=saved)
    assert "2026-11-02" in sources.texts["saved_answers"]
    assert saved.stat().st_mode & 0o777 == 0o600
    assert "2026-11-02" not in repr(sources)


def test_invalid_candidate_citation_fails_before_browser(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "cv.md").write_text("# Example\n## Skills\nExcel\n")
    sources = load_answer_sources(profile, saved_path=tmp_path / "saved.json")

    def runner(role, context, budget, llm):
        data = {"answers": [{"key": "name", "value": "Invented Name", "source": "profile",
                             "citations": [{"source_id": "cv.md", "content_hash": "a" * 64,
                                            "quote": "Invented Name"}], "question_to_owner": ""}]}
        return SimpleNamespace(output=role.tools[-1].arguments_model.model_validate(data))

    with pytest.raises(AnswerRefused, match="invalid_answer_evidence"):
        answer_application([{"key": "name", "question": "Name", "type": "text", "required": True}],
                           sources, job={}, budget=object(), llm=object(), reviewer=object(), runner=runner)


def test_questions_cannot_silently_disappear(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "cv.md").write_text("# Example\n## Skills\nExcel\n")
    sources = load_answer_sources(profile, saved_path=tmp_path / "saved.json")
    def runner(role, context, budget, llm):
        return SimpleNamespace(output=role.tools[-1].arguments_model.model_validate({"answers": []}))
    with pytest.raises(AnswerRefused, match="answer_coverage"):
        answer_application([{"key": "name", "question": "Name", "type": "text", "required": True}],
                           sources, job={}, budget=object(), llm=object(), reviewer=object(), runner=runner)


def test_no_approval_if_reviewer_omits_a_required_check(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "cv.md").write_text("# Example\n## Skills\nExcel\n")
    sources = load_answer_sources(profile, saved_path=tmp_path / "saved.json")
    def runner(role, context, budget, llm):
        data = {"answers": [{"key": "availability", "value": None, "source": "unknown",
                            "citations": [], "question_to_owner": "When can you start?"}]} if role.name == "prefill_answers" else {
                                "approved": True, "checks": {"coverage": True}, "feedback": []}
        return SimpleNamespace(output=role.tools[-1].arguments_model.model_validate(data))
    with pytest.raises(AnswerRefused, match="answer_review_failed"):
        answer_application([{"key": "availability", "question": "When can you start?", "type": "text", "required": True}],
                           sources, job={}, budget=object(), llm=object(), reviewer=object(), runner=runner)


def _answer_runner(sources, *, value, source="profile", source_id="cv.md"):
    def runner(role, context, budget, llm):
        data = {"answers": [{"key": "field", "value": value, "source": source,
                 "citations": [{"source_id": source_id, "content_hash": sources.hashes[source_id],
                                "quote": sources.texts[source_id]}], "question_to_owner": ""}]} \
            if role.name == "prefill_answers" else {
                "approved": True, "checks": dict.fromkeys(("coverage", "factual_support",
                    "no_invented_personal_facts", "answers_job_questions"), True), "feedback": []}
        return SimpleNamespace(output=role.tools[-1].arguments_model.model_validate(data))
    return runner


@pytest.mark.parametrize("typ,value,extra", [
    ("text", "   ", {}), ("select", [], {"multiple": True}),
    ("select", ["a", "b"], {}), ("checkbox", "true", {}),
    ("checkbox", False, {}), ("radio", True, {}),
    ("radio", "a", {"kind": "radio"}), ("email", ["person@example.test"], {}),
    ("select", ["a", "a"], {"multiple": True}),
])
def test_control_types_and_required_values_cannot_claim_false_completion(tmp_path, typ, value, extra):
    (tmp_path / "cv.md").write_text("Synthetic evidence a b person@example.test")
    sources = load_answer_sources(tmp_path)
    question = {"key": "field", "question": "Synthetic field", "type": typ, "required": True, **extra}
    with pytest.raises(AnswerRefused):
        answer_application([question], sources, job={}, budget=object(), llm=object(), reviewer=object(),
                           runner=_answer_runner(sources, value=value))


@pytest.mark.parametrize("typ,value,extra", [
    ("select", "a", {"options": [{"value": "a"}, {"value": "b"}]}),
    ("select", ["a", "b"], {"multiple": True, "options": [{"value": "a"}, {"value": "b"}]}),
    ("checkbox", False, {"required": False}), ("radio", True, {"kind": "radio"}),
])
def test_exact_supported_control_shapes_are_accepted(tmp_path, typ, value, extra):
    (tmp_path / "cv.md").write_text("Synthetic evidence a b")
    sources = load_answer_sources(tmp_path)
    result = answer_application([{"key": "field", "question": "Synthetic", "type": typ,
                                  "required": True, **extra}], sources, job={}, budget=object(), llm=object(),
                                reviewer=object(), runner=_answer_runner(sources, value=value))
    assert result.complete and result.fields["field"]["value"] == value


@pytest.mark.parametrize("source_id", ["career_ops_profile.md", "interests_and_criteria.yaml"])
def test_career_preferences_cannot_prove_qualifications_or_contact_facts(tmp_path, source_id):
    (tmp_path / source_id).write_text("I want to become a certified auditor")
    sources = load_answer_sources(tmp_path)
    with pytest.raises(AnswerRefused, match="framing_is_not_answer_evidence"):
        answer_application([{"key": "field", "question": "Do you hold the required qualification?", "type": "select",
                             "options": [{"value": "Yes"}, {"value": "No"}]}], sources,
                           job={}, budget=object(), llm=object(), reviewer=object(),
                           runner=_answer_runner(sources, value="Yes", source_id=source_id))


def test_agent_narrative_does_not_authorize_a_consent_or_contact_field(tmp_path):
    (tmp_path / "cv.md").write_text("Synthetic evidence")
    sources = load_answer_sources(tmp_path)
    for typ, value in (("checkbox", True), ("email", "invented@example.test")):
        with pytest.raises(AnswerRefused, match="answer_requires_explicit_fact"):
            answer_application([{"key": "field", "question": "Synthetic", "type": typ}], sources,
                               job={}, budget=object(), llm=object(), reviewer=object(),
                               runner=_answer_runner(sources, value=value, source="agent_draft"))


def test_legacy_verified_contact_records_and_groups_exclude_unverified_values(tmp_path):
    import json
    (tmp_path / "answers.yaml").write_text('''fields:
  availability:
    value: "2026-11-02"
    owner_verified: true
  salary:
    value: "not verified"
contact:
  email:
    value: "person@example.test"
    owner_verified: true
  phone:
    value: "unverified phone"
''')
    first = json.loads(load_answer_sources(tmp_path).texts["verified_answers"])
    assert first == {"fields.availability": "2026-11-02", "contact.email": "person@example.test"}
    (tmp_path / "answers.yaml").write_text('''contact:
  owner_verified: true
  email: "person@example.test"
  subscribe: false
''')
    second = json.loads(load_answer_sources(tmp_path).texts["verified_answers"])
    assert second == {"contact.email": "person@example.test", "contact.subscribe": False}


def test_simultaneous_owner_answers_preserve_every_answer_and_revision(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / "saved.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: save_owner_answer(path, question=f"Synthetic question {i}", value=f"Answer {i}"), range(12)))
    saved = json.loads(path.read_text())
    assert len(saved["answers"]) == 12
    assert len(list((tmp_path / "answer-history").glob("*.json"))) == 11
    assert path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".saved.json.lock").stat().st_mode & 0o777 == 0o600


def test_owner_answer_lock_refuses_symlinks(tmp_path):
    other = tmp_path / "other"
    other.write_text("untouched")
    (tmp_path / ".saved.json.lock").symlink_to(other)
    with pytest.raises(AnswerRefused, match="owner_answer_save_failed"):
        save_owner_answer(tmp_path / "saved.json", question="Synthetic?", value="Answer")
    assert other.read_text() == "untouched"


def test_actual_deepagents_reads_source_then_answers_and_gets_fresh_review(tmp_path):
    import json
    from jobwatch.util.llm import LLM
    from pipeline.agentic.runtime import BatchBudget, JobBudget
    (tmp_path / "cv.md").write_text("# Synthetic\nEmail: person@example.test\nReconciled ledgers in Excel.")
    sources = load_answer_sources(tmp_path)
    choices = iter([
        {"tool": "read_answer_source", "arguments": {"source_id": "cv.md"}},
        {"tool": "submit_answers", "arguments": {"answers": [
            {"key": "email", "value": "person@example.test", "source": "profile", "question_to_owner": "",
             "citations": [{"source_id": "cv.md", "content_hash": sources.hashes["cv.md"], "quote": "person@example.test"}]},
            {"key": "motivation", "value": "My ledger reconciliation in Excel fits this accounts role.",
             "source": "agent_draft", "question_to_owner": "", "citations": [{"source_id": "cv.md",
              "content_hash": sources.hashes["cv.md"], "quote": "Reconciled ledgers in Excel."}]},
        ]}},
        {"tool": "submit_answer_review", "arguments": {"approved": True,
         "checks": dict.fromkeys(("coverage", "factual_support", "no_invented_personal_facts", "answers_job_questions"), True),
         "feedback": []}},
    ])
    messages = []
    def transport(url, headers, body, timeout):
        messages.append(body["messages"])
        return 200, {"choices": [{"message": {"content": json.dumps(next(choices))}}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 10}}
    llm = LLM(transport=transport, keys=["synthetic-key"])
    budget = JobBudget("a" * 64, BatchBudget("answer-acceptance"))
    result = answer_application([
        {"key": "email", "question": "Email address", "type": "email", "required": True},
        {"key": "motivation", "question": "Why this role?", "type": "textarea", "required": True},
    ], sources, job={"title": "Accounts Assistant", "company": "Example"}, budget=budget, llm=llm, reviewer=llm)
    assert result.complete and len(messages) == 3
    assert budget.snapshot().role_turns["prefill_answers"] == 2
    assert budget.snapshot().role_turns["reviewer"] == 1
    assert '"tool_result": "read_answer_source"' in messages[1][-1]["content"]
    assert len(messages[2]) == 2  # Fresh independent reviewer, no writer tool transcript.
    assert "person@example.test" not in repr(result)
