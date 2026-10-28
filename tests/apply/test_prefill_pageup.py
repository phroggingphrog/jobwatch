"""Public PageUp entry shape replayed entirely through synthetic Chromium routes."""
import json
from types import SimpleNamespace
import pytest
from jobwatch.apply import prepare
from jobwatch.apply.ats import pageup_entry_link
from jobwatch.apply.prefill_workflow import discover_application, plan_from_discovery
from jobwatch.apply.prefill import PrefillRefused
from tests.apply.test_prefill_workflow import site, pdf_bytes
from tests.apply.test_prepare import inputs, planner

ADVERT = 'https://careers.pageuppeople.com/100/cw/en/job/12345/synthetic-role'
ENTRY = 'https://secure.dc2.pageuppeople.com/apply/synthetic'
FORM = 'https://secure.dc2.pageuppeople.com/apply/synthetic-form'
CAPTCHA = 'https://newassets.hcaptcha.com/captcha/v1/checkbox.html#synthetic-fragment'


def public_shape(page):
    responses = {
        ADVERT: '<input name=keywords><label><input type=checkbox name=filter>Location filter</label>'
                '<a href="' + ENTRY + '">Apply now</a>',
        ENTRY: '<iframe id=application src="' + FORM + '" style="width:100%;height:800px"></iframe>',
        FORM: '<form onsubmit="window.submits++;return false"><label>Full name<input name=full_name></label>'
              '<label>Why are you suitable?<textarea name=motivation></textarea></label>'
              '<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>'
              '<textarea name=h-captcha-response hidden></textarea>'
              '<iframe title="Human verification" src="' + CAPTCHA + '"></iframe>'
              '<button>Submit application</button></form><script>window.submits=0</script>',
        CAPTCHA.split('#')[0]: '<p>Synthetic owner-only verification widget</p>',
    }
    def response(route):
        text = responses.get(route.request.url)
        if text is None or route.request.method != 'GET':
            route.abort()
        else:
            route.fulfill(status=200, content_type='text/html', body=text)
    page.context.route('https://**/*', response)
    page._jobwatch_validate_request_url = lambda url: None  # all public-shaped URLs are fulfilled offline above
    page.goto(ADVERT)
    return responses


def test_pageup_advert_filters_do_not_become_answers_and_owner_challenge_can_resume(site, inputs, planner):
    page, _, seen, _ = site
    public_shape(page)
    before = list(seen)
    assert pageup_entry_link(page) == ENTRY
    inputs['allowed_hosts'] = ['careers.pageuppeople.com']
    first = prepare.prepare_application(page, **inputs)
    assert first.status == 'needs_owner' and first.reason == 'owner_session_required'
    assert page.url == ENTRY
    assert first.missing[0]['key'] == 'owner_verification'
    assert planner == []
    assert first.screenshots
    with pytest.raises(prepare.PreparationRefused, match='browser_sign_in_required'):
        prepare.record_owner_answer(inputs['data_root'], inputs['application_id'],
            question_id=first.missing[0]['question_id'], value='not-a-verification')
    form = page.frame(url=FORM)
    assert form.locator('[name=full_name]').input_value() == ''
    # Simulate an owner-completed LOCAL widget. Production never writes this.
    form.locator('[name=h-captcha-response]').evaluate("e=>e.value='SYNTHETIC_PRIVATE_CAPTCHA_TOKEN'")
    discovery = discover_application(page, allowed_hosts=['secure.dc2.pageuppeople.com'])
    assert discovery['owner_challenges'] == []
    assert 'SYNTHETIC_PRIVATE_CAPTCHA_TOKEN' not in json.dumps(discovery)
    assert not any(c['name']=='h-captcha-response' for s in discovery['scopes'] for c in s['fields'])
    inputs['allowed_hosts'] = ['secure.dc2.pageuppeople.com']
    second = prepare.prepare_application(page, **inputs)
    assert second.status == 'ready_for_owner', second
    assert form.locator('[name=full_name]').input_value() == 'Synthetic Person'
    assert form.locator('[name=cv]').evaluate('e=>e.files.length') == 1
    assert form.evaluate('window.submits') == 0
    assert seen == before
    for path in second.run_dir.rglob('*'):
        if path.is_file() and path.suffix in ('.json', '.yaml'):
            assert 'SYNTHETIC_PRIVATE_CAPTCHA_TOKEN' not in path.read_text()


