"""Browser checks against static controls and synthetic API responses."""
import os
from pathlib import Path

import pytest


@pytest.fixture
def controls_page():
    playwright = pytest.importorskip('playwright.sync_api')
    root = Path(__file__).resolve().parents[1] / 'pipeline' / 'agentic'
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=os.environ.get('JOBWATCH_TEST_BROWSER_CHANNEL'))
        page = browser.new_page(viewport={'width': 320, 'height': 700})
        run = {'id': 'x' * 160, 'state': 'running', 'interactions': [
            {'id': 'question', 'type': 'question', 'question': 'Synthetic answer?'}], 'artifacts': []}

        def route(request):
            path = request.request.url.split('https://controls.test')[-1]
            if path == '/':
                request.fulfill(body=(root / 'controls.html').read_text(), content_type='text/html')
            elif path.startswith('/agent/'):
                name = path.rsplit('/', 1)[-1]
                request.fulfill(body=(root / name).read_text(),
                                content_type='text/javascript' if name.endswith('.js') else 'text/css')
            elif path == '/api/agent/client/runs':
                request.fulfill(json={'runs': [run]})
            elif path.endswith('/cancel'):
                request.fulfill(json={})
            else:
                request.fulfill(json={'error': 'Synthetic failure'}, status=500)

        page.route('https://controls.test/**', route)
        page.goto('https://controls.test/')
        page.locator('#run-key').fill('synthetic-key')
        page.locator('#connect').click()
        page.locator('textarea').wait_for()
        yield page
        browser.close()


def test_refresh_preserves_drafts_focus_and_selection(controls_page):
    page = controls_page
    answer = page.locator('textarea')
    answer.fill('Draft العربية 中文 😀')
    answer.focus()
    answer.evaluate('(node) => node.setSelectionRange(2, 5)')
    page.evaluate('refresh()')
    assert answer.input_value() == 'Draft العربية 中文 😀'
    assert answer.evaluate('(node) => document.activeElement === node && node.selectionStart === 2 && node.selectionEnd === 5')
    page.get_by_role('button', name='Cancel run', exact=True).click()
    page.wait_for_function('document.activeElement.textContent === "Cancel run"')
    assert answer.input_value() == 'Draft العربية 中文 😀'


def test_confirmation_requests_overlap_and_digest_mismatch_blocks_approval(controls_page):
    page = controls_page
    page.evaluate('''() => {
      const original = window.fetch;
      let pending;
      window.fetch = async (path, options) => {
        const response = data => new Response(JSON.stringify(data), {status: 200});
        if (path === '/api/agent/client/runs') return response({runs: [{
          id: 'profile', state: 'waiting_for_approval', artifacts: [], interactions: [{
            id: 'confirm', type: 'approval', operation: 'profile_confirm',
            binding: {arguments: {proposal_id: 'proposal'}, proposal_digest: 'expected', scope_digest: 'scope'}
          }]
        }]});
        if (path.endsWith('/confirmation')) {
          pending();
          return response({proposal_digest: 'changed', scope_digest: 'scope'});
        }
        if (path.endsWith('/proposals/proposal')) {
          await new Promise(resolve => { pending = resolve; });
          return response({profile: 'synthetic'});
        }
        return original(path, options);
      };
    }''')
    page.locator('#connect').click()
    page.get_by_text('The profile or search scope changed.', exact=False).wait_for()
    assert page.get_by_role('button', name='Approve this exact operation').count() == 0
    assert page.locator('#connect').is_enabled()


def test_mobile_long_identifiers_do_not_overflow(controls_page):
    page = controls_page
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.evaluate('document.documentElement.style.fontSize = "200%"')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_upload_failure_is_announced_and_button_recovers(controls_page):
    page = controls_page
    page.locator('#upload').click()
    assert page.locator('#uploaded').inner_text() == 'Choose a document.'
    assert page.locator('#uploaded').get_attribute('role') == 'status'
    assert page.locator('#upload').is_enabled()
    page.locator('#file').set_input_files({'name': 'synthetic.txt', 'mimeType': 'text/plain', 'buffer': b'Synthetic'})
    page.locator('#upload').click()
    page.wait_for_function('document.getElementById("uploaded").textContent === "Synthetic failure"')
    assert page.locator('#upload').is_enabled()
