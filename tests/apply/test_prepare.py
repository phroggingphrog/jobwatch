"""Owner-facing preparation: automatic fields/answers/PDFs, no manual manifest."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from jobwatch.apply import answers_agent, prepare
from jobwatch.apply.answers_agent import save_owner_answer
from tests.apply.test_prefill_workflow import site, pdf_bytes


@pytest.fixture
def inputs(tmp_path, pdf_bytes):
    profile = tmp_path / 'profile'
    profile.mkdir(mode=0o700)
    text = 'Full name: Synthetic Person. Reconciled invoices in Excel. Consent to processing: yes.'
    (profile / 'cv.md').write_text(text)
    (profile / 'cv.md').chmod(0o600)
    data = tmp_path / 'data'
    data.mkdir(mode=0o700)
    paths = {role: tmp_path / (role + '.pdf') for role in ('cv', 'letter')}
    package = {'pdfs': {role: hashlib.sha256(pdf_bytes).hexdigest() for role in paths},
               'verification': dict.fromkeys(('cv_pdf', 'letter_pdf', 'claims', 'review'), True)}
    return dict(application_id='synthetic-app', package_manifest=package, document_paths=paths,
                profile_root=profile, data_root=data, job={'title': 'Accounts analyst', 'company': 'Synthetic employer'},
                budget=object(), llm=object(), reviewer=object(), allowed_hosts=['127.0.0.1'])


@pytest.fixture
def planner(monkeypatch):
    calls = []
    def runner(role, context, budget, llm):
        calls.append(role.name)
        if role.name == 'prefill_answers':
            source_ids = {item['source_id']: item['content_hash'] for item in context['sources']}
            rows = []
            for question in context['questions']:
                name = question['question'].lower()
                source_id, source = 'cv.md', 'profile'
                if 'start' in name:
                    if 'saved_answers' not in source_ids:
                        rows.append({'key': question['key'], 'value': None, 'source': 'unknown', 'citations': [],
                                     'question_to_owner': 'What date can you start?'})
                        continue
                    source_id, source = 'saved_answers', 'saved_answer'
                    value, quote = '2026-11-02', '2026-11-02'
                elif 'suitable' in name:
                    value = 'My invoice reconciliation experience in Excel fits this accounts role.'
                    quote, source = 'Reconciled invoices in Excel.', 'agent_draft'
                else:
                    value, quote = 'Synthetic Person', 'Synthetic Person'
                rows.append({'key': question['key'], 'value': value, 'source': source,
                             'citations': [{'source_id': source_id, 'content_hash': source_ids[source_id], 'quote': quote}],
                             'question_to_owner': ''})
            output = {'answers': rows}
        else:
            output = {'approved': True, 'checks': dict.fromkeys(answers_agent.CHECKS, True), 'feedback': []}
        return SimpleNamespace(output=role.tools[-1].arguments_model.model_validate(output))
    monkeypatch.setattr(answers_agent, 'run_role', runner)
    return calls


def final_page(page, base, *, extra=''):
    page.goto(base + '/two')
    page.set_content('<form onsubmit="window.submits++;return false">'
        '<label>Full name<input name=full_name></label>'
        '<label>Why are you suitable?<textarea name=motivation></textarea></label>'
        '<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>'
        + extra + '<button>Submit application</button></form><script>window.submits=0</script>')


def test_prepares_personal_details_questions_and_both_pdfs_without_manual_bindings(site, inputs, planner, pdf_bytes):
    page, base, _, _ = site
    final_page(page, base)
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'ready_for_owner', result
    assert page.locator('[name=full_name]').input_value() == 'Synthetic Person'
    assert page.locator('[name=motivation]').input_value().startswith('My invoice reconciliation')
    assert page.locator('[name=cv]').evaluate('e=>e.files[0].size') == len(pdf_bytes)
    assert page.locator('[name=letter]').evaluate('e=>e.files[0].type') == 'application/pdf'
    assert planner == ['prefill_answers', 'reviewer']
    assert page.evaluate('window.submits') == 0
    assert result.completed_steps == 1
    assert not result.missing
    assert 'Synthetic' not in (result.run_dir / 'status.json').read_text()
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in result.run_dir.rglob('*') if path.is_file())
    assert all(path.stat().st_mode & 0o777 == 0o700 for path in result.run_dir.rglob('*') if path.is_dir())
    page.locator('button').click()
    assert page.evaluate('window.submits') == 1


def test_missing_fact_is_one_private_intake_then_saved_answer_fills_it(site, inputs, planner):
    page, base, _, _ = site
    final_page(page, base, extra='<label>Start date<input type=date name=start></label>')
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'needs_owner'
    assert len(result.missing) == 1
    assert result.missing[0]['question'] == 'What date can you start?'
    assert page.locator('[name=start]').input_value() == ''
    assert (result.run_dir / 'questions.json').stat().st_mode & 0o777 == 0o600
    # Explicit owner reply goes to reusable intake; the owner never types the form.
    save_owner_answer(prepare.saved_answers_path(inputs['data_root']), question=result.missing[0]['question'], value='2026-11-02')
    second = prepare.prepare_application(page, **inputs)
    assert second.status == 'ready_for_owner', second
    assert second.run_dir != result.run_dir
    assert page.locator('[name=start]').input_value() == '2026-11-02'
    assert page.evaluate('window.submits') == 0


def test_controller_rediscovers_and_answers_native_next_page(site, inputs, planner):
    page, base, seen, pages = site
    page.goto(base + '/two')
    page.set_content('<form method=get action="/two"><label>Full name<input name=full_name></label>'
                     '<button name=stage value=next>Continue</button></form>')
    pages['/two?full_name=Synthetic+Person&stage=next'] = '''<form onsubmit="window.submits++;return false">
        <label>Why are you suitable?<textarea name=motivation></textarea></label>
        <label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>
        <button>Submit application</button></form><script>window.submits=0</script>'''
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'ready_for_owner', result
    assert result.completed_steps == 2
    assert planner == ['prefill_answers', 'reviewer', 'prefill_answers', 'reviewer']
    assert page.locator('[name=motivation]').input_value().startswith('My invoice')
    assert page.locator('[name=cv]').evaluate('e=>e.files.length') == 1
    assert page.evaluate('window.submits') == 0
    assert ('GET', '/two?full_name=Synthetic+Person&stage=next') in seen


def test_changed_pdf_refuses_before_browser_values(site, inputs, planner):
    page, base, _, _ = site
    final_page(page, base)
    inputs['document_paths']['cv'].write_bytes(b'%PDF-changed-synthetic')
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'blocked'
    assert result.reason == 'verified_pdf_package_required'
    assert not planner
    assert page.locator('[name=full_name]').input_value() == ''
    assert page.evaluate('window.submits') == 0


def test_complex_next_is_reported_as_adapter_gap_without_click(site, inputs, planner):
    page, base, _, _ = site
    final_page(page, base)
    page.locator('button').evaluate('''e=>{e.type='button';e.textContent='Continue';e.onclick=()=>window.submits++}''')
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'needs_adapter'
    assert result.reason == 'next_requires_site_adapter'
    assert page.locator('[name=full_name]').input_value() == 'Synthetic Person'
    assert page.evaluate('window.submits') == 0


def test_owner_authorization_is_required_before_read_or_fill(site, inputs, planner):
    page, _, _, _ = site
    with pytest.raises(prepare.PreparationRefused, match='owner_authorization_required'):
        prepare.prepare_application(page, **inputs, owner_authorized=False)
    assert not planner


def test_latest_private_review_and_only_current_intake_acceptance(site, inputs, planner):
    page, base, _, _ = site
    assert prepare.latest_preparation(inputs['data_root'], inputs['application_id']) is None
    final_page(page, base, extra='<label>Start date<input type=date name=start></label>')
    result = prepare.prepare_application(page, **inputs)
    state = prepare.latest_preparation(inputs['data_root'], inputs['application_id'])
    assert state['status'] == 'needs_owner'
    assert state['run_id'] == result.run_dir.name
    assert state['missing'][0]['type'] == 'date'
    assert state['review_answers'][0]['value'] == 'Synthetic Person'
    assert state['screenshots']
    with pytest.raises(prepare.PreparationRefused, match='pending_question_required'):
        prepare.record_owner_answer(inputs['data_root'], inputs['application_id'], question_id='not-current', value='No')
    prepare.record_owner_answer(inputs['data_root'], inputs['application_id'],
                                question_id=state['missing'][0]['question_id'], value='2026-11-02')
    second = prepare.prepare_application(page, **inputs)
    assert second.status == 'ready_for_owner'
    assert prepare.latest_preparation(inputs['data_root'], inputs['application_id'])['run_id'] == second.run_dir.name
    with pytest.raises(prepare.PreparationRefused, match='pending_question_required'):
        prepare.record_owner_answer(inputs['data_root'], inputs['application_id'],
                                    question_id=state['missing'][0]['question_id'], value='2027-01-01')


def test_advert_apply_anchor_is_followed_without_user_mapping(site, inputs, planner):
    page, base, _, pages = site
    page.goto(base + '/two')
    page.set_content('<article>Synthetic role</article><a href="/application">Apply now</a>')
    pages['/application'] = '<form onsubmit="window.submits++;return false"><label>Full name<input name=full_name></label>' \
        '<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>' \
        '<button>Submit application</button></form><script>window.submits=0</script>'
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'ready_for_owner', result
    assert page.url == base + '/application'
    assert page.locator('[name=full_name]').input_value() == 'Synthetic Person'
    assert page.evaluate('window.submits') == 0


def test_resume_only_form_reports_absent_letter_control_honestly(site, inputs, planner):
    page, base, _, _ = site
    final_page(page, base)
    page.locator('[name=letter]').evaluate('e=>e.closest("label").remove()')
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'ready_for_owner'
    assert result.reason == 'cover_letter_not_requested'
    state = prepare.latest_preparation(inputs['data_root'], inputs['application_id'])
    assert set(state['attached_documents']) == {'cv'}
    assert state['package_hash'] == hashlib.sha256(json.dumps(inputs['package_manifest'], sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def test_multipart_upload_next_then_missing_answer_retry_keeps_bound_attachments(site, inputs, planner):
    page, base, seen, pages = site
    page.goto(base + '/two')
    page.set_content('<form method=post enctype="multipart/form-data" action="/questions">'
        '<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>'
        '<button name=stage value=next>Continue</button></form>')
    pages[('POST', '/questions')] = '<form onsubmit="window.submits++;return false">' \
        '<label>Start date<input type=date name=start></label>' \
        '<label>Why are you suitable?<textarea name=motivation></textarea></label>' \
        '<button>Submit application</button></form><script>window.submits=0</script>'
    first = prepare.prepare_application(page, **inputs)
    assert first.status == 'needs_owner', first
    assert ('POST', '/questions') in seen
    assert page.url == base + '/questions'
    assert page.locator('[name=motivation]').input_value().startswith('My invoice')
    private = prepare.latest_preparation(inputs['data_root'], inputs['application_id'])
    assert set(private['attached_documents']) == {'cv', 'letter'}
    assert private['page_url_sha256'] == hashlib.sha256(page.url.encode()).hexdigest()
    prepare.record_owner_answer(inputs['data_root'], inputs['application_id'],
                                question_id=first.missing[0]['question_id'], value='2026-11-02')
    second = prepare.prepare_application(page, **inputs)
    assert second.status == 'ready_for_owner', second
    assert page.locator('[name=start]').input_value() == '2026-11-02'
    assert page.evaluate('window.submits') == 0


def test_multipart_uploads_questions_and_final_review_are_fully_automatic(site, inputs, planner):
    page, base, seen, pages = site
    page.goto(base + '/two')
    page.set_content('<form method=post enctype="multipart/form-data" action="/questions">'
        '<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>'
        '<button name=stage value=next>Save and continue</button></form>')
    pages[('POST', '/questions')] = '<form onsubmit="window.submits++;return false">' \
        '<label>Why are you suitable?<textarea name=motivation></textarea></label>' \
        '<button>Submit application</button></form><script>window.submits=0</script>'
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'ready_for_owner', result
    assert result.completed_steps == 2
    assert ('POST', '/questions') in seen
    assert page.locator('[name=motivation]').input_value().startswith('My invoice')
    assert page.evaluate('window.submits') == 0


def test_embedded_browser_controller_uploads_through_pinned_transport_and_binds_review(site, inputs, planner):
    from jobwatch.web.browser_session import BrowserSessionManager
    _, base, seen, pages = site
    pages['/managed'] = '<form method=post enctype="multipart/form-data" action="/questions">' \
        '<input type=hidden name=csrf value=synthetic-token>' \
        '<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>' \
        '<button name=stage value=next>Continue</button></form>'
    pages[('POST', '/questions')] = '<form onsubmit="window.submits++;return false">' \
        '<label>Why are you suitable?<textarea name=motivation></textarea></label>' \
        '<button>Submit application</button></form><script>window.submits=0</script>'
    manager = BrowserSessionManager(inputs['data_root'], allow_loopback=True)
    try:
        manager.open(inputs['application_id'], base + '/managed')
        result = manager.prepare(inputs['application_id'], lambda page: prepare.prepare_application(page, **inputs)).result(timeout=30)
        assert result.status == 'ready_for_owner', result
        assert ('POST', '/questions') in seen
        state = manager.status(inputs['application_id'])
        review = prepare.latest_preparation(inputs['data_root'], inputs['application_id'])
        assert review['session_id'] == state['target_id']
        assert review['owner_revision'] == state['owner_revision'] == 0
        assert review['page_url_sha256'] == state['page_url_sha256'] == hashlib.sha256((base + '/questions').encode()).hexdigest()
        assert manager.with_page(inputs['application_id'], lambda page: page.evaluate('window.submits')) == 0
        manager.action(inputs['application_id'], {'kind': 'key', 'key': 'Tab'})
        assert manager.status(inputs['application_id'])['owner_revision'] == 1
        assert review['owner_revision'] != manager.status(inputs['application_id'])['owner_revision']
    finally:
        manager.close_all()


@pytest.mark.parametrize('field,event,endpoint', [('full_name', 'input', '/autosave'), ('cv', 'change', '/upload')])
def test_blocked_autosave_or_upload_never_claims_ready(site, inputs, planner, field, event, endpoint):
    page, base, seen, _ = site
    final_page(page, base)
    page.locator('[name=' + field + ']').evaluate('''(e, args) => {
        e.addEventListener(args.event, () => fetch(args.endpoint, {method:'POST',body:'synthetic'}).catch(()=>{}));
    }''', {'event': event, 'endpoint': endpoint})
    result = prepare.prepare_application(page, **inputs)
    assert result.status == 'blocked', result
    assert prepare.latest_preparation(inputs['data_root'], inputs['application_id'])['status'] != 'ready_for_owner'
    assert ('POST', endpoint) not in seen
    assert page.evaluate('window.submits') == 0


def test_a_ready_fill_records_what_a_submit_confirmation_binds_to(site, inputs, planner):
    from jobwatch.apply import submit_confirm as sc
    page, base, _, _ = site
    final_page(page, base)
    assert prepare.prepare_application(page, **inputs).status == 'ready_for_owner'
    prepared = prepare.latest_preparation(inputs['data_root'], inputs['application_id'])
    control = prepared['final_control']
    assert control['label'] == 'submit application' and control['url'] == page.url and control['frame_path'] == []
    assert prepared['form_state'] == sc.form_state(page) and sc.digest(prepared)
    assert sc.final_control(page, control).evaluate('e=>e.textContent') == 'Submit application'
    page.locator('[name=full_name]').fill('Someone Else')
    assert sc.live_digest(prepared, page, session_id=prepared['session_id'],
                          owner_revision=prepared['owner_revision']) != sc.digest(prepared)

def test_the_original_cv_and_letter_file_names_are_kept_and_are_what_the_form_receives(site, inputs, planner):
    page, base, _, _ = site
    final_page(page, base)
    named = {}
    for role, name in (('cv', 'Alex_Example_CV_2026.pdf'), ('letter', 'Cover letter - Acme.pdf')):
        target = inputs['document_paths'][role].with_name(name)
        target.write_bytes(inputs['document_paths'][role].read_bytes())
        named[role] = target
    result = prepare.prepare_application(page, **dict(inputs, document_paths=named))
    assert result.status == 'ready_for_owner', result
    prepared = prepare.latest_preparation(inputs['data_root'], 'synthetic-app')
    assert prepared['document_names'] == {'cv': 'Alex_Example_CV_2026.pdf', 'letter': 'Cover letter - Acme.pdf'}
    assert page.locator('[name=cv]').evaluate('e=>e.files[0].name') == 'Alex_Example_CV_2026.pdf'
    assert page.locator('[name=letter]').evaluate('e=>e.files[0].name') == 'Cover letter - Acme.pdf'

def test_an_unsafe_original_name_falls_back_to_the_generic_one(site, inputs, planner):
    page, base, _, _ = site
    final_page(page, base)
    odd = inputs['document_paths']['cv'].with_name('x\u202eevil\n.pdf')
    odd.write_bytes(inputs['document_paths']['cv'].read_bytes())
    result = prepare.prepare_application(page, **dict(inputs, document_paths={**inputs['document_paths'], 'cv': odd}))
    assert result.status == 'ready_for_owner', result
    assert prepare.latest_preparation(inputs['data_root'], 'synthetic-app')['document_names']['cv'] == 'cv.pdf'
