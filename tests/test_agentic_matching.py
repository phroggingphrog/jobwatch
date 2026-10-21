"""Offline matching automation: no provider credentials or personal records."""
import copy
import json

import pytest

from jobwatch import model_choice
from jobwatch.llm import LLM
from pipeline.agentic.contracts import AgenticError, AgenticGateDecision
from pipeline.agentic.evaluation import blind_matching_packet, compare_matching_runs
from pipeline.agentic.execution import QWEN_EMBEDDING_MODEL, require_route
from pipeline.agentic.gateway import PaidGatewayEmbeddings
from pipeline.agentic.runtime import BatchBudget, JobBudget
from test_agentic_gate import evaluation  # shared synthetic fixture


def test_qwen_query_instructions_and_budget_use_one_explicit_route():
    calls = []
    def transport(url, headers, body, timeout):
        calls.append((url, body))
        return 200, {'data': [{'index': i, 'embedding': [1.0, 0.0]} for i in range(len(body['input']))],
                     'usage': {'prompt_tokens': 7}}
    llm = LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)
    job = JobBudget('a'*64, BatchBudget('embedding-fixture'))
    adapter = PaidGatewayEmbeddings(llm, QWEN_EMBEDDING_MODEL, job)
    assert adapter.embed_queries(['reconcile accounts']) == [[1.0, 0.0]]
    assert calls[0][1]['input'][0].startswith('Instruct: ')
    assert '\nQuery:reconcile accounts' in calls[0][1]['input'][0]
    adapter.embed_documents(['Exact evidence text'])
    assert calls[1][1]['input'] == ['Exact evidence text']
    assert all(url.endswith('/embeddings') and body['model'] == QWEN_EMBEDDING_MODEL for url, body in calls)
    assert job.charged_tokens == 14
    with pytest.raises(AgenticError, match='model_not_allowed'):
        require_route(llm, QWEN_EMBEDDING_MODEL)
    with pytest.raises(AgenticError, match='model_not_allowed'):
        PaidGatewayEmbeddings(llm, QWEN_EMBEDDING_MODEL + ':free', job)


@pytest.mark.parametrize('vector', [[0.0, 0.0], [float('nan'), 1.0], []])
def test_invalid_vectors_fail_without_retry_and_retain_charge(vector):
    calls = []
    def transport(*args):
        calls.append(1)
        return 200, {'data': [{'index': 0, 'embedding': vector}]}
    llm = LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)
    job = JobBudget('b'*64, BatchBudget('invalid-embedding-fixture'))
    with pytest.raises(AgenticError, match='embedding_invalid_response'):
        PaidGatewayEmbeddings(llm, QWEN_EMBEDDING_MODEL, job).embed_query('synthetic task')
    assert len(calls) == 1 and job.charged_tokens > 0


def matching_case(evaluation):
    prediction = {'evaluation': evaluation.model_dump(mode='json'),
        'decision': AgenticGateDecision(route='archive', reason='score_below_threshold',
            global_score=2, run_key=evaluation.run_key).model_dump(mode='json'),
        'latency_seconds': 1.0, 'charged_tokens': 100, 'actual_tokens': None}
    return {'case_id': 'synthetic-case', 'group_id': 'synthetic-company', 'split': 'holdout',
            'predictions': {'baseline-version': prediction, 'revised-version': copy.deepcopy(prediction)}}


def test_unlabeled_comparison_never_claims_quality(evaluation):
    case = matching_case(evaluation)
    result = compare_matching_runs([case])
    assert result['status'] == 'owner_holdout_labels_required'
    packet, key = blind_matching_packet([case], seed=42)
    assert 'baseline-version' not in json.dumps(packet) and 'revised-version' not in json.dumps(packet)
    assert set(key['case-1']['arms'].values()) == {'baseline-version', 'revised-version'}
    assert packet['cases'][0]['review']['suitable'] is None


def test_reviewed_comparison_counts_archived_suitable_jobs_and_missing_usage(evaluation):
    case = matching_case(evaluation)
    case['review'] = {'actor': 'owner', 'suitable': True, 'requirement_status': {}}
    result = compare_matching_runs([case])
    arm = result['reports']['holdout']['arms']['baseline-version']
    assert arm['false_exclusions'] == 1 and arm['suitable_cases'] == 1
    assert arm['unknown_usage_cases'] == 1
    assert result['status'] == 'descriptive_comparison'
    # Imported attribution is explicitly not authentication or promotion evidence.
    assert 'not authentication' in result['limits']


def test_comparison_rejects_group_leakage_and_snapshot_mismatch(evaluation):
    case = matching_case(evaluation)
    duplicate = copy.deepcopy(case)
    duplicate.update(case_id='second-case', split='development')
    with pytest.raises(AgenticError, match='comparison_split_leakage'):
        compare_matching_runs([case, duplicate])
    case['predictions']['revised-version']['evaluation']['run_key']['evidence_hash'] = 'e'*64
    with pytest.raises(AgenticError, match='comparison_identity_mismatch'):
        compare_matching_runs([case])
