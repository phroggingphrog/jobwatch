import json

from jobwatch.util.llm import LLM
from pipeline.agentic.persistence import latest_result
from pipeline.agentic.service import run_agentic_job
from pipeline.schemas import Stage
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401
from pipeline.agentic.contracts import AgenticError


def test_partial_capture_evaluates_and_persists_audit(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    from pipeline.agentic import service
    capture = service._capture
    monkeypatch.setattr(service, '_capture', lambda conn, pid: (*capture(conn, pid)[:2], 'partial'))
    monkeypatch.setattr(service.PersistenceAdapter, 'record_observation', lambda *a: False)
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    stage = run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    result = latest_result(conn, 42)
    assert stage == Stage.DLQ, result
    assert result['reason'] == 'evaluation_complete', result
    assert result['evaluation']['global_score'] == 4.3
    assert result['assessment_audit']['completeness'] == 'partial'
    assert 'incomplete_capture' in result['assessment_audit']['unknowns']
    assert 'complete_job_assessment' in gateway.calls


def test_partial_capture_injection_hold(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    from pipeline.agentic import service
    capture = service._capture
    monkeypatch.setattr(service, '_capture', lambda conn, pid: (*capture(conn, pid)[:2], 'partial'))
    monkeypatch.setattr(service.PersistenceAdapter, 'record_observation', lambda *a: False)
    monkeypatch.setattr(service, 'jev_screen', lambda *a, **kw: {'injection': 1.0})
    monkeypatch.setattr(service, 'extras_settings', lambda *a: {'knockout_at': {}, 'jev_hold_at': 0.5})
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=object(), operation='evaluate') == Stage.DLQ
    assert latest_result(conn, 42)['reason'] == 'ad_has_ai_instructions'


def test_bad_evaluator_citation_retains_assessment_as_unverified(world):
    conn, config, bundle, add = world
    add(42)
    gateway = SyntheticGateway(bundle)
    def transport(url, headers, body, timeout):
        status, response = gateway(url, headers, body, timeout)
        message = response.get('choices', [{}])[0].get('message', {})
        if 'content' in message:
            payload = json.loads(message['content'])
            if payload.get('tool') == 'complete_requirements':
                payload['arguments']['requirements']['requirements'][0]['jd_signal']['quote'] = 'not in the ad'
                message['content'] = json.dumps(payload)
        return status, response
    llm = LLM(transport=transport, keys=['synthetic'])
    run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    result = latest_result(conn, 42)
    assert result['reason'] == 'evaluation_complete', result
    assert 'requirement_citation_unverified' in result['assessment_audit']['unknowns']
    assert result['assessment_audit']['completeness'] == 'partial'


def test_invalid_evaluation_retains_safe_partial(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    from pipeline.agentic import service
    def invalid(*args, **kwargs):
        raise AgenticError('model_invalid_response')
    monkeypatch.setattr(service, 'evaluate_job', invalid)
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate') == Stage.DLQ
    result = latest_result(conn, 42)
    assert result['evaluation'] is None
    partial = result['partial_assessment']['assessment_decision']
    assert partial['fit_score'] is None
    assert partial['errors'] == ['model_invalid_response']
    assert partial['recommendation'] == 'retry'
    assert partial['completeness'] == 'unavailable'
