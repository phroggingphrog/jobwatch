"""Durable human selections, private queue identity and unpaid recovery."""
import pytest
from tests.baseline_support import frozen, world
from jobwatch import users
from pipeline.agentic import selection, shortlist
from pipeline.agentic.api_store import APIStore


def payload(frozen):
    entries = shortlist.build_shortlist(frozen.conn,frozen.config)
    selected = [e for e in entries if e.posting_id in (42,43)]
    return dict(posting_ids=[e.posting_id for e in selected],
                expected_entry_ids={str(e.posting_id):e.entry_id for e in selected},
                expected_run_keys={str(e.posting_id):e.run_key for e in selected})


def test_selection_retry_outbox_crash_recovery_and_person_isolation(frozen, monkeypatch):
    data = payload(frozen)
    row = selection.request(frozen.conn,frozen.config,**data,request_id='selected',actor='person')
    assert row['state'] == 'pending_dispatch' and row['run_id'] is None
    assert selection.request(frozen.conn,frozen.config,**data,request_id='selected',actor='person') == row
    with pytest.raises(selection.SelectionError,match='idempotency_conflict'):
        selection.request(frozen.conn,frozen.config,**{**data,'posting_ids':[42]},request_id='selected',actor='person')
    with users.use('other-person'):
        with pytest.raises(selection.SelectionError,match='not_found'):
            selection.status(frozen.conn,row['id'])
    # Simulate process death between queue commit and jobs/outbox reconciliation.
    original = selection._mark_queued
    monkeypatch.setattr(selection,'_mark_queued',lambda *a,**k: (_ for _ in ()).throw(OSError('synthetic crash')))
    with pytest.raises(OSError):
        selection.dispatch_pending(frozen.conn,frozen.config)
    monkeypatch.setattr(selection,'_mark_queued',original)
    selection.dispatch_pending(frozen.conn,frozen.config)
    current = selection.status(frozen.conn,row['id'])
    with APIStore(users.current()) as store:
        assert store.conn.execute('SELECT count(*) FROM api_runs').fetchone()[0] == 1
        assert store.conn.execute("SELECT count(*) FROM api_events WHERE kind='queued'").fetchone()[0] == 1
        assert store.raw_run(current['run_id'])['state'] == 'queued'
    assert frozen.conn.execute("SELECT count(*) FROM feedback_events WHERE kind='select'").fetchone()[0] == 2


def test_changed_inputs_cancelled_requests_and_model_writes_never_queue(frozen):
    data = payload(frozen)
    with pytest.raises(selection.SelectionError,match='person_required'):
        selection.request(frozen.conn,frozen.config,**data,request_id='model',actor='model')
    row = selection.request(frozen.conn,frozen.config,**data,request_id='cancel',actor='person')
    selection.cancel(frozen.conn,row['id'],actor='person')
    assert selection.dispatch_pending(frozen.conn,frozen.config) == 0
    assert selection.status(frozen.conn,row['id'])['state'] == 'cancelled'
    row = selection.request(frozen.conn,frozen.config,**data,request_id='changed',actor='person')
    frozen.conn.execute("UPDATE postings SET closed_at='2026-10-23' WHERE id=42"); frozen.conn.commit()
    assert selection.dispatch_pending(frozen.conn,frozen.config) == 0
    assert selection.status(frozen.conn,row['id'])['error'] == 'inputs_changed'


def test_selected_only_execution_passes_expected_keys_and_stable_batch(frozen,monkeypatch):
    data = payload(frozen)
    row = selection.request(frozen.conn,frozen.config,**data,request_id='work',actor='person')
    selection.dispatch_pending(frozen.conn,frozen.config)
    row = selection.status(frozen.conn,row['id'])
    calls = []
    def prepare(ids,config,conn,**kwargs):
        calls.append((ids,kwargs))
        return {'processed':0,'deferred':[]}
    monkeypatch.setattr('pipeline.agentic.service.agentic_batch_run',prepare)
    from types import SimpleNamespace
    from jobwatch.util import model_choice as model_choice
    result = selection.execute(frozen.conn,frozen.config,row['id'],row['input_hash'],row['run_id'],
                               llm=SimpleNamespace(base_url=model_choice.SERVER_URL))
    assert calls[0][0] == data['posting_ids']
    assert calls[0][1]['operation'] == 'prepare'
    assert calls[0][1]['expected_run_keys'] == {int(k):v for k,v in data['expected_run_keys'].items()}
    assert calls[0][1]['batch_id'] == 'selection-'+row['id']
    assert result['selection_id'] == row['id']


