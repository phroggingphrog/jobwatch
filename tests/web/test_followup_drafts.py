
from jobwatch.util import model_choice as model_choice
from datetime import UTC, datetime, timedelta
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from jobwatch import db
from jobwatch.candidate import intake, projection
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.config import Config, DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, _merge
from jobwatch.web.app import create_app
from test_web import seed, OK
from test_followup_draft import Writer, Reviewer


@pytest.fixture
def draft_client(tmp_path,monkeypatch):
    data=tmp_path/'data';profile=data/'profile';profile.mkdir(parents=True)
    (profile/'cv.md').write_text('# Synthetic Example\n\n## Skills\n- Reconciled ledgers.\n')
    monkeypatch.setenv('JOBWATCH_DATA_DIR',str(data));monkeypatch.setenv('JOBWATCH_PROFILE_DIR',str(profile));monkeypatch.delenv('JOBWATCH_DB',raising=False)
    config=Config(config_dir=DEFAULT_CONFIG_DIR,settings=_merge(DEFAULT_SETTINGS,{'db_path':str(data/'test.db'),'pipeline':{'agentic':{'enabled':True,'worker_model':'claude/sonnet','reviewer_model':'claude/haiku'}}}),rules={},searches={},feeds={},employers=[])
    conn=db.connect(config.db_path);pid=seed(conn,1,'Accounts role',company='Example',arm='accounting')
    conn.execute("INSERT INTO ad_text(posting_id,text,source,fetched_at) VALUES(?,?,'cached',?)",(pid,'Example seeks an accounts assistant. '+('Reconcile ledgers accurately. '*30),datetime.now(UTC).isoformat()));conn.commit();conn.close()
    version = intake._versions_root('owner') / '1'
    evidence_dir = version / 'evidence'
    evidence_dir.mkdir(parents=True)
    shutil.copy2(profile / 'cv.md', evidence_dir / 'cv.md')
    bundle = snapshot_evidence(evidence_dir)
    record = {'version': 1, 'facts': [], 'evidence_bundle_hash': bundle.bundle_hash}
    (version / 'approved.json').write_text(json.dumps(record))
    for name, text in projection.project(record).items():
        (version / name).write_text(text)
    writer=Writer(bundle);reviewer=Reviewer(verdicts=('approve',)*10)
    class Combo:
        base_url = model_choice.SERVER_URL
        def chat_once(self,model,*args,**kwargs):
            return (writer if model=='claude/sonnet' else reviewer).chat_once(model,*args,**kwargs)
    monkeypatch.setattr('jobwatch.followup.drafts.configured_llm',lambda _:Combo())
    with TestClient(create_app(config),base_url='http://localhost',headers=OK) as client:
        client.pid=pid;client.writer=writer;client.profile=profile;client.approved_evidence=evidence_dir;client.config=config
        client.post(f'/api/job/{pid}/status',json={'status':'applied'})
        client.post(f'/api/applications/{pid}/followup',json={'action':'applied_confirmed','operation_id':'actual-applied','owner_confirmed':'true','occurred_at':(datetime.now(UTC)-timedelta(days=10)).isoformat()})
        yield client


def test_owner_generates_reviews_and_cached_click_does_not_send(draft_client):
    c=draft_client;url=f'/applications/{c.pid}/followup-draft'
    assert 'Generate follow-up draft' in c.get(url).text
    result=c.post(url)
    assert result.status_code==200 and 'Draft ready for your review' in result.text
    assert 'I reconciled ledgers.' in result.text and 'Nothing has been sent.' in result.text
    c.post(url)
    assert len(c.writer.calls)==2


def test_changed_profile_hides_previously_approved_text(draft_client):
    c=draft_client;url=f'/applications/{c.pid}/followup-draft';c.post(url)
    (c.approved_evidence/'cv.md').write_text('# Synthetic Example\n\n## Skills\n- Prepared bank reconciliations.\n')
    page=c.get(url)
    assert 'Draft ready for your review' not in page.text
    assert 'I reconciled ledgers.' not in page.text


def test_not_due_and_cross_origin_cannot_start_paid_work(draft_client):
    c=draft_client;url=f'/applications/{c.pid}/followup-draft'
    assert c.post(url,headers={'origin':'https://outside.example'}).status_code==403
    c.post(f'/api/applications/{c.pid}/followup',json={'action':'pin','operation_id':'later','owner_confirmed':'true','due_on':(datetime.now(UTC)+timedelta(days=10)).date().isoformat()})
    assert c.post(url).status_code==409
    assert not c.writer.calls


def test_email_and_linkedin_are_distinct_reviewed_snapshots(draft_client):
    c=draft_client;url=f'/applications/{c.pid}/followup-draft'
    c.post(url)
    linkedin=c.post(url,data={'channel':'linkedin'})
    assert 'Draft ready for your review' in linkedin.text
    assert 'id="followup-subject"' not in linkedin.text
    assert len(c.writer.calls)==4
    c.post(url,data={'channel':'linkedin'})
    assert len(c.writer.calls)==4
    assert c.get(url+'?channel=unsupported').status_code==422


@pytest.mark.parametrize('invalid', ['missing', 'malformed'])
def test_invalid_profile_is_readiness_response_without_model_calls(draft_client, invalid):
    c=draft_client;url=f'/applications/{c.pid}/followup-draft'
    if invalid=='missing': (c.approved_evidence/'cv.md').unlink()
    else: (c.approved_evidence/'cv.md').write_text('identity: [invalid')
    page=c.get(url)
    assert page.status_code==200 and 'Check follow-up readiness' in page.text
    assert c.post(url).status_code==409
    assert not c.writer.calls


def test_owner_explicitly_retries_held_draft(draft_client,monkeypatch):
    c=draft_client;url=f'/applications/{c.pid}/followup-draft'
    original=__import__('jobwatch.followup.drafts',fromlist=['configured_llm']).configured_llm
    class Failed:
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw):raise RuntimeError('private failure')
    monkeypatch.setattr('jobwatch.followup.drafts.configured_llm',lambda _:Failed())
    assert 'Retry within remaining allowance' in c.post(url).text
    monkeypatch.setattr('jobwatch.followup.drafts.configured_llm',original)
    assert 'Draft held for verification' in c.post(url).text
    assert not c.writer.calls
    assert 'Draft ready for your review' in c.post(url,data={'retry':'true'}).text
    assert len(c.writer.calls)==2
