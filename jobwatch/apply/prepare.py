"""Discover, answer and prepare an owner application without manual field mapping.

The board calls this only after the owner's application-specific prepare action.
Unknown facts are returned together for one private intake; final submission is
always performed by the owner in their existing browser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlparse

import yaml

from .career_retrieval import relevant_facts
from .jev_forms import jev_next_button, jev_prefill
from .answers_agent import AnswerPlan, AnswerRefused, answer_application, load_answer_sources, save_owner_answer, with_career_record
from .prefill import PrefillRefused, file_snapshot, private_bytes, require_host
from .paths import safe_write_text
from .submit_confirm import FINAL_LABEL, form_state
from .prefill_workflow import (
    authorize_workflow, discover_application, fill_application, plan_from_discovery,
    prepare_next_navigation, private_write, session_id,
)
from jobwatch.settings import DEFAULT_MODEL


class PreparationRefused(ValueError):
    """Only fixed public failure codes, never candidate or browser error text."""


@dataclass(frozen=True)
class PreparedApplication:
    status: str
    filled_count: int
    completed_steps: int
    missing: tuple[dict, ...] = field(repr=False)
    reason: str = ''
    run_dir: Path | None = field(default=None, repr=False)
    screenshots: tuple[str, ...] = field(default=(), repr=False)

    def public_dict(self):
        return {'status': self.status, 'filled_count': self.filled_count,
                'completed_steps': self.completed_steps, 'missing_count': len(self.missing),
                'reason': self.reason, 'screenshot_count': len(self.screenshots),
                'browser_left_open': True}


def saved_answers_path(data_root: Path) -> Path:
    return Path(data_root) / 'browser' / 'saved-answers.json'


def _private_dir(path):
    if path.is_symlink():
        raise PreparationRefused('private_browser_directory_required')
    if not path.exists():
        path.mkdir(mode=0o700)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise PreparationRefused('private_browser_directory_required')
    return path


def _write_json(path, data):
    private_write(path, json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())


def _document_role(control):
    # Bind only explicit unambiguous upload labels; never guess file1/file2.
    label = ' '.join(str(control.get(k) or '') for k in ('name', 'question'))
    label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', label).replace('_', ' ').lower()
    cv = bool(re.search(r'\b(cv|resume|résumé|curriculum vitae)\b', label))
    letter = bool(re.search(r'\b(cover\s*(letter)?|covering letter|motivation letter|letter)\b', label))
    return 'cv' if cv and not letter else 'letter' if letter and not cv else None


def _finish(run_dir, status, filled, completed, missing=(), reason='', screenshots=(), review=None):
    # Keep questions/answers separate from status used by the public board.
    distinct = {}
    for item in missing:
        question = item['question'].strip()
        key = hashlib.sha256(question.casefold().encode()).hexdigest()
        distinct[key] = dict(item, question_id=key)
    missing = tuple(distinct.values())
    snapshots = list(dict.fromkeys([*screenshots, *(str(path) for path in run_dir.glob('step-*/*/stopped.png'))]))
    result = PreparedApplication(status, filled, completed, missing, reason, run_dir, tuple(snapshots))
    _write_json(run_dir / 'status.json', result.public_dict())
    if missing:
        _write_json(run_dir / 'questions.json', list(missing))
    review_answers = json.loads(private_bytes(run_dir / 'previous-review.json')) if (run_dir / 'previous-review.json').exists() else []
    for source in sorted(run_dir.glob('step-*/answer-plan.json')):
        answers = json.loads(private_bytes(source))
        discovery = json.loads(private_bytes(source.parent / 'discovery.json'))
        questions = {field['key']: field for scope in discovery['scopes'] for field in scope['fields']}
        for key, record in answers['fields'].items():
            review_answers.append({'key': key, 'step': source.parent.name,
                'question': questions.get(key, {}).get('question', key), **record})
    review_answers = list({(row['key'], row['question']): row for row in review_answers}.values())
    prepared = {**result.public_dict(), 'run_id': run_dir.name, 'missing': list(missing),
                'review_answers': review_answers, 'screenshots': snapshots}
    package_path = run_dir / 'package.json'
    if package_path.exists():
        package = json.loads(private_bytes(package_path))
        prepared['package_hash'] = hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    if (run_dir / 'browser-state.json').exists():
        prepared.update(json.loads(private_bytes(run_dir / 'browser-state.json')))
    if (run_dir / 'attachments.json').exists():
        prepared['attached_documents'] = json.loads(private_bytes(run_dir / 'attachments.json'))
    prepared.update(review or {})           # final_control + form_state: what an owner Submit confirmation binds to
    _write_json(run_dir / 'prepared.json', prepared)
    safe_write_text(run_dir.parent / 'latest.json', json.dumps({'run_id': run_dir.name}))
    return result


def latest_preparation(data_root: Path, application_id: str) -> dict | None:
    """Read private review details for this application; never emit them to logs."""
    if not isinstance(application_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', application_id):
        raise PreparationRefused('invalid_application_id')
    base = Path(data_root) / 'browser' / hashlib.sha256(application_id.encode()).hexdigest()
    pointer = base / 'latest.json'
    if not pointer.exists():
        return None
    try:
        if any(path.is_symlink() for path in (Path(data_root), base.parent, base)):
            raise ValueError()
        run_id = json.loads(private_bytes(pointer))['run_id']
        if not re.fullmatch(r'[0-9a-f]{32}', run_id) or (base / run_id).is_symlink():
            raise ValueError()
        return json.loads(private_bytes(base / run_id / 'prepared.json'))
    except Exception:
        raise PreparationRefused('private_preparation_unavailable') from None


def record_owner_answer(data_root: Path, application_id: str, *, question_id: str, value) -> None:
    """Accept only an explicit reply to a currently pending private question."""
    state = latest_preparation(data_root, application_id)
    question = next((item for item in (state or {}).get('missing', []) if item['question_id'] == question_id), None)
    if question is None or state.get('status') != 'needs_owner':
        raise PreparationRefused('pending_question_required')
    if question.get('key') in ('owner_login', 'owner_verification'):
        raise PreparationRefused('browser_sign_in_required')
    options = question.get('options') or []
    selected = value if isinstance(value, list) else [value]
    allowed = {str(option.get('value', option.get('label', ''))) for option in options}
    if allowed and any(str(item) not in allowed for item in selected):
        raise PreparationRefused('invalid_owner_answer_option')
    save_owner_answer(saved_answers_path(data_root), question=question['question'], value=value)



def _follow_application_links(page, allowed_hosts, run_dir):
    """Follow only unambiguous Apply anchors before there is an application form."""
    allowed_hosts = list(allowed_hosts)
    labels = {'apply', 'apply now', 'apply for this job', 'start application'}
    for index in range(4):
        from .ats import is_pageup_advert, pageup_entry_link
        provider = 'pageup' if is_pageup_advert(page.url) else None
        if provider == 'pageup':
            target = pageup_entry_link(page)
            if target is None:
                raise PreparationRefused('pageup_application_link_unavailable')
            links = [target]
        else:
            discovery = discover_application(page, allowed_hosts=allowed_hosts)
            controls = [field for scope in discovery['scopes'] for field in scope['fields']
                        if field['type'] != 'search' and field.get('name', '').casefold() not in ('search', 'query', 'q')]
            if controls or discovery.get('owner_challenges'):
                return allowed_hosts
            links = []
            for anchor in page.query_selector_all('a[href]'):
                if not anchor.is_visible() or anchor.get_attribute('onclick') is not None or anchor.get_attribute('download') is not None:
                    continue
                label = ' '.join((anchor.text_content() or '').strip().casefold().split())
                if label in labels:
                    links.append(anchor.evaluate('e => e.href'))
        if not links:
            return allowed_hosts
        if len(links) != 1 or index == 3:
            raise PreparationRefused('application_link_ambiguous')
        target = links[0]
        validator = getattr(page, '_jobwatch_validate_request_url', None)
        if validator is not None:
            validator(target)
        else:
            from jobwatch.web.browser_session import _public_url
            _public_url(target, allow_loopback=urlparse(target).hostname in ('127.0.0.1', 'localhost')
                        and urlparse(target).hostname in allowed_hosts)
        if urlparse(target).scheme != 'https' and urlparse(target).hostname not in ('127.0.0.1', 'localhost'):
            raise PreparationRefused('secure_application_url_required')
        _write_json(run_dir / f'application-link-{index + 1}.json', {'url': target})
        # Direct anchor navigation avoids executing an unrelated click handler;
        # it cannot invoke a button or form submission API.
        navigator = getattr(page, '_jobwatch_navigate', None)
        if navigator is not None:
            navigator(target, provider=provider)
        else:
            page.goto(target, wait_until='domcontentloaded', timeout=20000)
        if validator is not None:
            validator(page.url)
        if urlparse(page.url).hostname not in allowed_hosts:
            allowed_hosts.append(urlparse(page.url).hostname)
    return allowed_hosts

def prepare_application(page, *, application_id: str, package_manifest, document_paths: dict,
                        profile_root: Path, data_root: Path, job: dict, budget, llm, reviewer,
                        allowed_hosts: list[str], owner_authorized: bool = True, worker_model: str = DEFAULT_MODEL,
                        reviewer_model: str = DEFAULT_MODEL) -> PreparedApplication:
    """Prepare every supported step using profile facts and grounded agent answers.

    ``document_paths`` maps cv/letter to the verified package PDFs. Native
    URL-encoded and multipart Next/Continue forms are supported, including
    same-URL POSTs. An unsupported custom JS Next returns ``needs_adapter`` with the page
    safely filled to that point; it never asks the owner to hand-edit JSON or
    type those fields. Save explicit intake replies with save_owner_answer at
    saved_answers_path(data_root), then call this again on the owner's tab.
    """
    if owner_authorized is not True:
        raise PreparationRefused('owner_authorization_required')
    if not isinstance(application_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', application_id):
        raise PreparationRefused('invalid_application_id')
    require_host(page, allowed_hosts)
    root = Path(data_root)
    if not root.is_dir() or root.is_symlink():
        raise PreparationRefused('private_browser_directory_required')
    browser_root = _private_dir(root / 'browser')
    application_root = _private_dir(browser_root / hashlib.sha256(application_id.encode()).hexdigest())
    run_dir = _private_dir(application_root / uuid.uuid4().hex)
    screenshots = []
    filled = completed = 0
    attached = set()
    try:
        package = package_manifest.model_dump(mode='json') if hasattr(package_manifest, 'model_dump') else package_manifest
        if (not isinstance(package, dict) or set(document_paths) != {'cv', 'letter'} or
                any(package.get('verification', {}).get(key) is not True
                    for key in ('cv_pdf', 'letter_pdf', 'claims', 'review'))):
            raise PreparationRefused('verified_pdf_package_required')
        documents = {}
        for role, path in document_paths.items():
            path = Path(path)
            if path.is_symlink() or not path.is_file():
                raise PreparationRefused('verified_pdf_package_required')
            data = path.read_bytes()
            if not data.startswith(b'%PDF-') or package.get('pdfs', {}).get(role) != hashlib.sha256(data).hexdigest():
                raise PreparationRefused('verified_pdf_package_required')
            documents[role] = run_dir / (role + '.pdf')
            private_write(documents[role], data)
        _write_json(run_dir / 'package.json', package)
        package_hash = hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        def browser_state():
            return {'session_id': session_id(page), 'page_url_sha256': hashlib.sha256(page.url.encode()).hexdigest(),
                    'owner_revision': getattr(page, '_jobwatch_owner_revision', 0)}
        previous = latest_preparation(root, application_id)
        state = browser_state()
        if (previous and previous.get('package_hash') == package_hash and
                all(previous.get(key) == value for key, value in state.items())):
            attached.update(role for role, digest in previous.get('attached_documents', {}).items()
                            if role in package['pdfs'] and digest == package['pdfs'][role])
            _write_json(run_dir / 'previous-review.json', previous.get('review_answers', []))
        safe_write_text(run_dir / 'attachments.json', json.dumps({role: package['pdfs'][role] for role in sorted(attached)}))
        safe_write_text(run_dir / 'browser-state.json', json.dumps(state))
        sources = load_answer_sources(Path(profile_root), saved_path=saved_answers_path(root))
        expiry = datetime.now(timezone.utc) + timedelta(minutes=20)
        last_shape = None
        allowed_hosts = _follow_application_links(page, allowed_hosts, run_dir)
        for step_index in range(20):
            step_dir = _private_dir(run_dir / f'step-{step_index + 1:02d}')
            discovery = discover_application(page, allowed_hosts=allowed_hosts)
            safe_write_text(run_dir / 'browser-state.json', json.dumps(browser_state()))
            shape = hashlib.sha256(json.dumps(discovery['scopes'], sort_keys=True).encode()).hexdigest()
            if shape == last_shape:
                return _finish(run_dir, 'needs_adapter', filled, completed, reason='navigation_did_not_advance', screenshots=screenshots)
            last_shape = shape
            _write_json(step_dir / 'discovery.json', discovery)
            controls = [control for scope in discovery['scopes'] for control in scope['fields']]
            if discovery.get('owner_challenges'):
                checkpoint = step_dir / 'owner-checkpoint.png'
                private_write(checkpoint, page.screenshot(full_page=True))
                screenshots.append(str(checkpoint))
                return _finish(run_dir, 'needs_owner', filled, completed,
                               [{'key': 'owner_verification', 'question': 'Complete the site verification in the live browser, then choose Fill application.', 'required': True}],
                               reason='owner_session_required', screenshots=screenshots)
            if any(control.get('owner_only') for control in controls):
                return _finish(run_dir, 'needs_owner', filled, completed,
                               [{'key': 'owner_login', 'question': 'Complete the site sign-in in your browser, then prepare again.', 'required': True}],
                               reason='owner_session_required', screenshots=screenshots)
            fields = [control for control in controls if control['type'] != 'file']
            # Jev matches field labels to the owner's saved answers by name only; code types the values.
            # Whatever Jev cannot match goes to the answer agent as before.
            matched = jev_prefill(fields, Path(profile_root), job=job)
            rest = [control for control in fields if control['key'] not in matched]
            if rest:  # a field with no saved answer: tell the owner once that Chat has questions waiting
                try:
                    from jobwatch.web.ask_cards import notify_missing
                    notify_missing()
                except Exception:
                    pass
            # No model call is needed on a document-only/review page.
            # Embeddings pick the career-record facts closest to these questions (owner, 2026-10-12).
            step_sources = with_career_record(sources, relevant_facts(
                [control.get('question') or '' for control in rest], browser_root / 'career-vectors.sqlite')) if rest else sources
            answer_plan = answer_application(rest, step_sources, job=job, budget=budget, llm=llm, reviewer=reviewer,
                                             model=worker_model, reviewer_model=reviewer_model) if rest else \
                AnswerPlan({}, (), step_sources.snapshot_hash, {'profile': [], 'saved_answer': [], 'agent_draft': []}, {}, step_sources.hashes)
            _write_json(step_dir / 'answer-plan.json', dict(answer_plan.private_dict(), jev_matched=sorted(matched)))
            all_fields = {**answer_plan.fields, **matched}
            path = step_dir / 'answers.yaml'
            private_write(path, yaml.safe_dump({'fields': all_fields}, sort_keys=True).encode())
            upload_paths, roles, unresolved_uploads = {}, {}, []
            for control in controls:
                if control['type'] != 'file':
                    continue
                role = _document_role(control)
                if role is None:
                    unresolved_uploads.append(control['key'])
                else:
                    upload_paths[control['key']] = documents[role]
                    roles[control['key']] = role
            plan = plan_from_discovery(discovery)
            _, _, metadata = file_snapshot(path, upload_paths)
            plan.update(metadata)
            plan.update(application_id=application_id, owner_authorized=True,
                        authorization_reference='owner-prepare:' + run_dir.name,
                        expires_at=expiry.isoformat(), document_roles=roles, package_manifest=package,
                        answer_sources=answer_plan.answer_sources, authorized_fields=sorted(all_fields))
            manifest_path = step_dir / 'workflow.json'
            _write_json(manifest_path, plan)
            authorized, answers, uploads, expires = authorize_workflow(manifest_path, path, upload_paths,
                                                                     application_id=application_id)
            result = fill_application(page, answers, uploads, plan=authorized, expires_at=expires,
                                      screenshot_dir=step_dir / 'filled')
            filled += result.filled_count
            screenshots.extend(result.screenshots)
            attached.update(role for key, role in roles.items() if key not in result.missing)
            safe_write_text(run_dir / 'attachments.json', json.dumps({role: package['pdfs'][role] for role in sorted(attached)}))
            if answer_plan.missing:
                question_by_key = {control['key']: control for control in fields}
                missing = [dict(item, form_question=question_by_key[item['key']]['question'],
                                type=question_by_key[item['key']]['type'],
                                kind=question_by_key[item['key']].get('kind', 'native'),
                                multiple=question_by_key[item['key']].get('multiple', False),
                                options=question_by_key[item['key']].get('options', [])) for item in answer_plan.missing]
                return _finish(run_dir, 'needs_owner', filled, completed, missing,
                               reason='missing_profile_facts', screenshots=screenshots)
            if unresolved_uploads:
                return _finish(run_dir, 'needs_adapter', filled, completed,
                               reason='ambiguous_document_control', screenshots=screenshots)
            if result.missing:
                return _finish(run_dir, 'needs_adapter', filled, completed,
                               reason='unsupported_form_control', screenshots=screenshots)
            completed += 1
            buttons = [dict(button, frame_path=scope['frame_path'], url=scope['url'])
                       for scope in discovery['scopes'] for button in scope['buttons']]
            next_buttons = [button for button in buttons if button['label'].strip().casefold() in
                            ('next', 'next step', 'continue', 'continue application', 'save and continue', 'save & continue')]
            if not next_buttons:
                chosen = jev_next_button(buttons)
                next_buttons = [chosen] if chosen is not None else []
            if not next_buttons:
                final = [button for button in buttons if FINAL_LABEL.fullmatch(button['label'].strip().casefold())]
                if len(final) != 1:
                    return _finish(run_dir, 'needs_adapter', filled, completed, reason='final_review_control_unrecognized', screenshots=screenshots)
                if 'cv' not in attached:
                    return _finish(run_dir, 'needs_adapter', filled, completed, reason='document_controls_incomplete', screenshots=screenshots)
                control = {key: final[0][key] for key in ('selector', 'frame_path', 'url')}
                review = {'final_control': dict(control, label=' '.join(final[0]['label'].strip().casefold().split())),
                          'form_state': form_state(page)}
                return _finish(run_dir, 'ready_for_owner', filled, completed,
                               reason='' if 'letter' in attached else 'cover_letter_not_requested', screenshots=screenshots,
                               review=review)
            if len(next_buttons) != 1:
                return _finish(run_dir, 'needs_adapter', filled, completed, reason='next_control_ambiguous', screenshots=screenshots)
            if next_buttons[0]['frame_path']:
                return _finish(run_dir, 'needs_adapter', filled, completed, reason='embedded_next_requires_site_adapter', screenshots=screenshots)
            try:
                navigation = prepare_next_navigation(page, next_buttons[0]['selector'])
            except PrefillRefused:
                return _finish(run_dir, 'needs_adapter', filled, completed, reason='next_requires_site_adapter', screenshots=screenshots)
            # Reuse the verified bindings while taking one bounded, derived Next
            # request. The destination is deliberately rediscovered and answered
            # in the next loop, never guessed from its URL or the previous page.
            advance = dict(plan)
            advance['requests'] = [navigation['request']]
            advance['steps'] = [dict(plan['steps'][0], next=navigation['next']),
                                {'url': navigation['next']['target_url'], 'ready_selector': 'body',
                                 'scopes': [{'url': navigation['next']['target_url'], 'fields': {}}]}]
            _write_json(step_dir / 'advance.json', advance)
            after = fill_application(page, answers, uploads, plan=advance, expires_at=expires,
                                     screenshot_dir=step_dir / 'advanced')
            screenshots.extend(after.screenshots)
            safe_write_text(run_dir / 'browser-state.json', json.dumps(browser_state()))
            if after.completed_steps < 1:
                return _finish(run_dir, 'needs_adapter', filled, completed, reason='next_did_not_complete', screenshots=screenshots)
        return _finish(run_dir, 'needs_adapter', filled, completed, reason='step_limit_reached', screenshots=screenshots)
    except (AnswerRefused, PrefillRefused, PreparationRefused) as exc:
        reason = str(exc) if isinstance(exc, (AnswerRefused, PreparationRefused)) else 'browser_workflow_refused'
        return _finish(run_dir, 'blocked', filled, completed, reason=reason, screenshots=screenshots)
    except Exception:
        return _finish(run_dir, 'blocked', filled, completed, reason='application_preparation_failed', screenshots=screenshots)
