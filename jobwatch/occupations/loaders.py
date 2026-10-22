"""Deterministic public occupation texts; similarities are never qualification proof."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from jobwatch.candidate import reference
from jobwatch.candidate.contracts import StrictFrozen
from . import DiscoveryError
from . import datasets


class OccupationRecord(StrictFrozen):
    scheme: Literal['anzsco2022', 'onet', 'esco', 'osca']
    code: str
    title: str
    text: str = Field(max_length=1800)
    family: str | None = None
    dataset_version: str

    @property
    def id(self) -> str:
        return f'{self.scheme}:{self.code}'


class Correspondence(StrictFrozen):
    a: str
    b: str
    kind: Literal['exact', 'broad']


class LoadedReference(StrictFrozen):
    records: tuple[OccupationRecord, ...]
    correspondences: tuple[Correspondence, ...]
    versions: dict[str, str]
    skipped: dict[str, str]
    records_hash: str


def record_text(title: str, description: str = '', tasks=(), skills=(), *, limit: int = 1800) -> str:
    parts = [title.rstrip('. ') + '.']
    if description:
        parts.append(description)
    if tasks:
        parts.append('Tasks: ' + '; '.join(tasks).rstrip('. ') + '.')
    if skills:
        parts.append('Skills: ' + ', '.join(skills).rstrip('. ') + '.')
    text = ' '.join(' '.join(parts).split())
    limit = min(1800, max(0, limit))
    if len(text) > limit:
        cut = text.rfind(' ', 0, limit + 1)
        text = text[:cut if cut > 0 else limit]
    return text.rstrip()


def read_sheet(path: Path, number: int) -> Iterator[dict[str, str]]:
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    try:
        with zipfile.ZipFile(path) as archive:
            # Bound expanded XML, too: the hash verifies provenance, not ZIP safety.
            for info in archive.infolist():
                if info.file_size > datasets.MAX_FILE_BYTES:
                    raise DiscoveryError('dataset_too_large')
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
                strings = [''.join(t.itertext()) for t in root.findall('m:si', ns)]
            root = ET.fromstring(archive.read(f'xl/worksheets/sheet{number}.xml'))
            for row in root.findall('.//m:row', ns):
                values = {}
                for cell in row.findall('m:c', ns):
                    column = re.sub(r'\d', '', cell.attrib.get('r', ''))
                    node = cell.find('m:v', ns)
                    value = node.text or '' if node is not None else ''
                    if cell.attrib.get('t') == 's' and value:
                        value = strings[int(value)]
                    elif cell.attrib.get('t') == 'inlineStr':
                        inline = cell.find('m:is', ns)
                        value = ''.join(inline.itertext()) if inline is not None else ''
                    values[column] = value
                yield values
    except DiscoveryError:
        raise
    except (OSError, KeyError, ValueError, IndexError, ET.ParseError, zipfile.BadZipFile):
        raise DiscoveryError('dataset_schema_changed') from None


def _bundled_path() -> Path:
    from jobwatch import candidate
    return Path(candidate.__file__).with_name('data') / 'occupation-reference.json'


def load_bundled(path=None) -> tuple[list[OccupationRecord], list[Correspondence], str]:
    try:
        bundle = reference.load_reference(Path(path) if path is not None else _bundled_path())
        if bundle is None:
            raise DiscoveryError('reference_invalid')
        titles = {d.id: d.title for d in bundle.dwas}
        records = []
        for o in bundle.occupations:
            top = sorted(o.dwa_weights, key=lambda key: (-o.dwa_weights[key], key))[:12]
            records.append(OccupationRecord(scheme='anzsco2022', code=o.code, title=o.title,
                text=record_text(o.title, tasks=[titles[key] for key in top]), family=o.family, dataset_version=bundle.version))
        links = [Correspondence(a=f'onet:{c.soc}', b=f'anzsco2022:{code}', kind='broad')
                 for c in bundle.crosswalks for code in c.anzsco_codes]
        return records, links, bundle.version
    except DiscoveryError:
        raise
    except (ValueError, OSError):
        raise DiscoveryError('reference_invalid') from None


def _rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if not required.issubset(reader.fieldnames or ()):
                raise DiscoveryError('dataset_schema_changed')
            rows = list(reader)
            if any(any(row.get(k) is None for k in required) for row in rows):
                raise DiscoveryError('dataset_schema_changed')
            return rows
    except (OSError, UnicodeError, csv.Error):
        raise DiscoveryError('dataset_schema_changed') from None


def load_onet(directory: Path, version: str):
    directory = Path(directory)
    occupations = _rows(directory / 'occupation_data.csv', {'O*NET-SOC Code', 'Title', 'Description'})
    if (directory / 'esco.xlsx').exists():
        crosswalk = list(read_sheet(directory / 'esco.xlsx', 1))
        if not any(row.get('A') == 'ESCO/ISCO Code' and row.get('C') == 'O*NET-SOC 2019 Code' for row in crosswalk):
            raise DiscoveryError('dataset_schema_changed')
    tasks = defaultdict(list); skills = defaultdict(list)
    try:
        for row in _rows(directory / 'task_statements.csv', {'O*NET-SOC Code', 'Task ID', 'Task Type', 'Task'}):
            tasks[row['O*NET-SOC Code']].append((row['Task Type'] != 'Core', int(row['Task ID']), row['Task']))
        # O*NET 31.0 split Skills into Essential and Transferable Skills. Support the
        # historical skills.csv table for explicitly pinned older datasets as well.
        skill_files = [directory / n for n in ('essential_skills.csv', 'transferable_skills.csv') if (directory / n).exists()]
        if not skill_files:
            skill_files = [directory / 'skills.csv']
        for path in skill_files:
            for row in _rows(path, {'O*NET-SOC Code', 'Element Name', 'Scale ID', 'Data Value'}):
                if row['Scale ID'] != 'IM' or row.get('Recommend Suppress') == 'Y' or not row['Data Value']:
                    continue
                value = float(row['Data Value'])
                if not math.isfinite(value):
                    raise ValueError
                skills[row['O*NET-SOC Code']].append((-value, row['Element Name']))
        records = [OccupationRecord(scheme='onet', code=r['O*NET-SOC Code'], title=r['Title'], dataset_version=version,
            text=record_text(r['Title'], r['Description'], [t[2] for t in sorted(tasks[r['O*NET-SOC Code']])[:12]],
                             [s[1] for s in sorted(skills[r['O*NET-SOC Code']])[:10]])) for r in occupations]
    except (ValueError, TypeError):
        raise DiscoveryError('dataset_schema_changed') from None
    return records, []


def load_esco(directory: Path, version: str):
    directory = Path(directory)
    occupations = _rows(directory / 'occupations_en.csv', {'conceptUri', 'preferredLabel', 'description', 'iscoGroup', 'code'})
    skills = {r['conceptUri']: r['preferredLabel'] for r in _rows(directory / 'skills_en.csv', {'conceptUri', 'preferredLabel'})}
    essential = defaultdict(set)
    for row in _rows(directory / 'occupationSkillRelations_en.csv', {'occupationUri', 'skillUri', 'relationType'}):
        if row['relationType'] == 'essential':
            if row['skillUri'] not in skills:
                raise DiscoveryError('dataset_schema_changed')
            essential[row['occupationUri']].add(skills[row['skillUri']])
    records = [OccupationRecord(scheme='esco', code=r['conceptUri'], title=r['preferredLabel'], dataset_version=version,
        text=record_text(r['preferredLabel'], r['description'], skills=sorted(essential[r['conceptUri']])[:15])) for r in occupations]
    # ISCO groups are not loaded occupation records; no dangling ISCO links.
    return records, []


def _workbook(directory: Path, mapping: dict, *, correspondence: bool) -> Path:
    if 'file' in mapping:
        return datasets._file(directory, mapping['file'])
    files = sorted(directory.glob('*.xlsx'))
    matches = [p for p in files if ('correspond' in p.name.casefold()) == correspondence]
    if len(matches) != 1:
        raise DiscoveryError('dataset_schema_changed')
    return matches[0]


def load_osca(directory: Path, version: str, columns: dict):
    directory = Path(directory)
    try:
        structure = columns['structure']
        code, title, description = (structure[k] for k in ('code', 'title', 'description'))
        rows = list(read_sheet(_workbook(directory, structure, correspondence=False), structure['sheet']))
        if not any(all(row.get(c) for c in (code, title, description)) for row in rows):
            raise DiscoveryError('dataset_schema_changed')
        records = [OccupationRecord(scheme='osca', code=row[code], title=row[title], dataset_version=version,
            text=record_text(row[title], row.get(description, ''))) for row in rows
            if re.fullmatch(r'\d{6}', row.get(code, '')) and row.get(title)]
        if not records:
            raise DiscoveryError('dataset_schema_changed')
        links = []
        if 'correspondence' in columns:
            mapping = columns['correspondence']; previous = ''
            correspondence_rows = list(read_sheet(_workbook(directory, mapping, correspondence=True), mapping['sheet']))
            if not any(row.get(mapping['anzsco']) and row.get(mapping['osca']) for row in correspondence_rows):
                raise DiscoveryError('dataset_schema_changed')
            for row in correspondence_rows:
                source = row.get(mapping['anzsco'], '')
                if re.fullmatch(r'\d{6}', source):
                    previous = source
                target = row.get(mapping['osca'], '')
                if previous and re.fullmatch(r'\d{6}', target):
                    links.append(Correspondence(a=f'anzsco2022:{previous}', b=f'osca:{target}', kind='broad'))
        return records, links
    except DiscoveryError:
        raise
    except (KeyError, TypeError, ValueError):
        raise DiscoveryError('dataset_schema_changed') from None


@lru_cache(maxsize=8)
def _load_cached(bundled_path: str, bundled_hash: str, ready: tuple, skipped_items: tuple) -> LoadedReference:
    records, links, version = load_bundled(bundled_path)
    versions = {'anzsco2022': version}; skipped = dict(skipped_items)
    for name, directory, spec_json, receipt_json in ready:
        spec = datasets.DatasetSpec.model_validate_json(spec_json)
        try:
            if name == 'onet':
                extra, correspondences = load_onet(Path(directory), spec.version)
            elif name == 'esco':
                extra, correspondences = load_esco(Path(directory), spec.version)
            else:
                extra, correspondences = load_osca(Path(directory), spec.version, spec.columns)
            records.extend(extra); links.extend(correspondences); versions[name] = spec.version
        except DiscoveryError as exc:
            skipped[name] = exc.code
    loaded_dirs = {name: Path(directory) for name, directory, _, _ in ready if name in versions}
    if 'onet' in loaded_dirs and 'esco' in loaded_dirs and (loaded_dirs['onet'] / 'esco.xlsx').exists():
        # The official crosswalk has numeric ESCO/ISCO codes in A, titles in B,
        # and O*NET-SOC in C. Resolve codes through ESCO's own code-to-URI table.
        esco_rows = _rows(loaded_dirs['esco'] / 'occupations_en.csv', {'conceptUri', 'code'})
        esco_uris = {row['code']: row['conceptUri'] for row in esco_rows}
        for row in read_sheet(loaded_dirs['onet'] / 'esco.xlsx', 1):
            uri, soc = esco_uris.get(row.get('A', '')), row.get('C', '')
            if uri and re.fullmatch(r'\d{2}-\d{4}\.\d{2}', soc):
                links.append(Correspondence(a=f'esco:{uri}', b=f'onet:{soc}', kind='broad'))
    records.sort(key=lambda r: (r.scheme, r.code))
    ids = {r.id for r in records}
    links = sorted({(c.a, c.b, c.kind) for c in links if c.a in ids and c.b in ids})
    triples = [(r.scheme, r.code, r.text) for r in records]
    digest = hashlib.sha256(json.dumps(triples, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return LoadedReference(records=tuple(records), correspondences=tuple(Correspondence(a=a,b=b,kind=k) for a,b,k in links),
                           versions=versions, skipped=skipped, records_hash=digest)


def load_reference_records(*, only: tuple[str, ...] | None = None) -> LoadedReference:
    path = _bundled_path()
    try:
        bundled_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise DiscoveryError('reference_invalid') from None
    ready = []; skipped = {}
    for name, spec in sorted(datasets.PINNED.items()):
        if only is not None and name not in only:
            continue
        if not spec.enabled:
            skipped[name] = 'dataset_disabled'; continue
        try:
            # Always verify hashes before looking up parsed data in the LRU cache.
            receipt = datasets.verify_dataset(name, spec.version)
            ready.append((name, str(datasets.dataset_dir(name, spec.version)), spec.model_dump_json(), receipt.model_dump_json()))
        except DiscoveryError as exc:
            skipped[name] = exc.code
    return _load_cached(str(path), bundled_hash, tuple(ready), tuple(sorted(skipped.items())))