def test_recovery_accepts_its_own_progress_but_refuses_changed_ranking_context(frozen,monkeypatch):
    from types import SimpleNamespace
    from jobwatch.util import model_choice as model_choice
    data=payload(frozen)
    row=selection.request(frozen.conn,frozen.config,**data,request_id='recover',actor='person')
    selection.dispatch_pending(frozen.conn,frozen.config)
    row=selection.status(frozen.conn,row['id'])
    manifest=selection._manifest(frozen.conn,frozen.config,row)
    # A preparation checkpoint changes operational status, while its frozen
    # evaluation, ad, policy and approved evidence stay identical.
    frozen.conn.execute("UPDATE agentic_runs SET status='drafting' WHERE posting_id=42")
    frozen.conn.commit()
    assert selection._manifest(frozen.conn,frozen.config,row)==manifest
    frozen.config.settings['pipeline']['agentic']['relevance']='on'
    with pytest.raises(selection.SelectionError,match='inputs_changed'):
        selection._manifest(frozen.conn,frozen.config,row)


def test_completed_selection_republishes_same_result_after_api_crash_without_preparing_again(frozen,monkeypatch):
    from types import SimpleNamespace
    from jobwatch.util import model_choice as model_choice
    row=selection.request(frozen.conn,frozen.config,**payload(frozen),request_id='completion-crash',actor='person')
    selection.dispatch_pending(frozen.conn,frozen.config)
    row=selection.status(frozen.conn,row['id'])
    with APIStore(users.current()) as store:
        store.claim_next()
    calls=[]
    def prepare(*args,**kwargs):
        calls.append(kwargs['batch_id'])
        return dict(processed=0,deferred=[])
    monkeypatch.setattr('pipeline.agentic.service.agentic_batch_run',prepare)
    llm=SimpleNamespace(base_url=model_choice.SERVER_URL)
    original=selection.execute(frozen.conn,frozen.config,row['id'],row['input_hash'],row['run_id'],llm=llm)
    with APIStore(users.current()) as store:
        store.recover(); store.retry(row['run_id']); store.claim_next()
    recovered=selection.execute(frozen.conn,frozen.config,row['id'],row['input_hash'],row['run_id'],
        llm_factory=lambda:pytest.fail('completed recovery must not initialize a model client'))
    assert recovered==original
    assert calls==['selection-'+row['id']]


@pytest.mark.parametrize('crash',[False,True])
def test_cancelled_run_is_reconciled_after_generic_cancel_or_cross_store_crash(frozen,monkeypatch,crash):
    row=selection.request(frozen.conn,frozen.config,**payload(frozen),request_id='cancel-recovery',actor='person')
    selection.dispatch_pending(frozen.conn,frozen.config)
    row=selection.status(frozen.conn,row['id'])
    if crash:
        original=APIStore.cancel
        def interrupt(store,ident):
            original(store,ident)
            raise OSError('synthetic cross-store interruption')
        monkeypatch.setattr(APIStore,'cancel',interrupt)
        with pytest.raises(OSError):
            selection.cancel(frozen.conn,row['id'],actor='person')
    else:
        with APIStore(users.current()) as store:
            store.cancel(row['run_id'])
    selection.reconcile(frozen.conn)
    assert selection.status(frozen.conn,row['id'])['state']=='cancelled'
    assert selection.dispatch_pending(frozen.conn,frozen.config)==0


def test_reconciliation_reaches_cancelled_work_behind_interrupted_requests(frozen):
    data=payload(frozen)
    rows=[selection.request(frozen.conn,frozen.config,**data,request_id='fair-'+str(i),actor='person') for i in range(11)]
    selection.dispatch_pending(frozen.conn,frozen.config)
    selection.dispatch_pending(frozen.conn,frozen.config)
    with APIStore(users.current()) as store:
        for row in rows[:-1]:
            queued=selection.status(frozen.conn,row['id'])
            store.conn.execute("UPDATE api_runs SET state='interrupted' WHERE id=?",(queued['run_id'],))
        store.conn.commit()
        last=selection.status(frozen.conn,rows[-1]['id'])
        store.cancel(last['run_id'])
    selection.reconcile(frozen.conn,limit=10)
    selection.reconcile(frozen.conn,limit=10)
    assert selection.status(frozen.conn,last['id'])['state']=='cancelled'
