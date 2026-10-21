"""Prepare a conservative form map from validated screening answers."""
from __future__ import annotations

from jobwatch.candidate.evidence import verify_evidence_snapshot
from pipeline.agentic.contracts import AgenticError, AgenticEvaluation, AgenticScreeningAnswer, validate_citations
from pipeline.schemas import FormField, FormMap


def validate_screening_answers(evaluation: AgenticEvaluation, answers, *, evidence_bundle=None):
    """Resolve source citations to their primary snapshot, allowing supported paraphrases."""
    if type(evaluation) is not AgenticEvaluation or type(answers) is not tuple:
        raise AgenticError("invalid_form_map_input")
    checked = []
    try:
        sources = {}
        if any(item.source == "evidence" for item in answers):
            verify_evidence_snapshot(evidence_bundle)
            if evidence_bundle.bundle_hash != evaluation.run_key.evidence_hash:
                raise ValueError
            sources = {name: (evidence_bundle.sources[name], raw.decode("utf-8"))
                       for name, raw in evidence_bundle.contents.items()
                       if name in ("cv.md", "master_resume.md", "profile.yaml")}
        for answer in answers:
            item = answer if type(answer) is AgenticScreeningAnswer else AgenticScreeningAnswer.model_validate(answer)
            checked.append(item)
        if len(checked) > len(evaluation.screening_questions):
            raise ValueError
        for idx, item in enumerate(checked):
            if item.question != evaluation.screening_questions[idx]:
                raise ValueError
            if item.source == "evidence":
                if not item.citations:
                    raise ValueError
                validate_citations(item.citations, sources)
    except Exception:
        raise AgenticError("invalid_screening_answer") from None
    return checked


def build_form_map(evaluation: AgenticEvaluation, answers, *, evidence_bundle=None,
                   application_id=None, url="") -> FormMap:
    checked = validate_screening_answers(evaluation, answers, evidence_bundle=evidence_bundle)
    fields = []
    for idx, question in enumerate(evaluation.screening_questions):
        answer = checked[idx] if idx < len(checked) else None
        if answer is None or answer.source == "owner_to_answer":
            fields.append(FormField(field=f"Q: {question[:110]}", value="", source="owner_to_answer"))
        else:
            fields.append(FormField(field=f"Q: {question[:110]}", value=answer.answer, source="evidence"))
    return FormMap(posting_id=evaluation.run_key.posting_id,
                   application_id=application_id if application_id is not None else evaluation.run_key.posting_id,
                   url=url, fields=fields, owner_to_answer=sum(f.source == "owner_to_answer" for f in fields))
