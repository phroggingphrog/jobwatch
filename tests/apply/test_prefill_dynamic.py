"""Regression coverage for independently reproduced review blockers."""
import pytest
pytest.importorskip('playwright.sync_api',  # module-level: collection used to error without the
                    reason='the prefill tests need the browser extra')  # browser extra, not skip
from playwright.sync_api import sync_playwright
from jobwatch.apply.prefill import fill_page


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


@pytest.mark.parametrize('mutation', [
    "document.querySelector('[name=other]').remove()",
    "document.querySelector('[name=other]').outerHTML='<input name=other>'",
    "document.querySelector('[name=other]').before(Object.assign(document.createElement('input'),{name:'inserted'}))",
    "document.querySelector('[name=other]').name='declaration2'",
    "document.querySelector('[name=other]').type='password'",
    "document.querySelector('[name=other]').before(Object.assign(document.createElement('input'),{name:'other'}))",
])
def test_dynamic_controls_never_retarget_verified_answer(page, mutation):
    page.set_content('<input name=trigger><input name=other><input name=declaration>')
    original = page.query_selector('[name=other]')
    page.locator('[name=trigger]').evaluate('(e, script) => e.oninput = () => { eval(script); }', mutation)
    result = fill_page(page, {k: {'value': v, 'owner_verified': True} for k,v in
                            [('trigger','Synthetic trigger'),('other','Synthetic other')]}, {}, authorized_url=page.url)
    assert page.locator('[name=declaration]').input_value() == ''
    assert page.locator('[name=inserted]').count() == 0 or page.locator('[name=inserted]').input_value() == ''
    if 'inserted' in mutation:
        assert original.input_value() == 'Synthetic other'
    else:
        assert 'other' in result.missing
        assert page.locator('input').evaluate_all('(els) => els.every(e => e.value !== "Synthetic other")')


@pytest.mark.parametrize('record', [None, {'value':'on','owner_verified':False},
                                     {'value':None,'owner_verified':True}])
def test_valueless_radio_never_uses_absent_unverified_or_null_answer(page, record):
    page.set_content('<input type=radio name=legal_declaration>')
    bank = {} if record is None else {'legal_declaration':record}
    result = fill_page(page, bank, {}, authorized_url=page.url)
    assert not page.locator('input').is_checked()
    assert result.missing == ('legal_declaration',)
