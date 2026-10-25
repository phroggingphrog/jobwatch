"""Owner-confirmed Submit: Jobwatch presses final Submit only for the exact filled form the owner confirmed."""
import hashlib
import time
from datetime import datetime, timedelta, timezone

import pytest

from jobwatch import db as dbm
from jobwatch.apply import submit_confirm as sc
from jobwatch.web.browser_session import BrowserSessionError
from tests.test_browser_session import manager, submission_site  # noqa: F401 - fixtures


def _ready(manager, base, tmp_path, application_id='synthetic-app'):
    """Fill the synthetic form to the review page and build the prepared record a real fill writes."""
    from jobwatch.apply.prefill_workflow import discover_application, fill_application, plan_from_discovery
    manager.open(application_id, base)

    def fill(page):
        discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
        key = discovery['scopes'][0]['fields'][0]['key']
        return fill_application(page, {key: {'value': 'Synthetic', 'owner_verified': True}}, {},
                                plan=plan_from_discovery(discovery), expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                                screenshot_dir=tmp_path / 'review')
    assert manager.prepare(application_id, fill).result(timeout=10).status == 'ready_for_owner'
    status = manager.status(application_id)

    def record(page):
        return {'status': 'ready_for_owner', 'run_id': 'a' * 32, 'package_hash': 'p' * 64, 'attached_documents': {'cv': 'c'},
                'session_id': status['target_id'], 'owner_revision': status['owner_revision'],
                'page_url_sha256': hashlib.sha256(page.url.encode()).hexdigest(),
                'final_control': {'selector': '#submit', 'label': 'submit application', 'url': page.url, 'frame_path': []},
                'form_state': sc.form_state(page)}
    return manager.with_page(application_id, record)


def test_a_confirmed_digest_presses_the_recognised_submit_once(manager, submission_site, tmp_path):
    base, seen = submission_site
    prepared = _ready(manager, base, tmp_path)
    assert seen == [('GET', '/')]
    manager.confirm_submit('synthetic-app', sc.digest(prepared), prepared)
    manager.with_page('synthetic-app', lambda page: page.wait_for_url(base + 'submit'))
    assert seen == [('GET', '/'), ('POST', '/submit')]
    with pytest.raises(BrowserSessionError, match='submit_not_confirmable'):          # single use
        manager.confirm_submit('synthetic-app', sc.digest(prepared), prepared)
    assert seen == [('GET', '/'), ('POST', '/submit')]


def test_a_stale_or_wrong_confirmation_presses_nothing(manager, submission_site, tmp_path):
    base, seen = submission_site
    prepared = _ready(manager, base, tmp_path)
    with pytest.raises(BrowserSessionError, match='submit_confirmation_stale'):
        manager.confirm_submit('synthetic-app', '0' * 64, prepared)
    manager.with_page('synthetic-app', lambda page: page.locator('#name').evaluate("e=>{e.value='Changed'}"))
    with pytest.raises(BrowserSessionError, match='submit_confirmation_stale'):      # the form changed after the fill
        manager.confirm_submit('synthetic-app', sc.digest(prepared), prepared)
    field = manager.with_page('synthetic-app', lambda page: page.locator('#name').bounding_box())
    manager.action('synthetic-app', {'kind': 'click', 'x': field['x'] + 5, 'y': field['y'] + 5})
    with pytest.raises(BrowserSessionError, match='submit_confirmation_stale'):      # an owner touch voids it
        manager.confirm_submit('synthetic-app', sc.digest(prepared), prepared)
    manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(300))
    assert seen == [('GET', '/')] and manager.status('synthetic-app')['review_protected'] is True


def test_scrolling_to_review_keeps_the_confirmation(manager, submission_site, tmp_path):
    base, seen = submission_site
    prepared = _ready(manager, base, tmp_path)
    manager.action('synthetic-app', {'kind': 'scroll', 'dy': 200})
    assert manager.status('synthetic-app')['owner_revision'] == prepared['owner_revision']
    manager.confirm_submit('synthetic-app', sc.digest(prepared), prepared)
    manager.with_page('synthetic-app', lambda page: page.wait_for_url(base + 'submit'))
    assert seen == [('GET', '/'), ('POST', '/submit')]


