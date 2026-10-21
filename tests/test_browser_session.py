"""Remote browser process/session isolation; loopback synthetic pages only."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import socket
import threading

import pytest

from jobwatch.web.browser_session import BrowserSessionError, BrowserSessionManager, _public_url


@pytest.fixture
def local_site():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Set-Cookie', 'first=synthetic; Path=/')
            self.send_header('Set-Cookie', 'second=synthetic; Path=/')
            self.end_headers()
            self.wfile.write(b'''<form onsubmit="window.submits++;return false">
                <label>Synthetic name<input id=name></label><button id=submit>Submit</button>
                </form><script>window.submits=0</script>''')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/'
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def manager(tmp_path):
    instance = BrowserSessionManager(tmp_path, allow_loopback=True)
    yield instance
    instance.close_all()


def test_browser_opens_only_on_request_and_streams_owner_controls(manager, local_site):
    assert manager.sessions == {}
    state = manager.open('synthetic-app', local_site)
    assert state['state'] == 'ready'
    assert 'url' not in state
    image = manager.snapshot('synthetic-app')
    assert image.jpeg.startswith(b'\xff\xd8')
    assert image.width == 1280 and image.height == 900
    position = manager.with_page('synthetic-app', lambda page: page.locator('#name').bounding_box())
    manager.action('synthetic-app', {'kind': 'click', 'x': position['x'] + 8, 'y': position['y'] + 8})
    manager.action('synthetic-app', {'kind': 'type', 'text': 'Synthetic owner input'})
    assert manager.with_page('synthetic-app', lambda page: page.locator('#name').input_value()) == 'Synthetic owner input'
    button = manager.with_page('synthetic-app', lambda page: page.locator('#submit').bounding_box())
    assert manager.with_page('synthetic-app', lambda page: page.evaluate('window.submits')) == 0
    manager.action('synthetic-app', {'kind': 'click', 'x': button['x'] + 5, 'y': button['y'] + 5})
    assert manager.with_page('synthetic-app', lambda page: page.evaluate('window.submits')) == 1
    assert manager.close('synthetic-app')['state'] == 'closed'


def test_snapshot_stream_remains_available_during_prepare_owner_input_locked(manager, local_site):
    manager.open('synthetic-app', local_site)
    entered, release = threading.Event(), threading.Event()
    def prepare(page):
        page.locator('#name').fill('Synthetic prepared value')
        entered.set()
        release.wait(10)
        return {'status': 'ready_for_owner'}
    future = manager.prepare('synthetic-app', prepare)
    assert entered.wait(5)
    try:
        assert manager.status('synthetic-app')['automation_active'] is True
        with pytest.raises(BrowserSessionError, match='automation_in_progress'):
            manager.action('synthetic-app', {'kind': 'key', 'key': 'Enter'})
        with pytest.raises(BrowserSessionError, match='automation_in_progress'):
            manager.prepare('synthetic-app', lambda page: None)
        assert manager.snapshot('synthetic-app').jpeg.startswith(b'\xff\xd8')
    finally:
        release.set()
    assert future.result(timeout=10)['status'] == 'ready_for_owner'
    assert manager.with_page('synthetic-app', lambda page: page.evaluate('window.submits')) == 0


def test_profile_is_private_and_shared_so_logins_carry_over(manager, local_site):
    manager.open('accounts', local_site)
    manager.with_page('accounts', lambda page: page.evaluate("localStorage.setItem('synthetic','retained')"))
    profile = manager.sessions['accounts'].profile
    assert profile.stat().st_mode & 0o777 == 0o700
    manager.open('an-application', local_site)  # closes the first: one browser per profile
    assert manager.sessions['an-application'].profile == profile
    assert manager.sessions['accounts'].state == 'closed'
    assert manager.with_page('an-application', lambda page: page.evaluate("localStorage.getItem('synthetic')")) == 'retained'


def test_second_person_gets_their_own_profile_and_the_owners_stays_untouched(tmp_path, monkeypatch, local_site):
    """TASK-111.1: one person's Seek/LinkedIn logins must never land in another person's profile."""
    from jobwatch import users
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    manager = BrowserSessionManager(allow_loopback=True)          # no fixed root: per signed-in person
    try:
        digest = hashlib.sha256(b'accounts').hexdigest()   # one shared profile per person
        owner_profile = tmp_path / 'browser' / 'sessions' / digest / 'profile'

        # the owner signs in and opens a browser; his logins live in that profile
        assert manager.open('shared-app', local_site)['state'] == 'ready'
        assert manager.sessions[(users.DEFAULT_USER, 'shared-app')].profile == owner_profile
        (owner_profile / 'Default').mkdir(exist_ok=True)
        (owner_profile / 'Default' / 'Cookies').write_bytes(b'owner seek login')
        untouched = (owner_profile.stat().st_mtime_ns, sorted(p.name for p in owner_profile.iterdir()),
                     (owner_profile / 'Default' / 'Cookies').read_bytes())

        # a second person signs in and opens a session for the same application
        with users.use('friend'):
            users.create_user_dirs('friend')
            assert manager.open('shared-app', local_site)['state'] == 'ready'
            friend_profile = (tmp_path / 'users' / 'friend' / 'browser' / 'sessions' / digest / 'profile')
            assert manager.sessions[('friend', 'shared-app')].profile == friend_profile
            assert manager.status('shared-app')['state'] == 'ready'
            # work done in the browser thread runs as the person who asked for it (their DB and folders)
            assert manager.with_page('shared-app', lambda page: users.current()) == 'friend'
            friend_cookies = friend_profile / 'Default' / 'Cookies'
            assert b'owner seek login' not in (friend_cookies.read_bytes() if friend_cookies.exists() else b'')

        # both browsers are open at once; the owner's session works and his profile is unchanged
        assert manager.status('shared-app')['state'] == 'ready'
        assert (owner_profile.stat().st_mtime_ns, sorted(p.name for p in owner_profile.iterdir()),
                (owner_profile / 'Default' / 'Cookies').read_bytes()) == untouched
    finally:
        manager.close_all()


def test_subrequests_to_private_network_are_blocked(manager, local_site):
    manager.open('synthetic-app', local_site)
    # This request is aborted before making any connection to a LAN service.
    result = manager.with_page('synthetic-app', lambda page: page.evaluate('''async () => {
        try { await fetch('http://192.168.0.1/private'); return 'unexpected'; }
        catch(e) { return 'blocked'; }
    }'''))
    assert result == 'blocked'
    assert manager.status('synthetic-app')['blocked_requests'] >= 1


@pytest.mark.parametrize('url', ['http://127.0.0.1/', 'http://localhost/', 'http://192.168.0.1/',
                                'http://169.254.169.254/', 'http://[::1]/', 'file:///etc/passwd',
                                'https://user:password@example.com/'])
def test_production_browser_rejects_private_or_credential_urls(url):
    with pytest.raises(BrowserSessionError, match='public_browser_url_required'):
        _public_url(url)


def test_mixed_public_private_dns_is_refused(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(BrowserSessionError):
        _public_url('https://mixed.example.test/')


def test_pinned_transport_preserves_multiple_auth_cookies(manager, local_site):
    manager.open('synthetic-app', local_site)
    cookie = manager.with_page('synthetic-app', lambda page: page.evaluate('document.cookie'))
    assert 'first=synthetic' in cookie and 'second=synthetic' in cookie


def test_owner_login_popup_close_restores_application_and_prepare_target(manager, local_site):
    import time
    manager.open('synthetic-app', local_site)
    manager.with_page('synthetic-app', lambda page: page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button id=login type=button onclick=\"window.open(\\\'/popup\\\')\">Login</button>')"))
    button = manager.with_page('synthetic-app', lambda page: page.locator('#login').bounding_box())
    manager.action('synthetic-app', {'kind': 'click', 'x': button['x']+5, 'y': button['y']+5})
    for _ in range(100):
        if manager.status('synthetic-app')['popup_active']:
            break
        time.sleep(.02)
    assert manager.status('synthetic-app')['popup_active'] is True
    with pytest.raises(BrowserSessionError, match='owner_login_popup_open'):
        manager.prepare('synthetic-app', lambda page: None)
    assert manager.snapshot('synthetic-app').jpeg.startswith(b'\xff\xd8')
    manager.action('synthetic-app', {'kind': 'close_tab'})
    assert manager.status('synthetic-app')['popup_active'] is False
    assert manager.with_page('synthetic-app', lambda page: page.locator('#login').count()) == 1


def test_preparation_failure_is_visible_and_owner_control_is_released(manager, local_site):
    manager.open('synthetic-app', local_site)
    def fail(page):
        raise RuntimeError('SYNTHETIC_PRIVATE_ERROR')
    future = manager.prepare('synthetic-app', fail)
    with pytest.raises(BrowserSessionError):
        future.result(timeout=5)
    assert manager.status('synthetic-app')['last_error'] == 'browser_action_failed'
    assert manager.status('synthetic-app')['automation_active'] is False
    assert 'SYNTHETIC' not in json.dumps(manager.status('synthetic-app'))
    manager.action('synthetic-app', {'kind': 'key', 'key': 'Tab'})


def test_unprepared_script_requests_are_blocked_between_fill_steps(manager, local_site):
    manager.open('synthetic-app', local_site)
    def planning(page):
        return page.evaluate("""async () => {
            try { await fetch('/submit-application', {method:'POST', body:'synthetic'}); return 'sent'; }
            catch(e) { return 'blocked'; }
        }""")
    assert manager.prepare('synthetic-app', planning).result(timeout=5) == 'blocked'
    assert manager.status('synthetic-app')['blocked_requests'] >= 1


def test_prepared_apply_anchor_navigation_is_allowed_during_automation(manager, local_site):
    manager.open('synthetic-app', local_site)
    def planning(page):
        page._jobwatch_navigate(local_site + 'application')
        return page.url
    assert manager.prepare('synthetic-app', planning).result(timeout=5) == local_site + 'application'


@pytest.mark.parametrize('deferred', [False, True])
def test_strict_fill_handoff_preserves_manager_websocket_denial(manager, local_site, tmp_path, deferred):
    from datetime import datetime, timedelta, timezone
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery, fill_application
    manager.open('synthetic-app', local_site)
    def fill(page):
        page.set_content('<label>Name<input name=name></label><button type=button id=socket>Open test socket</button>')
        page.locator('#socket').evaluate("""(e,args)=>e.onclick=()=>{
            const attempt=()=>{try{window.socket=new WebSocket(args.url)}catch(error){window.denial=error.name}};
            args.deferred ? setTimeout(attempt,50) : attempt();
        }""", {'url':local_site.replace('http:', 'ws:'),'deferred':deferred})
        discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
        field = discovery['scopes'][0]['fields'][0]
        result = fill_application(page, {field['key']: {'value': 'Synthetic', 'owner_verified': True}}, {},
            plan=plan_from_discovery(discovery), expires_at=datetime.now(timezone.utc)+timedelta(minutes=1),
            screenshot_dir=tmp_path/'socket-handoff')
        return result.status, page.locator('#socket').bounding_box()
    status, button = manager.prepare('synthetic-app', fill).result(timeout=10)
    assert status == 'ready_for_owner'
    manager.action('synthetic-app', {'kind':'click','x':button['x']+5,'y':button['y']+5})
    def result(page):
        page.wait_for_function("window.denial==='SecurityError'",timeout=2000)
        return page.evaluate('window.denial')
    assert manager.with_page('synthetic-app', result) == 'SecurityError'
    assert manager.close('synthetic-app')['state'] == 'closed'


@pytest.fixture
def submission_site():
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(('GET', self.path))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'''<form id=f method=post action=/submit>
                <label>Name<input id=name name=name></label><button id=submit>Submit application</button>
                </form>''')
        def do_POST(self):
            seen.append(('POST', self.path))
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Owner submitted synthetic form')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/', seen
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize('attack', ['requestSubmit', 'fetch'])
@pytest.mark.parametrize('owner_submit', ['click', 'Enter'])
def test_review_blocks_delayed_submission_until_owner_final_control(manager, submission_site, tmp_path, attack, owner_submit):
    from datetime import datetime, timedelta, timezone
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery, fill_application
    base, seen = submission_site
    manager.open('synthetic-app', base)
    def fill(page):
        script = "document.getElementById('f').requestSubmit()" if attack=='requestSubmit' else "fetch('/submit',{method:'POST',body:'synthetic'}).catch(()=>{})"
        page.locator('#name').evaluate('(e,script)=>e.oninput=()=>setTimeout(()=>{eval(script);window.attackDone=true},300)', script)
        discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
        key = discovery['scopes'][0]['fields'][0]['key']
        return fill_application(page, {key:{'value':'Synthetic','owner_verified':True}}, {},
            plan=plan_from_discovery(discovery), expires_at=datetime.now(timezone.utc)+timedelta(minutes=1),
            screenshot_dir=tmp_path/'review')
    assert manager.prepare('synthetic-app', fill).result(timeout=10).status == 'ready_for_owner'
    manager.with_page('synthetic-app', lambda page: page.wait_for_function('window.attackDone===true'))
    assert seen == [('GET','/')]
    assert manager.status('synthetic-app')['owner_revision'] == 0
    assert manager.status('synthetic-app')['review_protected'] is True
    field = manager.with_page('synthetic-app', lambda page: page.locator('#name').bounding_box())
    manager.action('synthetic-app', {'kind':'click','x':field['x']+5,'y':field['y']+5})
    manager.action('synthetic-app', {'kind':'type','text':' owner review'})
    manager.action('synthetic-app', {'kind':'scroll','dy':10})
    manager.action('synthetic-app', {'kind':'key','key':'Enter'})
    manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(400))
    assert seen == [('GET','/')]
    assert manager.status('synthetic-app')['review_protected'] is True
    if owner_submit == 'Enter':
        manager.action('synthetic-app', {'kind':'key','key':'Tab'})
        assert manager.with_page('synthetic-app', lambda page: page.evaluate('document.activeElement.id')) == 'submit'
        manager.action('synthetic-app', {'kind':'key','key':'Enter'})
    else:
        button = manager.with_page('synthetic-app', lambda page: page.locator('#submit').bounding_box())
        manager.action('synthetic-app', {'kind':'click','x':button['x']+5,'y':button['y']+5})
    manager.with_page('synthetic-app', lambda page: page.wait_for_url(base+'submit'))
    assert seen == [('GET','/'),('POST','/submit')]
    assert manager.status('synthetic-app')['review_protected'] is False


def test_review_blocks_delayed_get_navigation_without_owner_action(manager, submission_site):
    base, seen = submission_site
    manager.open('synthetic-app', base)
    def fill(page):
        page.evaluate("setTimeout(()=>{location.href='/submit-by-get'},300)")
    manager.prepare('synthetic-app', fill).result(timeout=5)
    manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(600))
    assert seen == [('GET','/')]
    assert manager.status('synthetic-app')['blocked_requests'] >= 1
    assert manager.status('synthetic-app')['owner_revision'] == 0
    assert manager.status('synthetic-app')['review_protected'] is True



def test_owner_login_anchor_popup_stays_scoped_and_restores_protected_application(manager, submission_site):
    from types import SimpleNamespace
    base, seen = submission_site
    manager.open('synthetic-app', base)
    manager.with_page('synthetic-app', lambda page: page.evaluate("document.body.insertAdjacentHTML('beforeend','<a id=login target=_blank href=/login>Sign in</a>')"))
    manager.prepare('synthetic-app', lambda page: SimpleNamespace(reason='owner_session_required')).result(timeout=5)
    button = manager.with_page('synthetic-app', lambda page: page.locator('#login').bounding_box())
    manager.action('synthetic-app', {'kind':'click','x':button['x']+5,'y':button['y']+5})
    manager.with_page('synthetic-app', lambda page: page.wait_for_url(base+'login'))
    assert manager.status('synthetic-app')['popup_active'] is True
    assert manager.status('synthetic-app')['review_protected'] is True
    result = manager.with_page('synthetic-app', lambda page: page.evaluate("fetch('/submit',{method:'POST'}).then(()=>false).catch(()=>true)"))
    assert result is True
    assert ('POST','/submit') not in seen
    manager.action('synthetic-app', {'kind':'close_tab'})
    assert manager.status('synthetic-app')['popup_active'] is False
    assert manager.status('synthetic-app')['review_protected'] is True


def test_owner_native_login_submit_does_not_release_application_guard(manager, submission_site):
    from types import SimpleNamespace
    base, seen = submission_site
    manager.open('synthetic-app', base)
    manager.with_page('synthetic-app', lambda page: page.evaluate("f.action='/login';document.querySelector('#submit').textContent='Submit'"))
    manager.prepare('synthetic-app', lambda page: SimpleNamespace(reason='owner_session_required')).result(timeout=5)
    button = manager.with_page('synthetic-app', lambda page: page.locator('#submit').bounding_box())
    manager.action('synthetic-app', {'kind':'click','x':button['x']+5,'y':button['y']+5})
    manager.with_page('synthetic-app', lambda page: page.wait_for_url(base+'login'))
    assert ('POST','/login') in seen
    assert manager.status('synthetic-app')['review_protected'] is True
    assert ('POST','/submit') not in seen


@pytest.mark.parametrize('checkpoint', [False, True])
def test_owner_captcha_submit_allows_only_challenge_traffic(manager, submission_site, monkeypatch, checkpoint):
    from types import SimpleNamespace
    from jobwatch.apply import ats
    base, seen = submission_site
    monkeypatch.setattr(ats, 'challenge_provider', lambda url: 'hcaptcha' if '/challenge' in url else None)
    manager.open('synthetic-app', base)
    def fixture(page):
        page.evaluate("document.body.insertAdjacentHTML('beforeend','<iframe src=/challenge></iframe>')")
        page.wait_for_function("document.querySelector('iframe').contentDocument?.querySelector('#submit')")
        child = page.frames[1]
        child.locator('#submit').evaluate("e=>{e.type='button';e.onclick=()=>{fetch('/challenge-verify',{method:'POST'});fetch('/submit',{method:'POST'}).catch(()=>{});window.clicked=true}}")
        return child.locator('#submit').bounding_box()
    button = manager.with_page('synthetic-app', fixture)
    manager.prepare('synthetic-app', lambda page: SimpleNamespace(reason='owner_session_required' if checkpoint else '')).result(timeout=5)
    manager.action('synthetic-app', {'kind':'click','x':button['x']+5,'y':button['y']+5})
    manager.with_page('synthetic-app', lambda page: page.frames[1].wait_for_function('window.clicked===true'))
    manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(150))
    assert (('POST','/challenge-verify') in seen) is checkpoint
    assert ('POST','/submit') not in seen
    assert manager.status('synthetic-app')['review_protected'] is True


@pytest.mark.parametrize('reply,expected', [(b'Thank you for applying. We received it.', 'confident'), (b'Something happened', 'unsure')])
def test_owner_submit_is_detected_but_never_pressed_by_jobwatch(manager, tmp_path, reply, expected):
    import time
    from datetime import datetime, timedelta, timezone
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery, fill_application
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append('GET')
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            self.wfile.write(b'<form id=f method=post action=/done><label>Name<input id=name name=name></label><button id=submit>Submit application</button></form>')
        def do_POST(self):
            seen.append('POST')
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200); self.end_headers(); self.wfile.write(reply)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        manager.open('synthetic-app', f'http://127.0.0.1:{server.server_port}/')
        def fill(page):
            discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
            key = discovery['scopes'][0]['fields'][0]['key']
            return fill_application(page, {key: {'value': 'Synthetic', 'owner_verified': True}}, {},
                plan=plan_from_discovery(discovery), expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                screenshot_dir=tmp_path / 'review')
        assert manager.prepare('synthetic-app', fill).result(timeout=10).status == 'ready_for_owner'
        manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(1500))
        assert manager.take_submit_result('synthetic-app') is None and seen == ['GET']
        button = manager.with_page('synthetic-app', lambda page: page.locator('#submit').bounding_box())
        manager.action('synthetic-app', {'kind': 'click', 'x': button['x'] + 5, 'y': button['y'] + 5})
        result, deadline = None, time.monotonic() + 15
        while result is None and time.monotonic() < deadline:
            manager.with_page('synthetic-app', lambda page: page.wait_for_timeout(300))
            result = manager.take_submit_result('synthetic-app')
        assert result == expected and seen == ['GET', 'POST']
    finally:
        server.shutdown(); server.server_close()


@pytest.mark.parametrize('text', ['Your application is incomplete. Please correct the errors below.',
                                  'Your application is invalid'])
def test_failed_submit_text_is_not_a_confirmation(text):
    from jobwatch.web.browser_session import _CONFIRM_TEXT
    assert not _CONFIRM_TEXT.search(text)


@pytest.mark.parametrize('text', ['Thank you for applying', 'Your application is complete', 'Your application is in.',
                                  'Application has been submitted'])
def test_confirmation_text_is_recognised(text):
    from jobwatch.web.browser_session import _CONFIRM_TEXT
    assert _CONFIRM_TEXT.search(text)


@pytest.mark.parametrize('path,confirmed', [('/apply/complete-profile', False), ('/careers/confirm-email', False),
                                            ('/apply/your-details/complete', False), ('/apply/step/received-documents', False),
                                            ('/apply/thank-you', True), ('/application/submitted', True),
                                            ('/jobs/123/confirmation', True), ('/thankyou.html', True),
                                            ('/apply/success/', True)])
def test_confirmation_url_only_matches_a_final_confirmation_page(path, confirmed):
    from jobwatch.web.browser_session import _CONFIRM_URL
    assert bool(_CONFIRM_URL.search(path)) is confirmed


def test_open_applications_lists_only_the_current_persons_live_browsers(tmp_path, monkeypatch, local_site):
    from jobwatch import users
    from jobwatch.web.browser_session import BrowserSessionManager
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    manager = BrowserSessionManager(allow_loopback=True)
    try:
        manager.open('owner-app', local_site)
        with users.use('friend'):
            users.create_user_dirs('friend')
            manager.open('friend-app', local_site)
            assert manager.open_applications() == ['friend-app']
        assert manager.open_applications() == ['owner-app']
    finally:
        manager.close_all()
