"""Owner-confirmed Submit: Jobwatch presses final Submit only for the exact filled form the owner confirmed."""
import hashlib
import time
from datetime import datetime, timedelta, timezone

import pytest

from jobwatch import db as dbm
from jobwatch.apply import submit_confirm as sc
from jobwatch.web.browser_session import BrowserSessionError
from tests.test_browser_session import manager, submission_site  # noqa: F401 - fixtures


def _ready(manager, base, tmp_path):
    """Fill the synthetic form to the review page and build the prepared record a real fill writes."""
    from jobwatch.apply.prefill_workflow import discover_application, fill_application, plan_from_discovery
    manager.open('synthetic-app', base)

    def fill(page):
        discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
        key = discovery['scopes'][0]['fields'][0]['key']
        return fill_application(page, {key: {'value': 'Synthetic', 'owner_verified': True}}, {},
                                plan=plan_from_discovery(discovery), expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                                screenshot_dir=tmp_path / 'review')
    assert manager.prepare('synthetic-app', fill).result(timeout=10).status == 'ready_for_owner'
    status = manager.status('synthetic-app')

    def record(page):
        return {'status': 'ready_for_owner', 'run_id': 'a' * 32, 'package_hash': 'p' * 64, 'attached_documents': {'cv': 'c'},
                'session_id': status['target_id'], 'owner_revision': status['owner_revision'],
                'page_url_sha256': hashlib.sha256(page.url.encode()).hexdigest(),
                'final_control': {'selector': '#submit', 'label': 'submit application', 'url': page.url, 'frame_path': []},
                'form_state': sc.form_state(page)}
    return manager.with_page('synthetic-app', record)


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
    manager.action('synthetic-app', {'kind': 'scroll', 'dy': 10})
    with pytest.raises(BrowserSessionError, match='submit_confirmation_stale'):      # any owner touch voids it
        manager.confirm_submit('synthetic-app', sc.digest(prepared), prepared)
    manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(300))
    assert seen == [('GET', '/')] and manager.status('synthetic-app')['review_protected'] is True


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
