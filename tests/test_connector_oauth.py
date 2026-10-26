"""OAuth login for the connector (auth code + PKCE S256 + dynamic client registration) on the loopback JSON front.
Off by default. The consent page, code/token issuing and refresh live in Python; the TypeScript server only proxies
and asks /connector/oauth/verify. Tokens bind to the one configured person, are hashed at rest and survive a restart."""
import base64
import hashlib
import json
import secrets
import stat
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from pipeline.agentic import connector_http, mcp_oauth
from pipeline.agentic.runtime import RuntimeErrorSafe

CONNECTOR = 'x' * 40
H = {'Authorization': 'Bearer ' + CONNECTOR}
PUBLIC = 'https://jobwatch.example.test'
PASS = 'correct horse battery'
CB = 'https://chatgpt.example/callback'


def make_app(state, **kw):
    return connector_http.create_app(token=CONNECTOR, person='owner', oauth=True, public_url=PUBLIC,
                                     passphrase=PASS, oauth_state=state, **kw)


@pytest.fixture
def state(tmp_path):
    return tmp_path / 'cfg' / 'connector-oauth.json'


@pytest.fixture
def http(state):
    return TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)


def pkce():
    verifier = secrets.token_urlsafe(48)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def register(http, redirect=CB):
    r = http.post('/register', json={'redirect_uris': [redirect], 'client_name': 'Test ChatGPT', 'token_endpoint_auth_method': 'none',
                                     'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']})
    assert r.status_code == 201, r.text
    return r.json()['client_id']


def login(http, cid=None, challenge=None, passphrase=PASS):
    """Run /authorize and the consent page. Returns (client_id, verifier, code or None, response of the consent POST)."""
    cid = cid or register(http)
    verifier, challenge = (None, challenge) if challenge else pkce()
    auth = http.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': CB, 'state': 's1',
                                          'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': 'jobwatch'})
    assert auth.status_code == 302 and '/oauth/consent' in auth.headers['location']
    txn = parse_qs(urlparse(auth.headers['location']).query)['txn'][0]
    done = http.post('/oauth/consent', data={'txn': txn, 'passphrase': passphrase})
    code = parse_qs(urlparse(done.headers.get('location', '')).query).get('code', [None])[0]
    return cid, verifier, code, done


def token(http, cid, verifier, code):
    return http.post('/token', data={'grant_type': 'authorization_code', 'client_id': cid, 'code': code,
                                     'code_verifier': verifier, 'redirect_uri': CB})


def verify(http, value):
    return http.post('/connector/oauth/verify', headers=H, json={'token': value})


def issued(http):
    cid, verifier, code, _ = login(http)
    r = token(http, cid, verifier, code)
    assert r.status_code == 200, r.text
    return cid, r.json()


def test_oauth_is_off_by_default(monkeypatch):
    for name in ('JOBWATCH_CONNECTOR_OAUTH', 'JOBWATCH_MCP_PUBLIC_URL', 'JOBWATCH_MCP_OAUTH_PASSPHRASE'):
        monkeypatch.delenv(name, raising=False)
    http = TestClient(connector_http.create_app(token=CONNECTOR, person='owner'), follow_redirects=False)
    for method, path in (('get', '/.well-known/oauth-authorization-server'), ('get', '/.well-known/oauth-protected-resource'),
                         ('post', '/register'), ('get', '/authorize'), ('post', '/token'), ('post', '/revoke'),
                         ('get', '/oauth/consent'), ('post', '/connector/oauth/verify')):
        assert getattr(http, method)(path).status_code in (404, 405), path


@pytest.mark.parametrize('public,passphrase', [(None, PASS), (PUBLIC, None), (PUBLIC, 'short'), ('http://jobwatch.example.test', PASS),
                                                ('not a url', PASS)])
def test_oauth_needs_a_public_url_and_a_long_passphrase(state, public, passphrase):
    with pytest.raises(RuntimeErrorSafe) as exc:
        connector_http.create_app(token=CONNECTOR, person='owner', oauth=True, public_url=public, passphrase=passphrase,
                                  oauth_state=state)
    assert exc.value.code == 'connector_oauth_configuration_required'


def test_oauth_switch_comes_from_the_environment(monkeypatch, state):
    monkeypatch.setenv('JOBWATCH_CONNECTOR_OAUTH', '1')
    monkeypatch.setenv('JOBWATCH_MCP_PUBLIC_URL', PUBLIC)
    monkeypatch.setenv('JOBWATCH_MCP_OAUTH_PASSPHRASE', PASS)
    monkeypatch.setenv('JOBWATCH_CONNECTOR_OAUTH_STATE', str(state))
    http = TestClient(connector_http.create_app(token=CONNECTOR, person='owner'), base_url=PUBLIC)
    assert http.get('/.well-known/oauth-authorization-server').status_code == 200


