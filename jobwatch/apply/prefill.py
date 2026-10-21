"""Prepare owner-controlled application tabs without final submission.

Use --workflow for strict URL/session/hash binding and network interception.
The legacy standard-control API retains its original DOM-only protection.
Only use an application whose transmission has been specifically authorized.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import os
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import hashlib
import json

import yaml


class PrefillRefused(ValueError):
    """Safe public error: never include answers or Playwright exception text."""


@dataclass(frozen=True)
class FillResult:
    filled_count: int
    missing: tuple[str, ...]


def private_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PrefillRefused('private mode 600 file required')
    return path.read_bytes()


def parse_answers(content: bytes) -> dict:
    data = yaml.safe_load(content)
    fields = data.get('fields', {}) if isinstance(data, dict) else None
    if not isinstance(fields, dict) or any(not isinstance(k, str) for k in fields):
        raise PrefillRefused('invalid answers schema')
    return fields


def load_answers(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PrefillRefused('answers file must be private (mode 600)')
        return parse_answers(private_bytes(path))
    except PrefillRefused:
        raise
    except Exception:
        raise PrefillRefused('answers file unreadable or invalid') from None


def file_snapshot(answers_path: Path, documents: dict) -> tuple[dict, dict, dict]:
    """Hash the exact bytes consumed; never return values in public metadata."""
    try:
        content = private_bytes(answers_path)
        fields = parse_answers(content)
        uploads = {}
        for name, path in documents.items():
            path = Path(path)
            if not isinstance(name, str) or not name or path.is_symlink() or not path.is_file():
                raise ValueError()
            uploads[name] = {'name': path.name, 'mimeType': 'application/octet-stream', 'buffer': path.read_bytes()}
        metadata = {'answers_sha256': hashlib.sha256(content).hexdigest(),
                    'verified_fields': sorted(k for k, v in fields.items()
                                              if isinstance(v, dict) and v.get('owner_verified') is True),
                    'documents_sha256': {k: hashlib.sha256(v['buffer']).hexdigest() for k, v in sorted(uploads.items())}}
        return fields, uploads, metadata
    except Exception:
        raise PrefillRefused('manifest files unreadable or invalid') from None


def authorize_manifest(manifest_path: Path, answers_path: Path, documents: dict, *,
                       application_id: str, authorized_url: str) -> tuple[dict, dict, datetime]:
    """Local approval reference + immutable revision binding, not approval-service verification."""
    try:
        manifest = json.loads(private_bytes(manifest_path))
        if not isinstance(manifest, dict):
            raise ValueError()
        if not isinstance(manifest.get('board_approval_id'), str) or not manifest['board_approval_id'].strip():
            raise ValueError()
        if not application_id or manifest.get('application_id') != application_id:
            raise ValueError()
        url = urlparse(authorized_url)
        counters = parse_qs(url.query).get('in_jnCounter', [])
        supported_path = (url.path.rstrip('/') == '/WelcomeScreen' or
                          url.path == '/jobtools/apCustomAppMgr.WelcomeScreen')
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or
                url.fragment or not supported_path or len(counters) != 1 or not counters[0] or
                (url.scheme != 'https' and url.hostname not in ('127.0.0.1', 'localhost')) or
                manifest.get('host') != url.hostname or manifest.get('welcome_url') != authorized_url):
            raise ValueError()
        expiry = datetime.fromisoformat(manifest['expires_at'])
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError()
        fields, uploads, metadata = file_snapshot(answers_path, documents)
        if any(manifest.get(key) != value for key, value in metadata.items()):
            raise ValueError()
        return fields, uploads, expiry
    except Exception:
        raise PrefillRefused('transmission manifest refused; no fields filled') from None


def parse_documents(items: list[str]) -> dict[str, Path]:
    try:
        pairs = [item.split('=', 1) for item in items]
        if any(len(pair) != 2 or not all(pair) for pair in pairs) or len({p[0] for p in pairs}) != len(pairs):
            raise ValueError()
        return {name: Path(path) for name, path in pairs}
    except Exception:
        raise PrefillRefused('invalid document bindings') from None


_GUARD = '''() => {
    window.__jobwatchActive = true;
    if (window.__jobwatchGuard) return;
    window.__jobwatchGuard = true;
    document.addEventListener('submit', e => { if (window.__jobwatchActive && (!e.submitter || e.submitter !== window.__jobwatchAllowedSubmit)) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
    document.addEventListener('click', e => {
        const action = e.target.closest('button,input[type=submit],input[type=image],a,[role=button]');
        if (window.__jobwatchActive && action && window.__jobwatchAllowedClick !== action) {
            e.preventDefault(); e.stopImmediatePropagation();
        }
    }, true);
    const submit = HTMLFormElement.prototype.submit;
    const requestSubmit = HTMLFormElement.prototype.requestSubmit;
    HTMLFormElement.prototype.submit = function(...a) { if (!window.__jobwatchActive) return submit.apply(this, a); };
    HTMLFormElement.prototype.requestSubmit = function(...a) { if (!window.__jobwatchActive) return requestSubmit.apply(this, a); };
}'''


def require_host(page, allowed_hosts: list[str]) -> None:
    """Exact hostname allow-list; no URL, wildcard or suffix matching."""
    parsed = urlparse(page.url)
    if (parsed.scheme not in ('http', 'https') or not allowed_hosts or
            any(not h or urlparse('https://' + h).hostname != h or
                any(c in h for c in '/:*?#@') for h in allowed_hosts) or
            parsed.hostname not in allowed_hosts):
        raise PrefillRefused('authorized host required')


def select_owner_page(browser, allowed_hosts: list[str], *, tab_index: int | None = None):
    """Select an existing page without navigation, creation or focus changes."""
    pages = [page for context in browser.contexts for page in context.pages]
    if tab_index is None:
        if len(pages) != 1:
            raise PrefillRefused('explicit tab index required for multiple tabs')
        tab_index = 0
    if tab_index < 0 or tab_index >= len(pages):
        raise PrefillRefused('invalid tab index')
    page = pages[tab_index]
    require_host(page, allowed_hosts)
    return page


def discover_controls(page, *, allowed_hosts: list[str]) -> list[dict]:
    """Read metadata only. Never access input values, options or file paths."""
    require_host(page, allowed_hosts)
    url = page.url
    controls = page.eval_on_selector_all('input,select,textarea', '''els => els
        .filter(e => !['hidden','submit','button','reset','image'].includes(e.type))
        .map(e => ({name: e.getAttribute('name') || '', id: e.id || '',
            type: e.tagName === 'INPUT' ? e.type : e.tagName.toLowerCase(),
            label: Array.from(e.labels || []).map(l => {
                const copy = l.cloneNode(true);
                copy.querySelectorAll('input,select,textarea,option').forEach(n => n.remove());
                return copy.textContent.trim();
            }).join(' '), required: e.required === true}))''')
    require_host(page, allowed_hosts)
    if page.url != url:
        raise PrefillRefused('application changed; stopped')
    return controls


def generate_template(path: Path, controls: list[dict]) -> None:
    """Create only; refusing every existing path preserves all verified answers."""
    fields = {}
    for control in controls:
        key = control.get('name') or control.get('id')
        if key and control.get('type') != 'password':
            fields[key] = {'value': '', 'owner_verified': False}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), 0o600)
            yaml.safe_dump({'fields': fields}, output, sort_keys=False)
    except Exception:
        raise PrefillRefused('template destination must be new and writable') from None


def require_unexpired(expires_at: datetime | None) -> None:
    if expires_at is not None and (expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc)):
        raise PrefillRefused('transmission authorization expired; stopped')


def fill_page(page, answers: dict, documents: dict[str, Path], *, authorized_url: str,
              expires_at: datetime | None = None) -> FillResult:
    """Fill current standard controls; page/context stays owned by the caller.

    Keys are exact HTML names (or ids for nameless controls); documents use the
    same bindings. Sensitive declarations need owner_verified: true like all
    other answers. Missing includes optional unanswered fields as well.
    """
    require_unexpired(expires_at)
    # Check after control inspection, immediately before every mutation. The
    # CLI always supplies the manifest expiry; library-only callers may omit it.
    def mutate(action, *args, **kwargs):
        require_unexpired(expires_at)
        return action(*args, **kwargs)

    if not authorized_url or page.url != authorized_url:
        raise PrefillRefused('specific application authorization required')
    # Refuse credential bindings before filling any other field on a login gate.
    for el in page.query_selector_all('input[type=password]'):
        key = el.get_attribute('name') or el.get_attribute('id')
        if key in answers or key in documents:
            raise PrefillRefused('password targets are owner-only')
    page.evaluate(_GUARD)
    # Element handles retain DOM identity; positional locators retarget after
    # input handlers insert/remove controls. Snapshot attributes too.
    controls = page.query_selector_all('input,select,textarea')
    snapshots = {}
    groups = {}
    for index, el in enumerate(controls):
        snapshots[el] = el.evaluate('e => [e.tagName, e.getAttribute("name"), e.id, e.getAttribute("type")]')
        typ = (el.get_attribute('type') or 'text').lower()
        if typ in ('hidden', 'submit', 'button', 'reset', 'image'):
            continue
        key = el.get_attribute('name') or el.get_attribute('id') or f'unnamed-field-{index + 1}'
        groups.setdefault(key, []).append((el, typ))
    missing = []
    filled = 0
    for key, group in groups.items():
        if page.url != authorized_url:
            raise PrefillRefused('application changed; stopped')
        record = answers.get(key)
        value = record.get('value') if isinstance(record, dict) and record.get('owner_verified') is True else None
        try:
            for el, _ in group:
                if not el.evaluate('''(e, expected) => e.isConnected &&
                    JSON.stringify([e.tagName, e.getAttribute('name'), e.id, e.getAttribute('type')]) === JSON.stringify(expected)''', snapshots[el]):
                    raise ValueError()
            # A newly inserted same-name control makes the binding ambiguous.
            current_count = page.evaluate('''key => Array.from(document.querySelectorAll('input,select,textarea'))
                .filter(e => (e.getAttribute('name') || e.id) === key).length''', key)
            if current_count != len(group):
                raise ValueError()
            if any(not el.is_visible() or not el.is_enabled() for el, _ in group):
                raise ValueError()
            if all(typ == 'radio' for _, typ in group):
                # Omitted HTML values are unsupported; never let None match
                # absent/unverified/null answers to a legal declaration.
                if not isinstance(value, str) or not value.strip():
                    raise ValueError()
                matches = [el for el, _ in group if el.get_attribute('value') == value]
                if len(matches) != 1:
                    raise ValueError()
                mutate(matches[0].check, timeout=1500)
            elif len(group) != 1:
                raise ValueError()
            else:
                el, typ = group[0]
                tag = el.evaluate('(e) => e.tagName.toLowerCase()')
                if typ == 'file':
                    path = documents.get(key)
                    if isinstance(path, dict):
                        mutate(el.set_input_files, path, timeout=1500)
                    else:
                        if not path or not Path(path).is_file():
                            raise ValueError()
                        mutate(el.set_input_files, str(path), timeout=1500)
                elif typ == 'checkbox':
                    if not isinstance(value, bool):
                        raise ValueError()
                    mutate(el.set_checked, value, timeout=1500)
                elif tag == 'select':
                    if not isinstance(value, str) or not value:
                        raise ValueError()
                    options = el.query_selector_all('option')
                    matches = [o.get_attribute('value') or o.text_content() for o in options
                               if not o.is_disabled() and (o.get_attribute('value') == value or o.text_content() == value)]
                    if len(matches) != 1:
                        raise ValueError()
                    mutate(el.select_option, value=matches[0], timeout=1500)
                elif tag == 'textarea' or typ in ('text', 'email', 'tel', 'url', 'number', 'date'):
                    if not isinstance(value, str) or not value.strip() or el.get_attribute('readonly') is not None:
                        raise ValueError()
                    mutate(el.fill, value, timeout=1500)
                else:
                    raise ValueError()
            filled += 1
        except PrefillRefused:
            # Expiry is a hard stop, not an unsupported-field warning. Keep
            # the submit guard active when aborting a partially filled page.
            raise
        except Exception:
            # Playwright errors may contain field values; never expose them.
            missing.append(key)
    page.evaluate('window.__jobwatchActive = false')
    return FillResult(filled, tuple(missing))


def main() -> int:
    """Attach to an owner-controlled local Chromium; leave its page open."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=['manifest-hash'])
    parser.add_argument('--manifest', type=Path, help='private approval-bound JSON manifest')
    parser.add_argument('--workflow', type=Path, help='private strict v2 browser workflow manifest')
    parser.add_argument('--prepare-session', type=Path, help='create private exact-tab binding during discovery')
    parser.add_argument('--discover-application', action='store_true', help='discover all questions and frame/custom controls')
    parser.add_argument('--snapshots', type=Path, help='private directory for workflow screenshots')
    parser.add_argument('--application-id', help='jobwatch application id bound by the approval')
    parser.add_argument('--url')
    parser.add_argument('--attach', action='store_true', help='use an existing owner tab; never navigate')
    parser.add_argument('--allow-host', action='append', default=[], help='exact authorized hostname (repeatable)')
    parser.add_argument('--tab-index', type=int, help='zero-based index across existing context pages')
    parser.add_argument('--discover', action='store_true', help='metadata only; no values, fills or clicks')
    parser.add_argument('--generate-template', type=Path, help='create a NEW private fields template during discovery')
    parser.add_argument('--authorize-transmission', action='store_true',
                        help='specific permission to send these answers/documents to this application, including autosave')
    parser.add_argument('--cdp', default='http://127.0.0.1:9222')
    parser.add_argument('--answers', type=Path, default=Path.home() / 'brain/data/jobwatch/profile/answers.yaml')
    parser.add_argument('--document', action='append', default=[], metavar='FIELD=PATH')
    args = parser.parse_args()
    if args.command == 'manifest-hash':
        try:
            _, _, metadata = file_snapshot(args.answers, parse_documents(args.document))
            print(json.dumps(metadata, sort_keys=True))
            return 0
        except PrefillRefused:
            print('manifest hashing refused; no values logged')
            return 1
    if args.authorize_transmission and (not (args.manifest or args.workflow) or not args.application_id):
        parser.error('transmission requires --manifest or --workflow and --application-id')
    if args.workflow and (not args.attach or not args.snapshots or args.manifest or args.discover):
        parser.error('strict workflow requires --attach and --snapshots; forbids legacy manifest/discovery')
    if args.discover_application and not args.discover:
        parser.error('application discovery requires --discover')
    if args.prepare_session and not args.discover:
        parser.error('session preparation requires --discover')
    cdp = urlparse(args.cdp)
    if cdp.scheme not in ('http', 'https') or cdp.hostname not in ('127.0.0.1', 'localhost') or cdp.username or cdp.password:
        parser.error('local browser required')
    if not args.discover and not args.authorize_transmission:
        parser.error('specific transmission authorization required')
    if args.attach:
        if not args.allow_host or args.url:
            parser.error('attach requires exact --allow-host and forbids --url')
    elif args.discover or args.generate_template or args.tab_index is not None or args.allow_host:
        parser.error('discovery and tab/host selection require --attach')
    elif not args.url or urlparse(args.url).scheme not in ('https', 'http'):
        parser.error('HTTP(S) application URL required')
    if args.generate_template and not args.discover:
        parser.error('template generation requires --discover')
    if args.discover and args.document:
        parser.error('discovery forbids documents')
    try:
        # Discovery deliberately never reads the private answers file.
        answers = {}
        expires_at = None
        documents = parse_documents(args.document)
        if not args.discover and not args.attach:
            answers, documents, expires_at = authorize_manifest(args.manifest, args.answers, documents,
                                                   application_id=args.application_id, authorized_url=args.url)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(args.cdp)
            if args.attach:
                page = select_owner_page(browser, args.allow_host, tab_index=args.tab_index)
            else:
                context = browser.contexts[0]
                page = context.new_page()
                page.add_init_script('(' + _GUARD + ')()')
                page.goto(args.url)
            if args.discover:
                controls = discover_controls(page, allowed_hosts=args.allow_host)
                if args.generate_template:
                    generate_template(args.generate_template, controls)
                if args.prepare_session:
                    from .prefill_workflow import prepare_session
                    prepare_session(page, args.prepare_session)
                if args.discover_application:
                    from .prefill_workflow import discover_application, plan_from_discovery
                    discovery = discover_application(page, allowed_hosts=args.allow_host)
                    print(json.dumps({'discovery': discovery, 'plan': plan_from_discovery(discovery),
                                      'status': 'metadata_only; browser left open'}))
                else:
                    print(json.dumps({'controls': controls, 'status': 'metadata_only; browser left open'}))
            elif args.workflow:
                from .prefill_workflow import authorize_workflow, fill_application
                plan, answers, documents, expires_at = authorize_workflow(
                    args.workflow, args.answers, documents, application_id=args.application_id)
                result = fill_application(page, answers, documents, plan=plan, expires_at=expires_at,
                                          screenshot_dir=args.snapshots)
                print(json.dumps({'filled_count': result.filled_count, 'missing_fields': result.missing,
                                  'completed_steps': result.completed_steps, 'status': result.status,
                                  'screenshot_count': len(result.screenshots),
                                  'blocked_requests': result.blocked_requests, 'browser_left_open': True}))
            else:
                authorized_url = page.url if args.attach else args.url
                if args.attach:
                    answers, documents, expires_at = authorize_manifest(args.manifest, args.answers, documents,
                                                           application_id=args.application_id, authorized_url=authorized_url)
                result = fill_page(page, answers, documents, authorized_url=authorized_url, expires_at=expires_at)
                print(json.dumps({'filled_count': result.filled_count, 'missing_fields': result.missing,
                                  'status': 'stopped_before_submit; browser left open'}))
            # No browser.close(): stopping Playwright disconnects from the owner's browser.
        return 0
    except Exception:
        print('prefill stopped; inspect local browser; no error values logged')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
