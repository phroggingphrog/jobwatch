"""Synthetic frozen-case builder for baseline tests. No real candidate data."""
from __future__ import annotations

import hashlib
import sqlite3
import types

import pytest

from jobwatch.llm import LLM
from pipeline.agentic import baseline
from pipeline.agentic.contracts import (
    AgenticEvaluation, AgenticGateDecision, Dimension, EvidenceJudgment, Requirement, RequirementMatch,
    RequirementSet, RunKey, SourceCitation,
)
from pipeline.agentic.service import agentic_batch_run
from pipeline.schemas import JobFacts
from tests.test_agentic_service import SyntheticGateway, world as _source_world  # noqa: F401

AD = (
    "Graduate accounting analyst role based in Melbourne. Hybrid attendance with two days "
    "in the Melbourne office. Part-time, 24 hours per week. Australian work rights required."
)
AD_HASH = hashlib.sha256(AD.encode("utf-8")).hexdigest()
_RESUME_HASH = "3" * 64


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Use an invented reference for baseline persistence, retaining a large blob.

    These checks test freezing and replay, not the shipped occupation dataset.
    JSON whitespace gives the reference a realistic shared-artifact size without
    rebuilding thousands of unrelated occupation models for every freeze.
    """
    from tests.candidate.fixtures import fictional_reference
    source = _source_world.__wrapped__(tmp_path, monkeypatch)
    reference = fictional_reference(tmp_path)
    reference.write_bytes(reference.read_bytes() + b'\n' + b' ' * 220_000)
    source[1].settings['pipeline']['agentic']['occupation_reference_path'] = str(reference)
    return source


def _match(requirement_id: str, status: str) -> RequirementMatch:
    cited = (SourceCitation(source_id="master_resume.md", content_hash=_RESUME_HASH, quote="synthetic evidence"),)
    ad_quote = SourceCitation(source_id="ad", content_hash=AD_HASH, quote="Melbourne office")
    reviewed = ("master_resume.md",)
    if status == "demonstrated":
        return RequirementMatch(
            requirement_id=requirement_id, match="strong", evidence=cited,
            judgment=EvidenceJudgment(status="demonstrated", rationale="synthetic", reviewed_evidence_ids=reviewed))
    if status == "partial":
        return RequirementMatch(
            requirement_id=requirement_id, match="partial", evidence=cited, risk="r", mitigation="m",
            judgment=EvidenceJudgment(status="partial", rationale="synthetic", reviewed_evidence_ids=reviewed,
                                      open_question="q"))
    if status == "unknown":
        return RequirementMatch(
            requirement_id=requirement_id, match="missing", evidence=(), risk="r", mitigation="m",
            judgment=EvidenceJudgment(status="unknown", rationale="synthetic", reviewed_evidence_ids=reviewed,
                                      open_question="q"))
    if status == "contradicted":
        return RequirementMatch(
            requirement_id=requirement_id, match="missing", evidence=(), risk="r", mitigation="m",
            judgment=EvidenceJudgment(status="contradicted", rationale="synthetic", reviewed_evidence_ids=reviewed,
                                      contradiction_evidence=(ad_quote,), open_question="q"))
    if status == "legacy_missing":
        return RequirementMatch(requirement_id=requirement_id, match="missing", evidence=(), risk="r", mitigation="m")
    raise ValueError(f"unknown synthetic status {status!r}")


def synthetic_case(case_id: str = "c-1", *, posting_id: int = 1, title: str = "Junior Analyst",
                   company: str = "Synthetic Alpha", requirements=(("r1", "high", "demonstrated"),),
                   seniority: str = "junior", min_years: int | None = None, location_fit: str = "melbourne",
                   uncertainties=(), route: str = "draft", reason: str = "eligible", stored=None,
                   group_keys=()) -> baseline.FrozenCase:
    run_key = RunKey(posting_id=posting_id, ad_hash=AD_HASH, evidence_hash="1" * 64,
                     rubric_version="test", config_hash="2" * 64)
    ad_quote = SourceCitation(source_id="ad", content_hash=AD_HASH, quote="Melbourne office")
    stated = tuple(
        Requirement(id=rid, text=f"synthetic requirement {rid}", tier="stated", importance=importance,
                    jd_signal=ad_quote)
        for rid, importance, _ in requirements)
    evaluation = AgenticEvaluation(
        run_key=run_key, requirements=RequirementSet(ad_hash=AD_HASH, requirements=stated),
        matches=tuple(_match(rid, status) for rid, _, status in requirements),
        archetype="graduate accounting", global_score=4.0,
        dimensions={name: Dimension(score=4.0, reason="synthetic") for name in
                    ("cv_match", "north_star", "compensation", "culture", "red_flags")},
        facts=JobFacts(
            real_job=True, role_family="Accounting", duties=["reconcile accounts"],
            required_skills=[], preferred_skills=[], seniority=seniority, min_years=min_years,
            hours="part_time_ok", program=True,
            work_rights={"requirement": "none_stated", "quote": ""}, screening_questions=[]),
        location_fit=location_fit, location_evidence=ad_quote, legitimacy="verified",
        research_available=False, report={k: "synthetic" for k in "ABCDEFG"}, screening_questions=(),
        matching_diagnostics={"ad_uncertainties": list(uncertainties)} if uncertainties else None)
    decision = AgenticGateDecision(route=route, reason=reason, global_score=4.0, run_key=run_key)
    keys = tuple(group_keys) or (f"content:{AD_HASH}",)
    return baseline.FrozenCase(
        case_id=case_id, posting_id=posting_id, group_id=baseline.group_ids({case_id: keys})[case_id],
        tags=(), run_key=run_key.value, group_keys=tuple(group_keys),
        snapshot={"run_key": run_key.value,
                  "posting": {"title": title, "company": company, "location": "Melbourne VIC",
                              "url": f"https://example.invalid/jobs/{posting_id}", "source": "synthetic"},
                  "full_ad": AD, "text_kind": "full", "sources": {}, "contents": {}},
        structural_inputs={}, evaluation=evaluation.model_dump(mode="json"), candidate=None, model_insights=None,
        decision=decision.model_dump(mode="json"), commute_km=None,
        usage={"charged_tokens": 100, "actual_tokens": None, "latency_seconds": 1.0},
        stored=dict(stored or {}))


@pytest.fixture
def frozen(world, monkeypatch):
    """Three evaluated synthetic postings (42 and 43 share an employer, 44 has a low advisory score) behind a read-only
    connection. After the batch, every model call fails the test."""
    conn, config, bundle, add = world
    add(42)
    add(43, 'Synthetic Alpha Pty Ltd')
    add(44, 'Synthetic Beta', low=True)
    gateway = SyntheticGateway(bundle)
    agentic_batch_run([42, 43, 44], config, conn, evidence_bundle=bundle,
                      llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate')
    conn.commit()
    ro = sqlite3.connect(f'file:{config.db_path}?mode=ro', uri=True)
    ro.row_factory = sqlite3.Row

    def refuse(*args, **kwargs):
        raise AssertionError('the freeze must not call a model')

    for name in ('chat_once', 'chat', 'embed_once'):
        monkeypatch.setattr(LLM, name, refuse)
    yield types.SimpleNamespace(conn=conn, ro=ro, config=config, bundle=bundle, gateway=gateway, add=add)
    ro.close()
