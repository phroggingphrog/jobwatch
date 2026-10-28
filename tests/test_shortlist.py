"""Explained shortlists read current assessments without paid work or approvals."""
import json
from hashlib import sha256
import pytest
from tests.baseline_support import world, frozen
from jobwatch import db, users
from jobwatch.util import adtext as adtext
from jobwatch.candidate import intake
from pipeline.agentic import shortlist


def test_shortlist_tables_are_additive_and_migration_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / 'jobs.db')
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'shortlists','shortlist_entries','shortlist_impressions'} <= names
    assert db.migrate(conn) == len(db.MIGRATIONS)


def test_build_is_current_explained_idempotent_and_unpaid(frozen):
    before = frozen.conn.execute('SELECT count(*) FROM applications').fetchone()[0]
    entries = shortlist.build_shortlist(frozen.conn, frozen.config)
    assert {e.posting_id for e in entries} == {42,43,44}
    assert all(e.evidence and e.rank_reason and e.coverage and e.requirements for e in entries)
    assert all(e.ordering == 'provisional' for e in entries)
    assert shortlist.build_shortlist(frozen.conn, frozen.config) == entries
    assert frozen.conn.execute('SELECT count(*) FROM shortlists').fetchone()[0] == 1
    assert frozen.conn.execute('SELECT count(*) FROM applications').fetchone()[0] == before
    assert shortlist.load_latest(frozen.conn, config=frozen.config)['status'] == 'ok'


@pytest.mark.parametrize('change', ['ad','closed','profile','salary'])
def test_changed_inputs_hide_all_stale_entries(frozen, monkeypatch, change):
    assert shortlist.build_shortlist(frozen.conn, frozen.config)
    if change == 'ad':
        old = adtext.get_text(frozen.conn,42)[0]
        adtext.save_text(frozen.conn,42,old+' Changed condition.','synthetic-full')
    elif change == 'profile':
        old = intake.current_version(users.current())
        monkeypatch.setattr(intake,'current_version',lambda person:{**old,'confirmed_at':'2099-01-01'})
    else:
        column, value = ('closed_at','2026-10-22') if change == 'closed' else ('salary_text','$99/hour AUD')
        frozen.conn.execute(f'UPDATE postings SET {column}=? WHERE id=42',(value,))
    frozen.conn.commit()
    out = shortlist.load_latest(frozen.conn,config=frozen.config)
    assert out['status'] == 'stale' and out['entries'] == []
    assert shortlist.load_entry(frozen.conn,42,config=frozen.config) is None


def test_no_confirmed_profile_or_different_person_never_sees_snapshot(frozen,monkeypatch):
    assert shortlist.build_shortlist(frozen.conn,frozen.config)
    with users.use('unrelated-fixture'):
        assert shortlist.load_latest(frozen.conn,config=frozen.config)['entries'] == []
    monkeypatch.setattr(intake,'current_version',lambda person:None)
    assert shortlist.load_latest(frozen.conn,config=frozen.config)['status'] == 'no_confirmed_profile'


def test_impressions_are_deduplicated_and_are_never_choices(frozen):
    entries=shortlist.build_shortlist(frozen.conn,frozen.config)
    assert shortlist.record_impressions(frozen.conn,entries,'api') == 3
    assert shortlist.record_impressions(frozen.conn,entries,'api') == 0
    assert shortlist.record_impressions(frozen.conn,entries,'api_detail') == 3
    assert all(r[0] is None for r in frozen.conn.execute('SELECT probability FROM shortlist_impressions'))
    assert not frozen.conn.execute("SELECT 1 FROM sqlite_master WHERE name='preference_picks'").fetchone()


