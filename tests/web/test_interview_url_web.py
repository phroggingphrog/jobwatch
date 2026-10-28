from test_interview_web import prep_client
from test_interview_service import AD
from jobwatch import db
from jobwatch.interview_ad import InterviewAd,InterviewAdUnavailable


def test_url_workflow_without_tracker_writes(prep_client,monkeypatch):
    c=prep_client
    monkeypatch.setattr('jobwatch.interview_browser.acquire_ad',lambda url:InterviewAd(url,url,'Analyst','Example',AD,'2026-10-11T00:00:00+00:00','browser'))
    before=db.connect(c.config.db_path);count=before.execute('SELECT count(*) FROM postings').fetchone()[0];before.close()
    page=c.post('/interview-prep/open',data={'url':'https://example.test/new'})
    assert page.status_code==200 and '/interview-prep/subjects/' in str(page.url)
    url=str(page.url).replace('http://localhost','')
    assert 'JD source:</strong> Browser-verified visible description' in page.text and not c.writer.calls
    duplicate=c.post('/interview-prep/open',data={'url':'https://example.test/new'})
    assert str(duplicate.url)==str(page.url)
    report=c.post(url)
    assert 'Your reviewed interview preparation' in report.text
    download=c.get(url+'/download');assert download.status_code==200 and 'JD source: Browser-verified visible description' in download.text
    assert c.post(url+'/inputs',data={'revision':1,'invite':'Changed invite'}).status_code==200
    assert c.get(url+'/download').status_code==409
    assert c.post(url+'/inputs',data={'revision':1,'invite':'Stale'}).status_code==409
    conn=db.connect(c.config.db_path)
    assert conn.execute('SELECT count(*) FROM postings').fetchone()[0]==count
    assert conn.execute('SELECT count(*) FROM applications').fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM application_events').fetchone()[0]==0
    conn.close()


def test_matching_report_precedes_network(prep_client,monkeypatch):
    c=prep_client
    monkeypatch.setattr('jobwatch.interview_prep.matching_posting',lambda *a,**kw:c.pid)
    def forbidden(*a,**kw):raise AssertionError('network must not run')
    monkeypatch.setattr('jobwatch.interview_browser.acquire_ad',forbidden)
    page=c.post('/interview-prep/open',data={'url':'https://example.test/current'})
    assert str(page.url).endswith(f'/jobs/{c.pid}/interview-prep')


def test_closed_url_paste_recovery_and_origin(prep_client,monkeypatch):
    c=prep_client
    def closed(*a,**kw):raise InterviewAdUnavailable('interview_ad_closed')
    monkeypatch.setattr('jobwatch.interview_browser.acquire_ad',closed)
    assert 'paste the full description' in c.post('/interview-prep/open',data={'url':'https://example.test/closed'}).text
    page=c.post('/interview-prep/open',data={'url':'https://example.test/closed','title':'Analyst','company':'Example','pasted_jd':AD})
    assert 'Saved description supplied by you' in page.text and not c.writer.calls
    assert c.post('/interview-prep/open',data={'url':'https://example.test/closed'},headers={'origin':'https://evil.example'}).status_code==403


def test_saved_description_survives_missing_profile_and_validation_error(prep_client):
    c=prep_client;(c.profile/'cv.md').unlink()
    response=c.post('/interview-prep/open',data={'url':'https://example.test/unmatched','title':'Analyst','pasted_jd':AD})
    assert '/interview-prep/subjects/' in str(response.url) and 'Check interview readiness' in response.text
    failed=c.post('/interview-prep/open',data={'url':'https://example.test/missing-title','pasted_jd':AD})
    assert failed.status_code==409 and AD in failed.text and 'https://example.test/missing-title' in failed.text
