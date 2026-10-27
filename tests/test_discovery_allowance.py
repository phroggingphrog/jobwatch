"""Assessment allowances exclude normal deferrals while preserving all spending."""
import time

import pytest

from jobwatch.llm import LLM
from pipeline.agentic import incidents, service
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401


@pytest.fixture(autouse=True)
def no_public_screen(monkeypatch):
    monkeypatch.setattr(service, 'jev_screen', lambda *args, **kwargs: None)


def test_daily_assessment_count_ignores_deferrals_and_refreshes_without_erasing_prior_work(world):
    conn, config, _, add = world
    for pid in range(42, 47):
        add(pid)
    service.AgenticStore(conn).ensure()
    now = time.time()
    conn.execute("INSERT INTO agentic_batches(batch_id,token_ceiling,deadline,charged,state) VALUES('historical',1000,?,321,'active')", (now+300,))
    for pid, reason in [(42, 'evaluation_complete'), (42, 'daily_budget'), (43, 'daily_budget'),
                        (44, 'execution_failed'), (45, 'snapshot_changed'), (46, 'score_below_threshold')]:
        conn.execute('INSERT INTO agentic_activity(run_key,posting_id,batch_id,invocation_id,event,at,reason) '
                     "VALUES(?,?,?,'synthetic','finished',?,?)", ('synthetic-'+str(pid), pid, 'historical', now, reason))
    conn.commit()
    assert service._spent_today(conn, now-10) == (3, 321)
    assert conn.execute("SELECT charged FROM agentic_batches WHERE batch_id='historical'").fetchone()[0] == 321


def test_allowance_refusal_is_deferred_without_counting_held_or_processed_jobs(world):
    conn, config, bundle, add = world
    add(42); add(43)
    gateway = SyntheticGateway(bundle)
    out = service.agentic_batch_run([42, 43], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate', token_allowance=1)
    assert out['processed'] == out['held'] == out['charged_tokens'] == out['spent_tokens'] == 0
    assert out['skipped'] == 2 and out['skipped_reasons'] == {'daily_budget': 2}
    assert [item['posting_id'] for item in out['deferred']] == [42, 43]
    assert gateway.calls == []
    assert conn.execute('SELECT COUNT(*) FROM agentic_runs WHERE posting_id=43').fetchone()[0] == 0
    assert service._spent_today(conn, time.time()-100)[0] == 0
    assert incidents.list_incidents(conn) == []


def test_refreshed_ad_second_pass_allowance_refusal_defers_current_and_tail(world, monkeypatch):
    from pipeline.schemas import Stage
    conn, config, bundle, add = world
    add(42); add(43)
    calls = []
    def refreshed_then_deferred(pid, *args, **kwargs):
        calls.append(pid)
        reason = 'snapshot_changed' if len(calls) == 1 else 'daily_budget'
        conn.execute("INSERT INTO agentic_runs(run_key,posting_id,status,reason) VALUES(?,?,'held',?) "
                     "ON CONFLICT(run_key) DO UPDATE SET reason=excluded.reason", ('synthetic-42', pid, reason))
        conn.commit()
        return Stage.DLQ
    monkeypatch.setattr(service, 'run_agentic_job', refreshed_then_deferred)
    out = service.agentic_batch_run([42, 43], config, conn, evidence_bundle=bundle, operation='evaluate')
    assert calls == [42, 42]
    assert out['processed'] == out['held'] == out['spent_tokens'] == out['charged_tokens'] == 0
    assert out['skipped_reasons'] == {'daily_budget': 2}
    assert [item['posting_id'] for item in out['deferred']] == [42, 43]
