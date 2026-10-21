"""Real browser event capture must preserve remote typing and mouse control."""
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / 'jobwatch' / 'web' / 'static'


def test_remote_browser_controls_send_keys_to_the_remote_browser():
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('''
              <div id="preparation-status" data-automation-active="false"></div>
              <p id="browser-control-message"></p>
              <img id="application-browser" data-remote-browser tabindex="0"
                   data-action-url="/browser/action" width="300" height="100"
                   src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">''')
            page.evaluate('''() => {
              window.sentActions = [];
              window.fetch = async (url, options) => {
                if (url === '/browser/action') sentActions.push(JSON.parse(options.body));
                return {ok:true,json:async()=>({notes:[]})};
              };
            }''')
            for script in ('app/shell.js', 'browser.js'):
                page.add_script_tag(path=str(STATIC / script))
            remote = page.locator('#application-browser')
            remote.focus()
            page.keyboard.press('a')
            page.keyboard.press('d')
            page.keyboard.press('Escape')
            page.wait_for_function('sentActions.length === 3')
            assert page.evaluate('sentActions') == [
                {'kind': 'type', 'text': 'a'}, {'kind': 'type', 'text': 'd'}, {'kind': 'key', 'key': 'Escape'}]
        finally:
            browser.close()
