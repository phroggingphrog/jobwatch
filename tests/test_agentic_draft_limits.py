"""Offline quota races and paid-budget continuity across scheduler waits."""
import concurrent.futures
import sqlite3
import time

import pytest

from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.runtime import JobBudget, BatchBudget
from pipeline.agentic.service import agentic_batch_run, run_agentic_job, _draft_limits, _budget, _config
from pipeline.agentic.persistence import latest_result
from pipeline.agentic.store import AgenticStore
from pipeline.schemas import Stage
from jobwatch.util.llm import LLM
from test_agentic_service import world, SyntheticGateway
from test_agentic_store import Harness, key, empty, reserve


def test_atomic_daily_and_batch_caps_and_boundary(tmp_path):
    path = tmp_path / 'caps.sqlite'
    conn = sqlite3.connect(path); AgenticStore(conn).ensure(); conn.close()
    def attempt(i, batch='one', now=100000):
        c = sqlite3.connect(path, timeout=5)
        st = AgenticStore(c, clock=lambda: now)
        claim = st.claim(key(i), str(i), 100)
        result = st.admit_draft(claim, batch, 3, 5)
        st.release(claim); c.close()
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(1, 9)))
    assert results.count(None) == 3
    assert results.count('draft_batch_limit') == 5
    assert attempt(10, 'two') is None
    assert attempt(11, 'two') is None
    assert attempt(12, 'three') == 'draft_daily_limit'
    assert attempt(13, 'three', 186399) == 'draft_daily_limit'
    assert attempt(14, 'three', 186400) is None


def test_legacy_ready_drafts_count_without_double_counting(tmp_path):
    h = Harness(tmp_path / 'db')
    h.a.execute('CREATE TABLE drafts(id INTEGER, status TEXT, created_at TEXT)')
    h.a.execute("INSERT INTO drafts VALUES(1,'ready',datetime(100,'unixepoch'))")
    h.a.commit()
    claim = h.store.claim(key(), 'worker', 100)
    assert h.store.admit_draft(claim, 'one', 3, 1) == 'draft_daily_limit'
    assert h.store.admit_draft(claim, 'one', 3, 2) is None
    h.a.execute("INSERT INTO agentic_packages VALUES(?, 'hash',1,1,1,'folder','complete')", (claim.run_key,))
    h.a.commit()
    second = h.store.claim(key(2), 'two', 100)
    assert h.store.admit_draft(second, 'one', 3, 2) is None


def test_wait_preserves_checkpoint_and_only_excludes_explicit_wait(tmp_path):
    h = Harness(tmp_path / 'db')
    claim = h.store.claim(key(), 'worker', 100)
    cp = h.store.checkpoint(claim, empty(claim.run_key), expected_revision=0)
    assert h.store.admit_draft(claim, 'one', 0, 10) == 'draft_batch_limit'
    h.store.release(claim)
    h.now += 86401
    claim = h.store.claim(key(), 'worker', 100)
    assert h.store.resume_quota_clock(claim) == 86401
    assert h.store.load_checkpoint(claim) == cp
    assert h.store.resume_quota_clock(claim) == 86401
    h.now += 10
    assert h.store.admit_draft(claim, 'two', 0, 10) == 'draft_batch_limit'
    h.store.release(claim)
    h.now += 100
    claim = h.store.claim(key(), 'worker', 100)
    assert h.store.resume_quota_clock(claim) == 86501
    assert h.now - 86501 == 110  # ten seconds of actual retry work still spent


def test_unknown_started_cost_is_never_refunded_or_paused(tmp_path):
    h = Harness(tmp_path / 'db')
    claim = h.store.claim(key(), 'worker', 100)
    cp = h.store.checkpoint(claim, empty(claim.run_key), expected_revision=0)
    cp = h.store.checkpoint(claim, reserve(cp, role='drafter'), expected_revision=1, operation='reserve')
    assert h.store.admit_draft(claim, 'one', 1, 1) is None
    h.store.release(claim)
    claim = h.store.claim(key(), 'worker', 100)
    assert h.store.admit_draft(claim, 'two', 1, 1) == 'draft_daily_limit'
    assert h.store.resume_quota_clock(claim) == 0
    assert h.store.load_checkpoint(claim).job_charged == 30
    assert h.a.execute('SELECT COUNT(*) FROM agentic_draft_admissions').fetchone()[0] == 1


@pytest.mark.parametrize('limit', ['drafts_per_run', 'drafts_per_day'])
def test_zero_cap_still_evaluates_and_never_drafts(world, limit):
    conn, config, bundle, add = world
    config.settings['pipeline'][limit] = 0
    add(42); add(43)
    gateway = SyntheticGateway(bundle)
    summary = agentic_batch_run([42,43], config, conn, evidence_bundle=bundle,
                                llm=LLM(transport=gateway, keys=['synthetic']))
    assert summary['held'] == 2
    assert gateway.calls.count('complete_job_assessment') == 4
    assert 'submit_draft' not in gateway.calls
    assert conn.execute('SELECT COUNT(*) FROM agentic_draft_admissions').fetchone()[0] == 0
    assert latest_result(conn,42)['reason'] == ('draft_batch_limit' if limit.endswith('run') else 'draft_daily_limit')


def test_cap_change_reuses_evaluation_and_ready_without_new_admission(world):
    conn, config, bundle, add = world
    config.settings['pipeline']['drafts_per_run'] = 0
    add(42)
    gateway = SyntheticGateway(bundle); llm=LLM(transport=gateway, keys=['synthetic'])
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=llm) == Stage.DLQ
    before = latest_result(conn,42)['run_key']
    evaluations = gateway.calls.count('complete_job_assessment')
    config.settings['pipeline']['drafts_per_run'] = 1
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=llm) == Stage.READY
    assert latest_result(conn,42)['run_key'] == before
    assert gateway.calls.count('complete_job_assessment') == evaluations
    calls = len(gateway.calls)
    config.settings['pipeline']['drafts_per_day'] = 0
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=llm) == Stage.READY
    assert len(gateway.calls) == calls
    assert conn.execute('SELECT COUNT(*) FROM agentic_draft_admissions').fetchone()[0] == 1


