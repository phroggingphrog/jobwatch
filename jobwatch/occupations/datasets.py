"""Versioned, local public references. No downloads occur during ordinary reads."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import requests
from pydantic import Field

from jobwatch import users
from jobwatch.apply.paths import safe_write_bytes
from jobwatch.candidate.contracts import StrictFrozen
from . import DiscoveryError

MAX_FILE_BYTES = 300 * 1024 * 1024
_COMPONENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
_HASH = re.compile(r'^[a-f0-9]{64}$')


class FileSpec(StrictFrozen):
    name: str
    url: str
    sha256: str | None
    bytes: int | None


class DatasetSpec(StrictFrozen):
    dataset: Literal['onet', 'esco', 'osca']
    version: str
    source_url: str
    licence: str
    attribution: str
    files: tuple[FileSpec, ...]
    enabled: bool = True
    notes: str = ''
    columns: dict = Field(default_factory=dict)


class DatasetManifest(StrictFrozen):
    dataset: str
    version: str
    source_url: str
    licence: str
    retrieved_at: str
    sha256: dict[str, str]


# Official URLs and bytes inspected 2026-10-22. No file is acquired at import.
_ONET_BASE = 'https://www.onetcenter.org/dl_files/database/db_31_0_csv/'
_OSCA_BASE = ('https://www.abs.gov.au/statistics/classifications/'
              'osca-occupation-standard-classification-australia/2024-version-1-0/data-downloads/')
PINNED: dict[str, DatasetSpec] = {
    'onet': DatasetSpec(
        dataset='onet', version='31.0', source_url='https://www.onetcenter.org/database.html',
        licence='CC BY 4.0',
        attribution=('O*NET 31.0 Database, U.S. Department of Labor, Employment and Training Administration. '
                     'https://creativecommons.org/licenses/by/4.0/ . Jobwatch selects and combines occupation, '
                     'task and skill text; no endorsement is implied. O*NET is a trademark of USDOL/ETA.'),
        files=(
            FileSpec(name='occupation_data.csv', url=_ONET_BASE+'occupation_data.csv',
                     sha256='a09eae1d6609686e44e05b7290993a1c8b523d8ca224bc0eedc194c855c3ee02', bytes=268030),
            FileSpec(name='task_statements.csv', url=_ONET_BASE+'task_statements.csv',
                     sha256='4568e14d8db6f05551ad37e056e909b13ebae4a26bcb5ff915bb5f281d582c57', bytes=3461375),
            FileSpec(name='essential_skills.csv', url=_ONET_BASE+'essential_skills.csv',
                     sha256='68c4d31d8c55077238395dca40cc4e6d32e6a608b5474bb8264b1f98ae415bd7', bytes=2328135),
            FileSpec(name='transferable_skills.csv', url=_ONET_BASE+'transferable_skills.csv',
                     sha256='f17d0419e818a3bf2f55076510c76c4aef01cc8f5aee2670d2f44f6f44ac60f7', bytes=6081245),
            FileSpec(name='esco.xlsx', url='https://www.onetcenter.org/crosswalks/esco/ESCO_to_ONET-SOC.xlsx',
                     sha256='bf6c854f7ffc935eba67a296d6d7fa4d40b70fb26bcdb5ecb5621374bca6f35b', bytes=213061),
        ),
        notes=('Production release August 2026. Version 31.0 splits the former Skills table into '
               'Essential Skills and Transferable Skills. Crosswalk is a many-to-many search aid, '
               'resolved to ESCO URIs only when a verified ESCO package is also loaded.'),
    ),
    'esco': DatasetSpec(
        dataset='esco', version='1.2.1', source_url='https://esco.ec.europa.eu/en/use-esco/download',
        licence='unverified package licence; European Commission website reuse policy CC BY 4.0',
        attribution='European Commission, ESCO v1.2.1; package-specific notices must be reviewed before enabling.',
        files=(), enabled=False,
        notes=('Current v1.2.1 announcement dated 22 December 2025; footer says last update 10 December 2025. '
               'Official English CSV acquisition requires privacy-statement acceptance and an email download link. '
               'No stable direct CSV URLs, bytes, hashes or package-specific licence verified here. '
               'Do not fetch the HTML download page as a dataset. Owner must acquire occupations_en.csv, '
               'skills_en.csv and occupationSkillRelations_en.csv, review notices, then configure exact '
               'file URLs/hashes and enable. API software EUPL is not the classification licence.'),
    ),
    'osca': DatasetSpec(
        dataset='osca', version='2024-v1.0', source_url=_OSCA_BASE.rstrip('/'),
        licence='CC BY 4.0',
        attribution=('Based on Australian Bureau of Statistics data: OSCA 2024, Version 1.0. '
                     'https://creativecommons.org/licenses/by/4.0/ . Jobwatch selects and combines '
                     'titles and lead statements; no endorsement is implied.'),
        files=(
            FileSpec(name='category.xlsx', url=_OSCA_BASE+'OSCA%20Category%20Descriptions.xlsx',
                     sha256='4412b0a20a54ab7bab01063b83bec4ee0a29768204f84a36851d82b661238fe8', bytes=493401),
            FileSpec(name='correspondence.xlsx', url=_OSCA_BASE+'OSCA%20correspondence%20tables%20v2.xlsx',
                     sha256='a88be381b95a7d3c1340588c374e260bd27b9c9198b4d8a48b8c71016bb64ae9', bytes=641062),
        ),
        columns={
            'structure': {'file': 'category.xlsx', 'sheet': 2, 'code': 'A', 'title': 'B', 'description': 'D'},
            'correspondence': {'file': 'correspondence.xlsx', 'sheet': 6, 'anzsco': 'A', 'osca': 'C'},
        },
        notes=('Classification released 6 December 2024; downloaded category workbook contents label '
               '28 July 2025. Sheet 2 has Identifier/Principal Title/Lead Statement in A/B/D. '
               'Correspondence sheet 6 maps ANZSCO 2022 to OSCA; merged source codes carry forward. '
               'ABS marks partial targets with p in D; Jobwatch conservatively treats every link as broad. '
               'ABS website CC BY 4.0 excludes OSCA branding and artwork; those are not imported.'),
    ),
}


def reference_root() -> Path:
    return users.base_dir() / 'reference'


def _component(value: str, *, filename: bool = False) -> None:
    if not isinstance(value, str) or not _COMPONENT.fullmatch(value) or value in {'.', '..'} or (filename and value == 'manifest.json'):
        raise DiscoveryError('dataset_path_refused')


def _no_symlinks(path: Path) -> Path:
    # Include ancestors: the shared reference root itself must not redirect elsewhere.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise DiscoveryError('dataset_path_refused')
    return path


def dataset_dir(dataset: str, version: str) -> Path:
    _component(dataset); _component(version)
    return _no_symlinks(reference_root() / dataset / version)


def _file(directory: Path, name: str) -> Path:
    _component(name, filename=True)
    return _no_symlinks(directory / name)


def read_manifest(dataset: str, version: str) -> DatasetManifest | None:
    directory = dataset_dir(dataset, version)
    path = _no_symlinks(directory / 'manifest.json')
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError
        manifest = DatasetManifest.model_validate_json(path.read_bytes())
        if manifest.dataset != dataset or manifest.version != version or not manifest.sha256:
            raise ValueError
        for name, digest in manifest.sha256.items():
            _component(name, filename=True)
            if not _HASH.fullmatch(digest):
                raise ValueError
        return manifest
    except (ValueError, OSError):
        raise DiscoveryError('dataset_manifest_invalid') from None


def _digest(path: Path) -> str:
    if not path.is_file():
        raise DiscoveryError('dataset_missing')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DiscoveryError('dataset_too_large')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_dataset(dataset: str, version: str) -> DatasetManifest:
    directory = dataset_dir(dataset, version)
    manifest = read_manifest(dataset, version)
    if manifest is None:
        raise DiscoveryError('dataset_missing')
    spec = PINNED.get(dataset)
    if spec is not None and spec.version == version:
        if set(manifest.sha256) != {f.name for f in spec.files} or manifest.source_url != spec.source_url or manifest.licence != spec.licence:
            raise DiscoveryError('dataset_manifest_invalid')
        for f in spec.files:
            if f.sha256 and manifest.sha256.get(f.name) != f.sha256:
                raise DiscoveryError('dataset_hash_mismatch')
    for name, expected in manifest.sha256.items():
        path = _file(directory, name)
        if _digest(path) != expected:
            raise DiscoveryError('dataset_hash_mismatch')
    return manifest


def status() -> dict[str, dict]:
    result = {}
    for name, spec in PINNED.items():
        state = 'disabled'
        if spec.enabled:
            try:
                verify_dataset(name, spec.version)
                state = 'ready'
            except DiscoveryError as exc:
                state = 'missing' if exc.code == 'dataset_missing' else 'mismatch'
        result[name] = {'state': state, 'version': spec.version, 'licence': spec.licence}
    return result


def _allowed_url(url: str, hosts: set[str]) -> None:
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
            raise ValueError
    except ValueError:
        raise DiscoveryError('dataset_url_refused') from None


def _download(url: str, hosts: set[str]) -> bytes:
    # Refuse redirect targets before sending a request to them.
    from urllib.parse import urljoin
    for _ in range(6):
        _allowed_url(url, hosts)
        with requests.get(url, timeout=120, stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            response.raise_for_status()
            if int(response.headers.get('Content-Length', '0')) > MAX_FILE_BYTES:
                raise DiscoveryError('dataset_too_large')
            chunks = []; size = 0
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise DiscoveryError('dataset_too_large')
                chunks.append(chunk)
            return b''.join(chunks)
    raise DiscoveryError('dataset_url_refused')


def fetch_dataset(spec: DatasetSpec, *, opener=None, trust_on_first_use: bool = False) -> DatasetManifest:
    directory = dataset_dir(spec.dataset, spec.version)
    source_host = urlsplit(spec.source_url).hostname
    if not source_host:
        raise DiscoveryError('dataset_url_refused')
    # A file cannot grant itself a new host: additional hosts must have an explicit,
    # independently configured official source (none of the current specs need one).
    hosts = {source_host}
    names = set()
    if not spec.files:
        raise DiscoveryError('dataset_unpinned')
    for f in spec.files:
        _file(directory, f.name)
        if f.name in names:
            raise DiscoveryError('dataset_manifest_invalid')
        names.add(f.name)
        _allowed_url(f.url, hosts)
        if f.sha256 is None and not trust_on_first_use:
            raise DiscoveryError('dataset_unpinned')
        if f.sha256 is not None and not _HASH.fullmatch(f.sha256):
            raise DiscoveryError('dataset_manifest_invalid')
        if f.bytes is not None and f.bytes > MAX_FILE_BYTES:
            raise DiscoveryError('dataset_too_large')
    hashes = {}; written = []
    try:
        # An interrupted replacement is never represented by an old ready manifest.
        manifest_path = _no_symlinks(directory / 'manifest.json')
        manifest_path.unlink(missing_ok=True)
        for f in spec.files:
            try:
                payload = opener(f.url) if opener is not None else _download(f.url, hosts)
            except DiscoveryError:
                raise
            except Exception:
                raise DiscoveryError('dataset_download_failed') from None
            if not isinstance(payload, bytes):
                raise DiscoveryError('dataset_download_failed')
            if len(payload) > MAX_FILE_BYTES:
                raise DiscoveryError('dataset_too_large')
            digest = hashlib.sha256(payload).hexdigest()
            if f.sha256 and digest != f.sha256:
                _file(directory, f.name).unlink(missing_ok=True)
                raise DiscoveryError('dataset_hash_mismatch')
            if f.bytes is not None and len(payload) != f.bytes:
                raise DiscoveryError('dataset_hash_mismatch')
            path = _file(directory, f.name)
            safe_write_bytes(path, payload); written.append(path)
            hashes[f.name] = digest
        manifest = DatasetManifest(dataset=spec.dataset, version=spec.version, source_url=spec.source_url,
                                   licence=spec.licence, retrieved_at=datetime.now(timezone.utc).isoformat(), sha256=hashes)
        safe_write_bytes(manifest_path, manifest.model_dump_json().encode())
        return manifest
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    for name in ('verify', 'fetch'):
        cmd = commands.add_parser(name); cmd.add_argument('dataset', choices=tuple(PINNED))
        if name == 'fetch':
            cmd.add_argument('--trust-on-first-use', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'status':
        print(json.dumps(status(), sort_keys=True)); return 0
    spec = PINNED[args.dataset]
    try:
        manifest = (verify_dataset(spec.dataset, spec.version) if args.command == 'verify' else
                    fetch_dataset(spec, trust_on_first_use=args.trust_on_first_use))
    except DiscoveryError as exc:
        print(exc.code); return 1
    for name, digest in sorted(manifest.sha256.items()):
        print(f'{name} sha256={digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
