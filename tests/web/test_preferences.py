import sqlite3
from jobwatch import preference_service as service
from jobwatch.preferences import PreferenceStore
from tests.preferences.test_core import alternative, CTX
from tests.web.test_agentic import _client


def setup(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = [alternative(i) for i in (1,2,3)]
    rows[0]['title'] = '<script>synthetic</script>'
    monkeypatch.setattr(service, 'pool', lambda *args: (CTX, rows))
    return client, rows


def test_get_is_read_only_and_choice_is_explicit(tmp_path, monkeypatch):
    client, _ = setup(tmp_path, monkeypatch)
    conn = sqlite3.connect(client.data/'jobwatch.db')
    before = conn.total_changes
    page = client.get('/preferences')
    assert page.status_code == 200 and 'no data' in page.text
    assert PreferenceStore(conn).list_sets() == [] and conn.total_changes == before
    response = client.post('/preferences/new', follow_redirects=False)
    assert response.status_code == 303
    item = PreferenceStore(conn).list_sets()[0]
    page = client.get('/preferences')
    assert '&lt;script&gt;synthetic&lt;/script&gt;' in page.text
    assert not PreferenceStore(conn).get_set(item['id'])['answered']
    response = client.post(f"/preferences/{item['id']}/pick", data={'selected':'none','request_id':'owner-click'}, follow_redirects=False)
    assert response.status_code == 303
    assert PreferenceStore(conn).get_set(item['id'])['selected'] is None
    assert PreferenceStore(conn).get_set(item['id'])['answered']
    assert client.post(f"/preferences/{item['id']}/pick", data={'selected':'none','request_id':'owner-click'}, follow_redirects=False).status_code == 303
    conn.close()


def test_cross_origin_and_stale_choice_rejected(tmp_path, monkeypatch):
    client, rows = setup(tmp_path, monkeypatch)
    assert client.post('/preferences/new', headers={'origin':'https://evil.example'}, follow_redirects=False).status_code == 403
    client.post('/preferences/new')
    conn = sqlite3.connect(client.data/'jobwatch.db')
    item = PreferenceStore(conn).list_sets()[0]
    rows[0]['ad_hash'] = 'c'*64
    assert client.post(f"/preferences/{item['id']}/pick", data={'selected':'1','request_id':'stale'}, follow_redirects=False).status_code == 409
    assert not PreferenceStore(conn).get_set(item['id'])['answered']
    conn.close()


def test_three_fresh_evaluations_required(tmp_path, monkeypatch):
    client, rows = setup(tmp_path, monkeypatch)
    rows.pop()
    assert client.post('/preferences/new', follow_redirects=False).status_code == 409


def test_inspect_predictions_only_after_explicit_choice(tmp_path, monkeypatch):
    from jobwatch.web import preference_routes
    from jobwatch.preferences.model import predict_set
    from jobwatch.preferences.features import NAMES, FAMILIES
    client, rows = setup(tmp_path, monkeypatch)
    for i, row in enumerate(rows): row['features']['coverage'] = i / 2
    client.post('/preferences/new')
    conn = sqlite3.connect(client.data/'jobwatch.db')
    item = PreferenceStore(conn).list_sets()[0]
    b = [0.] * (2 * len(NAMES)); b[NAMES.index('coverage')] = 2.
    fit = {'id':'memory-only-test','context_hash':CTX,'origin':'owner','profile_hash':'b'*64,
           'draws':{'beta':[b,b], 'alpha':[[0.]*len(FAMILIES),[0.]*len(FAMILIES)]},
           'preprocessing':{'centers':[0.]*len(NAMES), 'scales':[1.]*len(NAMES),'missing_rates':[0.]*len(NAMES)},
           'n_train':20,'n_holdout':5,'holdout_log_score':-4.,'prior_log_score':-8.}
    original_status = PreferenceStore.status
    def status(self, ctx=None):
        value = original_status(self, ctx)
        return {**value, 'status':'valid','fit':fit}
    monkeypatch.setattr(PreferenceStore, 'status', status)
    calls = []
    def inspected(*args):
        calls.append(True)
        return predict_set(*args)
    monkeypatch.setattr(preference_routes, 'predict_set', inspected)
    page = client.get('/preferences')
    assert page.status_code == 200 and not calls
    client.post(f"/preferences/{item['id']}/pick", data={'selected':'3','request_id':'reviewed'}, follow_redirects=False)
    page = client.get('/preferences')
    assert page.status_code == 200 and len(calls) == 1
    assert 'Model ranking and uncertainty' in page.text
    assert 'not hiring or eligibility probability' in page.text
    assert '61.0%' in page.text and 'retrospective' in page.text
    conn.close()
