"""Bounded synthetic deadline and first-failure scenarios; no live account or network."""
import time
from types import SimpleNamespace

import pytest

from pipeline.agentic import incidents, service
from pipeline.nodes import ingest
from tests.test_agentic_service import world  # noqa: F401


def test_expired_invocation_never_ingests_or_charges(world, monkeypatch):
    conn, config, _, add = world
    add(42)
    monkeypatch.setattr(ingest, 'run', lambda *a, **k: pytest.fail('Expired invocation ingested'))
    result = service.after_collect(conn, config, max_seconds=600, deadline=time.time()-1)
    assert result['deferred'] == 'batch_deadline'
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone() is None
    assert incidents.list_incidents(conn) == []


def test_ingestion_elapsed_time_cannot_renew_assessment_deadline(world, monkeypatch):
    conn, config, _, add = world
    add(42)
    clock = [time.time()]
    monkeypatch.setattr(service.time, 'time', lambda: clock[0])
    def slow_ingest(*args, **kwargs):
        assert kwargs['deadline'] == clock[0]+10
        clock[0] += 11
    monkeypatch.setattr(ingest, 'run', slow_ingest)
    monkeypatch.setattr(service, 'agentic_batch_run', lambda *a, **k: pytest.fail('Deadline renewed'))
    result = service.after_collect(conn, config, max_seconds=10)
    assert result['deferred'] == 'batch_deadline'
    assert 'ingestion' in result['phase_seconds']
    assert incidents.list_incidents(conn) == []


def test_unstarted_batch_jobs_stay_uncharged_and_unpaused(world, monkeypatch):
    conn, config, bundle, add = world
    add(42); add(43)
    monkeypatch.setattr(service, 'run_agentic_job', lambda *a, **k: pytest.fail('Too little time to start'))
    result = service.agentic_batch_run([42, 43], config, conn, evidence_bundle=bundle,
                                      max_seconds=600, deadline=time.time()+1)
    assert result['skipped_reasons'] == {'batch_deadline': 2}
    assert result['charged_tokens'] == 0
    assert incidents.list_incidents(conn) == []


def test_paused_job_is_skipped_while_unrelated_job_is_attempted(world, monkeypatch):
    from pipeline.schemas import Stage
    conn, config, bundle, add = world
    add(42); add(43)
    incidents.report(conn, posting_id=42, run_id='failed-attempt', reason='deadline_exceeded', phase='assessment')
    called = []
    real = service.run_agentic_job
    def attempt(pid, *args, **kwargs):
        if pid == 42:
            return real(pid, *args, **kwargs)
        called.append(pid)
        return Stage.ARCHIVED
    monkeypatch.setattr(service, 'run_agentic_job', attempt)
    result = service.agentic_batch_run([42, 43], config, conn, evidence_bundle=bundle)
    assert result['skipped_reasons'] == {'paused_error': 1}
    assert result['archived'] == 1 and called == [43]


def test_collector_budget_does_not_invent_minimum_time(monkeypatch):
    from jobwatch import pipeline
    monkeypatch.setattr(pipeline.time, 'monotonic', lambda: 1000.)
    assert pipeline.ai_budget(0.) == 0


def test_collector_http_refuses_requests_after_deadline(monkeypatch):
    from jobwatch.util.http import Fetcher, Blocked
    fetcher = Fetcher(deadline=time.time()-1)
    monkeypatch.setattr(fetcher.session, 'request', lambda *a, **kw: pytest.fail('Network after deadline'))
    with pytest.raises(Blocked, match='collection_deadline'):
        fetcher.get_text('https://example.invalid/job')


def test_ingestion_does_not_start_a_posting_after_deadline(world):
    conn, config, _, add = world
    add(42)
    result = ingest.run(conn, config, deadline=time.time()-1)
    assert result['seen'] == 0 and result['deferred'] == 'batch_deadline'


