"""Guard behavior in the browser while automation is active."""
import pytest

pytest.importorskip('playwright.sync_api',  # module-level: collection used to error without the
                    reason='the prefill tests need the browser extra')  # browser extra, not skip
from playwright.sync_api import sync_playwright
from jobwatch.apply.prefill import _GUARD


def test_guard_blocks_buttons_and_both_submit_apis_then_releases_owner():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content('''<form onsubmit="window.submitted++;return false">
            <button onclick="window.clicked++">Submit</button></form>
            <script>window.submitted=0;window.clicked=0</script>''')
        page.evaluate(_GUARD)
        page.locator('button').click()
        page.evaluate('document.querySelector("form").submit()')
        page.evaluate('document.querySelector("form").requestSubmit()')
        assert page.evaluate('window.submitted + window.clicked') == 0
        page.evaluate('window.__jobwatchActive = false')
        page.locator('button').click()
        assert page.evaluate('window.submitted + window.clicked') == 2
        browser.close()