def test_metadata_names_the_public_origin(http):
    meta = http.get('/.well-known/oauth-authorization-server').json()
    assert meta['issuer'].rstrip('/') == PUBLIC
    for key in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint', 'revocation_endpoint'):
        assert meta[key].startswith(PUBLIC + '/'), (key, meta[key])
    assert 'S256' in meta['code_challenge_methods_supported']
    resource = http.get('/.well-known/oauth-protected-resource').json()
    assert resource['resource'].startswith(PUBLIC) and [a.rstrip('/') for a in resource['authorization_servers']] == [PUBLIC]


def test_full_login_register_authorize_exchange_refresh(http):
    cid, tokens = issued(http)
    assert tokens['token_type'].lower() == 'bearer' and tokens['access_token'] != tokens['refresh_token']
    ok = verify(http, tokens['access_token'])
    assert ok.status_code == 200 and ok.json()['valid'] is True and ok.json()['expires_at'] > time.time()
    refreshed = http.post('/token', data={'grant_type': 'refresh_token', 'client_id': cid, 'refresh_token': tokens['refresh_token']})
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()
    assert new['access_token'] != tokens['access_token'] and verify(http, new['access_token']).json()['valid'] is True
    # the refresh token rotated: the old one is dead
    again = http.post('/token', data={'grant_type': 'refresh_token', 'client_id': cid, 'refresh_token': tokens['refresh_token']})
    assert again.status_code in (400, 401) and 'invalid_grant' in again.text


def test_wrong_passphrase_issues_no_code_and_deny_is_access_denied(http):
    cid = register(http)
    _, _, code, done = login(http, cid=cid, passphrase='nope nope nope nope')
    assert code is None and done.status_code == 200 and 'wrong' in done.text
    auth = http.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': CB, 'state': 's2',
                                          'code_challenge': pkce()[1], 'code_challenge_method': 'S256', 'scope': 'jobwatch'})
    txn = parse_qs(urlparse(auth.headers['location']).query)['txn'][0]
    denied = http.post('/oauth/consent', data={'txn': txn, 'passphrase': '', 'deny': '1'})
    assert denied.status_code == 302 and parse_qs(urlparse(denied.headers['location']).query)['error'] == ['access_denied']


def test_too_many_wrong_passphrases_end_the_attempt(http):
    cid = register(http)
    auth = http.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': CB, 'state': 's',
                                          'code_challenge': pkce()[1], 'code_challenge_method': 'S256', 'scope': 'jobwatch'})
    txn = parse_qs(urlparse(auth.headers['location']).query)['txn'][0]
    codes = [http.post('/oauth/consent', data={'txn': txn, 'passphrase': 'x' * 20}).status_code for _ in range(mcp_oauth.MAX_ATTEMPTS)]
    assert codes[-1] == 429
    assert http.post('/oauth/consent', data={'txn': txn, 'passphrase': PASS}).status_code == 400    # the right one is too late


def test_wrong_code_verifier_is_refused_and_burns_nothing_useful(http):
    cid, verifier, code, _ = login(http)
    bad = token(http, cid, secrets.token_urlsafe(48), code)
    assert bad.status_code in (400, 401) and 'invalid_grant' in bad.text and 'access_token' not in bad.text


def test_code_is_single_use(http):
    cid, verifier, code, _ = login(http)
    assert token(http, cid, verifier, code).status_code == 200
    again = token(http, cid, verifier, code)
    assert again.status_code in (400, 401) and 'invalid_grant' in again.text


def test_plain_pkce_and_unregistered_redirects_are_refused(http):
    cid = register(http)
    base = {'response_type': 'code', 'client_id': cid, 'state': 's', 'scope': 'jobwatch'}
    assert http.get('/authorize', params=base | {'redirect_uri': CB, 'code_challenge': 'plain-challenge-' * 3,
                                                  'code_challenge_method': 'plain'}).status_code in (302, 400)
    r = http.get('/authorize', params=base | {'redirect_uri': 'https://evil.example/cb', 'code_challenge': pkce()[1],
                                              'code_challenge_method': 'S256'})
    assert r.status_code == 400 and 'consent' not in r.headers.get('location', '')
    plain = http.get('/authorize', params=base | {'redirect_uri': CB, 'code_challenge': 'p' * 43, 'code_challenge_method': 'plain'})
    assert 'consent' not in plain.headers.get('location', '')


