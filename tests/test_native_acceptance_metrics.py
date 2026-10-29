"""Acceptance diagnostics distinguish provider quality, cost and runtime readiness."""
import pytest

from pipeline.agentic.eval_metrics import native_acceptance_report


def inputs():
    return dict(usage={'model_calls': 5, 'actual_tokens': 80, 'charged_tokens': 90, 'unknown_usage_calls': 1},
        native_counts={'calls': 4, 'purposes': {'requirements': 1, 'evidence_matching': 1,
            'evaluation': 1, 'evidence_embeddings': 1}, 'prompt_tokens': 50, 'completion_tokens': 25,
            'details': [{'completion_tokens_details': {'reasoning_tokens': 5},
                'prompt_tokens_details': {'cached_tokens': 30}, 'private': 'never copy'}]},
        digest_counts={'calls': 0, 'charged_tokens': 0, 'reused': True,
            'cold': {'calls': 12, 'tokens': 147776, 'charged_tokens': 147776}},
        classifier_calls=1, checks={key: True for key in (
            'canonical_evaluation', 'coverage', 'citations', 'judgments', 'gate', 'identity', 'protocol', 'digest_current')},
        gate_route='hold', ledger_charged=90, seconds=7.5,
        resume_usage={'model_calls': 0, 'charged_tokens': 0, 'actual_tokens': 0, 'unknown_usage_calls': 0})


def test_held_gate_can_be_valid_acceptance_without_claiming_application_ready():
    result = native_acceptance_report(**inputs())
    assert result['accepted'] is True and result['quality']['gate_route'] == 'hold'
    assert result['efficiency']['per_job_model_calls'] == 4
    assert result['paid_operations'] == {'native_model': 3, 'classifier_model': 1,
        'embedding': 1, 'digest_model': 0, 'other_model': 0, 'total': 5}
    assert result['tokens']['charged'] == 90 and result['tokens']['known_actual'] == 80
    assert result['tokens']['reasoning'] == 5 and result['tokens']['cached_prompt'] == 30
    assert result['digest']['new_calls'] == 0 and result['digest']['historical_cold_calls'] == 12
    assert 'never copy' not in str(result) and 'ready' not in result


def test_failed_provider_never_passes_from_low_counts():
    args = inputs();args['checks']['canonical_evaluation'] = False;args['gate_route'] = None
    result = native_acceptance_report(**args)
    assert result['quality']['passed'] is False and result['accepted'] is False


def test_cached_evaluation_plus_classifier_and_embedding_is_not_provider_acceptance():
    args = inputs();args['usage']['model_calls'] = 2
    args['native_counts']['calls'] = 1
    args['native_counts']['purposes'] = {'evidence_embeddings': 1}
    result = native_acceptance_report(**args)
    assert result['quality']['passed'] is False and result['accepted'] is False


def test_classifier_counts_in_efficiency_target_without_changing_runtime_limits():
    args = inputs();args['usage']['model_calls'] = 8;args['native_counts']['calls'] = 7
    result = native_acceptance_report(**args)
    assert result['quality']['passed'] is True and result['efficiency']['passed'] is False
    assert result['efficiency']['per_job_model_calls'] == 7 and result['accepted'] is True


@pytest.mark.parametrize('change', ['missing_check', 'ledger', 'paid_reuse', 'unverified_reuse',
                                  'unattributed', 'cold_digest', 'unverified_digest_reuse'])
def test_incomplete_acceptance_evidence_cannot_activate(change):
    args = inputs()
    if change == 'missing_check': del args['checks']['citations']
    if change == 'ledger': args['ledger_charged'] = 89
    if change == 'paid_reuse': args['resume_usage']['model_calls'] = 1
    if change == 'unverified_reuse': args['resume_usage'] = None
    if change == 'unattributed': args['usage']['model_calls'] += 1
    if change == 'cold_digest':
        args['digest_counts']['calls'] = 1;args['digest_counts']['reused'] = False
    if change == 'unverified_digest_reuse': args['digest_counts']['reused'] = False
    result = native_acceptance_report(**args)
    assert result['accepted'] is False
    if change == 'unverified_digest_reuse':
        assert result['quality']['passed'] is True and result['accounting']['reconciled'] is True


@pytest.mark.parametrize('field', ['ledger_charged', 'classifier_calls'])
def test_nonnumeric_metadata_is_rejected_instead_of_copied(field):
    args = inputs();args[field] = {'private': 'not a count'}
    with pytest.raises(ValueError, match='invalid_acceptance_counts'):
        native_acceptance_report(**args)
