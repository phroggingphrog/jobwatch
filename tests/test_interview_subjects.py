from dataclasses import replace
import json

import pytest

from jobwatch import db, ledger
from jobwatch.interview.ad import InterviewAd
from jobwatch.interview.inputs import InterviewInputs
from jobwatch.interview.subjects import create_subject, load_subject, save_subject_inputs
from pipeline.agentic.contracts import AgenticError


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    connection = db.connect(tmp_path/'test.db')
    yield connection
    connection.close()


@pytest.fixture
def ad():
    return InterviewAd('https://example.test/jobs/1','https://example.test/api/1',
                       'Synthetic analyst','Synthetic employer','Complete synthetic duties. '*900,
                       '2026-10-11T00:00:00+00:00')


def test_source_and_report_reference_survive_reindex_without_tracker_rows(conn, ad):
    subject_id = create_subject(conn, ad, InterviewInputs(invite='Synthetic private invitation'))
    ledger.upsert(conn,'applications','interview_subject_runs',{
        'run_key':'synthetic-run','subject_id':subject_id,'detail_json':'{"report":"synthetic"}'})
    before = ledger.snapshot(conn)
    ledger.reindex(conn)
    assert ledger.snapshot(conn)==before
    subject = load_subject(conn,subject_id)
    assert subject['ad']==ad
    assert subject['revision']==1
    assert subject['inputs'].invite=='Synthetic private invitation'
    assert 'Synthetic' not in repr(subject)
    for table in ('postings','applications','application_events'):
        assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0


def test_stale_save_across_connections(conn, ad):
    subject_id=create_subject(conn,ad)
    other=db.connect(conn.execute('PRAGMA database_list').fetchone()[2])
    try:
        old=load_subject(other,subject_id)
        inputs, revision=save_subject_inputs(conn,subject_id,InterviewInputs(invite='Current'),expected_revision=1)
        assert revision==2
        with pytest.raises(AgenticError,match='^interview_inputs_changed$'):
            save_subject_inputs(other,subject_id,InterviewInputs(invite='Stale'),expected_revision=old['revision'])
        assert load_subject(other,subject_id)['inputs']==inputs
        assert not other.in_transaction
    finally:other.close()


def test_duplicate_reuses_original_source_and_preserves_owner_notes(conn,ad):
    subject_id=create_subject(conn,ad)
    save_subject_inputs(conn,subject_id,InterviewInputs(invite='Keep notes'),expected_revision=1)
    newer=replace(ad,acquired_at='2026-10-12T00:00:00+00:00')
    assert create_subject(conn,newer)==subject_id
    assert create_subject(conn,replace(newer,url=ad.url+'?utm_source=synthetic#detail'))==subject_id
    assert load_subject(conn,subject_id)['revision']==2
    assert load_subject(conn,subject_id)['ad']==ad
    assert create_subject(conn,newer,InterviewInputs(invite='Keep notes'))==subject_id
    with pytest.raises(AgenticError,match='^interview_subject_inputs_conflict$'):
        create_subject(conn,newer,InterviewInputs())
    assert not conn.in_transaction
    assert create_subject(conn,replace(ad,text=ad.text+'New duties'))!=subject_id


@pytest.mark.parametrize('field,value',[
    ('url','http://private.test/x'),('source_url','https://user:password@example.test/x'),
    ('source_url','https://example.test:444/x'),('url','https://example.test/\nprivate'),
    ('title',''),('title','x'*501),('company','x'*501),('text','short'),
    ('text','x'*100001),('acquired_at','private invalid date'),
    ('acquired_at','2026-10-11'),('acquisition','invented'),('text',42),
])
def test_invalid_ad_does_not_write_or_leak(conn,ad,field,value):
    with pytest.raises(AgenticError,match='^interview_subject_invalid$'):
        create_subject(conn,replace(ad,**{field:value}))
    assert conn.execute('SELECT COUNT(*) FROM interview_subjects').fetchone()[0]==0
    assert not list(ledger.read('applications'))
    assert not conn.in_transaction


def test_invalid_inputs_and_revision_cannot_change_subject(conn,ad):
    subject_id=create_subject(conn,ad)
    before=ledger.snapshot(conn)
    for inputs,revision in [(InterviewInputs().model_copy(update={'invite':'x'*20001}),1),
                             (InterviewInputs.model_construct(invite=42),1),
                             (InterviewInputs(),True),(InterviewInputs(),0)]:
        with pytest.raises(AgenticError,match='^interview_inputs_invalid$'):
            save_subject_inputs(conn,subject_id,inputs,expected_revision=revision)
    assert ledger.snapshot(conn)==before