def test_captcha_fragment_is_explicit_owner_checkpoint_not_invalid_url(site):
    page, _, _, _ = site
    public_shape(page)
    page.goto(ENTRY)
    found = discover_application(page, allowed_hosts=['secure.dc2.pageuppeople.com'])
    assert found['owner_challenges'] == ['hcaptcha']
    assert len(found['scopes']) == 2
    with pytest.raises(PrefillRefused, match='owner verification'):
        plan_from_discovery(found)


def test_pageup_entry_refuses_ambiguous_or_uninspected_destination(site):
    page, _, _, _ = site
    public_shape(page)
    page.locator('a').evaluate("e=>e.href='https://uninspected.example.test/apply'")
    assert pageup_entry_link(page) is None
    page.locator('a').evaluate('(e,target)=>e.href=target', ENTRY)
    page.locator('body').evaluate('(e,target)=>e.insertAdjacentHTML("beforeend", `<a href="${target}/other">Apply now</a>`)', ENTRY)
    assert pageup_entry_link(page) is None


@pytest.mark.parametrize('method,kind,url,allowed', [
    ('GET','script','https://secure.dc2.pageuppeople.com/assets/app.js',True),
    ('GET','stylesheet','https://newassets.hcaptcha.com/captcha.css',True),
    ('POST','script','https://secure.dc2.pageuppeople.com/assets/app.js',False),
    ('GET','fetch','https://secure.dc2.pageuppeople.com/apply/save',False),
    ('GET','script','https://secure.dc2.pageuppeople.com/submit-application',False),
    ('GET','script','https://uninspected.example.test/app.js',False),
])
def test_pageup_entry_resource_scope_is_read_only_and_specific(method, kind, url, allowed):
    from jobwatch.web.browser_session import _Session
    session = _Session.__new__(_Session)
    session.entry_provider = 'pageup'
    request = SimpleNamespace(method=method,resource_type=kind,url=url,is_navigation_request=lambda:False)
    assert session._entry_resource(request) is allowed


def test_embedded_manager_pageup_entry_loads_declared_form_then_stops_for_owner(site, inputs, planner, monkeypatch):
    from urllib.parse import urlsplit
    from jobwatch.web import browser_session
    page, _, _, _ = site
    responses = public_shape(page)
    requests = []
    def offline(self, route):
        requests.append((route.request.method, route.request.resource_type))
        body = responses.get(route.request.url)
        if body is None or route.request.method != 'GET':
            route.abort()
        else:
            route.fulfill(status=200, content_type='text/html', body=body)
    monkeypatch.setattr(browser_session, '_public_url', lambda url, **kwargs: urlsplit(url))
    monkeypatch.setattr(browser_session._Session, '_fetch_public', offline)
    manager = browser_session.BrowserSessionManager(inputs['data_root'])
    inputs['allowed_hosts'] = ['careers.pageuppeople.com']
    try:
        manager.open(inputs['application_id'], ADVERT)
        result = manager.prepare(inputs['application_id'], lambda page: prepare.prepare_application(page, **inputs)).result(timeout=30)
        assert result.status == 'needs_owner', result
        assert result.reason == 'owner_session_required'
        assert result.missing[0]['key'] == 'owner_verification'
        assert not planner
        assert all(method == 'GET' for method, _ in requests)
        assert sum(kind == 'document' for _, kind in requests) == 4
    finally:
        manager.close_all()
