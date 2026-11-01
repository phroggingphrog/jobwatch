import pytest

from pipeline.agentic.contracts import SourceCitation
from pipeline.agentic.gate import assessment_audit, decide
from tests.candidate.policy_fixtures import fact, policy_of
from tests.test_agentic_gate import AD, evaluation, policy  # noqa: F401
from tests.test_agentic_gate_policy import job


@pytest.mark.parametrize('citation', ['missing', 'bad_quote'])
def test_requirement_citation_gap_is_advisory(evaluation, policy, citation):
    signal = None if citation == 'missing' else SourceCitation(
        source_id='ad', content_hash=evaluation.run_key.ad_hash, quote='not in the advertisement')
    ev = evaluation.model_copy(update={'location_evidence': signal})
    decision = decide(ev, ad_text=AD, policy=policy)
    audit = assessment_audit(ev, ad_text=AD, decision=decision)
    assert decision.route == 'draft'
    assert 'location_citation_unverified' in audit.unknowns
    assert audit.completeness == 'partial'


def test_incomplete_capture_and_ad_provenance_are_advisory(evaluation, policy):
    decision = decide(evaluation, ad_text=AD + ' updated', policy=policy, captured_complete=False)
    audit = assessment_audit(evaluation, ad_text=AD + ' updated', captured_complete=False, decision=decision)
    assert decision.route == 'draft'
    assert {'incomplete_capture', 'ad_provenance_mismatch'} <= set(audit.unknowns)


def test_bad_rights_quote_cannot_mask_known_conflict(evaluation, policy):
    ad = 'Accounting analyst. Australian citizens only.'
    ev = job(evaluation, ad, quote='Accounting', work_rights={
        'requirement': 'citizen_only', 'quote': 'not present'})
    dp = policy_of(fact('work_rights', {'citizen': False}))
    decision = decide(ev, ad_text=ad, policy=policy, decision_policy=dp, captured_complete=False)
    assert (decision.route, decision.reason) == ('archive', 'hard_gate')
    assert assessment_audit(ev, ad_text=ad, captured_complete=False, decision=decision).recommendation == 'exclude'


def test_wrong_run_identity_stays_blocked(evaluation, policy):
    other = evaluation.run_key.model_copy(update={'posting_id': 124})
    assert decide(evaluation, ad_text=AD, policy=policy, expected_run_key=other).route == 'hold'
