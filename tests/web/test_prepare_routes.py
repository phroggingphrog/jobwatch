"""Protected owner browser controls and reviewed application handoff."""
import hashlib
import json
import sqlite3
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from jobwatch.web import prepare_routes
from tests.web.test_agentic import _client, OK


class Browser:
    def __init__(self):
        self.opened = self.active = False
        self.actions, self.preparations = [], []
        self.frames = 0
    def status(self, aid):
        return {'state': 'ready' if self.opened else 'closed', 'automation_active': self.active,
                'target_id': 'synthetic-target', 'owner_revision': len(self.actions), 'page_url_sha256': 'synthetic-page'}
    def open(self, aid, url):
        self.opened = True
    def prepare(self, aid, callback):
        self.preparations.append((aid, callback))
        self.active = True
        return Future()
    def action(self, aid, action):
        if self.active:
            raise ValueError
        self.actions.append(action)
    def close(self, aid):
        self.opened = False
    def close_all(self):
        self.opened = False
    result = None
    def take_submit_result(self, aid):
        result, self.result = self.result, None
        return result
    confirms = None
    def confirm_submit(self, aid, digest, prepared):
        if self.confirms is None:
            self.confirms = []
        if getattr(self, 'refuse', None):
            from jobwatch.web.browser_session import BrowserSessionError
            raise BrowserSessionError(self.refuse)
        self.confirms.append((aid, digest))
        self.result = getattr(self, 'after_press', None)          # the page's verdict exists only after a press
        return 'pressed'
    def snapshot(self, aid):
        self.frames += 1
        self.opened = False
        return {'jpeg': b'\xff\xd8synthetic-frame\xff\xd9', 'width': 1280, 'height': 900}


def setup(tmp_path, monkeypatch, *, package=True):
    from jobwatch.web import browser_session
    browser = Browser()
    monkeypatch.setattr(browser_session, 'BrowserSessionManager', lambda *a, **k: browser)
    client = _client(tmp_path, monkeypatch)
    manifest = {'pdfs': {'cv': 'a' * 64, 'letter': 'b' * 64}, 'verification': {'review': True}}
    result = {'run_key': 'c' * 64, 'status': 'ready', 'manifest': manifest, 'cv_pdf': '/synthetic/cv.pdf',
              'letter_pdf': '/synthetic/letter.pdf', 'candidate': None, 'evaluation': None}
    monkeypatch.setattr(prepare_routes, 'latest_result', lambda conn, pid: result if package else None)
    monkeypatch.setattr(prepare_routes, 'package_is_current', lambda *a: True)
    monkeypatch.setattr(prepare_routes, 'configured_llm', lambda config: object())
    return client, browser, manifest


