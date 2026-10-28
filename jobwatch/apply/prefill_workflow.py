"""Owner-authorized application preparation; never follows page instructions.

A workflow is an explicit local recipe, not a browser agent interpreting HTML.
Every outgoing request during automation must match an exact method/URL pair.
The owner-controlled browser remains open after Playwright disconnects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import re
from email import policy
from email.parser import BytesParser
from urllib.parse import urlparse, unquote, parse_qsl

from .prefill import PrefillRefused, _GUARD, file_snapshot, private_bytes, require_unexpired


@dataclass(frozen=True)
class ApplicationFillResult:
    filled_count: int
    missing: tuple[str, ...]
    completed_steps: int
    status: str
    screenshots: tuple[str, ...]
    blocked_requests: int = 0


def _url(value):
    if not isinstance(value, str):
        raise ValueError()
    url = urlparse(value)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.fragment or (url.scheme == 'http' and url.hostname not in ('127.0.0.1', 'localhost'))):
        raise ValueError()
    return url


def _origin(value):
    url = _url(value)
    return url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80)


def session_id(page) -> str:
    """Chromium target identity survives steps but cannot select another tab."""
    session = page.context.new_cdp_session(page)
    try:
        return session.send('Target.getTargetInfo')['targetInfo']['targetId']
    finally:
        session.detach()


def private_write(path: Path, content: bytes):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
    except Exception:
        raise PrefillRefused('private output requires a new writable file') from None


def prepare_session(page, path: Path):
    """Create a private tab binding without reading any candidate values."""
    _url(page.url)
    private_write(path, json.dumps({'schema_version': 2, 'session_id': session_id(page),
                                    'initial_url': page.url}, indent=2).encode())


def validate_plan(plan: dict):
    try:
        if plan.get('schema_version') != 2 or not isinstance(plan.get('session_id'), str) or not plan['session_id']:
            raise ValueError()
        steps = plan['steps']
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ValueError()
        origins = set()
        for index, step in enumerate(steps):
            origins.add(_origin(step['url']))
            scopes = step['scopes']
            if not isinstance(scopes, list) or not scopes:
                raise ValueError()
            if not any(scope.get('frame_selector') is None and not scope.get('frame_path') for scope in scopes):
                raise ValueError()
            seen_scopes = set()
            for scope in scopes:
                frame = scope.get('frame_selector')
                frame_path = scope.get('frame_path', [])
                if not isinstance(frame_path, list):
                    raise ValueError()
                for segment in frame_path:
                    if not isinstance(segment.get('selector'), str) or not segment['selector']:
                        raise ValueError()
                    origins.add(_origin(segment['url']))
                identity = tuple((segment['selector'], segment['url']) for segment in frame_path) if frame_path else frame
                if frame is not None and (not isinstance(frame, str) or not frame):
                    raise ValueError()
                if identity in seen_scopes:
                    raise ValueError()
                seen_scopes.add(identity)
                origins.add(_origin(scope['url']))
                if frame is None and not frame_path and scope['url'] != step['url']:
                    raise ValueError()
                fields = scope['fields']
                if not isinstance(fields, dict):
                    raise ValueError()
                for key, binding in fields.items():
                    if not isinstance(key, str) or not key or not isinstance(binding, dict):
                        raise ValueError()
                    if not isinstance(binding.get('selector'), str) or not binding['selector']:
                        raise ValueError()
                    if binding.get('kind', 'native') not in ('native', 'combobox', 'checkbox', 'radio'):
                        raise ValueError()
                    options = binding.get('options', {})
                    if not isinstance(options, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v
                                                            for k, v in options.items()):
                        raise ValueError()
            if index < len(steps) - 1:
                nxt = step['next']
                if not isinstance(nxt['selector'], str) or not nxt['selector'] or nxt['target_url'] != steps[index + 1]['url']:
                    raise ValueError()
                # A page marker also supports same-URL JavaScript wizards.
                if not isinstance(steps[index + 1].get('ready_selector'), str):
                    raise ValueError()
            elif 'next' in step:
                raise ValueError()
        requests = plan['requests']
        if not isinstance(requests, list):
            raise ValueError()
        for request in requests:
            if request['method'] not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'):
                raise ValueError()
            if _origin(request['url']) not in origins:
                raise ValueError()
            if request['method'] not in ('GET', 'HEAD', 'OPTIONS') and not any(re.fullmatch(r'[0-9a-f]{64}', request.get(key, '')) for key in ('body_sha256', 'form_sha256')):
                raise ValueError()
    except Exception:
        raise PrefillRefused('invalid explicit browser workflow') from None


def authorize_workflow(manifest_path: Path, answers_path: Path, documents: dict, *, application_id: str):
    """Bind exact answer/PDF bytes to the application, tab, recipe and expiry."""
    try:
        plan = json.loads(private_bytes(manifest_path))
        validate_plan(plan)
        if (not application_id or plan['application_id'] != application_id or
                plan.get('owner_authorized') is not True or not plan.get('authorization_reference')):
            raise ValueError()
        expiry = datetime.fromisoformat(plan['expires_at'])
        require_unexpired(expiry)
        fields, uploads, metadata = file_snapshot(answers_path, documents)
        if any(plan.get(key) != value for key, value in metadata.items()):
            raise ValueError()
        roles = plan.get('document_roles', {})
        if not isinstance(roles, dict) or set(roles) != set(uploads):
            raise ValueError()
        if uploads:
            package = plan['package_manifest']
            verification = package['verification']
            if any(verification.get(key) is not True for key in ('cv_pdf', 'letter_pdf', 'claims', 'review')):
                raise ValueError()
            # This is the persisted receipt produced after verify_pdf, not an
            # invitation to trust a PDF merely because its filename ends .pdf.
            if not set(roles.values()) <= {'cv', 'letter'}:
                raise ValueError()
            for key, upload in uploads.items():
                if (roles[key] not in ('cv', 'letter') or not upload['buffer'].startswith(b'%PDF-') or
                        not upload['name'].lower().endswith('.pdf') or
                        package['pdfs'][roles[key]] != metadata['documents_sha256'][key]):
                    raise ValueError()
                upload['mimeType'] = 'application/pdf'
        # Every authorized upload must have an explicit form binding.
        bound = {key for step in plan['steps'] for scope in step['scopes'] for key in scope['fields']}
        if not set(uploads) <= bound:
            raise ValueError()
        sources = plan.get('answer_sources', {})
        effective = {}
        for key, record in fields.items():
            if not isinstance(record, dict):
                continue
            approved = record.get('owner_verified') is True
            source = record.get('source')
            source_hash = record.get('source_hash')
            if (source in ('profile', 'saved_answer', 'agent_draft') and
                    isinstance(source_hash, str) and re.fullmatch(r'[0-9a-f]{64}', source_hash) and
                    source_hash in sources.get(source, [])):
                approved = True
            effective[key] = dict(record, owner_verified=approved)
        if 'authorized_fields' in plan and plan['authorized_fields'] != sorted(
                key for key, record in effective.items() if record['owner_verified']):
            raise ValueError()
        return plan, effective, uploads, expiry
    except Exception:
        raise PrefillRefused('workflow authorization refused; no fields filled') from None


def _single(scope, selector):
    handles = scope.query_selector_all(selector)
    if len(handles) != 1:
        raise PrefillRefused('field binding is absent or ambiguous')
    return handles[0]


def _scope(page, spec):
    if spec.get('frame_path'):
        frame = page.main_frame
        for segment in spec['frame_path']:
            frame = _single(frame, segment['selector']).content_frame()
            if frame is None or frame.url != segment['url']:
                raise PrefillRefused('frame changed or is not explicitly authorized')
    elif spec.get('frame_selector') is None:
        frame = page.main_frame
    else:
        frame = _single(page, spec['frame_selector']).content_frame()
    if frame is None or frame.url != spec['url']:
        raise PrefillRefused('frame changed or is not explicitly authorized')
    return frame


def _identity(element):
    return element.evaluate('e => [e.tagName,e.id,e.getAttribute("name"),e.getAttribute("type"),e.getAttribute("role")]')


def _intact(element, expected):
    return element.evaluate('(e,x) => e.isConnected && JSON.stringify([e.tagName,e.id,e.getAttribute("name"),'
                            'e.getAttribute("type"),e.getAttribute("role")]) === JSON.stringify(x)', expected)


def _allowed_click(frame, element, check, *, allow_submit=False):
    # Never permit a submit-type button, a link, an implicit form button or
    # an element whose closest button ancestor would submit the form.
    if not allow_submit and not element.evaluate('''e => {
        const b=e.closest('button,input[type=submit],input[type=image],a');
        return !b || (b.tagName==='BUTTON' && b.type==='button');
    }'''):
        raise PrefillRefused('submit-capable controls are owner-only')
    check()
    element.evaluate('(e,allow) => { window.__jobwatchAllowedClick=e; window.__jobwatchAllowedSubmit=allow?e:null; }', allow_submit)
    try:
        element.click(timeout=1500)
    finally:
        try:
            frame.evaluate('window.__jobwatchAllowedClick = null; window.__jobwatchAllowedSubmit = null')
        except Exception:
            pass


def _fill(frame, elements, binding, record, document, check):
    kind = binding.get('kind', 'native')
    value = record.get('value') if isinstance(record, dict) and record.get('owner_verified') is True else None
    if not elements or any((not el.is_visible() and el.get_attribute('type') != 'file') or not el.is_enabled() for el in elements):
        raise ValueError()
    identities = [_identity(el) for el in elements]

    def mutate(action, *args, **kwargs):
        check()
        if any(not _intact(el, identity) for el, identity in zip(elements, identities)):
            raise PrefillRefused('field changed; stopped')
        result = action(*args, **kwargs)
        check()
        return result

    if kind == 'native':
        if all(el.get_attribute('type') == 'radio' for el in elements):
            if not isinstance(value, str) or not value:
                raise ValueError()
            matches = [el for el in elements if el.get_attribute('value') == value]
            if len(matches) != 1:
                raise ValueError()
            mutate(matches[0].check, timeout=1500)
            if not matches[0].is_checked():
                raise ValueError()
            return
        if len(elements) != 1:
            raise ValueError()
        el = elements[0]
        tag, _, _, typ, _ = identities[0]
        typ = (typ or 'text').lower()
        if typ == 'file':
            if not document:
                raise ValueError()
            mutate(el.set_input_files, document, timeout=1500)
            if el.evaluate('e => e.files.length') != 1:
                raise ValueError()
        elif typ == 'checkbox':
            if not isinstance(value, bool):
                raise ValueError()
            mutate(el.set_checked, value, timeout=1500)
            if el.is_checked() != value:
                raise ValueError()
        elif tag == 'SELECT':
            multiple = el.get_attribute('multiple') is not None
            values = value if multiple and isinstance(value, list) else [value]
            if (not values or any(not isinstance(v, str) or not v for v in values) or
                    len(set(values)) != len(values) or not multiple and not isinstance(value, str)):
                raise ValueError()
            targets = []
            for choice in values:
                options = [o for o in el.query_selector_all('option') if not o.is_disabled() and
                           (o.get_attribute('value') == choice or o.text_content() == choice)]
                if len(options) != 1:
                    raise ValueError()
                target = options[0].get_attribute('value')
                targets.append(options[0].text_content() if target is None else target)
            mutate(el.select_option, value=targets if multiple else targets[0], timeout=1500)
            selected = el.evaluate('e => Array.from(e.selectedOptions).map(o=>o.value)')
            if sorted(selected) != sorted(targets):
                raise ValueError()
        elif (tag == 'TEXTAREA' or tag == 'INPUT' and typ in ('text', 'email', 'tel', 'url', 'number', 'date')):
            if not isinstance(value, str) or not value.strip() or el.get_attribute('readonly') is not None:
                raise ValueError()
            mutate(el.fill, value, timeout=1500)
            if el.input_value() != value:
                raise ValueError()
        else:
            raise ValueError()
        if not el.evaluate('e => !e.validity || e.validity.valid'):
            raise ValueError()
        return
    if len(elements) != 1:
        raise ValueError()
    el = elements[0]
    if el.get_attribute('role') != kind:
        raise ValueError()
    if kind in ('checkbox', 'radio'):
        if not isinstance(value, bool):
            raise ValueError()
        current = el.get_attribute('aria-checked')
        if current not in ('true', 'false'):
            raise ValueError()
        if (current == 'true') != value:
            if kind == 'radio' and value is False:
                raise ValueError()
            mutate(_allowed_click, frame, el, check)
        if el.get_attribute('aria-checked') != str(value).lower():
            raise ValueError()
    else:
        if not isinstance(value, str) or value not in binding.get('options', {}):
            raise ValueError()
        mutate(_allowed_click, frame, el, check)
        option = _single(frame, binding['options'][value])
        if option.get_attribute('role') != 'option':
            raise ValueError()
        mutate(_allowed_click, frame, option, check)
        # A supported custom widget must expose its selected state. No guess
        # from nearby prose, hidden candidate values or generated answers.
        selected = option.get_attribute('aria-selected') == 'true'
        if not selected and el.evaluate('e => e.tagName === "INPUT"'):
            selected = el.input_value() in (value, binding.get('option_labels', {}).get(value))
        if not selected:
            raise ValueError()


def fill_application(page, answers: dict, documents: dict, *, plan: dict,
                     expires_at: datetime, screenshot_dir: Path) -> ApplicationFillResult:
    validate_plan(plan)
    require_unexpired(expires_at)
    if page.url != plan['steps'][0]['url'] or session_id(page) != plan['session_id']:
        raise PrefillRefused('exact authorized application tab required')
    if page.context.service_workers:
        raise PrefillRefused('service workers require a fresh owner browser context')
    try:
        screenshot_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        if screenshot_dir.is_symlink() or not screenshot_dir.is_dir() or stat.S_IMODE(screenshot_dir.stat().st_mode) != 0o700:
            raise ValueError()
    except Exception:
        raise PrefillRefused('private snapshot directory required') from None
    allowed = {(r['method'], r['url'], r.get('body_sha256'), r.get('form_sha256')) for r in plan['requests']}
    blocked = []
    current_step = None
    completed = filled = 0
    missing = []
    screenshots = []

    def check():
        require_unexpired(expires_at)
        if page.url != current_step['url'] or page.context.service_workers:
            raise PrefillRefused('application changed; stopped')
        if blocked:
            raise PrefillRefused('unapproved browser transmission blocked; stopped')

    def route_request(route):
        try:
            require_unexpired(expires_at)
        except PrefillRefused:
            blocked.append(True)
            route.abort()
            return
        request = route.request
        body = request.post_data_buffer
        body_hash = hashlib.sha256(body or b'').hexdigest() if body is not None or request.method not in ('GET', 'HEAD', 'OPTIONS') else None
        form_hash = None
        if body is not None and request.headers.get('content-type', '').startswith('multipart/form-data'):
            try:
                form_hash = multipart_digest(body, request.headers['content-type'])
            except PrefillRefused:
                pass
        permitted = ((request.method, request.url, body_hash, None) in allowed or
                     form_hash is not None and (request.method, request.url, None, form_hash) in allowed)
        if permitted:
            validator = getattr(page, '_jobwatch_validate_request_url', None)
            if validator:
                try:
                    validator(request.url)
                except Exception:
                    blocked.append(True)
                    route.abort()
                    return
            pinned_fetch = getattr(page, '_jobwatch_fetch_request', None)
            if pinned_fetch:
                try:
                    pinned_fetch(route)
                except Exception:
                    blocked.append(True)
                    route.abort()
                return
            # continue_() may let redirected traffic bypass this handler;
            # fetch(max_redirects=0) keeps every redirect separately checked.
            try:
                response = route.fetch(max_redirects=0, timeout=15000)
                route.fulfill(response=response)
            except Exception:
                blocked.append(True)
                route.abort()
        else:
            blocked.append(True)
            route.abort()

    def snapshot(index):
        path = screenshot_dir / f'step-{index + 1:02d}.png'
        private_write(path, page.screenshot(full_page=True))
        screenshots.append(str(path))

    # Attach read-only runtime inspection before any candidate mutation. Existing
    # workers/sockets could transmit outside page HTTP interception.
    cdp = page.context.new_cdp_session(page)
    contexts = []
    cdp.on('Runtime.executionContextCreated', lambda event: contexts.append(event['context']))
    cdp.send('Runtime.enable')
    try:
        for context in contexts:
            if not context.get('auxData', {}).get('isDefault'):
                continue
            for constructor in ('WebSocket', 'Worker', 'SharedWorker'):
                obj = cdp.send('Runtime.evaluate', {'expression': constructor + '.prototype',
                    'contextId': context['id'], 'objectGroup': 'jobwatch-inspect'})
                object_id = obj.get('result', {}).get('objectId')
                if not object_id:
                    continue
                objects = cdp.send('Runtime.queryObjects', {'prototypeObjectId': object_id,
                                                           'objectGroup': 'jobwatch-inspect'})
                count = cdp.send('Runtime.callFunctionOn', {'objectId': objects['objects']['objectId'],
                    'functionDeclaration': 'function(){ return this.filter(x => !("readyState" in x) || x.readyState < 2).length; }',
                    'returnByValue': True})['result'].get('value', 0)
                if count:
                    raise PrefillRefused('existing background transports require a fresh owner browser tab')
    except Exception:
        cdp.detach()
        raise PrefillRefused('background browser transport inspection refused') from None
    finally:
        try:
            cdp.send('Runtime.releaseObjectGroup', {'objectGroup': 'jobwatch-inspect'})
        except Exception:
            pass
    page.route('**/*', route_request)
    websocket_active = True
    def websocket_route(ws):
        if websocket_active:
            blocked.append(True)
            ws.on_message(lambda _message: None)
        elif getattr(page, '_jobwatch_block_websocket', None):
            page._jobwatch_block_websocket(ws)
        else:
            ws.connect_to_server()
    page.route_web_socket('**/*', websocket_route)
    # Prevent an existing worker from bypassing request interception. A newly
    # registered worker is blocked at registration while automation owns page.
    worker_guard = '''() => {
        if (navigator.serviceWorker && !window.__jobwatchRegister) {
            window.__jobwatchRegister = navigator.serviceWorker.register.bind(navigator.serviceWorker);
            navigator.serviceWorker.register = () => Promise.reject(new Error('Owner browser action required'));
        }
        for(const key of ['Worker','SharedWorker']) if(window[key] && !window['__jobwatch'+key]) {
            window['__jobwatch'+key]=window[key];
            window[key]=function(){throw new Error('Owner browser action required')};
        }
    }'''
    init = '(' + _GUARD + ')();(' + worker_guard + ')();'
    script_id = cdp.send('Page.addScriptToEvaluateOnNewDocument', {'source': init})['identifier']
    try:
        for index, step in enumerate(plan['steps']):
            current_step = step
            check()
            if step.get('ready_selector'):
                page.wait_for_selector(step['ready_selector'], state='visible', timeout=5000)
            scopes = [(spec, _scope(page, spec)) for spec in step['scopes']]
            snapshots = []
            for spec, frame in scopes:
                frame.evaluate(_GUARD)
                frame.evaluate(worker_guard)
                fields = []
                covered = set()
                for key, binding in spec['fields'].items():
                    elements = frame.query_selector_all(binding['selector'])
                    if any(el.get_attribute('type') == 'password' for el in elements):
                        raise PrefillRefused('password targets are owner-only')
                    fields.append((key, binding, elements, [_identity(el) for el in elements]))
                    for el in elements:
                        covered.add(el.evaluate('e => { if(!e.__jobwatchFieldId) e.__jobwatchFieldId=crypto.randomUUID(); return e.__jobwatchFieldId; }'))
                snapshots.append((spec, frame, fields, covered))
            for spec, frame, fields, covered in snapshots:
                def check_scope():
                    check()
                    if frame.url != spec['url'] or _scope(page, spec) != frame:
                        raise PrefillRefused('frame changed; stopped')
                ordered = sorted(fields, key=lambda item: item[1].get('kind') == 'radio' and answers.get(item[0], {}).get('value') is False)
                for key, binding, elements, identities in ordered:
                    check_scope()
                    try:
                        current = frame.query_selector_all(binding['selector'])
                        if len(current) != len(elements) or any(not _intact(el, identity) for el, identity in zip(elements, identities)):
                            raise ValueError()
                        _fill(frame, elements, binding, answers.get(key), documents.get(key), check_scope)
                        filled += 1
                    except PrefillRefused:
                        raise
                    except Exception:
                        missing.append(key)
                for key, binding, elements, identities in fields:
                    if binding.get('kind') == 'radio' and key not in missing:
                        record = answers.get(key, {})
                        if (len(elements) != 1 or not _intact(elements[0], identities[0])
                                or elements[0].get_attribute('aria-checked') != str(record.get('value')).lower()):
                            missing.append(key)
                # Unmapped visible fields stay visible in the owner handoff.
                unknown = frame.eval_on_selector_all('input,select,textarea,[role=combobox],[role=checkbox],[role=radio]', '''els => els.filter(e =>
                    !['hidden','submit','button','reset','image'].includes(e.type) && !['h-captcha-response','g-recaptcha-response'].includes(e.name) && !e.disabled &&
                    !!e.getClientRects().length).map((e,i) => ({token:e.__jobwatchFieldId,
                    name:e.getAttribute('name') || e.id || 'unmapped-field-'+(i+1)}))''')
                missing.extend(c['name'] for c in unknown if c.get('token') not in covered)
            check()
            bound_frames = {frame for _, frame in scopes}
            from .ats import challenge_provider, challenge_complete
            if any(frame not in bound_frames and frame.frame_element().is_visible()
                   and not (challenge_provider(frame.url) and challenge_complete(frame, challenge_provider(frame.url)))
                   for frame in page.frames if frame != page.main_frame):
                missing.append('unmapped-frame')
            snapshot(index)
            if missing:
                break
            completed += 1
            if 'next' in step:
                nxt = _single(page, step['next']['selector'])
                native_submit = nxt.evaluate('e => e.type === "submit"')
                if native_submit:
                    if step['next'].get('allow_form_submit') is not True:
                        raise PrefillRefused('multi-step navigation requires an approved Next control')
                    navigation = prepare_next_navigation(page, step['next']['selector'])
                    request = navigation['request']
                    if (navigation['next']['target_url'] != step['next']['target_url'] or
                            (request['method'], request['url'], request.get('body_sha256'), request.get('form_sha256')) not in allowed):
                        raise PrefillRefused('prepared Next request changed; stopped')
                elif nxt.evaluate('e => e.tagName !== "BUTTON" || e.getAttribute("type") !== "button"'):
                    raise PrefillRefused('multi-step navigation requires a supported Next control')
                _allowed_click(page.main_frame, nxt, check, allow_submit=native_submit)
                page.wait_for_url(step['next']['target_url'], timeout=5000)
        status = 'ready_for_owner' if completed == len(plan['steps']) and not missing else 'needs_owner'
        return ApplicationFillResult(filled, tuple(dict.fromkeys(missing)), completed, status, tuple(screenshots), len(blocked))
    except Exception as exc:
        # Preserve a private image of the partially filled page for review.
        try:
            private_write(screenshot_dir / 'stopped.png', page.screenshot(full_page=True))
        except Exception:
            pass
        if isinstance(exc, PrefillRefused):
            raise
        raise PrefillRefused('browser workflow stopped; inspect owner browser') from None
    finally:
        websocket_active = False
        page.unroute('**/*', route_request)
        try:
            cdp.send('Page.removeScriptToEvaluateOnNewDocument', {'identifier': script_id})
        finally:
            cdp.detach()
        # Release submission only once our code has finished; never click it.
        for frame in page.frames:
            try:
                frame.evaluate('''preserve => { window.__jobwatchActive=preserve; window.__jobwatchAllowedClick=null; window.__jobwatchAllowedSubmit=null;
                    if(window.__jobwatchRegister) { navigator.serviceWorker.register=window.__jobwatchRegister;
                        delete window.__jobwatchRegister; }
                    for(const key of ['Worker','SharedWorker']) if(window['__jobwatch'+key]) {
                        window[key]=window['__jobwatch'+key]; delete window['__jobwatch'+key];
                    } }''', bool(getattr(page, '_jobwatch_preserve_submit_guard', False)))
            except Exception:
                pass


_DISCOVER = r'''() => {
    const selector = e => {
        if(e.id && document.querySelectorAll('#'+CSS.escape(e.id)).length===1) return '#'+CSS.escape(e.id);
        const parts=[];
        for(let p=e;p && p.nodeType===1;p=p.parentElement) {
            const peers=p.parentElement ? Array.from(p.parentElement.children).filter(x=>x.tagName===p.tagName) : [p];
            parts.unshift(p.tagName.toLowerCase()+':nth-of-type('+(peers.indexOf(p)+1)+')');
        }
        return parts.join(' > ');
    };
    const text = e => {
        if(!e) return '';
        const clone=e.cloneNode(true);
        clone.querySelectorAll('input,textarea,select,option,script,style').forEach(x=>x.remove());
        return (clone.textContent || '').trim().slice(0,2000);
    };
    const label = e => e.getAttribute('aria-label') ||
        (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>text(document.getElementById(id))).join(' ').trim() ||
        Array.from(e.labels || []).map(text).join(' ') ||
        (['radio','checkbox'].includes(e.getAttribute('role')) ? text(e) : '') ||
        text(e.closest('fieldset')?.querySelector('legend')) ||
        e.getAttribute('placeholder') || (e.tagName==='BUTTON' ? text(e) : '') || e.name || e.id || '';
    const elements = Array.from(document.querySelectorAll('input,select,textarea,[role=combobox],[role=checkbox],[role=radio]'));
    const controls=[]; const radios=new Set();
    for(const e of elements) {
        if(['h-captcha-response','g-recaptcha-response'].includes(e.name)) continue;
        if(['hidden','submit','button','reset','image'].includes(e.type) && !e.getAttribute('role')) continue;
        if(e.disabled || (!e.getClientRects().length && e.type !== 'file')) continue;
        const role=e.getAttribute('role');
        const type=role || (e.tagName==='INPUT' ? e.type : e.tagName.toLowerCase());
        if(type==='password') { controls.push({selector:selector(e),name:e.name||e.id,type,question:label(e),required:!!e.required,options:[],owner_only:true}); continue; }
        let options=[]; let target=selector(e); let question=label(e);
        if(role==='radio') {
            const group=e.closest('[role=radiogroup],fieldset');
            const context=group && (group.getAttribute('aria-label') ||
                (group.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>text(document.getElementById(id))).join(' ').trim() ||
                text(group.querySelector(':scope > legend')));
            if(context) question=context+' (option: '+label(e)+')';
        }
        if(type==='radio' && !role && e.name) {
            if(radios.has(e.name)) continue;
            radios.add(e.name);
            const group=e.closest('fieldset,[role=radiogroup]');
            const groupQuestion=group && (group.getAttribute('aria-label') ||
                (group.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>text(document.getElementById(id))).join(' ').trim() ||
                text(group.querySelector(':scope > legend')));
            // A radio's own label describes its choice (Yes/No), not the
            // question. Keep group context separate from each option label.
            question=groupQuestion || e.name;
            const peers=elements.filter(x=>x.type==='radio' && x.name===e.name);
            target='input[type="radio"][name="'+CSS.escape(e.name)+'"]';
            options=peers.map(x=>({value:x.getAttribute('value'),label:label(x),selector:selector(x)}));
        } else if(e.tagName==='SELECT') {
            options=Array.from(e.options).filter(o=>!o.disabled).map(o=>({value:o.getAttribute('value') ?? o.textContent,label:o.textContent.trim()}));
        } else if(role==='combobox') {
            const list=document.getElementById(e.getAttribute('aria-controls') || e.getAttribute('aria-owns') || '');
            options=Array.from((list || e).querySelectorAll('[role=option]')).map(o=>({value:o.getAttribute('data-value') || text(o),label:text(o),selector:selector(o)}));
        }
        controls.push({selector:target,name:e.name||e.id,type,kind:role && ['combobox','checkbox','radio'].includes(role)?role:'native',
            question,required:e.required===true || e.getAttribute('aria-required')==='true',maxlength:e.maxLength>0?e.maxLength:null,multiple:e.multiple===true,options});
    }
    const buttons=Array.from(document.querySelectorAll('button,input[type=submit],[role=button]'))
        .filter(e=>!e.disabled && e.getClientRects().length)
        .map(e=>({selector:selector(e),label:text(e)||e.getAttribute('aria-label')||(e.tagName==='INPUT'?e.value:'')||'',
            non_submit:e.tagName==='BUTTON' && e.getAttribute('type')==='button'}));
    return {controls,buttons};
}'''


def discover_application(page, *, allowed_hosts: list[str]) -> dict:
    """Read questions, options and selectors from current page and child frames.

    Never reads text input values, textarea contents, checked state, selected
    options, uploads or credentials. Text from the page is untrusted evidence.
    """
    from .prefill import require_host
    require_host(page, allowed_hosts)
    initial_url = page.url
    result = {'schema_version': 2, 'session_id': session_id(page), 'url': initial_url, 'scopes': [], 'owner_challenges': []}
    for index, frame in enumerate(page.frames):
        if frame.url == 'about:blank':
            continue
        from .ats import challenge_provider, challenge_complete
        provider = challenge_provider(frame.url) if frame.parent_frame is not None else None
        if provider:
            if frame.frame_element().is_visible() and not challenge_complete(frame, provider) and provider not in result['owner_challenges']:
                result['owner_challenges'].append(provider)
            # These external verification widgets are owner-only. Their URL
            # fragments and response controls are never application bindings.
            continue
        try:
            _url(frame.url)
        except ValueError:
            raise PrefillRefused('unsupported frame URL requires an explicit adapter') from None
        if urlparse(frame.url).hostname not in allowed_hosts:
            raise PrefillRefused('frame hostname requires explicit authorization')
        # Build the exact frame chain; no wildcard host or frame matching.
        path = []
        cursor = frame
        while cursor.parent_frame is not None:
            element = cursor.frame_element()
            selector = element.evaluate('''e => {
                if(e.id && e.ownerDocument.querySelectorAll('#'+CSS.escape(e.id)).length===1) return '#'+CSS.escape(e.id);
                const parts=[];
                for(let p=e;p && p.nodeType===1;p=p.parentElement) {
                    const peers=p.parentElement ? Array.from(p.parentElement.children).filter(x=>x.tagName===p.tagName) : [p];
                    parts.unshift(p.tagName.toLowerCase()+':nth-of-type('+(peers.indexOf(p)+1)+')');
                }
                return parts.join(' > ');
            }''')
            path.insert(0, {'selector': selector, 'url': cursor.url})
            cursor = cursor.parent_frame
        data = frame.evaluate(_DISCOVER)
        scope = {'url': frame.url, 'frame_path': path, 'fields': [], 'buttons': data['buttons']}
        counts = {}
        for control in data['controls']:
            stem = control.get('name') or 'field'
            counts[stem] = counts.get(stem, 0) + 1
            control['key'] = f'scope-{index}:{stem}:{counts[stem]}'
            scope['fields'].append(control)
        result['scopes'].append(scope)
    if page.url != initial_url:
        raise PrefillRefused('application changed during discovery')
    return result


def plan_from_discovery(discovery: dict) -> dict:
    """Build all current field bindings automatically for the answer planner.

    Navigation and network permissions are added by the trusted preparation
    flow after inspecting the actual site's steps. No HTML is an instruction.
    """
    if discovery.get('owner_challenges'):
        raise PrefillRefused('owner verification required before preparing a workflow')
    scopes = []
    for source in discovery['scopes']:
        fields = {}
        for control in source['fields']:
            if control.get('owner_only'):
                continue
            binding = {'selector': control['selector'], 'kind': control['kind']}
            if control['kind'] == 'combobox':
                binding['options'] = {option['value']: option['selector'] for option in control['options']}
                binding['option_labels'] = {option['value']: option['label'] for option in control['options']}
            fields[control['key']] = binding
        scopes.append({'url': source['url'], 'frame_path': source['frame_path'], 'fields': fields})
    return {'schema_version': 2, 'session_id': discovery['session_id'],
            'steps': [{'url': discovery['url'], 'scopes': scopes}], 'requests': []}


def _form_digest(fields):
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def multipart_digest(body: bytes, content_type: str) -> str:
    """Hash transmitted form semantics, preserving field order/duplicates/files."""
    try:
        if len(body) > 25 * 1024 * 1024 or '\r' in content_type or '\n' in content_type:
            raise ValueError()
        message = BytesParser(policy=policy.default).parsebytes(
            ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
        if not message.is_multipart() or message.defects:
            raise ValueError()
        fields = []
        for part in message.iter_parts():
            if part.is_multipart() or part.defects or part.get_content_disposition() != 'form-data':
                raise ValueError()
            name = part.get_param('name', header='content-disposition')
            if not isinstance(name, str):
                raise ValueError()
            payload = part.get_payload(decode=True)
            filename = part.get_filename()
            if filename is None:
                fields.append({'name': name, 'value': payload.decode('utf-8')})
            else:
                fields.append({'name': name, 'filename': filename, 'content_type': part.get_content_type(),
                               'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
        return _form_digest(fields)
    except Exception:
        raise PrefillRefused('multipart Next request is not the prepared form') from None


def prepare_next_navigation(page, selector: str) -> dict:
    """Derive one non-final native Next request from the already filled form.

    Native URL-encoded and multipart forms are supported. Multipart permission
    binds each text value, file name/type/size/SHA256 and the exact submitter,
    independently of the browser's random MIME boundary. No click occurs here.
    """
    el = _single(page, selector)
    details = el.evaluate(r'''async e => {
        const label=(e.tagName==='INPUT'?e.value:e.textContent).trim().toLowerCase().replace(/\s+/g,' ');
        const safe=['next','next step','continue','continue application','save and continue','save & continue'].includes(label);
        const form=e.form, attr=(node,key)=>Element.prototype.getAttribute.call(node,key);
        if(!safe || !form || e.type!=='submit' || e.disabled || e.formTarget || attr(form,'target') ||
            e.hasAttribute('onclick') || attr(form,'onsubmit')!==null) return null;
        // Controls called action/method/target shadow form properties.
        const enctype=e.getAttribute('formenctype') || attr(form,'enctype') || 'application/x-www-form-urlencoded';
        if(!['application/x-www-form-urlencoded','multipart/form-data'].includes(enctype)) return null;
        const action=e.hasAttribute('formaction') ? e.formAction : new URL(attr(form,'action')||location.href,document.baseURI).href;
        const method=(e.getAttribute('formmethod') || attr(form,'method') || 'get').toUpperCase();
        if(!['GET','POST'].includes(method)) return null;
        const data=new FormData(form,e), encoded=new URLSearchParams(), fields=[];
        // Native form submission normalizes line endings to CRLF.
        const norm=value=>value.replace(/\r\n|\r|\n/g,'\r\n');
        for(const [key,value] of data.entries()) {
            if(value instanceof File) {
                if(value.size && (enctype!=='multipart/form-data' || method!=='POST')) return null;
                const digest=await crypto.subtle.digest('SHA-256',await value.arrayBuffer());
                fields.push({name:norm(key),filename:value.name,content_type:value.type||'application/octet-stream',size:value.size,
                    sha256:Array.from(new Uint8Array(digest)).map(x=>x.toString(16).padStart(2,'0')).join('')});
            } else fields.push({name:norm(key),value:norm(value)});
            encoded.append(norm(key),value instanceof File ? value.name : norm(value));
        }
        const hidden=Array.from(Element.prototype.querySelectorAll.call(form,'input[type=hidden]')).map(x=>({name:x.name,value:x.value}));
        return {action,method,enctype,body:encoded.toString(),fields,hidden,submitter:{name:e.name,value:e.value}};
    }''')
    if not details or _origin(details['action']) != _origin(page.url):
        raise PrefillRefused('Next transition requires an explicit ATS adapter')
    url = details['action']
    endpoint = unquote(urlparse(url).path).lower()
    final = re.compile(r'(?:^|[/_.-])(?:submit(?:[-_]?application)?|finali[sz]e|send[-_]?application|complete[-_]?application)(?:$|[/_.-])')
    if final.search(endpoint):
        raise PrefillRefused('final submission endpoint is owner-only')
    controls = list(details.get('hidden', [])) + [details['submitter']] + [{'name': key, 'value': value} for key, value in parse_qsl(urlparse(url).query)]
    for control in controls:
        name, value = control['name'].lower(), control['value'].lower().strip()
        if (re.search(r'(action|operation|intent|mode|submit|final)', name) and
                re.fullmatch(r'(submit(?:[-_ ]?application)?|send(?:[-_ ]?application)?|finali[sz]e|complete(?:[-_ ]?application)?|true|1)', value)):
            raise PrefillRefused('final submission action is owner-only')
    if details['method'] == 'GET':
        url = url.split('?', 1)[0] + ('?' + details['body'] if details['body'] else '')
        request = {'method': 'GET', 'url': url}
    elif details['enctype'] == 'multipart/form-data':
        request = {'method': 'POST', 'url': url, 'form_sha256': _form_digest(details['fields'])}
    else:
        request = {'method': 'POST', 'url': url,
                   'body_sha256': hashlib.sha256(details['body'].encode()).hexdigest()}
    return {'next': {'selector': selector, 'target_url': url, 'allow_form_submit': True}, 'request': request}