def test_shadow_relevance_does_not_exclude(frozen,monkeypatch):
    from pipeline.agentic import discovery
    from jobwatch.occupations.plan import search_plan, save_plan
    from jobwatch.candidate.policy import policy_for
    plan=search_plan(policy_for(users.current()),[])
    save_plan(users.current(),plan)
    row=discovery.RelevanceJudgment(posting_id=42,relevant='no',quotes=(),similarity=0.,
        matched_hypotheses=(),reason='Unrelated fictional field',ad_hash=sha256(adtext.get_text(frozen.conn,42)[0].encode()).hexdigest(),plan_hash=plan.plan_hash)
    discovery._store_judgment(frozen.conn,row,'shadow'); frozen.conn.commit()
    assert 42 in {e.posting_id for e in shortlist.build_shortlist(frozen.conn,frozen.config)}
    frozen.config.settings['pipeline']['agentic']['relevance']='on'
    assert 42 not in {e.posting_id for e in shortlist.build_shortlist(frozen.conn,frozen.config)}


def test_snapshot_change_before_persistence_rolls_back(frozen,monkeypatch):
    original=shortlist._pin
    calls=[]
    def changed(*args,**kwargs):
        value=original(*args,**kwargs)
        calls.append(value)
        return value if len(calls)==1 else 'changed'
    monkeypatch.setattr(shortlist,'_pin',changed)
    with pytest.raises(ValueError,match='snapshot_changed'):
        shortlist.build_shortlist(frozen.conn,frozen.config)
    assert frozen.conn.execute('SELECT count(*) FROM shortlists').fetchone()[0] == 0


def test_clock_expiry_invalidates_without_any_database_write(frozen,monkeypatch):
    from datetime import datetime,timedelta
    from pipeline.agentic import service
    assert shortlist.build_shortlist(frozen.conn,frozen.config)
    original=service.observation_current
    observed=service.latest_observation(frozen.conn,42)
    later=datetime.fromisoformat(observed.checked_at)+timedelta(hours=25)
    monkeypatch.setattr(service,'observation_current',lambda observation,**kwargs:original(observation,now=later,**kwargs))
    assert shortlist.load_latest(frozen.conn,config=frozen.config)['status']=='stale'
    from jobwatch.preference_service import current_runs
    assert current_runs(frozen.conn,frozen.config)[3]==[]


def test_only_hypotheses_linked_to_confirmed_focus_get_focus_priority():
    from types import SimpleNamespace
    approved={'facts':[{'id':'f1','section':'career_focus','basis':'evidence'},
                       {'id':'f2','section':'career_focus','basis':'inference'},
                       {'id':'f3','section':'experience','basis':'evidence'}]}
    fields=[SimpleNamespace(id='scope:a',supporting_facts=('f1',)),
            SimpleNamespace(id='scope:b',supporting_facts=('f2','f3'))]
    assert shortlist._focus_hypotheses(approved,fields)=={'scope:a'}


def test_valid_complete_utilities_personalise_but_incomplete_ones_do_not(frozen,monkeypatch):
    from jobwatch.preferences import PreferenceStore
    from jobwatch.preferences import model
    original=PreferenceStore.status
    monkeypatch.setattr(PreferenceStore,'status',lambda self,identity=None:{**original(self,identity),'status':'valid'})
    def predict(*args):
        return {'fit_id':'synthetic-test-transport-only','context_hash':args[2],'alternatives':[
            {'posting_id':pid,'utility':{'mean':float(pid)}} for pid in (42,43,44)]}
    monkeypatch.setattr(model,'predict_utilities',predict)
    entries=shortlist.build_shortlist(frozen.conn,frozen.config)
    assert entries[0].posting_id==44 and all(e.ordering=='personalised' for e in entries)
    monkeypatch.setattr(model,'predict_utilities',lambda *a:{'fit_id':'incomplete','alternatives':[]})
    entries=shortlist.build_shortlist(frozen.conn,frozen.config)
    assert all(e.ordering=='provisional' for e in entries)


def test_implementation_change_invalidates_saved_presentation(frozen,monkeypatch):
    from pipeline.agentic import service
    assert shortlist.build_shortlist(frozen.conn,frozen.config)
    monkeypatch.setattr(service,'IMPLEMENTATION_VERSION','synthetic-next-implementation')
    assert shortlist.load_latest(frozen.conn,config=frozen.config)['status']=='stale'