def test_browser_fallback_receives_the_remaining_invocation_time(monkeypatch):
    from jobwatch.interview import browser as interview_browser
    seen = []
    monkeypatch.setattr(interview_browser, 'browser_ad', lambda *a, **kw: seen.append(kw['deadline']) or SimpleNamespace(text=''))
    before = time.monotonic()
    ingest._browser_text(None, {'id': 42, 'url': 'https://example.invalid/job'}, 'teaser', 'teaser', deadline=time.time()+2)
    assert before < seen[0] <= before+2.1


def test_public_extras_stop_at_shared_deadline_without_renewing_timeout(monkeypatch):
    from jobwatch.util import openrouter_extras as extras
    monkeypatch.setattr(extras, '_key', lambda config: 'synthetic')
    seen = []
    monkeypatch.setattr(extras.requests, 'post', lambda *a, **kw:
                        seen.append(kw['timeout']) or SimpleNamespace(status_code=200, json=lambda: {}))
    with extras.deadline_scope(time.time()+2):
        assert extras._post(extras.DEFAULTS, 'systemone', {}) == {}
    assert 0 < seen[0] <= 2
    with extras.deadline_scope(time.time()-1):
        assert extras._post(extras.DEFAULTS, 'systemone', {}) is None
    assert len(seen) == 1


def test_daily_allowance_caps_resumed_checkpoint_without_new_spending(world, monkeypatch):
    from jobwatch.util.llm import LLM
    from tests.test_agentic_service import SyntheticGateway
    from pipeline.agentic.persistence import latest_result
    conn, config, bundle, add = world
    add(42)
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    original = service.evaluate_job
    def interrupt(*args, **kwargs):
        raise OSError('synthetic')
    monkeypatch.setattr(service, 'evaluate_job', interrupt)
    first = service.agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    assert first['charged_tokens'] > 0
    incident = incidents.list_incidents(conn)[0]
    incidents.release(conn, incident['incident_id'], 42)
    monkeypatch.setattr(service, 'evaluate_job', original)
    before = len(gateway.calls)
    second = service.agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=llm,
                                      operation='evaluate', token_allowance=1)
    assert latest_result(conn, 42)['reason'] == 'daily_budget'
    assert second['spent_tokens'] == 0 and len(gateway.calls) == before
    assert second['charged_tokens'] == first['charged_tokens']
    assert first['batch_id'] in {item['batch_id'] for item in second['batches']}
    assert incidents.list_incidents(conn) == []


def test_cancellation_releases_job_and_preserves_invocation_posting(world):
    from jobwatch.util.llm import LLM
    from tests.test_agentic_service import SyntheticGateway
    from pipeline.agentic import execution
    from pipeline.agentic.runtime import RuntimeErrorSafe
    conn, config, bundle, add = world
    add(42); add(43)
    gateway = SyntheticGateway(bundle)
    cancelled = [False]
    def transport(*args, **kwargs):
        response = gateway(*args, **kwargs)
        cancelled[0] = True
        return response
    incidents.begin_run(conn, 'cancelled-discovery')
    scope = execution.Execution('cancelled-discovery', cancelled=lambda: cancelled[0])
    with execution.use(scope), pytest.raises(RuntimeErrorSafe, match='cancelled'):
        service.agentic_batch_run([42, 43], config, conn, evidence_bundle=bundle,
            llm=LLM(transport=transport, keys=['synthetic']), run_id='cancelled-discovery', operation='evaluate')
    row = conn.execute('SELECT phase,posting_id,state FROM agentic_invocations WHERE run_id=?',
                       ('cancelled-discovery',)).fetchone()
    assert tuple(row) == ('assessment', 42, 'running')
    job = conn.execute('SELECT status,reason,lease_until FROM agentic_runs WHERE posting_id=42').fetchone()
    assert job[0] == 'held' and job[1] == 'cancelled' and job[2] == 0
    assert conn.execute('SELECT COUNT(*) FROM agentic_runs WHERE posting_id=43').fetchone()[0] == 0
    assert len(gateway.calls) == 1
    assert incidents.list_incidents(conn) == []
