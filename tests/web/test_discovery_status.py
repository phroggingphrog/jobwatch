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
    assert 'Refresh status' in response.text and 'Hermes notification' in response.text
    assert 'Last successful phase' in response.text
    status = client.get('/api/discovery/status')
    assert status.status_code == 200
    assert status.json()['incidents'][0]['reason'] == 'deadline_exceeded'


def test_discovery_empty_state_is_not_an_error(client):
    response = client.get('/discovery-status')
    assert response.status_code == 200 and 'No unresolved failures' in response.text