@pytest.mark.parametrize('mutation',['hash','unknown','bad_inputs','bad_ad','bad_json'])
def test_corrupt_record_fixed_error(conn,ad,mutation):
    subject_id=create_subject(conn,ad)
    detail=json.loads(conn.execute('SELECT detail_json FROM interview_subjects').fetchone()[0])
    if mutation=='hash':detail['text_hash']='0'*64
    if mutation=='unknown':detail['private_extra']='secret'
    if mutation=='bad_inputs':detail['inputs']['invite']=42
    if mutation=='bad_ad':detail['ad']['acquisition']='secret'
    payload='{secret' if mutation=='bad_json' else json.dumps(detail)
    conn.execute('UPDATE interview_subjects SET detail_json=?',(payload,));conn.commit()
    with pytest.raises(AgenticError,match='^interview_subject_invalid$'):load_subject(conn,subject_id)


def test_ledger_failure_rolls_back_create_and_save(conn,ad,monkeypatch):
    subject_id=create_subject(conn,ad)
    before=ledger.snapshot(conn)
    def fail(*args,**kwargs):raise OSError('synthetic failure')
    monkeypatch.setattr(ledger,'append',fail)
    with pytest.raises(OSError):create_subject(conn,replace(ad,text=ad.text+'Changed'))
    with pytest.raises(OSError):save_subject_inputs(conn,subject_id,InterviewInputs(invite='New'),expected_revision=1)
    assert ledger.snapshot(conn)==before
    assert not conn.in_transaction


@pytest.mark.parametrize('method',['structured_ats','browser','unconfirmed (fetched without browser)','owner_supplied'])
def test_supported_acquisitions_preserved(conn,ad,method):
    ad=replace(ad,acquisition=method)
    assert load_subject(conn,create_subject(conn,ad))['ad']==ad


def test_v10_upgrade_creates_replayable_subject_tables(tmp_path):
    import sqlite3
    connection=sqlite3.connect(tmp_path/'old.db')
    for script in db.MIGRATIONS[:10]:connection.executescript(script)
    connection.execute('PRAGMA user_version=10')
    connection.commit()
    assert db.migrate(connection)==len(db.MIGRATIONS)
    assert db.migrate(connection)==len(db.MIGRATIONS)
    for table in ('interview_subjects','interview_subject_runs'):
        assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
    connection.close()


def test_missing_subject_and_active_transaction_leave_state_untouched(conn,ad):
    for subject_id in (1,True,'private-invalid-id','a'*32):
        with pytest.raises(AgenticError,match='^interview_subject_missing$'):
            load_subject(conn,subject_id)
    conn.execute('BEGIN IMMEDIATE')
    with pytest.raises(AgenticError,match='^transaction_already_active$'):create_subject(conn,ad)
    assert conn.in_transaction
    conn.rollback()


def test_legacy_ad_without_expiry_loads_and_reuses_saved_notes(conn,ad):
    ident=create_subject(conn,ad,InterviewInputs(invite='Keep existing notes'))
    row=conn.execute('SELECT detail_json FROM interview_subjects WHERE subject_id=?',(ident,)).fetchone()
    detail=json.loads(row[0]);detail['ad'].pop('expires_at')
    conn.execute('UPDATE interview_subjects SET detail_json=? WHERE subject_id=?',(json.dumps(detail),ident));conn.commit()
    assert load_subject(conn,ident)['ad']==ad
    assert create_subject(conn,ad)==ident
    assert load_subject(conn,ident)['inputs'].invite=='Keep existing notes'


def test_optional_ad_expiry_round_trips(conn,ad):
    value=replace(ad,expires_at='2026-10-12T10:00:00+00:00')
    assert load_subject(conn,create_subject(conn,value))['ad']==value


@pytest.mark.parametrize('expiry',[False,1,'not-a-date','2026-10-12T10:00:00'])
def test_invalid_ad_expiry_rejected_without_write(conn,ad,expiry):
    with pytest.raises(AgenticError,match='interview_subject_invalid'):
        create_subject(conn,replace(ad,expires_at=expiry))
    assert conn.execute('SELECT count(*) FROM interview_subjects').fetchone()[0]==0
