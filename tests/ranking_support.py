"""Validator-correct synthetic ranking inputs; no candidate records or I/O."""
from hashlib import sha256
from types import SimpleNamespace

from pipeline.agentic.contracts import (
    AgenticEvaluation, Dimension, EvidenceJudgment, Requirement, RequirementMatch,
    RequirementSet, RunKey, SourceCitation,
)
from pipeline.schemas import JobFacts, WorkRights


def make_evaluation(spec, *, blockers=(), legacy=(), posting_id=1, score=4.0,
                    north_star=4.0, hours='part_time_ok', open_questions=None):
    ad_text = '\n'.join(f'Requirement {rid}' for rid, _, _ in spec) or 'Synthetic opening'
    ad_hash = sha256(ad_text.encode()).hexdigest()
    evidence_text = '\n'.join(f'Approved primary evidence for {rid}.' for rid, _, _ in spec)
    evidence_hash = sha256(evidence_text.encode()).hexdigest()
    requirements, matches = [], []
    for rid, importance, status in spec:
        citation = SourceCitation(source_id='master_resume.md', content_hash=evidence_hash,
                                  quote=f'Approved primary evidence for {rid}.')
        requirements.append(Requirement(id=rid, text=f'Requirement {rid}', importance=importance,
            tier='stated', blocker=rid in blockers,
            jd_signal=SourceCitation(source_id='ad', content_hash=ad_hash, quote=f'Requirement {rid}')))
        judgment = None if rid in legacy else EvidenceJudgment(status=status,
            rationale=f'Synthetic {status} assessment.', reviewed_evidence_ids=(f'evidence-{rid}',),
            contradiction_evidence=(citation,) if status == 'contradicted' else (),
            open_question=(open_questions or {}).get(rid, f'Can you clarify {rid}?')
            if status in ('partial', 'unknown', 'contradicted') else '')
        matches.append(RequirementMatch(requirement_id=rid,
            match={'demonstrated':'strong', 'partial':'partial', 'unknown':'missing',
                   'contradicted':'missing', 'not_applicable':'not_applicable'}[status],
            evidence=(citation,) if status in ('demonstrated', 'partial') else (),
            judgment=judgment, risk='Synthetic gap risk.', mitigation='Ask for primary evidence.'))
    return AgenticEvaluation(
        run_key=RunKey(posting_id=posting_id, ad_hash=ad_hash, evidence_hash=evidence_hash,
                       config_hash='c'*64, rubric_version='synthetic-ranking-v1'),
        requirements=RequirementSet(ad_hash=ad_hash, requirements=tuple(requirements)),
        matches=tuple(matches), archetype='synthetic', global_score=score,
        dimensions={name: Dimension(score=north_star if name == 'north_star' else score,
                                    reason='Synthetic dimension.')
                    for name in ('cv_match','north_star','compensation','culture','red_flags')},
        facts=JobFacts(real_job=True, role_family='other', duties=['Prepare reports'],
            required_skills=['Report preparation'], preferred_skills=[], seniority='junior',
            min_years=1, hours=hours, program=False,
            work_rights=WorkRights(requirement='none_stated', quote=''), screening_questions=[]),
        location_fit='unknown', legitimacy='verified', research_available=False,
        report={name:'Synthetic report.' for name in 'ABCDEFG'}, screening_questions=())


def policy_stub(strategy='employment_first', focus=(), open_questions=()):
    return SimpleNamespace(strategy=strategy, focus=focus, open_questions=open_questions,
        regions=(), remote_ok=None, profile_version=1, policy_hash='d'*64)


def relevance_stub(relevant='yes', similarity=0.5, matched=()):
    return SimpleNamespace(relevant=relevant, similarity=similarity, matched_hypotheses=matched)
