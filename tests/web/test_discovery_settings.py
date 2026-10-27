from pathlib import Path

import pytest

from jobwatch import users
from jobwatch.web.auth_routes import COOKIE, set_password
from tests.web.test_agentic import _client


def test_daily_token_allowance_finite_and_unlimited_roundtrip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    page = client.get('/preferences')
    assert page.status_code == 200
    assert 'Daily discovery token allowance' in page.text
    assert 'The 40-assessment daily cap and each run’s own limits still apply.' in page.text
    assert 'Daily token allowance mode' in page.text

    limited = client.post('/preferences/discovery-settings', data={
        'mode': 'limited', 'daily_token_ceiling': '125000'}, follow_redirects=False)
    assert limited.status_code == 303 and limited.headers['location'] == '/preferences'
    page = client.get('/preferences')
    assert 'value="limited" checked' in page.text
    assert 'value="125000"' in page.text
    assert 'Current setting: 125000 tokens per day' in page.text

    unlimited = client.post('/preferences/discovery-settings', data={
        'mode': 'unlimited', 'daily_token_ceiling': ''}, follow_redirects=False)
    assert unlimited.status_code == 303 and unlimited.headers['location'] == '/preferences'
    page = client.get('/preferences')
    assert 'value="unlimited" checked' in page.text
    assert 'Current setting: Unlimited' in page.text


@pytest.mark.parametrize('value', ['', '0', '-1', '1.5', '1e3'])
def test_invalid_daily_token_allowance_is_visible_and_not_saved(tmp_path, monkeypatch, value):
    client = _client(tmp_path, monkeypatch)
    response = client.post('/preferences/discovery-settings', data={
        'mode': 'limited', 'daily_token_ceiling': value}, follow_redirects=False)
    assert response.status_code == 400
    assert 'Enter a positive whole-number daily token limit' in response.text
    if value:
        assert f'value="{value}"' not in response.text
    page = client.get('/preferences')
    assert 'Current setting: 2000000 tokens per day' in page.text


def test_daily_token_allowance_requires_a_known_mode(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post('/preferences/discovery-settings', data={
        'mode': 'automatic', 'daily_token_ceiling': '1'}, follow_redirects=False)
    assert response.status_code == 400
    assert 'Choose Unlimited or Limited' in response.text
    assert 'value="1"' not in response.text


def test_unreadable_saved_allowance_can_be_replaced(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    config_file = Path(client.data) / 'config' / 'discovery.json'
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{broken json')

    page = client.get('/preferences')
    assert page.status_code == 200
    assert 'The saved daily allowance could not be read.' in page.text
    assert 'Current setting: Unavailable' in page.text

    response = client.post('/preferences/discovery-settings', data={'mode': 'unlimited'}, follow_redirects=False)
    assert response.status_code == 303
    assert 'Current setting: Unlimited' in client.get('/preferences').text


def test_daily_token_allowance_is_bound_to_authenticated_person(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_SESSION_SECRET', 'synthetic-session-secret')
    client = _client(tmp_path, monkeypatch)
    users.create_user_dirs('friend')
    set_password('friend', 'synthetic-password')
    login = client.post('/login', data={'username': 'friend', 'password': 'synthetic-password'},
                        follow_redirects=False)
    assert login.status_code == 303
    assert COOKIE in client.cookies

    response = client.post('/preferences/discovery-settings', data={
        'mode': 'limited', 'daily_token_ceiling': '9000', 'person': users.DEFAULT_USER},
        follow_redirects=False)
    assert response.status_code == 303
    friend_settings = Path(client.data) / 'users' / 'friend' / 'config' / 'discovery.json'
    owner_settings = Path(client.data) / 'config' / 'discovery.json'
    assert friend_settings.exists() and not owner_settings.exists()
    page = client.get('/preferences')
    assert 'Current setting: 9000 tokens per day' in page.text


def test_daily_token_allowance_rejects_cross_origin_posts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post('/preferences/discovery-settings',
        data={'mode': 'unlimited'}, headers={'origin': 'https://evil.example'}, follow_redirects=False)
    assert response.status_code == 403
