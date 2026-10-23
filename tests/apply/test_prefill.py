"""Synthetic only: mutations to verified gating or button avoidance must fail these tests."""
from pathlib import Path

import pytest
pytest.importorskip('playwright.sync_api',  # module-level: collection used to error without the
                    reason='the prefill tests need the browser extra')  # browser extra, not skip
from playwright.sync_api import sync_playwright

from jobwatch.apply import prefill


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''<form onsubmit="window.submitted++; return false">
          <label for="name">Full name</label><input id="name" name="full_name">
          <select name="notice"><option value="">Choose</option><option>Two weeks</option></select>
          <input type="radio" name="rights" value="yes"><input type="radio" name="rights" value="no">
          <input type="checkbox" name="consent">
          <textarea name="screening"></textarea><input name="unknown">
          <input type="file" name="cv"><input type="file" name="letter">
          <input type="hidden" name="csrf" value="synthetic">
          <input type="password" name="password">
          <button onclick="window.clicked++">Submit</button>
        </form><script>window.submitted=0;window.clicked=0</script>''')
        yield page
        browser.close()


def answer(value, verified=True):
    return {'value': value, 'owner_verified': verified}


def test_fill_controls_documents_and_never_submit(page, tmp_path):
    cv = tmp_path / 'cv.pdf'; cv.write_bytes(b'synthetic CV')
    letter = tmp_path / 'letter.pdf'; letter.write_bytes(b'synthetic letter')
    bank = {'full_name': answer('Synthetic Person'), 'notice': answer('Two weeks'),
            'rights': answer('no'), 'consent': answer(False),
            'screening': answer('Synthetic verified response')}
    result = prefill.fill_page(page, bank, {'cv': cv, 'letter': letter}, authorized_url=page.url)
    assert page.locator('[name=full_name]').input_value() == 'Synthetic Person'
    assert page.locator('[name=notice]').input_value() == 'Two weeks'
    assert page.locator('[name=rights][value=no]').is_checked()
    assert not page.locator('[name=consent]').is_checked()
    assert page.locator('[name=cv]').evaluate('(e) => e.files.length') == 1
    assert page.locator('[name=letter]').evaluate('(e) => e.files.length') == 1
    assert result.missing == ('unknown', 'password')
    assert 'Synthetic Person' not in repr(result)
    assert page.evaluate('window.submitted + window.clicked') == 0
    # The guard is released for owner takeover; only the owner submits.
    page.evaluate('document.querySelector("form").requestSubmit()')
    assert page.evaluate('window.submitted') == 1


def test_unverified_partial_unknown_and_invalid_choices_remain_blank(page):
    result = prefill.fill_page(page, {'full_name': answer('Never use', False),
        'notice': answer('Not an option'), 'rights': answer('maybe'),
        'consent': answer('yes')}, {}, authorized_url=page.url)
    assert page.locator('[name=full_name]').input_value() == ''
    assert page.locator('[name=notice]').input_value() == ''
    assert page.locator('[name=rights]:checked').count() == 0
    assert not page.locator('[name=consent]').is_checked()
    assert set(result.missing) == {'full_name','notice','rights','consent','screening','unknown','cv','letter','password'}


def test_requires_exact_application_authorization_before_mutation(page):
    with pytest.raises(prefill.PrefillRefused, match='authorization'):
        prefill.fill_page(page, {'full_name': answer('Do not send')}, {}, authorized_url='https://different.invalid/')
    assert page.locator('[name=full_name]').input_value() == ''


def test_duplicate_names_and_unsupported_controls_fail_closed(page):
    page.set_content('<input name="same"><input name="same"><input type="range" name="salary">')
    result = prefill.fill_page(page, {'same': answer('Ambiguous'), 'salary': answer('100')}, {}, authorized_url=page.url)
    assert result.missing == ('same', 'salary')
    assert page.locator('[name=same]').first.input_value() == ''


def test_answers_file_private_and_schema_errors_do_not_echo_values(tmp_path):
    path = tmp_path / 'answers.yaml'
    path.write_text('fields:\n  full_name:\n    value: Synthetic Person\n    owner_verified: true\n')
    path.chmod(0o600)
    assert prefill.load_answers(path)['full_name']['owner_verified'] is True
    path.chmod(0o644)
    with pytest.raises(prefill.PrefillRefused, match='private'):
        prefill.load_answers(path)
    path.chmod(0o600)
    path.write_text('fields: [PRIVATE VALUE')
    with pytest.raises(prefill.PrefillRefused) as exc:
        prefill.load_answers(path)
    assert 'PRIVATE VALUE' not in str(exc.value)
