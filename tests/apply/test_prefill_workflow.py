"""Actual Chromium on loopback: no candidate data, live ATS, or model calls."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
pytest.importorskip('playwright.sync_api',  # module-level: collection used to error without the
                    reason='the prefill tests need the browser extra')  # browser extra, not skip
from playwright.sync_api import sync_playwright
import yaml

from jobwatch.apply.prefill import PrefillRefused, file_snapshot
from jobwatch.apply.prefill_workflow import authorize_workflow, fill_application, session_id


@pytest.fixture
def site():
    seen = []
    pages = {
        '/one': '''<form onsubmit="window.submits++;return false"><input name=full_name id=name>
          <button type=button role=combobox id=choice onclick="document.querySelector('#options').hidden=false">Choice</button>
          <div id=options hidden><div id=option role=option aria-selected=false onclick="this.setAttribute('aria-selected','true')">Synthetic</div></div>
          <button type=button role=checkbox id=consent aria-checked=false onclick="this.setAttribute('aria-checked','true')">Consent</button>
          <iframe id=details src=/frame></iframe>
          <button type=button id=next onclick="location.href='/two'">Next</button>
          <button id=submit>Submit</button></form><script>window.submits=0</script>''',
        '/frame': '<input name=availability>',
        '/two': '''<form onsubmit="window.submits++;return false"><input type=file name=cv><input type=file name=letter>
          <button id=submit>Submit</button></form><script>window.submits=0</script>''',
        '/submit': 'This endpoint must never receive an automated request.',
    }
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(('GET', self.path))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(pages.get(self.path, '').encode())
        def do_POST(self):
            seen.append(('POST', self.path))
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(pages.get(('POST', self.path), '').encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        base = f'http://127.0.0.1:{server.server_port}'
        page.goto(base + '/one')
        yield page, base, seen, pages
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def pdf_bytes(tmp_path):
    from weasyprint import HTML
    from jobwatch.apply.verify_pdf import verify_pdf
    body = 'Synthetic documented analysis communication research planning and evidence. ' * 10
    data = HTML(string='<p>' + body + '</p>').write_pdf()
    paths = []
    for name in ('cv', 'letter'):
        path = tmp_path / f'{name}.pdf'
        path.write_bytes(data)
        path.chmod(0o600)
        paths.append(path)
    report = verify_pdf(*paths, {'cv': {}}, [], SimpleNamespace(by_id={}))
    assert report['ok'] is True
    return data


def recipe(page, base):
    return {
        'schema_version': 2, 'session_id': session_id(page),
        'steps': [
            {'url': base + '/one', 'ready_selector': '#name', 'scopes': [
                {'url': base + '/one', 'fields': {
                    'full_name': {'selector': '#name'},
                    'choice': {'selector': '#choice', 'kind': 'combobox', 'options': {'synthetic': '#option'}},
                    'consent': {'selector': '#consent', 'kind': 'checkbox'}}},
                {'frame_selector': '#details', 'url': base + '/frame', 'fields': {
                    'availability': {'selector': '[name=availability]'}}}],
             'next': {'selector': '#next', 'target_url': base + '/two'}},
            {'url': base + '/two', 'ready_selector': '[name=cv]', 'scopes': [
                {'url': base + '/two', 'fields': {'cv': {'selector': '[name=cv]'},
                                                'letter': {'selector': '[name=letter]'}}}]}],
        'requests': [{'method': 'GET', 'url': base + '/two'}],
    }


def bank():
    return {key: {'value': value, 'owner_verified': True} for key, value in {
        'full_name': 'Synthetic Person', 'choice': 'synthetic', 'consent': True,
        'availability': 'Synthetic verified availability'}.items()}


def run(page, plan, tmp_path, *, answers=None, docs=None):
    return fill_application(page, bank() if answers is None else answers, docs or {}, plan=plan,
                            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                            screenshot_dir=tmp_path / 'snapshots')


def test_multi_step_custom_frame_pdfs_private_snapshot_and_owner_submit(site, pdf_bytes, tmp_path):
    page, base, seen, _ = site
    plan = recipe(page, base)
    docs = {key: {'name': key + '.pdf', 'mimeType': 'application/pdf', 'buffer': pdf_bytes}
            for key in ('cv', 'letter')}
    result = run(page, plan, tmp_path, docs=docs)
    assert result.status == 'ready_for_owner'
    assert result.filled_count == 6
    assert result.completed_steps == 2
    assert not result.missing
    assert page.url == base + '/two'
    assert page.locator('[name=cv]').evaluate('e => e.files[0].type') == 'application/pdf'
    assert page.locator('[name=letter]').evaluate('e => e.files[0].size') == len(pdf_bytes)
    assert page.evaluate('window.submits') == 0
    assert ('POST', '/submit') not in seen
    assert all(Path(p).stat().st_mode & 0o777 == 0o600 for p in result.screenshots)
    assert (tmp_path / 'snapshots').stat().st_mode & 0o777 == 0o700
    assert len(result.screenshots) == 2
    # Only after automation returns does the owner press Submit.
    page.locator('#submit').click()
    assert page.evaluate('window.submits') == 1
    assert not page.is_closed()


def test_unknown_or_unverified_answers_stop_before_next(site, tmp_path):
    page, base, seen, _ = site
    answers = bank()
    answers['availability']['owner_verified'] = False
    result = run(page, recipe(page, base), tmp_path, answers=answers)
    assert result.status == 'needs_owner'
    assert result.completed_steps == 0
    assert result.missing == ('availability',)
    assert page.frame(url=base + '/frame').locator('input').input_value() == ''
    assert page.url == base + '/one'
    assert ('GET', '/two') not in seen


@pytest.mark.parametrize('fault', ['session', 'url', 'frame', 'duplicate', 'submit_next'])
def test_binding_faults_fail_closed(site, tmp_path, fault):
    page, base, seen, _ = site
    plan = recipe(page, base)
    if fault == 'session':
        plan['session_id'] = 'different-tab'
    elif fault == 'url':
        plan['steps'][0]['url'] = base + '/other'
        plan['steps'][0]['scopes'][0]['url'] = base + '/other'
    elif fault == 'frame':
        plan['steps'][0]['scopes'][1]['url'] = base + '/other'
    elif fault == 'duplicate':
        page.locator('#name').evaluate('e => e.after(e.cloneNode())')
    elif fault == 'submit_next':
        page.locator('#next').evaluate("e => e.setAttribute('type','submit')")
    if fault == 'duplicate':
        result = run(page, plan, tmp_path)
        assert 'full_name' in result.missing
        assert page.locator('#name').first.input_value() == ''
    else:
        with pytest.raises(PrefillRefused):
            run(page, plan, tmp_path)
    assert page.evaluate('window.submits') == 0
    assert ('GET', '/two') not in seen
    if fault in ('session', 'url', 'frame'):
        assert page.locator('#name').input_value() == ''


def test_network_submit_side_effect_is_blocked(site, tmp_path):
    page, base, seen, _ = site
    page.locator('#name').evaluate("e => e.oninput = () => fetch('/submit', {method:'POST',body:e.value}).catch(()=>{})")
    with pytest.raises(PrefillRefused, match='transmission'):
        run(page, recipe(page, base), tmp_path)
    assert ('POST', '/submit') not in seen
    assert ('GET', '/two') not in seen
    assert page.evaluate('window.submits') == 0


def test_dynamic_replacement_does_not_receive_verified_answer(site, tmp_path):
    page, base, _, _ = site
    page.locator('#name').evaluate("e => e.oninput=()=>{document.querySelector('#choice').outerHTML='<input id=choice>'}")
    result = run(page, recipe(page, base), tmp_path)
    assert 'choice' in result.missing
    assert page.locator('#choice').input_value() == ''
    assert result.status == 'needs_owner'


def test_authorized_manifest_binds_verified_package_bytes_and_session(site, pdf_bytes, tmp_path):
    page, base, _, _ = site
    answers = tmp_path / 'answers.yaml'
    answers.write_text(yaml.safe_dump({'fields': bank()}))
    answers.chmod(0o600)
    docs = {}
    for key in ('cv', 'letter'):
        docs[key] = tmp_path / (key + '.pdf')
        docs[key].write_bytes(pdf_bytes)
    _, _, metadata = file_snapshot(answers, docs)
    plan = recipe(page, base)
    plan.update(metadata)
    plan.update(application_id='synthetic-app', owner_authorized=True, authorization_reference='owner-synthetic',
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                document_roles={'cv': 'cv', 'letter': 'letter'},
                package_manifest={'pdfs': {key: hashlib.sha256(pdf_bytes).hexdigest() for key in docs},
                                  'verification': dict.fromkeys(('cv_pdf', 'letter_pdf', 'claims', 'review'), True)})
    manifest = tmp_path / 'workflow.json'
    manifest.write_text(json.dumps(plan))
    manifest.chmod(0o600)
    verified, fields, uploads, expiry = authorize_workflow(manifest, answers, docs, application_id='synthetic-app')
    docs['cv'].write_bytes(b'changed after authorization')
    result = fill_application(page, fields, uploads, plan=verified, expires_at=expiry,
                              screenshot_dir=tmp_path / 'snapshots')
    assert result.status == 'ready_for_owner'
    assert page.locator('[name=cv]').evaluate('e => e.files[0].size') == len(pdf_bytes)
    with pytest.raises(PrefillRefused):
        authorize_workflow(manifest, answers, docs, application_id='synthetic-app')


def test_discovery_covers_questions_frames_options_without_candidate_values(site):
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery, validate_plan
    page, base, _, _ = site
    page.locator('#choice').evaluate("e=>e.setAttribute('aria-controls','options')")
    page.locator('#name').fill('PRIVATE_NOT_DISCOVERED')
    page.frame(url=base + '/frame').locator('input').fill('PRIVATE_FRAME_VALUE')
    page.locator('form').evaluate('''e => e.insertAdjacentHTML('beforeend',
        '<label>Screening question<textarea name=screening>PRIVATE_TEXTAREA</textarea></label>' +
        '<label>Available start<select name=start><option value=soon>Soon</option></select></label>' +
        '<input name=password type=password value=PRIVATE_PASSWORD>' +
        '<input name=hidden_doc type=file style="display:none">')''')
    discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
    fields = [field for scope in discovery['scopes'] for field in scope['fields']]
    assert {'full_name', 'choice', 'consent', 'availability', 'screening', 'start', 'password', 'hidden_doc'} <= {f['name'] for f in fields}
    assert 'PRIVATE_' not in json.dumps(discovery)
    screening = next(f for f in fields if f['name'] == 'screening')
    assert screening['question'] == 'Screening question'
    choice = next(f for f in fields if f['name'] == 'choice')
    assert choice['options'] == [{'value': 'Synthetic', 'label': 'Synthetic', 'selector': '#option'}]
    plan = plan_from_discovery(discovery)
    validate_plan(plan)
    assert len(plan['steps'][0]['scopes']) == 2
    assert not any('password' in key for scope in plan['steps'][0]['scopes'] for key in scope['fields'])
    assert page.locator('#name').input_value() == 'PRIVATE_NOT_DISCOVERED'


def test_handoff_removes_guards_from_future_navigation(site, tmp_path):
    page, base, _, _ = site
    result = run(page, recipe(page, base), tmp_path, answers={})
    assert result.status == 'needs_owner'
    page.goto(base + '/two')
    page.locator('#submit').click()
    assert page.evaluate('window.submits') == 1
    assert page.evaluate('!!window.__jobwatchActive') is False


def test_network_body_allowlist_distinguishes_save_from_submit(site, tmp_path):
    page, base, seen, _ = site
    plan = recipe(page, base)
    plan['requests'].append({'method': 'POST', 'url': base + '/submit',
                             'body_sha256': hashlib.sha256(b'action=save').hexdigest()})
    page.locator('#name').evaluate("e => e.oninput = () => fetch('/submit', {method:'POST',body:'action=submit'}).catch(()=>{})")
    with pytest.raises(PrefillRefused, match='transmission'):
        run(page, plan, tmp_path)
    assert ('POST', '/submit') not in seen
    assert (tmp_path / 'snapshots' / 'stopped.png').stat().st_mode & 0o777 == 0o600


def test_strict_native_fields_can_attach_hidden_file_input(site, pdf_bytes, tmp_path):
    page, base, _, _ = site
    page.goto(base + '/two')
    page.locator('[name=cv]').evaluate("e=>e.style.display='none'")
    plan = recipe(page, base)
    plan['steps'] = plan['steps'][1:]
    plan['steps'][0]['ready_selector'] = '[name=letter]'
    docs = {key: {'name': key + '.pdf', 'mimeType': 'application/pdf', 'buffer': pdf_bytes}
            for key in ('cv', 'letter')}
    result = run(page, plan, tmp_path, docs=docs)
    assert result.status == 'ready_for_owner'
    assert result.filled_count == 2


@pytest.mark.parametrize('source', ['profile', 'saved_answer', 'agent_draft'])
def test_authority_bound_sources_fill_without_per_field_owner_verification(site, tmp_path, source):
    page, base, _, _ = site
    digest = hashlib.sha256(b'synthetic-approved-source').hexdigest()
    answers = tmp_path / 'answers.yaml'
    records = {key: {'value': record['value'], 'source': source, 'source_hash': digest} for key, record in bank().items()}
    answers.write_text(yaml.safe_dump({'fields': records}))
    answers.chmod(0o600)
    _, _, metadata = file_snapshot(answers, {})
    plan = recipe(page, base)
    plan['steps'] = plan['steps'][:1]
    del plan['steps'][0]['next']
    plan.update(metadata)
    plan.update(application_id='synthetic', owner_authorized=True, authorization_reference='owner-action',
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                answer_sources={source: [digest]}, authorized_fields=sorted(records))
    manifest = tmp_path / 'workflow.json'
    manifest.write_text(json.dumps(plan))
    manifest.chmod(0o600)
    verified, fields, uploads, expiry = authorize_workflow(manifest, answers, {}, application_id='synthetic')
    result = fill_application(page, fields, uploads, plan=verified, expires_at=expiry,
                              screenshot_dir=tmp_path / 'snapshots')
    assert result.status == 'ready_for_owner'
    assert page.locator('#name').input_value() == 'Synthetic Person'
    assert 'owner_verified' not in yaml.safe_load(answers.read_text())['fields']['full_name']
    plan['answer_sources'] = {}
    manifest.write_text(json.dumps(plan))
    with pytest.raises(PrefillRefused):
        authorize_workflow(manifest, answers, {}, application_id='synthetic')


def test_native_next_request_is_derived_from_filled_form(site, tmp_path):
    from jobwatch.apply.prefill_workflow import prepare_next_navigation
    page, base, seen, pages = site
    page.goto(base + '/two')
    page.set_content('<form method=get action="/two"><input name=response value="Synthetic verified">'
                     '<button name=stage value=next>Continue</button></form>')
    prepared = prepare_next_navigation(page, 'button')
    assert prepared['request'] == {'method': 'GET', 'url': base + '/two?response=Synthetic+verified&stage=next'}
    assert 'body' not in prepared['request']
    assert not any(path.startswith('/two?') for _, path in seen)


def test_native_submit_next_advances_without_clicking_final_submit(site, tmp_path):
    from jobwatch.apply.prefill_workflow import prepare_next_navigation
    page, base, seen, pages = site
    page.goto(base + '/two')
    page.set_content('<form method=get action="/two"><button name=stage value=next id=next>Continue</button></form>')
    prepared = prepare_next_navigation(page, '#next')
    target = prepared['next']['target_url']
    pages['/two?stage=next'] = '<form onsubmit="window.submits++;return false"><button id=final>Submit application</button></form><script>window.submits=0</script>'
    plan = {'schema_version': 2, 'session_id': session_id(page), 'requests': [prepared['request']],
            'steps': [{'url': page.url, 'scopes': [{'url': page.url, 'fields': {}}], 'next': prepared['next']},
                      {'url': target, 'ready_selector': '#final', 'scopes': [{'url': target, 'fields': {}}]}]}
    result = run(page, plan, tmp_path, answers={})
    assert result.status == 'ready_for_owner'
    assert result.completed_steps == 2
    assert page.evaluate('window.submits') == 0
    assert ('GET', '/two?stage=next') in seen
    page.locator('#final').click()
    assert page.evaluate('window.submits') == 1


@pytest.mark.parametrize('label', ['Submit', 'Apply now', 'Send', 'Complete application', 'Continue and submit'])
def test_final_or_ambiguous_controls_never_become_native_next(site, label):
    from jobwatch.apply.prefill_workflow import prepare_next_navigation
    page, _, _, _ = site
    page.set_content('<form method=post><button>' + label + '</button></form>')
    with pytest.raises(PrefillRefused):
        prepare_next_navigation(page, 'button')


def test_native_post_next_same_url_uses_prepared_exact_body(site, tmp_path):
    from jobwatch.apply.prefill_workflow import prepare_next_navigation
    page, base, seen, pages = site
    page.goto(base + '/two')
    page.set_content('<form method=post action="/two"><input name=response value="Synthetic verified">'
                     '<button name=stage value=next id=next>Save and continue</button></form>')
    prepared = prepare_next_navigation(page, '#next')
    assert prepared['request']['body_sha256'] == hashlib.sha256(b'response=Synthetic+verified&stage=next').hexdigest()
    pages[('POST', '/two')] = '<form onsubmit="window.submits++;return false"><button id=final>Submit application</button></form><script>window.submits=0</script>'
    plan = {'schema_version': 2, 'session_id': session_id(page), 'requests': [prepared['request']],
            'steps': [{'url': page.url, 'scopes': [{'url': page.url, 'fields': {'response': {'selector': '[name=response]'}}}], 'next': prepared['next']},
                      {'url': page.url, 'ready_selector': '#final', 'scopes': [{'url': page.url, 'fields': {}}]}]}
    result = run(page, plan, tmp_path, answers={'response': {'owner_verified': True, 'value': 'Synthetic verified'}})
    assert result.status == 'ready_for_owner'
    assert result.completed_steps == 2
    assert ('POST', '/two') in seen
    assert page.evaluate('window.submits') == 0


def test_dynamically_added_frame_stops_completion(site, tmp_path):
    page, base, seen, _ = site
    page.locator('#name').evaluate("e => e.oninput=()=>{let f=document.createElement('iframe'); document.body.append(f)}")
    result = run(page, recipe(page, base), tmp_path)
    assert result.status == 'needs_owner'
    assert 'unmapped-frame' in result.missing
    assert ('GET', '/two') not in seen


def test_native_multiple_select_uses_exact_verified_choices(site, tmp_path):
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery
    page, base, _, _ = site
    page.goto(base + '/two')
    page.set_content('<label>Preferred locations<select name=locations multiple><option value=melbourne>Melbourne</option>'
                     '<option value=remote>Remote</option><option value=other>Other</option></select></label>')
    discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
    question = discovery['scopes'][0]['fields'][0]
    assert question['multiple'] is True
    plan = plan_from_discovery(discovery)
    result = run(page, plan, tmp_path, answers={question['key']: {'owner_verified': True, 'value': ['melbourne', 'remote']}})
    assert result.status == 'ready_for_owner'
    assert page.locator('select').evaluate('e=>Array.from(e.selectedOptions).map(x=>x.value)') == ['melbourne', 'remote']


@pytest.mark.parametrize('action', ['/submit-application', '/application/submit', '/apply?action=submit', '/apply?final=true'])
def test_continue_label_does_not_authorize_final_endpoint_or_action(site, action):
    from jobwatch.apply.prefill_workflow import prepare_next_navigation
    page, _, seen, _ = site
    page.set_content('<form method=post action="' + action + '"><button>Continue</button></form>')
    before = list(seen)
    with pytest.raises(PrefillRefused, match='owner-only'):
        prepare_next_navigation(page, 'button')
    assert seen == before


@pytest.mark.parametrize('control', ['<input type=hidden name=action value=submit><button>Continue</button>',
                                     '<button name=action value=submit>Continue</button>'])
def test_continue_label_does_not_authorize_hidden_or_submitter_final_action(site, control):
    from jobwatch.apply.prefill_workflow import prepare_next_navigation
    page, _, seen, _ = site
    page.set_content('<form method=post action="/apply">' + control + '</form>')
    before = list(seen)
    with pytest.raises(PrefillRefused, match='owner-only'):
        prepare_next_navigation(page, 'button')
    assert seen == before


def test_repeated_native_radio_choices_preserve_distinct_group_questions(site):
    from jobwatch.apply.prefill_workflow import discover_application
    page, base, _, _ = site
    page.goto(base + '/two')
    page.set_content('''<fieldset><legend>Do you require employer sponsorship?</legend>
        <label><input type=radio name=sponsorship value=yes>Yes</label>
        <label><input type=radio name=sponsorship value=no>No</label></fieldset>
        <div role=radiogroup aria-labelledby=rights><p id=rights>Do you have current work rights?</p>
        <label><input type=radio name=work_rights value=yes>Yes</label>
        <label><input type=radio name=work_rights value=no>No</label></div>''')
    fields = discover_application(page, allowed_hosts=['127.0.0.1'])['scopes'][0]['fields']
    assert [field['question'] for field in fields] == ['Do you require employer sponsorship?', 'Do you have current work rights?']
    assert [[choice['label'] for choice in field['options']] for field in fields] == [['Yes', 'No'], ['Yes', 'No']]
    assert [field['name'] for field in fields] == ['sponsorship', 'work_rights']


def test_websocket_route_retains_owner_browser_policy_after_fill(site, tmp_path):
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery
    page, base, seen, pages = site
    pages['/socket-test'] = '<input name=full_name>'
    denied = []
    def owner_policy(ws):
        denied.append(True)
        ws.on_message(lambda _message: None)
    page.context.route_web_socket('**/*', owner_policy)
    page.goto(base + '/socket-test')
    page._jobwatch_block_websocket = owner_policy
    discovered = discover_application(page, allowed_hosts=['127.0.0.1'])
    key = discovered['scopes'][0]['fields'][0]['key']
    result = run(page, plan_from_discovery(discovered), tmp_path,
                 answers={key:{'value':'Synthetic','owner_verified':True}})
    assert result.status == 'ready_for_owner'
    page.evaluate('(url)=>setTimeout(()=>{window.socket=new WebSocket(url)},50)', base.replace('http:', 'ws:')+'/after')
    page.wait_for_function('window.socket && window.socket.readyState===1', timeout=3000)
    assert denied == [True]
    assert ('GET','/after') not in seen


@pytest.mark.parametrize('contradictory', [False, True])
def test_custom_radio_applies_selection_before_false_checks_and_verifies_group(site, tmp_path, contradictory):
    from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery
    page, base, _, _ = site
    page.goto(base + '/two')
    page.set_content('''<div role=radiogroup aria-label="Choose one answer">
        <div id=no role=radio aria-checked=true tabindex=0 onclick="this.setAttribute('aria-checked','true');yes.setAttribute('aria-checked','false')">No</div>
        <div id=yes role=radio aria-checked=false tabindex=0 onclick="this.setAttribute('aria-checked','true');no.setAttribute('aria-checked','false')">Yes</div></div>''')
    discovery = discover_application(page, allowed_hosts=['127.0.0.1'])
    fields = discovery['scopes'][0]['fields']
    assert [field['question'] for field in fields] == ['Choose one answer (option: No)', 'Choose one answer (option: Yes)']
    answers = {field['key']:{'owner_verified':True,'value':field['name']=='yes' or contradictory} for field in fields}
    result = run(page, plan_from_discovery(discovery), tmp_path, answers=answers)
    assert page.locator('#yes').get_attribute('aria-checked') == 'true'
    assert page.locator('#no').get_attribute('aria-checked') == 'false'
    assert result.status == ('needs_owner' if contradictory else 'ready_for_owner')
    assert bool(result.missing) is contradictory
