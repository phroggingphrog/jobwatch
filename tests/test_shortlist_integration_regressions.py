from pathlib import Path
import pytest
from tests.baseline_support import world, frozen
from jobwatch import preference_service, users
from jobwatch.candidate import intake
from pipeline.agentic import shortlist, service, discovery
from tests.test_agentic_service import _seed, _stub_batch


def test_saved_shortlist_rejects_corrupt_candidate_artifact(frozen):
    shortlist.build_shortlist(frozen.conn,frozen.config)
    row=preference_service.current_runs(frozen.conn,frozen.config)[3][0]
    Path(row.result['artifact_paths']['candidate']).write_text('{}')
    assert all(r.posting_id!=row.posting_id for r in preference_service.current_runs(frozen.conn,frozen.config)[3])
    out=shortlist.load_latest(frozen.conn,config=frozen.config)
    assert out['status']=='stale', out


def test_profile_capture_precedes_freshness_fence(frozen,monkeypatch):
    approved=intake.current_version(users.current())
    first=True
    def latest(person):
        nonlocal first
        if first:
            first=False
            return {**approved,'version':approved['version']+1}
        return approved
    monkeypatch.setattr(intake,'current_version',latest)
    with pytest.raises(ValueError,match='snapshot_changed'):
        shortlist.build_shortlist(frozen.conn,frozen.config)
    assert frozen.conn.execute('SELECT count(*) FROM shortlists').fetchone()[0]==0


def test_completed_prefix_does_not_starve_new_pending_work(world,monkeypatch):
    conn,config,bundle,add=world
    _seed(conn,add,201)
    selected=[]
    _stub_batch(monkeypatch,selected)
    monkeypatch.setattr(service,'_without_completed',lambda conn,config,pending:[pid for pid in pending if pid>200])
    monkeypatch.setattr(service,'_near_duplicates',lambda *a,**k:None)
    monkeypatch.setattr(discovery,'enforce_exclusions',lambda *a,**k:[])
    monkeypatch.setattr(discovery,'reconsider',lambda *a,**k:None)
    monkeypatch.setattr(discovery,'screen_step',lambda *a,**k:{})
    service.after_collect(conn,config,max_seconds=600)
    assert 201 in selected, selected
from tests.baseline_support import world,frozen
from jobwatch import db
from jobwatch.outcomes.readiness import response_time_readiness
from pipeline.agentic import shortlist


def test_stored_response_readiness_freshness_tracks_source_events(frozen):
    shortlist.build_shortlist(frozen.conn,frozen.config)
    before=shortlist.load_latest(frozen.conn,config=frozen.config)
    assert before['ordering_basis']['response_time']['responses']==0
    at=db.ts()
    frozen.conn.execute('INSERT INTO applications(posting_id,status,created_at,updated_at,applied_at) VALUES(?,?,?,?,?)',
        (42,'interview',at,at,'2026-01-01'))
    ident=frozen.conn.execute('SELECT id FROM applications WHERE posting_id=42').fetchone()[0]
    frozen.conn.execute('INSERT INTO application_events(application_id,at,kind,to_status,actor) VALUES(?,?,?,?,?)',
        (ident,at,'status','interview','owner'))
    frozen.conn.commit()
    assert response_time_readiness(frozen.conn)['responses']==1
    after=shortlist.load_latest(frozen.conn,config=frozen.config)
    assert after['status']=='stale' or after['ordering_basis']['response_time']['responses']==1, after['ordering_basis']['response_time']