def test_invocation_wall_deadline_still_limits_virtual_clock():
    batch = BatchBudget('one', deadline=200)
    budget = JobBudget('a'*64,batch,clock=lambda:100,deadline=150)
    budget._invocation_deadline = time.time()-1
    assert budget.remaining_seconds() < 0
    with pytest.raises(AgenticError):
        budget.ensure_live()


@pytest.mark.parametrize('value',[-1,True,'3',1.5])
def test_invalid_caps_fail_closed(value):
    with pytest.raises(AgenticError):
        _draft_limits({'pipeline':{'drafts_per_run':value}})


def test_next_day_resume_retains_paid_budget_and_does_not_repeat_evaluation(world, monkeypatch):
    import pipeline.agentic.service as service
    conn, config, bundle, add = world
    add(42)
    config.settings['pipeline']['drafts_per_day'] = 0
    now = [time.time()]
    real_store = AgenticStore
    monkeypatch.setattr(service, 'AgenticStore', lambda c: real_store(c, clock=lambda: now[0]))
    monkeypatch.setattr(time, 'time', lambda: now[0])
    gateway = SyntheticGateway(bundle); llm = LLM(transport=gateway, keys=['synthetic'])
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=llm) == Stage.DLQ
    import json
    before = json.loads(conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0])
    calls = gateway.calls.count('complete_job_assessment')
    now[0] += 86401
    config.settings['pipeline']['drafts_per_day'] = 1
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=llm) == Stage.READY
    after = json.loads(conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0])
    assert gateway.calls.count('complete_job_assessment') == calls
    for field in ('batch_id','job_token_ceiling','batch_token_ceiling','job_deadline','batch_deadline','failed_attempts'):
        assert after[field] == before[field]
    assert after['reservations'][:len(before['reservations'])] == before['reservations']
    assert after['job_charged'] > before['job_charged']
    assert conn.execute('SELECT offset_seconds FROM agentic_quota_waits').fetchone()[0] == 86401


@pytest.mark.parametrize('role,usage,pauses', [('evaluator', 10, True), ('evaluator', None, False),
                                            ('drafter', 10, False), ('reviewer', 10, False)])
def test_only_safe_predraft_waits_resume_with_failure_count_intact(tmp_path, role, usage, pauses):
    h = Harness(tmp_path / 'db')
    claim = h.store.claim(key(), 'worker', 100)
    batch = BatchBudget('batch', token_ceiling=1000, deadline=500, clock=lambda:h.now)
    budget = JobBudget(claim.run_key, batch, token_ceiling=500, deadline=400,
                       clock=lambda:h.now, persist=lambda cp, **kw:h.store.checkpoint(claim, cp, **kw))
    budget._commit('snapshot')
    rid = budget.reserve(role, 10, 20)
    budget.dispatched(rid); budget.settle(rid, usage)
    budget.failed('transient')
    before = h.store.load_checkpoint(claim)
    assert h.store.admit_draft(claim, 'one', 0, 10) == 'draft_batch_limit'
    h.store.release(claim); h.now += 86401
    claim = h.store.claim(key(), 'next', 100)
    assert h.store.resume_quota_clock(claim) == (86401 if pauses else 0)
    assert h.store.load_checkpoint(claim) == before


def test_virtual_clock_never_renews_current_invocation(monkeypatch, tmp_path):
    import pipeline.agentic.service as service
    h = Harness(tmp_path / 'db')
    claim = h.store.claim(key(), 'worker', 100)
    h.store.checkpoint(claim, empty(claim.run_key), expected_revision=0)
    h.store.admit_draft(claim, 'one', 0, 10)
    h.store.release(claim); h.now += 86401
    claim = h.store.claim(key(), 'next', 100)
    monkeypatch.setattr(time, 'time', lambda:h.now)
    invocation = BatchBudget('invocation',token_ceiling=1000,deadline=h.now+7,clock=lambda:h.now)
    h.store.create_batch('invocation',1000,h.now+7)
    budget = service._budget(h.store, claim, service._config({}), invocation)
    assert budget.remaining_seconds() == 7
    assert budget.snapshot().job_deadline == 400
    h.now += 8
    with pytest.raises(AgenticError): budget.ensure_live()
    # An unrelated failed run in the old batch still has no time adjustment.
    other = JobBudget('f'*64,budget.batch,deadline=400,clock=lambda:h.now)
    with pytest.raises(AgenticError): other.ensure_live()


def test_existing_batch_honors_zero_current_invocation_seconds(world):
    conn, config, bundle, add = world
    add(42)
    store = AgenticStore(conn); store.ensure()
    old_deadline = time.time() + 1000
    store.create_batch('existing', 2000000, old_deadline)
    gateway = SyntheticGateway(bundle)
    summary = agentic_batch_run([42],config,conn,batch_id='existing',max_seconds=0,
                                evidence_bundle=bundle,llm=LLM(transport=gateway,keys=['synthetic']))
    # Since 6d71835 (2026-10-14) a job with no time left is skipped, not recorded as a false "posting_unavailable".
    assert summary['skipped'] == 1 and summary['held'] == 0 and not gateway.calls
    assert latest_result(conn,42) is None
    assert conn.execute("SELECT deadline FROM agentic_batches WHERE batch_id='existing'").fetchone()[0] == old_deadline
