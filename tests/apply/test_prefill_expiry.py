"""Deterministic transmission-time expiry; intercepted loopback pages only."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
pytest.importorskip('playwright.sync_api',  # module-level: collection used to error without the
                    reason='the prefill tests need the browser extra')  # browser extra, not skip
from playwright.sync_api import ElementHandle, sync_playwright

from jobwatch.apply import prefill
from tests.apply.test_prefill_manifest import URL, bundle, authorize


@pytest.fixture
def clock(monkeypatch):
    now = datetime.now(timezone.utc)
    state = SimpleNamespace(now=now)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state.now

    monkeypatch.setattr(prefill, 'datetime', Clock)
    return state


@pytest.mark.parametrize('stage', ['connect', 'navigation', 'attach_inspection'])
def test_cli_expiry_before_first_mutation(bundle, clock, monkeypatch, capsys, stage):
    answers, doc, manifest, _ = bundle
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context()
        context.route('**/*', lambda route: route.fulfill(content_type='text/html', body='<input name=response><input type=file name=cv>'))
        page = context.new_page()
        page.goto(URL)
        real_goto = page.goto
        real_query = page.query_selector_all

        def expire():
            clock.now += timedelta(hours=2)

        def goto(url):
            real_goto(url)
            expire()

        def query(selector):
            result = real_query(selector)
            expire()
            return result

        def connect(_):
            if stage == 'connect':
                expire()
            return SimpleNamespace(contexts=[SimpleNamespace(pages=[page], new_page=lambda: page)])

        if stage == 'navigation':
            monkeypatch.setattr(page, 'goto', goto)
        if stage == 'attach_inspection':
            monkeypatch.setattr(page, 'query_selector_all', query)

        @contextmanager
        def fake_playwright():
            yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))

        monkeypatch.setattr('playwright.sync_api.sync_playwright', fake_playwright)
        argv = ['prefill', '--authorize-transmission', '--manifest', str(manifest),
                '--application-id', 'synthetic-app', '--answers', str(answers), '--document', f'cv={doc}']
        argv += ['--attach', '--allow-host', '127.0.0.1'] if stage == 'attach_inspection' else ['--url', URL]
        monkeypatch.setattr('sys.argv', argv)
        assert prefill.main() == 1
        output = capsys.readouterr()
        assert 'SYNTHETIC' not in output.out + output.err
        assert page.locator('[name=response]').input_value() == ''
        assert page.locator('[name=cv]').evaluate('e => e.files.length') == 0
        browser.close()


def test_expiry_during_multifield_fill_stops_next_upload(bundle, clock, monkeypatch):
    fields, docs, expiry = authorize(bundle)
    original_fill = ElementHandle.fill

    def fill_then_expire(self, *args, **kwargs):
        result = original_fill(self, *args, **kwargs)
        clock.now = expiry
        return result

    monkeypatch.setattr(ElementHandle, 'fill', fill_then_expire)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content('<input name=response><input type=file name=cv>')
        with pytest.raises(prefill.PrefillRefused, match='expired') as exc:
            prefill.fill_page(page, fields, docs, authorized_url=page.url, expires_at=expiry)
        assert 'SYNTHETIC' not in str(exc.value)
        assert page.locator('[name=response]').input_value() == 'SYNTHETIC_PRIVATE'
        assert page.locator('[name=cv]').evaluate('e => e.files.length') == 0
        browser.close()


@pytest.mark.parametrize('html,value,documents', [
    ('<input name=response>', 'synthetic', {}),
    ('<textarea name=response></textarea>', 'synthetic', {}),
    ('<input type=checkbox name=response>', True, {}),
    ('<input type=radio name=response value=synthetic>', 'synthetic', {}),
    ('<select name=response><option value="">Empty</option><option>synthetic</option></select>', 'synthetic', {}),
    ('<input type=file name=response>', None, {'response': {'name': 'synthetic.txt', 'buffer': b'synthetic'}}),
])
def test_expiry_during_control_validation_blocks_each_mutation(clock, monkeypatch, html, value, documents):
    expiry = clock.now + timedelta(minutes=1)
    original_enabled = ElementHandle.is_enabled

    def enabled_then_expire(self):
        result = original_enabled(self)
        clock.now = expiry
        return result

    monkeypatch.setattr(ElementHandle, 'is_enabled', enabled_then_expire)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        with pytest.raises(prefill.PrefillRefused, match='expired'):
            prefill.fill_page(page, {'response': {'value': value, 'owner_verified': True}}, documents,
                              authorized_url=page.url, expires_at=expiry)
        assert page.locator('[name=response]').evaluate('e => e.type === "file" ? e.files.length === 0 : '
                                                       'e.type === "checkbox" || e.type === "radio" ? !e.checked : e.value === ""')
        browser.close()