def pending_state(monkeypatch, manifest, questions=None):
    state = {'status': 'needs_owner', 'reason': 'missing_profile_facts', 'run_id': 'a' * 32,
             'missing': questions or [{'question_id': 'known', 'question': 'When can you start?', 'type': 'date'}],
             'review_answers': [], 'session_id': 'synthetic-target', 'owner_revision': 0,
             'page_url_sha256': 'synthetic-page', 'package_hash': hashlib.sha256(json.dumps(
                 manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()}
    monkeypatch.setattr(prepare_routes, 'latest_preparation', lambda *a: state)
    monkeypatch.setattr(prepare_routes, 'prepare_application', lambda *a, **kwargs: None)
    return state


def test_auto_fill_without_agentic_runs_table_is_nothing_ready_and_the_loop_survives_a_bad_tick(tmp_path, monkeypatch):
    import asyncio
    import time
    client, browser, _ = setup(tmp_path, monkeypatch)
    client.app.state.auto_fill_ready()                      # no agentic_runs table yet: nothing ready, no exception
    real_sleep, ticks = asyncio.sleep, []
    async def fast(delay, *a):
        return await real_sleep(0.01 if delay == 60 else delay, *a)
    def flaky():
        ticks.append(1)
        if len(ticks) == 1:
            raise sqlite3.OperationalError('no such table: agentic_runs')
    monkeypatch.setattr(asyncio, 'sleep', fast)
    client.app.state.auto_fill_ready = flaky
    with client:                                            # runs the lifespan, so the auto-fill loop
        deadline = time.monotonic() + 5
        while len(ticks) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
    assert len(ticks) >= 3


def complete_queued_intake(browser):
    browser.preparations[-1][1](SimpleNamespace(url='https://example.org/application'))


def test_viewing_job_and_candidate_pages_never_starts_browser(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch, package=False)
    for url in ('/candidate', f'/job/{client.pid}/evaluation', f'/job/{client.pid}/prepare'):
        response = client.get(url)
        assert response.status_code == 200
    assert not browser.opened and not browser.preparations
    assert 'apply by hand' not in client.get(f'/job/{client.pid}').text


def test_open_automatically_prepares_verified_application_and_displays_live_stream(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch)
    response = client.post(f'/job/{client.pid}/browser/open')
    assert response.status_code == 200
    assert len(browser.preparations) == 1
    assert f'/job/{client.pid}/browser/stream' in response.text
    assert 'Filling your application' in response.text
    assert 'data-automation-active="true"' in response.text


def test_owner_controls_require_same_origin_and_wait_for_automation(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch)
    browser.opened = True
    url = f'/job/{client.pid}/browser/action'
    assert client.post(url, json={'kind': 'key', 'key': 'Enter'}, headers={'origin': 'https://evil.invalid'}).status_code == 403
    browser.active = True
    assert client.post(url, json={'kind': 'key', 'key': 'Enter'}).status_code == 409
    assert browser.actions == []
    browser.active = False
    assert client.post(url, json={'kind': 'click', 'x': 40, 'y': 60}).status_code == 200
    assert browser.actions == [{'kind': 'click', 'x': 40, 'y': 60}]


def test_browser_stream_has_private_headers_and_actual_image_frame(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch)
    browser.opened = True
    response = client.get(f'/job/{client.pid}/browser/stream')
    assert response.status_code == 200 and b'synthetic-frame' in response.content
    assert 'multipart/x-mixed-replace' in response.headers['content-type']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-accel-buffering'] == 'no'


def test_new_package_invalidates_old_ready_preparation(tmp_path, monkeypatch):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = {'status': 'ready_for_owner', 'reason': '', 'missing': [], 'review_answers': [], 'package_hash': 'old',
             'session_id': 'synthetic-target', 'owner_revision': 0, 'page_url_sha256': 'synthetic-page'}
    monkeypatch.setattr(prepare_routes, 'latest_preparation', lambda *a: state)
    assert 'Filled and ready for your review' not in client.get(f'/job/{client.pid}/prepare').text
    state['package_hash'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert 'Filled and ready for your review' in client.get(f'/job/{client.pid}/prepare').text


def test_owner_intake_accepts_only_current_question_ids_and_restarts_filling(tmp_path, monkeypatch):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = pending_state(monkeypatch, manifest)
    saved = []
    monkeypatch.setattr(prepare_routes, 'record_owner_answer', lambda *a, **k: saved.append(k))
    url = f'/job/{client.pid}/answers'
    assert client.post(url, data={'preparation_run_id': state['run_id'], 'answer_unknown': 'invented'}).status_code == 400
    assert not saved
    response = client.post(url, data={'preparation_run_id': state['run_id'], 'answer_known': '2026-11-02'}, follow_redirects=False)
    assert response.status_code == 303
    assert not saved  # Store only after the manager locks the bound browser.
    complete_queued_intake(browser)
    assert saved == [{'question_id': 'known', 'value': '2026-11-02'}]
    assert len(browser.preparations) == 1


def test_owner_intake_preserves_multiple_choices_and_boolean_controls(tmp_path, monkeypatch):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = pending_state(monkeypatch, manifest, [
        {'question_id': 'days', 'question': 'Available days?', 'type': 'select', 'multiple': True},
        {'question_id': 'consent', 'question': 'Consent?', 'type': 'radio', 'kind': 'radio'}])
    saved = []
    monkeypatch.setattr(prepare_routes, 'record_owner_answer', lambda *a, **k: saved.append(k))
    response = client.post(f'/job/{client.pid}/answers', data={'preparation_run_id': state['run_id'],
        'answer_days': ['Monday', 'Tuesday'], 'answer_consent': 'false'}, follow_redirects=False)
    assert response.status_code == 303
    complete_queued_intake(browser)
    assert saved == [{'question_id': 'days', 'value': ['Monday', 'Tuesday']}, {'question_id': 'consent', 'value': False}]


@pytest.mark.parametrize('changed', ['profile', 'package', 'session', 'revision', 'page', 'closed', 'run', 'questions', 'status'])
def test_stale_intake_never_saves_answers_or_starts_filling(tmp_path, monkeypatch, changed):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = pending_state(monkeypatch, manifest)
    posted = {'preparation_run_id': state['run_id'], 'answer_known': '2026-11-02'}
    if changed == 'profile': monkeypatch.setattr(prepare_routes, 'package_is_current', lambda *a: False)
    elif changed == 'package': state['package_hash'] = 'changed'
    elif changed == 'session': state['session_id'] = 'old-target'
    elif changed == 'revision': state['owner_revision'] = 9
    elif changed == 'page': state['page_url_sha256'] = 'old-page'
    elif changed == 'closed': browser.opened = False
    elif changed == 'run': state['run_id'] = 'b' * 32
    elif changed == 'questions': state['missing'][0]['question_id'] = 'replaced'
    elif changed == 'status': state['status'] = 'ready_for_owner'
    saved = []
    monkeypatch.setattr(prepare_routes, 'record_owner_answer', lambda *a, **k: saved.append(k))
    assert client.post(f'/job/{client.pid}/answers', data=posted).status_code == 400
    assert not saved and not browser.preparations


@pytest.mark.parametrize('changed', ['profile', 'run', 'revision'])
def test_queued_intake_rechecks_binding_before_any_answer_save(tmp_path, monkeypatch, changed):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = pending_state(monkeypatch, manifest)
    saved = []
    monkeypatch.setattr(prepare_routes, 'record_owner_answer', lambda *a, **k: saved.append(k))
    response = client.post(f'/job/{client.pid}/answers', data={'preparation_run_id': state['run_id'],
        'answer_known': '2026-11-02'}, follow_redirects=False)
    assert response.status_code == 303
    if changed == 'profile': monkeypatch.setattr(prepare_routes, 'package_is_current', lambda *a: False)
    elif changed == 'run': state['run_id'] = 'b' * 32
    elif changed == 'revision': browser.actions.append({'kind': 'type'})
    with pytest.raises(ValueError, match='application_inputs_changed'):
        complete_queued_intake(browser)
    assert not saved


def test_missing_fact_batch_is_validated_before_any_save(tmp_path, monkeypatch):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = pending_state(monkeypatch, manifest, [
        {'question_id': 'date', 'question': 'When can you start?', 'type': 'date'},
        {'question_id': 'day', 'question': 'Which day?', 'type': 'select', 'options': [{'value': 'Monday'}]}])
    saved = []
    monkeypatch.setattr(prepare_routes, 'record_owner_answer', lambda *a, **k: saved.append(k))
    response = client.post(f'/job/{client.pid}/answers', data={'preparation_run_id': state['run_id'],
        'answer_date': '2026-11-02', 'answer_day': 'Invalid choice'})
    assert response.status_code == 400 and not saved and not browser.preparations


def test_evaluation_displays_actual_evidence_risk_and_mitigation_with_escaping(tmp_path, monkeypatch):
    client, _, _ = setup(tmp_path, monkeypatch)
    evaluation = {'global_score': 4.0, 'archetype': 'Accounting', 'dimensions': {}, 'report': {},
        'requirements': {'requirements': [{'id': 'r1', 'text': 'Reconcile ledgers', 'importance': 'high'}]},
        'matches': [{'requirement_id': 'r1', 'match': 'partial',
            'evidence': [{'source_id': 'master_resume.md', 'quote': 'Used Excel <script>unsafe()</script>'}],
            'risk': 'Payroll experience is unproven', 'mitigation': 'Show supervised practice'}]}
    monkeypatch.setattr(prepare_routes, 'latest_result', lambda *a: {'evaluation': evaluation})
    response = client.get(f'/job/{client.pid}/evaluation')
    assert response.status_code == 200
    assert 'Partial' in response.text and 'Payroll experience is unproven' in response.text
    assert 'Show supervised practice' in response.text and 'master_resume.md' in response.text
    assert 'Used Excel &lt;script&gt;unsafe()&lt;/script&gt;' in response.text
    assert '<script>unsafe()</script>' not in response.text


def test_current_profile_or_ad_change_holds_preparation(tmp_path, monkeypatch):
    from tests.test_agentic_service import world
    from pipeline.agentic.service import snapshot_inventory
    from jobwatch import adtext
    from jobwatch.apply.paths import profile_dir
    conn, config, bundle, add = world.__wrapped__(tmp_path, monkeypatch)
    try:
        add(42)
        package = {'run_key': snapshot_inventory(conn, config, posting_ids=[42])[0]['run_key']}
        from pipeline.agentic.service import observe_posting
        import time
        posting = dict(conn.execute('SELECT * FROM postings WHERE id=42').fetchone())
        observation = observe_posting(posting, deadline=time.monotonic()+30)
        monkeypatch.setattr(prepare_routes, 'latest_observation', lambda *a: observation)
        assert prepare_routes.package_is_current(conn, config, 42, package)
        adtext.save_text(conn, 42, 'Changed full job description ' * 40, 'synthetic-full'); conn.commit()
        assert not prepare_routes.package_is_current(conn, config, 42, package)
        package = {'run_key': snapshot_inventory(conn, config, posting_ids=[42])[0]['run_key']}
        profile = profile_dir() / 'cv.md'
        profile.write_text(profile.read_text() + '- A newly verified skill.\n')
        assert not prepare_routes.package_is_current(conn, config, 42, package)
    finally:
        conn.close()


def test_preparation_requires_fresh_active_source_bound_observation(tmp_path, monkeypatch):
    from tests.test_agentic_service import world
    from pipeline.agentic.service import snapshot_inventory, observe_posting
    from datetime import datetime, timezone, timedelta
    import time
    conn, config, bundle, add = world.__wrapped__(tmp_path, monkeypatch)
    try:
        add(42)
        package = {'run_key': snapshot_inventory(conn, config, posting_ids=[42])[0]['run_key']}
        posting = dict(conn.execute('SELECT * FROM postings WHERE id=42').fetchone())
        observation = observe_posting(posting, deadline=time.monotonic()+30)
        for invalid in (None,
                observation.model_copy(update={'status': 'closed'}),
                observation.model_copy(update={'checked_at': (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()}),
                observation.model_copy(update={'checked_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}),
                observation.model_copy(update={'url_hash': '0'*64}),
                observation.model_copy(update={'ad_hash': '0'*64})):
            monkeypatch.setattr(prepare_routes, 'latest_observation', lambda *a: invalid)
            assert not prepare_routes.package_is_current(conn, config, 42, package)
    finally:
        conn.close()


def test_held_or_missing_package_cannot_display_old_ready_state(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch, package=False)
    browser.opened = True
    monkeypatch.setattr(prepare_routes, 'latest_preparation', lambda *a: {'status': 'ready_for_owner', 'missing': [], 'review_answers': []})
    assert 'Filled and ready for your review' not in client.get(f'/job/{client.pid}/prepare').text


def test_prepare_post_reaches_specific_route_before_generic_job_action(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch)
    browser.opened = True
    response = client.post(f'/job/{client.pid}/prepare', follow_redirects=False)
    assert response.status_code == 303 and len(browser.preparations) == 1


def test_candidate_page_computes_local_statistics_without_model_calls(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch, package=False)
    root=client.data/'profile';root.mkdir(parents=True,exist_ok=True)
    (root/'cv.md').write_text('# Fictional\n\n## Skills\n- Prepare financial reports and reconcile financial accounts\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR',str(root))
    def forbidden(*args,**kwargs):
        raise AssertionError('GET must never call a model')
    monkeypatch.setattr(prepare_routes,'configured_llm',forbidden)
    response=client.get('/candidate')
    assert response.status_code==200
    assert 'Statistical occupation fit' in response.text
    assert 'onet31.0-anzsco2022' in response.text
    assert 'suggested path' in response.text
    assert 'Untrained: no observed outcomes' in response.text
    assert 'not hiring probability' in response.text
    assert not browser.opened


def ready_state(monkeypatch, manifest):
    state = dict(pending_state(monkeypatch, manifest), status='ready_for_owner', reason='', missing=[],
                 attached_documents={'cv': 'a' * 64}, form_state='f' * 64,
                 final_control={'selector': '#submit', 'label': 'submit application', 'url': 'https://x', 'frame_path': []})
    monkeypatch.setattr(prepare_routes, 'latest_preparation', lambda *a: state)
    return state


def test_board_confirmation_presses_submit_for_the_shown_fill_only(tmp_path, monkeypatch):
    from jobwatch.apply import submit_confirm as sc
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = ready_state(monkeypatch, manifest)
    page = client.get(f'/job/{client.pid}/prepare').text
    digest = sc.digest(state)
    assert 'Submit this application' in page and digest in page
    assert client.post(f'/job/{client.pid}/prepare/submit', data={'digest': '0' * 64}).status_code == 409
    assert browser.confirms is None                                   # a digest for another fill presses nothing
    response = client.post(f'/job/{client.pid}/prepare/submit', data={'digest': digest}, follow_redirects=False)
    conn = sqlite3.connect(client.data / 'jobwatch.db')
    aid = conn.execute('SELECT id FROM applications WHERE posting_id=?', (client.pid,)).fetchone()[0]
    assert response.status_code == 303 and browser.confirms == [(str(aid), digest)]
    kind, actor, source = conn.execute("SELECT kind, actor, source FROM application_events ORDER BY id DESC LIMIT 1").fetchone()
    assert (kind, actor, source) == ('submit_confirmed', 'owner', 'board')


def test_a_refused_board_confirmation_says_nothing_was_submitted(tmp_path, monkeypatch):
    from jobwatch.apply import submit_confirm as sc
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened, browser.refuse = True, 'submit_confirmation_stale'
    state = ready_state(monkeypatch, manifest)
    response = client.post(f'/job/{client.pid}/prepare/submit', data={'digest': sc.digest(state)})
    assert response.status_code == 409 and 'Nothing was submitted' in response.text


def test_no_submit_button_without_a_confirmable_fill(tmp_path, monkeypatch):
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    ready_state(monkeypatch, manifest).pop('final_control')
    assert 'Submit this application' not in client.get(f'/job/{client.pid}/prepare').text


def _queue(client, digest, *, now=None):
    from jobwatch.apply import submit_confirm as sc
    conn = sqlite3.connect(client.data / 'jobwatch.db')
    aid = conn.execute('SELECT id FROM applications WHERE posting_id=?', (client.pid,)).fetchone()[0]
    request = sc.queue(conn, posting_id=client.pid, application_id=aid, confirm_digest=digest, approval='appr', now=now)
    conn.close()
    return aid, request['request_id']


def _request(client, rid):
    conn = sqlite3.connect(client.data / 'jobwatch.db')
    try:
        return tuple(conn.execute('SELECT status, reason FROM submit_requests WHERE id=?', (rid,)).fetchone())
    finally:
        conn.close()


def test_an_approved_chat_request_is_pressed_through_the_live_check_and_recorded(tmp_path, monkeypatch):
    from jobwatch.apply import submit_confirm as sc
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened, browser.after_press = True, 'confident'
    state = ready_state(monkeypatch, manifest)
    aid, rid = _queue(client, sc.digest(state))
    client.app.state.process_submit_requests()
    assert browser.confirms == [(str(aid), sc.digest(state))] and _request(client, rid) == ('submitted', None)
    conn = sqlite3.connect(client.data / 'jobwatch.db')
    assert conn.execute('SELECT status FROM applications WHERE id=?', (aid,)).fetchone()[0] == 'applied'
    assert conn.execute("SELECT source FROM application_events WHERE kind='submit_confirmed'").fetchone()[0] == 'agent-api'


def test_a_stale_or_expired_chat_request_presses_nothing(tmp_path, monkeypatch):
    import time
    from jobwatch.apply import submit_confirm as sc
    client, browser, manifest = setup(tmp_path, monkeypatch)
    browser.opened = True
    state = ready_state(monkeypatch, manifest)
    _, stale = _queue(client, '0' * 64)
    client.app.state.process_submit_requests()
    assert browser.confirms is None and _request(client, stale) == ('refused', 'submit_confirmation_stale')
    conn = sqlite3.connect(client.data / 'jobwatch.db')
    conn.execute("UPDATE submit_requests SET approval='old'"); conn.commit(); conn.close()
    _, expired = _queue(client, sc.digest(state), now=time.time() - sc.CONFIRM_SECONDS - 1)
    client.app.state.process_submit_requests()
    assert browser.confirms is None and _request(client, expired) == ('expired', None)


def test_background_work_runs_once_per_person_as_that_person(tmp_path, monkeypatch):
    from jobwatch import users
    client, browser, _ = setup(tmp_path, monkeypatch)
    users.create_user_dirs('friend')
    (users.user_dir('friend') / 'jobwatch.db').touch()
    seen = []
    client.app.state.for_each_person(lambda: seen.append(users.current()))
    assert seen == [users.DEFAULT_USER, 'friend']


def test_a_submit_seen_while_no_prepare_page_is_open_is_still_recorded(tmp_path, monkeypatch):
    client, browser, _ = setup(tmp_path, monkeypatch)
    conn = sqlite3.connect(client.data / 'jobwatch.db')
    aid = conn.execute('SELECT id FROM applications WHERE posting_id=?', (client.pid,)).fetchone()[0]
    browser.opened, browser.result = True, 'confident'
    browser.open_applications = lambda: [str(aid)]
    client.app.state.settle_open_sessions()
    assert conn.execute('SELECT status FROM applications WHERE id=?', (aid,)).fetchone()[0] == 'applied'
