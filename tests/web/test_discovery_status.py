from tests.web.test_web import client  # noqa: F401
from jobwatch import db as dbm
from pipeline.agentic import incidents


def test_discovery_failure_is_visible_and_page_uses_safe_codes(client):
    from jobwatch.config import load_config
    # The existing web fixture exposes its isolated database through the app's config.
    path = client.tmp / 'data' / 'jobwatch.db'
    conn = dbm.connect(path)
    incidents.report(conn, posting_id=client.ids['a'], run_id='synthetic-failure',
                     reason='deadline_exceeded', phase='evaluation')
    conn.close()
    response = client.get('/discovery-status')
    assert response.status_code == 200
    assert 'deadline exceeded' in response.text and 'Paused.' in response.text
    assert 'Refresh status' in response.text and 'Notification channel' in response.text
    assert 'Last successful phase' in response.text
    status = client.get('/api/discovery/status')
    assert status.status_code == 200
    assert status.json()['incidents'][0]['reason'] == 'deadline_exceeded'


def test_discovery_empty_state_is_not_an_error(client):
    response = client.get('/discovery-status')
    assert response.status_code == 200 and 'No unresolved failures' in response.text


def test_completed_request_shows_budget_deferral_without_claiming_an_assessment(client, monkeypatch):
    from pipeline.agentic import discovery_ops
    original = discovery_ops.status
    def status(*args):
        result = original(*args)
        result['latest_run'] = {'state': 'completed', 'error': None,
            'result': {'processed': 0, 'deferred': [{'posting_id': 1, 'reason': 'daily_budget'}]}}
        return result
    monkeypatch.setattr(discovery_ops, 'status', status)
    response = client.get('/discovery-status')
    assert response.status_code == 200
    assert '0 assessment outcomes recorded.' in response.text
    assert 'Deferred: 1 jobs (daily budget).' in response.text
    assert 'No unresolved failures' in response.text