def test_expired_access_token_is_rejected(http, monkeypatch):
    _, tokens = issued(http)
    assert verify(http, tokens['access_token']).json()['valid'] is True
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + mcp_oauth.ACCESS_SECONDS + 5)
    assert verify(http, tokens['access_token']).json()['valid'] is False


def test_expired_refresh_token_is_rejected(http, monkeypatch):
    cid, tokens = issued(http)
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + mcp_oauth.REFRESH_SECONDS + 5)
    r = http.post('/token', data={'grant_type': 'refresh_token', 'client_id': cid, 'refresh_token': tokens['refresh_token']})
    assert r.status_code in (400, 401) and 'invalid_grant' in r.text


def test_revoked_tokens_are_rejected(http):
    cid, tokens = issued(http)
    assert http.post('/revoke', data={'token': tokens['access_token'], 'client_id': cid}).status_code == 200
    assert verify(http, tokens['access_token']).json()['valid'] is False
    cid, tokens = issued(http)
    assert http.post('/revoke', data={'token': tokens['refresh_token'], 'client_id': cid}).status_code == 200
    r = http.post('/token', data={'grant_type': 'refresh_token', 'client_id': cid, 'refresh_token': tokens['refresh_token']})
    assert r.status_code in (400, 401) and 'invalid_grant' in r.text


def test_verify_answers_only_to_the_connector_bearer_and_never_echoes_the_token(http):
    _, tokens = issued(http)
    body = {'token': tokens['access_token']}
    assert http.post('/connector/oauth/verify', json=body).status_code == 401
    assert http.post('/connector/oauth/verify', headers={'Authorization': 'Bearer ' + 'y' * 40}, json=body).status_code == 401
    got = verify(http, tokens['access_token'])
    assert tokens['access_token'] not in got.text and got.json()['person'] == 'owner'
    for junk in ('', 'garbage', CONNECTOR, 'a' * 5000):
        assert verify(http, junk).json() == {'valid': False}


def test_an_oauth_token_does_not_open_the_data_plane(http):
    _, tokens = issued(http)
    r = http.get('/connector/overview', headers={'Authorization': 'Bearer ' + tokens['access_token']})
    assert r.status_code == 401


def test_tokens_survive_a_restart_and_are_not_stored_in_clear(state):
    first = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    cid, tokens = issued(first)
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    raw = state.read_text()
    for secret in (tokens['access_token'], tokens['refresh_token'], PASS):
        assert secret not in raw
    assert json.loads(raw)                                      # valid json
    second = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)      # restart
    assert verify(second, tokens['access_token']).json()['valid'] is True
    r = second.post('/token', data={'grant_type': 'refresh_token', 'client_id': cid, 'refresh_token': tokens['refresh_token']})
    assert r.status_code == 200
    assert second.post('/register', json={'redirect_uris': [CB]}).status_code == 201
    # the hash of the stored value is not itself a usable token
    stored = json.loads(raw)
    some_hash = next(iter(next(v for k, v in stored.items() if k == 'access').keys()))
    assert verify(second, some_hash).json()['valid'] is False


def test_revocation_and_rotation_are_persisted(state):
    first = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    cid, tokens = issued(first)
    first.post('/revoke', data={'token': tokens['access_token'], 'client_id': cid})
    second = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    assert verify(second, tokens['access_token']).json()['valid'] is False


def test_a_damaged_state_file_starts_empty_instead_of_failing_or_trusting_it(state):
    state.parent.mkdir(parents=True)
    state.write_text('{"access": {"' + 'a' * 64 + '": {"client_id": 5')
    http = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    assert http.get('/.well-known/oauth-authorization-server').status_code == 200
    assert verify(http, 'anything').json()['valid'] is False
    _, tokens = issued(http)
    assert verify(http, tokens['access_token']).json()['valid'] is True


def test_a_loose_state_file_is_not_trusted(state):
    first = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    _, tokens = issued(first)
    state.chmod(0o644)
    second = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    assert verify(second, tokens['access_token']).json()['valid'] is False


def test_expired_tokens_are_not_kept_on_disk(state, monkeypatch):
    first = TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    issued(first)
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + mcp_oauth.REFRESH_SECONDS + 5)
    TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False)
    cid2, _ = issued(TestClient(make_app(state), base_url=PUBLIC, follow_redirects=False))
    stored = json.loads(state.read_text())
    assert len(stored['access']) == 1 and len(stored['refresh']) == 1
