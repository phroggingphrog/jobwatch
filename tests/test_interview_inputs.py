import pytest

from jobwatch import db, ledger
from jobwatch.interview_inputs import InterviewInputs, load_inputs, save_inputs
from pipeline.agentic.contracts import AgenticError


@pytest.fixture
def conn(tmp_path,monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR',str(tmp_path))
    c=db.connect(tmp_path/'test.db')
    c.execute("INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,first_seen_at,last_seen_at) VALUES(1,'test','1','https://example.test/job','h','d','Synthetic role','2020-01-01','2020-01-01')")
    c.commit()
    yield c
    c.close()


def test_optional_inputs_do_not_create_or_change_application(conn):
    assert load_inputs(conn,1)==(InterviewInputs(),0)
    note=InterviewInputs(invite='Synthetic interview via Teams',story_bank='I reconciled ledgers.')
    save_inputs(conn,1,note,expected_revision=0)
    assert load_inputs(conn,1)==(note,1)
    assert conn.execute('select count(*) from applications').fetchone()[0]==0
    assert conn.execute('select count(*) from application_events').fetchone()[0]==0


def test_inputs_replay_and_retention_preserve_prep_without_application(conn):
    save_inputs(conn,1,InterviewInputs(invite='Synthetic invitation'),expected_revision=0)
    before=ledger.snapshot(conn);ledger.reindex(conn)
    assert ledger.snapshot(conn)==before
    assert db.prune(conn,1)==0
    assert load_inputs(conn,1)[1]==1


def test_stale_tabs_cannot_replace_newer_owner_inputs(conn):
    save_inputs(conn,1,InterviewInputs(invite='New details'),expected_revision=0)
    with pytest.raises(AgenticError,match='interview_inputs_changed'):
        save_inputs(conn,1,InterviewInputs(invite='Old details'),expected_revision=0)
    assert load_inputs(conn,1)[0].invite=='New details'


def test_invalid_ids_and_metadata_fail_without_rows(conn):
    with pytest.raises(AgenticError):save_inputs(conn,2,InterviewInputs(),expected_revision=0)
    with pytest.raises(AgenticError):save_inputs(conn,1,InterviewInputs(),expected_revision=True)
    with pytest.raises(AgenticError):save_inputs(conn,1,{'invite':'unvalidated'},expected_revision=0)
    assert conn.execute('select count(*) from interview_inputs').fetchone()[0]==0


def test_malformed_private_record_has_fixed_error(conn):
    save_inputs(conn,1,InterviewInputs(),expected_revision=0)
    conn.execute("update interview_inputs set inputs_json=?",('{private corrupt text',));conn.commit()
    with pytest.raises(AgenticError,match='^interview_inputs_invalid$'):load_inputs(conn,1)


def test_unchecked_model_copy_cannot_bypass_input_limits(conn):
    unchecked=InterviewInputs().model_copy(update={'invite':'x'*20001})
    with pytest.raises(AgenticError,match='^interview_inputs_invalid$'):
        save_inputs(conn,1,unchecked,expected_revision=0)
    assert load_inputs(conn,1)[1]==0


def test_ledger_failure_rolls_back_owner_edit(conn,monkeypatch):
    def fail(*a,**kw):raise OSError('synthetic ledger failure')
    monkeypatch.setattr(ledger,'append',fail)
    with pytest.raises(OSError):save_inputs(conn,1,InterviewInputs(invite='New'),expected_revision=0)
    assert load_inputs(conn,1)[1]==0
    assert not conn.in_transaction


def test_separate_connections_reject_stale_revision(conn):
    path=conn.execute('PRAGMA database_list').fetchone()[2]
    second=db.connect(path)
    try:
        _,old_revision=load_inputs(second,1)
        save_inputs(conn,1,InterviewInputs(invite='First edit'),expected_revision=0)
        with pytest.raises(AgenticError,match='interview_inputs_changed'):
            save_inputs(second,1,InterviewInputs(invite='Stale edit'),expected_revision=old_revision)
        assert load_inputs(second,1)[0].invite=='First edit'
    finally:second.close()


@pytest.mark.skip(reason="strict schemas removed, owner 2026-10-19")
def test_aggregate_limit_and_unknown_fields_cannot_be_persisted(conn):
    for unchecked in [InterviewInputs.model_construct(invite='x'*20000,panelist_profiles='x'*20000,story_bank='x'*20000,coffee_chat='x'),
                      InterviewInputs.model_construct(invite=42)]:
        with pytest.raises(AgenticError):save_inputs(conn,1,unchecked,expected_revision=0)
    conn.execute("INSERT INTO interview_inputs VALUES(1,'now',1,?)",('{"private_unknown":"sensitive"}',));conn.commit()
    with pytest.raises(AgenticError,match='^interview_inputs_invalid$'):load_inputs(conn,1)