def test_form_state_ignores_hidden_tokens_and_captcha_but_sees_every_selected_option(manager, submission_site, tmp_path):
    base, _ = submission_site
    manager.open('synthetic-app', base)
    def check(page):
        page.set_content('<form><input name=name value=A><input type=hidden name=csrf value=t1>'
                         '<textarea name=g-recaptcha-response>x</textarea>'
                         '<select name=s multiple><option value=a selected>a</option><option value=b>b</option></select></form>')
        before = sc.form_state(page)
        page.evaluate("document.querySelector('[name=csrf]').value='t2';document.querySelector('textarea').value='y'")
        same = sc.form_state(page) == before
        page.evaluate("document.querySelector('option[value=b]').selected=true")
        return same, sc.form_state(page) != before
    assert manager.with_page('synthetic-app', check) == (True, True)


def test_digest_needs_a_ready_fill_with_a_final_control():
    ready = {'status': 'ready_for_owner', 'run_id': 'r', 'package_hash': 'p', 'session_id': 's', 'page_url_sha256': 'u',
             'owner_revision': 0, 'attached_documents': {'cv': 'c'}, 'final_control': {'selector': '#s'}, 'form_state': 'f'}
    assert sc.digest(ready) and sc.digest(dict(ready, owner_revision=1)) != sc.digest(ready)
    assert sc.digest(dict(ready, status='needs_owner')) is None and sc.digest(dict(ready, final_control=None)) is None


def test_requests_queue_once_expire_and_settle(tmp_path):
    conn = dbm.connect(tmp_path / 'j.db')
    first = sc.queue(conn, posting_id=1, application_id=7, confirm_digest='d', approval='a1', now=1000)
    assert first['status'] == 'queued' and sc.queue(conn, posting_id=1, application_id=7, confirm_digest='d',
                                                    approval='a1', now=1001)['request_id'] == first['request_id']
    assert [r['id'] for r in sc.pending(conn, now=1000 + sc.CONFIRM_SECONDS - 1)] == [first['request_id']]
    assert sc.pending(conn, now=1000 + sc.CONFIRM_SECONDS) == []                    # 15 minutes after approval: expired
    assert sc.outcome(conn, 1)['status'] == 'expired'
    second = sc.queue(conn, posting_id=1, application_id=7, confirm_digest='d', approval='a2', now=time.time())
    sc.settle(conn, second['request_id'], 'submitted')
    assert sc.outcome(conn, 1) == {'request_id': second['request_id'], 'status': 'submitted', 'reason': None}


def test_a_pressed_request_without_a_page_verdict_becomes_unsure(tmp_path):
    conn = dbm.connect(tmp_path / 'j.db')
    assert sc.pending(conn) == [] and not conn.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone()
    rid = sc.queue(conn, posting_id=1, application_id=7, confirm_digest='d', approval='a', now=time.time())['request_id']
    sc.settle(conn, rid, 'pressed')
    sc.pending(conn, now=time.time() + sc.PRESS_WAIT_SECONDS + 1)
    assert sc.outcome(conn, 1)['status'] == 'unsure'
    rid2 = sc.queue(conn, posting_id=2, application_id=8, confirm_digest='d', approval='b', now=time.time())['request_id']
    sc.settle(conn, rid2, 'pressed')
    sc.verdict(conn, 8, 'confident')
    assert sc.outcome(conn, 2)['status'] == 'submitted'


def test_a_pressed_request_is_never_pressed_again_after_a_restart(tmp_path):
    conn = dbm.connect(tmp_path / 'j.db')
    rid = sc.queue(conn, posting_id=1, application_id=7, confirm_digest='d', approval='a', now=time.time())['request_id']
    sc.settle(conn, rid, 'pressed')
    conn.close()
    restarted = dbm.connect(tmp_path / 'j.db')                              # a new web process reads the same DB
    assert sc.pending(restarted) == []
    assert sc.queue(restarted, posting_id=1, application_id=7, confirm_digest='d', approval='a')['status'] == 'pressed'
    assert sc.pending(restarted) == []
