"""Approval bindings, synthetic bytes only; no external site."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from playwright.sync_api import sync_playwright

from jobwatch.apply import prefill

URL = 'http://127.0.0.1/WelcomeScreen?in_jnCounter=synthetic-1'
CAREERS_URL = ('https://jobs.careers.vic.gov.au/jobtools/apCustomAppMgr.WelcomeScreen'
               '?in_jnCounter=226701307&in_organid=14123&in_template_orgid=17342&in_site=jobs.careers')


@pytest.fixture(params=[URL, CAREERS_URL])
def bundle(tmp_path, request):
    answers = tmp_path / 'answers.yaml'
    answers.write_text(yaml.safe_dump({'fields': {'response': {'value': 'SYNTHETIC_PRIVATE', 'owner_verified': True},
                                                'notes': {'value': 'SYNTHETIC_UNVERIFIED', 'owner_verified': False}}}))
    answers.chmod(0o600)
    doc = tmp_path / 'cv.pdf'; doc.write_bytes(b'SYNTHETIC_DOCUMENT')
    manifest = tmp_path / 'manifest.json'
    data = {'board_approval_id': 'synthetic-approval', 'application_id': 'synthetic-app',
            'host': prefill.urlparse(request.param).hostname, 'welcome_url': request.param,
            'answers_sha256': hashlib.sha256(answers.read_bytes()).hexdigest(),
            'verified_fields': ['response'],
            'documents_sha256': {'cv': hashlib.sha256(doc.read_bytes()).hexdigest()},
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    manifest.write_text(json.dumps(data)); manifest.chmod(0o600)
    return answers, doc, manifest, data


def authorize(bundle, **kwargs):
    answers, doc, manifest, _ = bundle
    return prefill.authorize_manifest(manifest, answers, {'cv': doc},
                                      application_id=kwargs.get('application_id', 'synthetic-app'),
                                      authorized_url=kwargs.get('url', bundle[3]['welcome_url']))


@pytest.mark.parametrize('fault', ['missing', 'permissions', 'symlink', 'invalid_json', 'approval', 'expiry',
                                  'naive_expiry', 'application', 'host', 'url', 'counter', 'answers',
                                  'documents', 'verified', 'extra_verified', 'unsorted', 'document_edit', 'answers_edit'])
def test_refuses_before_any_fill_or_upload(bundle, fault):
    answers, doc, manifest, data = bundle
    authorized_url = data['welcome_url']
    if fault == 'missing': manifest.unlink()
    elif fault == 'permissions': manifest.chmod(0o644)
    elif fault == 'symlink':
        target = manifest.with_suffix('.target'); manifest.rename(target); manifest.symlink_to(target)
    elif fault == 'invalid_json': manifest.write_text('SYNTHETIC_PRIVATE invalid')
    elif fault == 'document_edit': doc.write_bytes(b'SYNTHETIC_CHANGED')
    elif fault == 'answers_edit': answers.write_text(answers.read_text() + '\n# changed revision\n')
    else:
        key, value = {'approval': ('board_approval_id', ''), 'expiry': ('expires_at', '2000-01-01T00:00:00+00:00'),
                      'naive_expiry': ('expires_at', '2999-01-01T00:00:00'),
                      'application': ('application_id', 'different'), 'host': ('host', 'localhost'),
                      'url': ('welcome_url', authorized_url + '&other=1'),
                      'counter': ('welcome_url', authorized_url.split('?')[0]),
                      'answers': ('answers_sha256', '0'*64), 'documents': ('documents_sha256', {}),
                      'verified': ('verified_fields', []), 'extra_verified': ('verified_fields', ['notes', 'response']),
                      'unsorted': ('verified_fields', ['response', 'notes'])}[fault]
        data[key] = value; manifest.write_text(json.dumps(data))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(); page = browser.new_page()
        page.set_content('<input name=response><input type=file name=cv>')
        with pytest.raises(prefill.PrefillRefused) as exc:
            fields, docs, expiry = authorize(bundle, url=authorized_url)
            prefill.fill_page(page, fields, docs, authorized_url=page.url, expires_at=expiry)
        assert 'SYNTHETIC' not in str(exc.value)
        assert page.locator('[name=response]').input_value() == ''
        assert page.locator('[name=cv]').evaluate('e => e.files.length') == 0
        browser.close()


def test_matching_manifest_uses_authorized_snapshots(bundle):
    fields, docs, expiry = authorize(bundle)
    answers, doc, _, _ = bundle
    answers.write_text('changed after validation'); doc.write_bytes(b'changed after validation')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(); page = browser.new_page()
        page.set_content('<input name=response><input type=file name=cv><button>Submit</button>')
        result = prefill.fill_page(page, fields, docs, authorized_url=page.url, expires_at=expiry)
        assert result.filled_count == 2
        assert page.locator('[name=response]').input_value() == 'SYNTHETIC_PRIVATE'
        assert page.locator('[name=cv]').evaluate('async e => await e.files[0].text()') == 'SYNTHETIC_DOCUMENT'
        browser.close()


@pytest.mark.parametrize('path', [
    '/arbitrary', '/jobtools/WelcomeScreen', '/apCustomAppMgr.WelcomeScreen',
    '/jobtools/apCustomAppMgr.WelcomeScreen/extra',
    '/jobtools/apCustomAppMgr.WelcomeScreen/',
    '/jobtools/apCustomAppMgr.WelcomeScreen.evil',
    '/jobtools/apCustomAppMgr.welcomescreen',
    '/jobtools/%61pCustomAppMgr.WelcomeScreen',
])
def test_even_self_bound_unsupported_paths_are_refused(bundle, path):
    _, _, manifest, data = bundle
    url = 'https://jobs.careers.vic.gov.au' + path + '?in_jnCounter=synthetic-1'
    data.update(host='jobs.careers.vic.gov.au', welcome_url=url)
    manifest.write_text(json.dumps(data))
    with pytest.raises(prefill.PrefillRefused):
        authorize(bundle, url=url)


@pytest.mark.parametrize('query', ['', '?in_jnCounter=', '?in_jnCounter=1&in_jnCounter=2'])
def test_supported_path_still_requires_one_counter(bundle, query):
    _, _, manifest, data = bundle
    url = CAREERS_URL.split('?')[0] + query
    data.update(host='jobs.careers.vic.gov.au', welcome_url=url)
    manifest.write_text(json.dumps(data))
    with pytest.raises(prefill.PrefillRefused):
        authorize(bundle, url=url)


@pytest.mark.parametrize('url', [
    CAREERS_URL.replace('https:', 'http:'),
    CAREERS_URL.replace('https:', 'ftp:'),
    CAREERS_URL.replace('https://', 'https://user:password@'),
    CAREERS_URL + '#fragment',
])
def test_supported_path_does_not_bypass_url_safety(bundle, url):
    _, _, manifest, data = bundle
    data.update(host=prefill.urlparse(url).hostname, welcome_url=url)
    manifest.write_text(json.dumps(data))
    with pytest.raises(prefill.PrefillRefused):
        authorize(bundle, url=url)


def test_hash_command_outputs_only_hashes_and_verified_names(bundle):
    answers, doc, _, data = bundle
    result = subprocess.run([sys.executable, '-m', 'jobwatch.apply.prefill', 'manifest-hash',
                             '--answers', str(answers), '--document', f'cv={doc}'], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {k: data[k] for k in ['answers_sha256', 'verified_fields', 'documents_sha256']}
    assert 'SYNTHETIC' not in result.stdout + result.stderr
    assert str(doc) not in result.stdout


def test_authorize_cli_requires_manifest_before_browser(bundle):
    result = subprocess.run([sys.executable, '-m', 'jobwatch.apply.prefill', '--authorize-transmission',
                             '--url', URL], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'manifest' in result.stderr
