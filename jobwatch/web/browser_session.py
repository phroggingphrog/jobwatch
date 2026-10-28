"""On-demand, owner-controlled Chromium sessions streamed by the existing web app.

No browser starts at import. Each application owns one private persistent profile
and one Playwright thread. Snapshot attachments disconnect without closing it.
"""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import ipaddress
import math
import os
from pathlib import Path
import queue
import re
import socket
import stat
import ssl
import threading
import time
import uuid
from urllib.parse import urlsplit


_CONFIRM_TEXT = re.compile(r"thank you for (applying|your application|submitting)|thanks for applying|"
    r"application (has been |was )?(submitted|received|sent)|(successfully|we've|we have) (submitted|received) your application|"
    r"your application (is|has been) (complete|in)", re.I)
_CONFIRM_URL = re.compile(r"(?:^|[/_.-])(thank-?you|confirm(ation|ed)?|success|submitted|received|complete(d)?)(?:$|[/_.-])", re.I)


class BrowserSessionError(ValueError):
    """Safe public codes; never include URLs, controls, cookies or candidate text."""


def _public_target(url: str, *, allow_loopback: bool = False, websocket: bool = False):
    try:
        parsed = urlsplit(url)
        allowed = ('ws', 'wss') if websocket else ('http', 'https')
        if (parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or '%' in parsed.hostname or len(url) > 8192):
            raise ValueError()
        host = parsed.hostname
        if host.endswith(('.local', '.internal')) or host == 'localhost' and not allow_loopback:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme in ('https', 'wss') else 80)
        addresses = {row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        if not addresses or any(not (ipaddress.ip_address(address).is_global or
                allow_loopback and ipaddress.ip_address(address).is_loopback) for address in addresses):
            raise ValueError()
        return parsed, sorted(addresses, key=lambda address: ':' in address)[0]
    except Exception:
        raise BrowserSessionError('public_browser_url_required') from None


def _public_url(url: str, *, allow_loopback: bool = False, websocket: bool = False):
    return _public_target(url, allow_loopback=allow_loopback, websocket=websocket)[0]


def _private_dir(path: Path):
    if path.is_symlink():
        raise BrowserSessionError('private_browser_profile_required')
    if not path.exists():
        path.mkdir(mode=0o700)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise BrowserSessionError('private_browser_profile_required')
    return path


@dataclass(frozen=True)
class BrowserSnapshot:
    jpeg: bytes
    width: int
    height: int

    def __getitem__(self, key):
        return getattr(self, key)


class _Session:
    def __init__(self, application_id, url, profile, allow_loopback):
        self.application_id, self.initial_url, self.profile = application_id, url, profile
        self.allow_loopback = allow_loopback
        self.id = uuid.uuid4().hex
        self.width, self.height = 1280, 900
        self.lock = threading.RLock()
        self.tasks = queue.Queue()
        self.started = Future()
        self.state, self.automation_active = 'starting', False
        self.blocked_requests = 0
        self.cdp_url = self.target_id = None
        self.page_url_sha256 = None
        self.page = self.context = self.application_page = None
        self.last_error = ''
        self.owner_revision = 0
        self.allowed_navigation = None
        self.entry_provider = None
        self.review_protected = False
        self.owner_checkpoint = False
        self.checkpoint_until = 0
        self.owner_request = None
        self.submit_watch = self.submit_result = None
        self.thread = threading.Thread(target=self._run, name='jobwatch-browser-' + self.id[:8], daemon=True)
        self.thread.start()

    def status(self):
        with self.lock:
            return {'session_id': self.id, 'state': self.state, 'automation_active': self.automation_active,
                    'width': self.width, 'height': self.height, 'blocked_requests': self.blocked_requests,
                    'last_error': self.last_error, 'popup_active': self.page is not self.application_page,
                    'target_id': self.target_id, 'owner_revision': self.owner_revision,
                    'page_url_sha256': self.page_url_sha256, 'review_protected': self.review_protected}

    def _fetch_public(self, route):
        # Resolve once, validate every returned address, then connect to the
        # selected IP directly. The original hostname still controls TLS/SNI
        # and Host, so DNS rebinding cannot switch a checked URL to a LAN host.
        import urllib3
        request = route.request
        parsed, address = _public_target(request.url, allow_loopback=self.allow_loopback)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        options = {'timeout': urllib3.Timeout(connect=5, read=20), 'retries': False}
        if parsed.scheme == 'https':
            pool = urllib3.HTTPSConnectionPool(address, port=port, ssl_context=ssl.create_default_context(),
                server_hostname=parsed.hostname, assert_hostname=parsed.hostname, **options)
        else:
            pool = urllib3.HTTPConnectionPool(address, port=port, **options)
        try:
            headers = dict(request.all_headers())
            headers['host'] = parsed.netloc
            path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
            response = pool.urlopen(request.method, path, body=request.post_data_buffer, headers=headers,
                                    redirect=False, preload_content=True, decode_content=False)
            response_headers = {key: value for key, value in response.headers.items()
                                if key.lower() not in ('content-length', 'transfer-encoding', 'connection')}
            cookies = response.headers.getlist('set-cookie')
            if cookies:
                response_headers['set-cookie'] = '\n'.join(cookies)
            route.fulfill(status=response.status, headers=response_headers, body=response.data)
        finally:
            pool.close()

    def _guard_request(self, route):
        try:
            if self.automation_active:
                request = route.request
                initial = (self.allowed_navigation == request.url and request.method == 'GET'
                           and request.is_navigation_request() and request.frame == self.page.main_frame)
                if not initial and not self._entry_resource(request):
                    raise BrowserSessionError('unprepared_automation_request')
                if initial:
                    self.allowed_navigation = None
            elif self.review_protected:
                from jobwatch.apply.ats import challenge_provider
                request = route.request
                direct_owner_request = (self.owner_request is not None and
                    self.owner_request[:2] == (request.method, request.url) and
                    time.monotonic() < self.owner_request[2])
                verification = (self.owner_checkpoint and time.monotonic() < self.checkpoint_until
                                and challenge_provider(request.url))
                if not direct_owner_request and not verification:
                    with self.lock:
                        self.last_error = 'unapproved_browser_request'
                    raise BrowserSessionError('review_submission_protected')
                if direct_owner_request:
                    self.owner_request = None
            self._fetch_public(route)
        except Exception:
            with self.lock:
                self.blocked_requests += 1
            try:
                route.abort()
            except Exception:
                pass

    def _protect_review(self, page):
        from jobwatch.apply.prefill import _GUARD
        self.review_protected = True
        page._jobwatch_preserve_submit_guard = True
        if not getattr(page, '_jobwatch_review_script', None):
            cdp = self.context.new_cdp_session(page)
            page._jobwatch_review_script = cdp.send('Page.addScriptToEvaluateOnNewDocument', {'source':'(' + _GUARD + ')();'})['identifier']
            page._jobwatch_review_cdp = cdp
        for frame in page.frames:
            frame.evaluate(_GUARD)

    def _release_review(self, page):
        self.review_protected = False
        page._jobwatch_preserve_submit_guard = False
        script = getattr(page, '_jobwatch_review_script', None)
        if script:
            cdp = page._jobwatch_review_cdp
            try:
                cdp.send('Page.removeScriptToEvaluateOnNewDocument', {'identifier':script})
                page._jobwatch_review_script = None
            finally:
                cdp.detach()
        for frame in page.frames:
            frame.evaluate('window.__jobwatchActive=false')

    def _owner_target(self, page, action):
        frame = page.main_frame
        x, y = action.get('x'), action.get('y')
        while True:
            element = frame.evaluate_handle('p=>p.key ? document.activeElement : document.elementFromPoint(p.x,p.y)',
                {'key':action['kind']=='key','x':x,'y':y}).as_element()
            if element is None:
                return frame, None
            if element.evaluate("e=>e.tagName!=='IFRAME'"):
                target = element.evaluate_handle("e=>e.closest('button,input[type=submit],input[type=image],a,[role=button]')").as_element()
                return frame, target
            child = element.content_frame()
            if child is None:
                return frame, None
            if action['kind'] != 'key':
                box = element.bounding_box()
                metrics = element.evaluate('e=>({width:e.offsetWidth,height:e.offsetHeight,left:e.clientLeft,top:e.clientTop})')
                x = (action['x']-box['x'])*metrics['width']/box['width']-metrics['left']
                y = (action['y']-box['y'])*metrics['height']/box['height']-metrics['top']
            frame = child

    def _owner_interaction(self, page, action, callback):
        if (not self.review_protected or action['kind'] not in ('click', 'key') or
                action['kind'] == 'key' and action.get('key') != 'Enter'):
            return callback(page)
        frame, target = self._owner_target(page, action)
        from jobwatch.apply.ats import challenge_provider
        verification = bool(challenge_provider(frame.url))
        if verification and self.owner_checkpoint:
            self.checkpoint_until = time.monotonic() + 300
        if target is not None:
            label = target.evaluate(r"e=>(e.tagName==='INPUT'?e.value:(e.innerText||e.getAttribute('aria-label')||'')).trim().toLowerCase().replace(/\s+/g,' ')")
            # Verification/login buttons can also say Submit. They must never
            # authorize transmission of the employer's application form.
            if (page is self.application_page and not self.owner_checkpoint and not verification and
                    re.fullmatch(r'(submit|apply|send)( (application|now|my application))?', label)):
                self._release_review(page)
                self._arm_submit_watch(page)
                return callback(page)
            frame.evaluate('(e)=>{window.__jobwatchAllowedClick=e}', target)
            if verification:
                frame.evaluate('(e)=>{window.__jobwatchAllowedSubmit=e}', target)
            elif self.owner_checkpoint and label in ('sign in', 'log in', 'login', 'continue', 'verify', 'submit'):
                details = target.evaluate("""e=>{
                    if(e.tagName==='A' && e.hasAttribute('href') && !e.hasAttribute('onclick'))
                        return {url:e.href,method:'GET'};
                    const f=e.form;
                    if(!f || e.type!=='submit')return null;
                    return {url:new URL(e.getAttribute('formaction')||f.getAttribute('action')||location.href,document.baseURI).href,
                            method:(e.getAttribute('formmethod')||f.getAttribute('method')||'get').toUpperCase()};
                }""")
                if (details and details['method'] in ('GET', 'POST') and
                        re.search(r'(?:^|[/_.-])(login|signin|sign-in|authenticate|session|oauth|authorize)(?:$|[/_.-])', urlsplit(details['url']).path.lower())):
                    _public_url(details['url'], allow_loopback=self.allow_loopback)
                    self.owner_request = (details['method'], details['url'], time.monotonic() + 5)
                    frame.evaluate('(e)=>{window.__jobwatchAllowedSubmit=e}', target)
        try:
            return callback(page)
        finally:
            try:
                frame.evaluate('window.__jobwatchAllowedClick=null;window.__jobwatchAllowedSubmit=null')
            except Exception:
                pass

    def _arm_submit_watch(self, page):
        # The owner just pressed Submit. Watch the page afterwards for a confirmation;
        # nothing here ever clicks anything.
        try:
            text = page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
        except Exception:
            text = ''
        now = time.monotonic()
        self.submit_result = None
        self.submit_watch = {'url': page.url, 'text_before': bool(_CONFIRM_TEXT.search(text)),
                             'unsure_at': now + 6, 'until': now + 90, 'next': now + 1}

    def _check_submit(self):
        watch = self.submit_watch
        now = time.monotonic()
        if not watch or now < watch['next']:
            return
        watch['next'] = now + 1
        page = self.application_page
        try:
            url = page.url
            text = page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
        except Exception:
            text = None
        if text is not None:
            changed = url != watch['url']
            if ((_CONFIRM_TEXT.search(text) and not watch['text_before'])
                    or (changed and _CONFIRM_URL.search(urlsplit(url).path))):
                self.submit_watch, self.submit_result = None, 'confident'
                return
            if changed and now >= watch['unsure_at']:
                self.submit_watch, self.submit_result = None, 'unsure'
                return
        if now >= watch['until']:
            self.submit_watch = None

    def _entry_resource(self, request):
        if self.entry_provider != 'pageup' or request.method != 'GET':
            return False
        from jobwatch.apply.ats import PAGEUP_APPLY_HOSTS, challenge_provider
        parsed = urlsplit(request.url)
        if re.search(r'(?:^|[/_.-])(submit|finalize|finalise)(?:$|[/_.-])', parsed.path.casefold()):
            return False
        host = parsed.hostname or ''
        if request.resource_type in ('script', 'stylesheet', 'image', 'font'):
            return (host in PAGEUP_APPLY_HOSTS or host.endswith('.pageuppeople.com')
                    or host.endswith('.hcaptcha.com') or host.endswith('.recaptcha.net'))
        if (request.is_navigation_request() and request.frame.parent_frame is not None
                and (host in PAGEUP_APPLY_HOSTS or challenge_provider(request.url))):
            # Follow only the exact declared child-frame URL, never redirects,
            # main-page navigation, arbitrary fetch/XHR or any POST.
            return request.url == request.frame.frame_element().evaluate('e => e.src').split('#', 1)[0]
        return False

    def _navigate_application(self, page, url, *, provider=None):
        # The controller derives one visible Apply anchor. Permit only that
        # exact main-document GET; background writes and redirects stay closed
        # until a target-specific recipe explicitly authorizes them.
        if page is not self.page or not self.automation_active:
            raise BrowserSessionError('application_navigation_not_prepared')
        _public_url(url, allow_loopback=self.allow_loopback)
        self.allowed_navigation = url
        self.entry_provider = provider
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            if provider == 'pageup':
                page.wait_for_load_state('load', timeout=15000)
        finally:
            self.allowed_navigation = None
            self.entry_provider = None

    def _guard_socket(self, ws):
        # Browser WebSocket forwarding resolves DNS outside our pinned HTTP
        # transport. Keep it closed; an ATS needing it needs a scoped adapter.
        with self.lock:
            self.blocked_requests += 1
        # A routed socket never reaches an upstream server unless explicitly
        # connected. Keep it local and discard messages; sync close() inside
        # the route callback can deadlock Playwright during owner actions.
        ws.on_message(lambda _message: None)

    def _set_page(self, page):
        with self.lock:
            if self.automation_active:
                page.close()
                return
        previous_page = self.page
        target = getattr(page, '_jobwatch_target_id', None)
        fresh = target is None
        if fresh:
            session = self.context.new_cdp_session(page)
            try:
                target = session.send('Target.getTargetInfo')['targetInfo']['targetId']
                page._jobwatch_target_id = target
            finally:
                session.detach()
        with self.lock:
            self.page, self.target_id = page, target
            self.page_url_sha256 = hashlib.sha256(page.url.encode()).hexdigest()
            if self.application_page is None:
                self.application_page = page
            page._jobwatch_owner_revision = self.owner_revision
            if fresh:
                def navigated(frame):
                    if frame == page.main_frame and self.page is page:
                        with self.lock:
                            self.page_url_sha256 = hashlib.sha256(frame.url.encode()).hexdigest()
                page.on('framenavigated', navigated)
                def restore_opener():
                    if self.page is not page:
                        return
                    alive = [candidate for candidate in self.context.pages if candidate is not page and not candidate.is_closed()]
                    fallback = previous_page if previous_page in alive else self.application_page if self.application_page in alive else next(iter(alive), None)
                    if fallback is not None:
                        # Reuse the known target, with no yielding CDP call in a
                        # close event. The owner action returns the restored tab.
                        self._set_page(fallback)
                page.once('close', restore_opener)
                page._jobwatch_validate_request_url = lambda url: _public_url(url, allow_loopback=self.allow_loopback)
                page._jobwatch_fetch_request = self._fetch_public
                page._jobwatch_block_websocket = self._guard_socket
                page._jobwatch_navigate = lambda url, **kwargs: self._navigate_application(page, url, **kwargs)

    def _run(self):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile), headless=True, viewport={'width': self.width, 'height': self.height},
                    service_workers='block', accept_downloads=False,
                    args=['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                          '--disable-background-networking', '--disable-sync', '--no-first-run',
                          '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
                self.context = context
                context.add_init_script("""(() => {
                    for(const key of ['RTCPeerConnection','webkitRTCPeerConnection'])
                        if(window[key]) Object.defineProperty(window,key,{value:undefined,writable:false,configurable:false});
                    const deniedSocket=function(){throw new DOMException('This browser transport is unavailable','SecurityError')};
                    Object.assign(deniedSocket,{CONNECTING:0,OPEN:1,CLOSING:2,CLOSED:3});
                    Object.defineProperty(window,'WebSocket',{value:deniedSocket,writable:false,configurable:false});
                })();""")
                context.route('**/*', self._guard_request)
                context.route_web_socket('**/*', self._guard_socket)
                context.on('page', self._set_page)
                page = context.pages[0] if context.pages else context.new_page()
                self._set_page(page)
                port_file = self.profile / 'DevToolsActivePort'
                port = int(port_file.read_text().splitlines()[0])
                if not 1 <= port <= 65535:
                    raise ValueError()
                self.cdp_url = 'http://127.0.0.1:' + str(port)
                page.goto(self.initial_url, wait_until='domcontentloaded', timeout=30000)
                with self.lock:
                    self.state = 'ready'
                self.started.set_result(self.status())
                while True:
                    # Poll through Playwright to keep route/page event handlers
                    # active even when no owner command is queued.
                    try:
                        kind, callback, future = self.tasks.get_nowait()
                    except queue.Empty:
                        if not context.pages:
                            break
                        self._check_submit()
                        context.pages[0].wait_for_timeout(50)
                        continue
                    if kind == 'close':
                        context.close()
                        with self.lock:
                            self.state = 'closed'
                        future.set_result(None)
                        break
                    if future.cancelled():
                        if kind == 'prepare':
                            with self.lock:
                                self.automation_active = False
                        continue
                    try:
                        if kind == 'owner' and self.automation_active:
                            raise BrowserSessionError('automation_in_progress')
                        if kind == 'owner':
                            self.owner_revision += 1
                            self.page._jobwatch_owner_revision = self.owner_revision
                            if self.application_page is not None:
                                self.application_page._jobwatch_owner_revision = self.owner_revision
                        if kind == 'prepare':
                            self._protect_review(self.page)
                        result = callback(self.page)
                        if kind == 'prepare':
                            self.owner_checkpoint = getattr(result, 'reason', '') == 'owner_session_required'
                        if kind == 'prepare':
                            with self.lock:
                                self.automation_active = False
                        future.set_result(result)
                    except Exception as exc:
                        with self.lock:
                            self.last_error = str(exc) if isinstance(exc, BrowserSessionError) else 'browser_action_failed'
                        if kind == 'prepare':
                            with self.lock:
                                self.automation_active = False
                        future.set_exception(BrowserSessionError('browser_action_failed'))
                    finally:
                        if kind == 'prepare':
                            with self.lock:
                                self.automation_active = False
                with self.lock:
                    self.state = 'closed'
        except Exception:
            with self.lock:
                self.state = 'failed'
                self.last_error = 'browser_start_failed'
                self.automation_active = False
            if not self.started.done():
                self.started.set_exception(BrowserSessionError('browser_start_failed'))
        finally:
            if self.context:
                try:
                    self.context.close()
                except Exception:
                    pass
            while not self.tasks.empty():
                _, _, future = self.tasks.get_nowait()
                if not future.done():
                    future.set_exception(BrowserSessionError('browser_session_closed'))

    def submit(self, kind, callback):
        future = Future()
        with self.lock:
            if self.state != 'ready':
                raise BrowserSessionError('browser_session_not_ready')
            if self.automation_active:
                raise BrowserSessionError('automation_in_progress')
            if kind == 'prepare':
                if self.page is not self.application_page:
                    raise BrowserSessionError('owner_login_popup_open')
                self.last_error = ''
                self.owner_checkpoint = False
                self.automation_active = True
            self.tasks.put((kind, callback, future))
        return future


class BrowserSessionManager:
    def __init__(self, data_root: Path | None = None, *, allow_loopback: bool = False):
        # data_root=None: use the signed-in person's own folder (users.user_dir()) on every call,
        # so each person's Chromium profile and logins stay under <their folder>/browser/.
        self.data_root = Path(data_root) if data_root is not None else None
        self.allow_loopback = allow_loopback
        self.sessions = {}
        self.lock = threading.RLock()

    def _root(self) -> Path:
        if self.data_root is not None:
            return self.data_root
        from jobwatch import users
        return users.user_dir()

    def _key(self, application_id):
        if self.data_root is not None:
            return application_id
        from jobwatch import users
        return (users.current(), application_id)

    def _get(self, application_id):
        with self.lock:
            session = self.sessions.get(self._key(application_id))
        if session is None:
            raise BrowserSessionError('browser_session_not_open')
        return session

    def open(self, application_id: str, url: str):
        if not isinstance(application_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', application_id):
            raise BrowserSessionError('invalid_application_id')
        _public_url(url, allow_loopback=self.allow_loopback)
        key, root = self._key(application_id), self._root()
        with self.lock:
            existing = self.sessions.get(key)
            if existing and existing.state not in ('closed', 'failed'):
                if existing.initial_url != url:
                    raise BrowserSessionError('application_session_url_changed')
                session = existing
            else:
                if root.is_symlink() or not root.is_dir():
                    raise BrowserSessionError('private_browser_profile_required')
                browser = _private_dir(root / 'browser')
                base = _private_dir(browser / 'sessions')
                # One shared profile per person for the Accounts page and every application, so
                # logins carry over. Chromium allows one process per profile: close that person's
                # other open session first (another person's browser keeps running).
                app = _private_dir(base / hashlib.sha256(b'accounts').hexdigest())
                profile = _private_dir(app / 'profile')
                for other in list(self.sessions.values()):
                    if other.state not in ('closed', 'failed') and other.profile == profile:
                        self._close(other)
                session = _Session(application_id, url, profile, self.allow_loopback)
                self.sessions[key] = session
        return session.started.result(timeout=40)

    def status(self, application_id):
        return self._get(application_id).status()

    def take_submit_result(self, application_id):
        """'confident' | 'unsure' | None: what the page showed after the owner pressed Submit. Read once."""
        try:
            session = self._get(application_id)
        except BrowserSessionError:
            return None
        with session.lock:
            result, session.submit_result = session.submit_result, None
        return result

    def prepare(self, application_id, callback) -> Future:
        return self._get(application_id).submit('prepare', callback)

    def with_page(self, application_id, callback, *, timeout=120):
        return self._get(application_id).submit('inspect', callback).result(timeout=timeout)

    def snapshot(self, application_id) -> BrowserSnapshot:
        from playwright.sync_api import sync_playwright
        session = self._get(application_id)
        with session.lock:
            if session.state != 'ready':
                raise BrowserSessionError('browser_session_not_ready')
            endpoint, target = session.cdp_url, session.target_id
        try:
            # This connection lives entirely in the snapshot caller's thread.
            # Stopping Playwright disconnects; it does not close the owned browser.
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=5000)
                for context in browser.contexts:
                    for page in context.pages:
                        cdp = context.new_cdp_session(page)
                        try:
                            found = cdp.send('Target.getTargetInfo')['targetInfo']['targetId'] == target
                        finally:
                            cdp.detach()
                        if found:
                            jpeg = page.screenshot(type='jpeg', quality=70, timeout=5000)
                            return BrowserSnapshot(jpeg, session.width, session.height)
            raise ValueError()
        except Exception:
            raise BrowserSessionError('browser_snapshot_unavailable') from None

    def action(self, application_id, action: dict):
        session = self._get(application_id)
        if not isinstance(action, dict):
            raise BrowserSessionError('invalid_browser_action')
        kind = action.get('kind')
        if kind == 'click':
            x, y = action.get('x'), action.get('y')
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in (x, y)) or not (0 <= x < session.width and 0 <= y < session.height):
                raise BrowserSessionError('invalid_browser_coordinates')
            callback = lambda page: page.mouse.click(x, y)
        elif kind == 'close_tab':
            if session.page is session.application_page:
                raise BrowserSessionError('application_tab_must_remain_open')
            callback = lambda page: page.close()
        elif kind == 'type':
            text = action.get('text')
            if not isinstance(text, str) or len(text) > 20000:
                raise BrowserSessionError('invalid_browser_text')
            callback = lambda page: page.keyboard.insert_text(text)
        elif kind == 'key':
            key = action.get('key')
            if key not in ('Enter', 'Tab', 'Shift+Tab', 'Backspace', 'Delete', 'Escape', 'ArrowLeft', 'ArrowRight',
                           'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', 'Space', 'Control+A', 'Meta+A'):
                raise BrowserSessionError('invalid_browser_key')
            callback = lambda page: page.keyboard.press(key)
        elif kind == 'scroll':
            dx, dy = action.get('dx', 0), action.get('dy', 0)
            if any(type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 5000 for value in (dx, dy)):
                raise BrowserSessionError('invalid_browser_scroll')
            callback = lambda page: page.mouse.wheel(dx, dy)
        else:
            raise BrowserSessionError('invalid_browser_action')
        operation = callback
        session.submit('owner', lambda page: session._owner_interaction(page, action, operation)).result(timeout=15)
        return session.status()

    def close(self, application_id):
        return self._close(self._get(application_id))

    def _close(self, session):
        with session.lock:
            if session.state in ('closed', 'failed'):
                return session.status()
            session.state = 'closing'
            done = Future()
            session.tasks.put(('close', None, done))
        try:
            done.result(timeout=15)
        except Exception:
            # A currently executing preparation is bounded by its own timeouts;
            # reject new controls while its queued close awaits completion.
            pass
        return session.status()

    def close_all(self):
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            self._close(session)          # every person's sessions, wherever they were opened
