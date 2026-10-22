import hashlib
import json
import stat

import pytest

from jobwatch.occupations import DiscoveryError
from jobwatch.occupations import datasets
from jobwatch.occupations.datasets import DatasetSpec, FileSpec, dataset_dir, fetch_dataset, verify_dataset


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))


def spec(sha=None, url='https://data.example.invalid/a.csv', **kwargs):
    return DatasetSpec(dataset='onet', version='t1', source_url='https://data.example.invalid/',
                       licence='CC BY 4.0', attribution='Test',
                       files=(FileSpec(name='a.csv', url=url, sha256=sha, bytes=None),), **kwargs)


def test_fetch_refuses_hash_mismatch_and_leaves_nothing():
    with pytest.raises(DiscoveryError, match='^dataset_hash_mismatch$'):
        fetch_dataset(spec('0' * 64), opener=lambda url: b'x,y\n1,2\n')
    assert not (dataset_dir('onet', 't1') / 'a.csv').exists()
    assert not (dataset_dir('onet', 't1') / 'manifest.json').exists()


def test_unpinned_fetch_needs_trust_on_first_use_then_records_the_hash():
    with pytest.raises(DiscoveryError, match='dataset_unpinned'):
        fetch_dataset(spec(), opener=lambda url: b'x\n')
    m = fetch_dataset(spec(), opener=lambda url: b'x\n', trust_on_first_use=True)
    assert m.sha256['a.csv'] == hashlib.sha256(b'x\n').hexdigest()
    assert stat.S_IMODE((dataset_dir('onet', 't1') / 'a.csv').stat().st_mode) == 0o600
    assert stat.S_IMODE(dataset_dir('onet', 't1').stat().st_mode) == 0o700
    assert verify_dataset('onet', 't1') == m


def test_verify_detects_tampering():
    fetch_dataset(spec(), opener=lambda url: b'x\n', trust_on_first_use=True)
    (dataset_dir('onet', 't1') / 'a.csv').write_bytes(b'tampered')
    with pytest.raises(DiscoveryError, match='dataset_hash_mismatch'):
        verify_dataset('onet', 't1')


@pytest.mark.parametrize('url', ['http://data.example.invalid/a.csv', 'https://elsewhere.example.invalid/a.csv',
                                 'https://user:pass@data.example.invalid/a.csv'])
def test_fetch_refuses_non_https_and_foreign_hosts(url):
    with pytest.raises(DiscoveryError, match='dataset_url_refused'):
        fetch_dataset(spec(url=url), opener=lambda u: b'x', trust_on_first_use=True)


def test_status_never_touches_the_network_and_reports_missing(monkeypatch):
    monkeypatch.setattr(datasets, 'PINNED', {'onet': spec()})
    assert datasets.status()['onet']['state'] == 'missing'


@pytest.mark.parametrize('name', ['../escape', '/tmp/escape', 'manifest.json', 'nested/file.csv'])
def test_fetch_refuses_unsafe_file_names(name):
    unsafe = spec().model_copy(update={'files': (FileSpec(name=name, url='https://data.example.invalid/a.csv', sha256=None, bytes=None),)})
    with pytest.raises(DiscoveryError, match='dataset_path_refused'):
        fetch_dataset(unsafe, opener=lambda u: b'x', trust_on_first_use=True)


def test_manifest_refuses_path_traversal_and_wrong_identity():
    m = fetch_dataset(spec(), opener=lambda url: b'x', trust_on_first_use=True)
    p = dataset_dir('onet', 't1') / 'manifest.json'
    for update in ({'sha256': {'../outside': '0'*64}}, {'version': 'other'}, {'sha256': {}}):
        p.write_text(json.dumps({**m.model_dump(), **update}))
        with pytest.raises(DiscoveryError, match='dataset_manifest_invalid'):
            verify_dataset('onet', 't1')


def test_dataset_directory_rejects_traversal_and_symlinks(tmp_path):
    with pytest.raises(DiscoveryError, match='dataset_path_refused'):
        dataset_dir('onet', '../../outside')
    root = datasets.reference_root()
    root.mkdir(parents=True)
    outside = tmp_path / 'outside'; outside.mkdir()
    (root / 'onet').symlink_to(outside, target_is_directory=True)
    with pytest.raises(DiscoveryError, match='dataset_path_refused'):
        dataset_dir('onet', 't1')


def test_fetch_caps_bytes_and_normalises_download_failure(monkeypatch):
    monkeypatch.setattr(datasets, 'MAX_FILE_BYTES', 3)
    with pytest.raises(DiscoveryError, match='dataset_too_large'):
        fetch_dataset(spec(), opener=lambda u: b'abcd', trust_on_first_use=True)
    def fail(_): raise OSError('secret path')
    with pytest.raises(DiscoveryError, match='^dataset_download_failed$'):
        fetch_dataset(spec(), opener=fail, trust_on_first_use=True)


def test_pins_are_checked_even_after_manifest_is_rewritten(monkeypatch):
    payload = b'original'; pinned = spec(hashlib.sha256(payload).hexdigest())
    m = fetch_dataset(pinned, opener=lambda u: payload)
    monkeypatch.setattr(datasets, 'PINNED', {'onet': pinned})
    p = dataset_dir('onet', 't1')
    (p / 'a.csv').write_bytes(b'new')
    (p / 'manifest.json').write_text(m.model_copy(update={'sha256': {'a.csv': hashlib.sha256(b'new').hexdigest()}}).model_dump_json())
    with pytest.raises(DiscoveryError, match='dataset_hash_mismatch'):
        verify_dataset('onet', 't1')


def test_discovery_error_does_not_echo_arbitrary_input():
    assert str(DiscoveryError('raw_private_fact')) == 'discovery_failed'
