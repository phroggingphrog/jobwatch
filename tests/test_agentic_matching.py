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
from pipeline.agentic.matching import EvidenceSearch, EvidenceSearchBatch, RequirementEvidenceSearch
from pipeline.agentic.contracts import Requirement, RequirementSet
from pipeline.agentic.contracts import SourceCitation
from jobwatch.candidate.evidence import snapshot_evidence
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


@pytest.mark.parametrize('model', ['deepseek-flash', 'deepseek-flash-fast', 'openai/luna', 'distiller', 'automated-model', 'my-paid-combo'])
def test_owner_approved_paid_combos_use_only_the_configured_gateway(model):
    from pipeline.agentic import chat
    llm = LLM(keys=['synthetic'], base_url=model_choice.SERVER_URL)
    require_route(llm, model)
    chat._route(llm, model)
    other = LLM(keys=['synthetic'], base_url='https://unapproved.example/v1')
    with pytest.raises(AgenticError, match='gateway_not_allowed'):
        require_route(other, model)


@pytest.mark.parametrize('model', ['deepseek-flash:free', 'deepseek-flash/free',
                                  'free-stack', 'stealth-stack', '../bad-model', '', 'openai/astra', 'claude/opus'])
def test_configured_combo_names_preserve_denied_route_boundaries(model):
    llm = LLM(keys=['synthetic'], base_url=model_choice.SERVER_URL)
    with pytest.raises(AgenticError, match='model_not_allowed'):
        require_route(llm, model)


def test_chat_combo_exception_does_not_authorise_embeddings():
    llm = LLM(keys=['synthetic'], base_url=model_choice.SERVER_URL)
    with pytest.raises(AgenticError, match='model_not_allowed'):
        require_route(llm, 'deepseek-flash', embedding=True)


def test_batch_search_matches_individual_searches_and_reads_shared_records_once(tmp_path):
    (tmp_path / "cv.md").write_text("# Synthetic\n- Reconciled ledgers and reconciled reports\n")
    bundle = snapshot_evidence(tmp_path)
    requirements = RequirementSet(ad_hash="a" * 64, requirements=(
        Requirement(id="r1", text="Reconciled ledgers", tier="stated", importance="high",
                    jd_signal=SourceCitation(source_id="ad", content_hash="a"*64, quote="Reconciled ledgers")),
        Requirement(id="r2", text="Reconciled reports", tier="stated", importance="high",
                    jd_signal=SourceCitation(source_id="ad", content_hash="a"*64, quote="Reconciled reports")),
    ))
    queries = (EvidenceSearch(requirement_id="r1"), EvidenceSearch(requirement_id="r2"))
    batch = RequirementEvidenceSearch(bundle, requirements)
    result = batch.search_many(EvidenceSearchBatch(queries=queries))
    individual = RequirementEvidenceSearch(bundle, requirements)
    singles = [individual.search(query) for query in queries]
    assert [search["hits"] for search in result["searches"]] == [single["hits"] for single in singles]
    assert result["hits_by_requirement"] == {search["requirement_id"]: search["hits"] for search in result["searches"]}
    expected = {item["id"]: item for single in singles for item in single["items"]}
    assert {item["id"]: item for item in result["items"]} == expected
    assert len(result["items"]) == len({item["id"] for item in result["items"]})
    assert batch.accessed == individual.accessed
    assert batch.searches == individual.searches


@pytest.mark.parametrize("queries,error", [
    ((EvidenceSearch(requirement_id="r1"), EvidenceSearch(requirement_id="r1")), "invalid_search"),
    ((EvidenceSearch(requirement_id="missing"), EvidenceSearch(requirement_id="r1")), "unknown_requirement"),
])
def test_invalid_batch_search_is_rejected_before_any_evidence_access(tmp_path, queries, error):
    (tmp_path / "cv.md").write_text("# Synthetic\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(tmp_path)
    requirements = RequirementSet(ad_hash="a" * 64, requirements=(
        Requirement(id="r1", text="Reconciled ledgers", tier="stated", importance="high",
                    jd_signal=SourceCitation(source_id="ad", content_hash="a"*64, quote="Reconciled ledgers")),))
    retrieval = RequirementEvidenceSearch(bundle, requirements)
    with pytest.raises(AgenticError, match=error):
        retrieval.search_many(EvidenceSearchBatch(queries=queries))
    assert retrieval.accessed == set() and retrieval.searches == []


def test_model_catalog_labels_paid_bare_combo_without_losing_other_options(monkeypatch):
    from pipeline.agentic import client_api, service
    llm = LLM(keys=['synthetic'], base_url=model_choice.SERVER_URL)
    monkeypatch.setattr(service, 'configured_llm', lambda config: llm)
    monkeypatch.setattr(model_choice, 'chosen', lambda person: {})
    client_api._MODEL_CATALOG.clear()
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'data': [{'id': x} for x in ['openai/sol', 'deepseek-flash', 'openai/luna', 'free-stack']]}
    monkeypatch.setattr('requests.Session.get', lambda *args, **kwargs: Response())
    catalog = client_api.model_catalog('synthetic-catalog', {'chat': {'model': 'openai/sol'}})
    assert catalog['catalog_available'] is True
    assert {row['id'] for row in catalog['options']} == {'openai/sol', 'deepseek-flash', 'openai/luna'}
    assert next(row for row in catalog['options'] if row['id'] == 'deepseek-flash') == {
        'id': 'deepseek-flash', 'label': 'Deepseek Flash', 'provider': 'OmniRoute'}
