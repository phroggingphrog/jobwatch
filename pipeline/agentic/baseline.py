"""Frozen baseline: models, gate version, case grouping and tags, freezing and loading.

A baseline freezes the live gate's inputs and decisions for a set of real postings so a later change can
be compared against it. The first sections hold the data models, the gate-version digest, the grouping that
keeps related postings together and the review tags. The last section freezes a person's stored pipeline
records into a hash-verified folder and loads it back. Freezing reads the database and the live profile and
calls no model. The final section holds the owner's labels, the only part of a baseline that changes after it
is frozen; only the owner's own command writes them.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator

from jobwatch import users
from jobwatch.apply import paths as apaths
from jobwatch.apply.paths import ensure_dir, pin_profile_dir, safe_write_bytes
from jobwatch.candidate import intake
from jobwatch.candidate._private_io import read_profile_source, read_regular_file
from jobwatch.candidate.contracts import CandidateError, digest
from jobwatch.candidate.evidence import _ALLOWED, _MAX_SOURCE_BYTES, bundle_from_contents, snapshot_evidence
from jobwatch.candidate.policy import default_policy
from jobwatch.dedupe import _COMPANY_NOISE, _norm

from .contracts import AgenticError, AgenticEvaluation, RunKey, StrictFrozen, parse_budget_checkpoint_json
from .location import km_from_home
from .persistence import _read_artifact
from .runtime import validate_model_payload

# --------------------------------------------------------------------------- models

TAGS = ('previously_rejected', 'transferable_skills', 'unknown_facts', 'misleading_title', 'stretch',
        'explicit_exclusion')


class FrozenCase(StrictFrozen):
    model_config = ConfigDict(protected_namespaces=())  # `model_insights` is a contract field name

    case_id: str
    posting_id: int
    group_id: str
    tags: tuple[str, ...]
    snapshot: dict
    structural_inputs: dict
    evaluation: dict
    candidate: dict | None
    model_insights: dict | None
    decision: dict
    commute_km: float | None
    usage: dict
    run_key: str
    group_keys: tuple[str, ...] = ()
    stored: dict = {}
    blob_refs: dict[str, str] = {}


class Baseline(StrictFrozen):
    baseline_id: str
    created_at: str
    git_commit: str
    gate_version: str
    implementation_version: str
    matching_version: str
    profile_version: int
    profile_files_sha256: dict[str, str]
    case_ids: tuple[str, ...]
    gate_dependencies: dict[str, str]
    person: str
    policy: dict
    runtime_config_sha256: str
    evidence_bundle_hash: str | None
    approved_sha256: str
    decision_policy_sha256: str | None = None  # None when the decision-policy path was not active
    case_sha256: dict[str, str]
    content_sha256: str
    summary: dict


# --------------------------------------------------------------------------- gate version

_GATE_MODULES = ('pipeline.agentic.gate', 'pipeline.agentic.location', 'jobwatch.candidate.person',
                 'jobwatch.reader', 'jobwatch.candidate.contracts', 'jobwatch.candidate.policy')
_GATE_DATA = ('pipeline.agentic/data/vic-geo.json', 'pipeline.agentic/data/metro-localities.json')


def _source_path(key: str) -> Path:
    """Where one gate source lives. Every gate source lookup goes through this name, so a test can swap it."""
    if key in _GATE_DATA:
        package, _, relative = key.partition('/')
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            raise FileNotFoundError(key)
        return Path(next(iter(spec.submodule_search_locations))) / relative
    spec = importlib.util.find_spec(key)
    if spec is None or not spec.origin:
        raise FileNotFoundError(key)
    return Path(spec.origin)


def gate_sources() -> dict[str, str]:
    """sha256 of the bytes of every file the live gate depends on (the policy module only when it exists)."""
    result: dict[str, str] = {}
    for key in (*_GATE_MODULES, *_GATE_DATA):
        try:
            path = _source_path(key)
        except FileNotFoundError:
            if key == 'jobwatch.candidate.policy':
                continue
            raise
        if key == 'jobwatch.candidate.policy' and not path.is_file():
            continue
        result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def current_gate_version() -> str:
    text = json.dumps(gate_sources(), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


GATE_VERSION = current_gate_version()
# GATE_VERSION when the frozen-baseline release was made; a baseline whose gate_version differs was frozen
# after the gate was revised.
PRE_REVISION_GATE_VERSION = '9b11d0241b99131f91897ed4403829b6ab03bebcdaf5d5d64ce7289a73457a06'

# --------------------------------------------------------------------------- grouping


def _field(posting: Mapping, name: str) -> str:
    try:
        value = posting[name]
    except (KeyError, IndexError):
        return ''
    return value if isinstance(value, str) else ''


def group_keys_for(posting: Mapping, ad_hash: str) -> tuple[str, ...]:
    """Keys that tie a posting to related ones: the same advert text, the same company and title, the same employer."""
    keys = [f'content:{ad_hash}']
    parts = _field(posting, 'dedupe_key').split('|')
    if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
        keys.append(f"dedupe:{_field(posting, 'dedupe_key')}")
    employer = _norm(_field(posting, 'company'), _COMPANY_NOISE)
    if employer:
        keys.append(f'employer:{employer}')
    return tuple(keys)


def group_ids(keys: Mapping[str, Iterable[str]]) -> dict[str, str]:
    """Union cases that share any key (transitively). The id depends only on the members' keys, not on order."""
    parent = {case: case for case in keys}

    def find(case: str) -> str:
        while parent[case] != case:
            parent[case] = parent[parent[case]]
            case = parent[case]
        return case

    owner: dict[str, str] = {}
    own_keys = {case: set(values) for case, values in keys.items()}
    for case in sorted(own_keys):
        for key in sorted(own_keys[case]):
            if key in owner:
                parent[find(case)] = find(owner[key])
            else:
                owner[key] = case
    members: dict[str, set[str]] = {}
    for case, values in own_keys.items():
        members.setdefault(find(case), set()).update(values or {f'case:{case}'})
    ids = {root: 'group:' + hashlib.sha256('\n'.join(sorted(values)).encode('utf-8')).hexdigest()[:32]
           for root, values in members.items()}
    return {case: ids[find(case)] for case in keys}


# --------------------------------------------------------------------------- tags

_JUNIOR_TITLE = re.compile(r'\b(?:entry[ -]level|junior|graduate|intern(?:ship)?|trainee|cadet(?:ship)?)\b', re.I)
_SENIOR_TITLE = re.compile(r'\b(?:senior|lead|principal|head of|director)\b', re.I)
_LEGACY_STATUS = {'strong': 'demonstrated', 'partial': 'partial', 'missing': 'unknown',
                  'not_applicable': 'not_applicable'}


def _statuses(evaluation: AgenticEvaluation) -> list[tuple[str, str, bool]]:
    return [(m.requirement_id, m.judgment.status if m.judgment else _LEGACY_STATUS[m.match], bool(m.evidence))
            for m in evaluation.matches]


def tag_case(case: FrozenCase) -> tuple[str, ...]:
    evaluation = validate_model_payload(AgenticEvaluation, case.evaluation)
    decision, stored = case.decision, case.stored
    title = (case.snapshot.get('posting') or {}).get('title') or ''
    facts = evaluation.facts
    statuses = _statuses(evaluation)
    found = {status for _, status, _ in statuses}
    importance = {r.id: r.importance for r in evaluation.requirements.requirements}
    uncertainties = (evaluation.matching_diagnostics or {}).get('ad_uncertainties')
    years = facts.min_years
    tags = {
        'previously_rejected': (decision.get('route') == 'archive' or stored.get('run_status') == 'archived'
                                or stored.get('application_status') == 'skipped'),
        'transferable_skills': any(status == 'partial' and cited for _, status, cited in statuses),
        'unknown_facts': 'unknown' in found or bool(uncertainties) or evaluation.location_fit == 'unknown',
        'misleading_title': bool(
            (_JUNIOR_TITLE.search(title) and (facts.seniority in ('mid', 'senior') or (years or 0) >= 2))
            or (_SENIOR_TITLE.search(title) and facts.seniority in ('entry', 'junior')
                and (years is None or years < 2))),
        'stretch': ('contradicted' not in found and 'demonstrated' in found and any(
            status in ('partial', 'unknown') and importance.get(rid) in ('critical', 'high')
            for rid, status, _ in statuses)),
        'explicit_exclusion': decision.get('reason') == 'policy_excluded',
    }
    return tuple(tag for tag in TAGS if tags[tag])


# --------------------------------------------------------------------------- freeze, load and replay-pinning
#
# Layout of one baseline, under the signed-in person's own folder:
#   baselines/<id>/baseline.json   the Baseline record, written last
#                  approved.json   the approved profile version the baseline was frozen under
#                  decision_policy.json   only when the decision-policy path was active
#                  profile/        a copy of the profile files the gate and evidence bundle read
#                  cases/<case_id>.json   one FrozenCase, large fields moved out into blobs/
#                  blobs/<sha256>.json    large fields shared by many cases, stored once
# Freezing only reads the database (a read-only connection is enough) and writes only into a staging folder
# that is renamed into place when everything is written, so a failed freeze leaves nothing visible.

PROFILE_FILES = tuple(dict.fromkeys(_ALLOWED + ('interests_and_criteria.yaml',)))
_BASELINE_ID = re.compile(r'bl-\d{8}T\d{6}Z-[0-9a-f]{8}')
_CASE_ID = re.compile(r'c-\d+-[0-9a-f]{8}')
_HEX64 = re.compile(r'[0-9a-f]{64}')
_ARTIFACT_KINDS = ('snapshot', 'structural_inputs', 'candidate', 'evaluation', 'model_insights')
_ROUTES = ('draft', 'archive', 'hold')


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def _git_commit(root: Path | None = None) -> str:
    """The checkout's HEAD commit, or 'unknown' when there is no checkout or git cannot answer."""
    folder = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_CEILING_DIRECTORIES'] = str(folder.parent)   # a folder outside a checkout never finds one above it
    try:
        done = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=folder, env=env, capture_output=True, text=True,
                              timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return 'unknown'
    head = done.stdout.strip()
    return head if done.returncode == 0 and re.fullmatch(r'[0-9a-f]{40,64}', head) else 'unknown'


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _corrupt() -> AgenticError:
    return AgenticError('baseline_corrupt')


# ----- reading a stored baseline

def _baselines_root() -> Path:
    return users.user_dir() / 'baselines'


def _baseline_dir(baseline_id: str) -> Path:
    """The folder of one stored baseline. The id is checked against the fixed pattern before it touches a path."""
    if type(baseline_id) is not str or not _BASELINE_ID.fullmatch(baseline_id):
        raise AgenticError('invalid_baseline_id')
    path = _baselines_root() / baseline_id
    if not (path / 'baseline.json').is_file():
        raise AgenticError('baseline_not_found')
    if path.is_symlink():
        raise _corrupt()
    return path


def _read_verified(path: Path, sha256: str) -> bytes:
    """The bytes of one stored file, only when they still hash to what the baseline recorded."""
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError
        raw = path.read_bytes()
    except (OSError, ValueError):
        raise _corrupt() from None
    if _sha(raw) != sha256:
        raise _corrupt()
    return raw


def _read_record(folder: Path, baseline_id: str) -> Baseline:
    try:
        record = Baseline.model_validate(json.loads((folder / 'baseline.json').read_bytes()))
    except (OSError, ValueError):
        raise _corrupt() from None
    if record.baseline_id != baseline_id or set(record.case_ids) != set(record.case_sha256):
        raise _corrupt()
    expected = digest({'cases': record.case_sha256, 'profile': record.profile_files_sha256,
                       'approved': record.approved_sha256})
    if record.content_sha256 != expected:
        raise _corrupt()
    return record


def _read_blob(folder: Path, sha256: str, cache: dict[str, Any]) -> Any:
    if not _HEX64.fullmatch(sha256):
        raise _corrupt()
    if sha256 not in cache:
        try:
            cache[sha256] = json.loads(_read_verified(folder / 'blobs' / f'{sha256}.json', sha256))
        except ValueError:
            raise _corrupt() from None
    return cache[sha256]


def _inflate(folder: Path, raw: bytes, cache: dict[str, Any]) -> FrozenCase:
    """One case with its large fields put back. Each blob is read once per call, so cases share the object."""
    try:
        data = json.loads(raw)
        for name, sha256 in dict(data['blob_refs']).items():
            value = _read_blob(folder, sha256, cache)
            if name == 'candidate':
                data['candidate'] = value
            elif name == 'structural_inputs.reference_utf8':
                data['structural_inputs'] = {**data['structural_inputs'], 'reference_utf8': value}
            elif name == 'snapshot.contents':
                data['snapshot'] = {**data['snapshot'], 'contents': value}
            else:
                raise _corrupt()
        return FrozenCase.model_validate(data)
    except AgenticError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise _corrupt() from None


def load_baseline(baseline_id: str) -> tuple[Baseline, list[FrozenCase]]:
    """A stored baseline and its cases (sorted by posting id). Anything that no longer matches its hash is refused."""
    folder = _baseline_dir(baseline_id)
    record = _read_record(folder, baseline_id)
    cache: dict[str, Any] = {}
    cases = []
    for case_id in record.case_ids:
        if not _CASE_ID.fullmatch(case_id):
            raise _corrupt()
        raw = _read_verified(folder / 'cases' / f'{case_id}.json', record.case_sha256[case_id])
        case = _inflate(folder, raw, cache)
        if case.case_id != case_id:
            raise _corrupt()
        cases.append(case)
    return record, sorted(cases, key=lambda c: c.posting_id)


def list_baselines() -> list[Baseline]:
    """The signed-in person's baselines, oldest first. Folders without baseline.json and dot-folders are ignored."""
    root = _baselines_root()
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith('.') or not _BASELINE_ID.fullmatch(entry.name) \
                or not (entry / 'baseline.json').is_file():
            continue
        found.append(_read_record(_baseline_dir(entry.name), entry.name))
    return sorted(found, key=lambda b: (b.created_at, b.baseline_id))


def _verify_profile(folder: Path, record: Baseline) -> None:
    try:
        present = {entry.name for entry in folder.iterdir()}
    except OSError:
        raise _corrupt() from None
    if present != set(record.profile_files_sha256):
        raise _corrupt()
    for name, sha256 in record.profile_files_sha256.items():
        _read_verified(folder / name, sha256)


@contextlib.contextmanager
def pinned_profile(baseline_id: str) -> Iterator[Path]:
    """Make the baseline's own profile copy the profile folder for the block, after checking it is unchanged."""
    folder = _baseline_dir(baseline_id)
    record = _read_record(folder, baseline_id)
    profile = Path(os.path.abspath(folder / 'profile'))
    _verify_profile(profile, record)
    with pin_profile_dir(profile) as pinned:
        yield pinned


def frozen_approved(baseline_id: str) -> dict:
    """The approved profile version the baseline was frozen under, checked against its recorded hash."""
    folder = _baseline_dir(baseline_id)
    record = _read_record(folder, baseline_id)
    try:
        value = json.loads(_read_verified(folder / 'approved.json', record.approved_sha256))
    except ValueError:
        raise _corrupt() from None
    if type(value) is not dict:
        raise _corrupt()
    return value


def frozen_decision_policy(baseline_id: str) -> dict | None:
    """The stored decision policy, or None when the policy path was not active at freeze time."""
    folder = _baseline_dir(baseline_id)
    record = _read_record(folder, baseline_id)
    if record.decision_policy_sha256 is None:
        return None
    try:
        value = json.loads(_read_verified(folder / 'decision_policy.json', record.decision_policy_sha256))
    except ValueError:
        raise _corrupt() from None
    if type(value) is not dict:
        raise _corrupt()
    return value


# ----- the gate decision, rebuilt from stored inputs

def _active_decision_policy(config, approved: dict) -> object | None:
    """The person's decision policy when the policy path is active. Neither `policy_for` nor
    `decision_policy_mode` exists before the decision-policy work merges, so this is None until then."""
    from jobwatch.candidate import policy as policy_module
    from . import service
    policy_for = getattr(policy_module, 'policy_for', None)
    mode = getattr(service, 'decision_policy_mode', None)
    if policy_for is None or mode is None or mode(config) != 'profile':
        return None
    return policy_for(users.current(), approved=approved)


def decide_frozen(snapshot: dict, evaluation: dict, *, commute_km: float | None,
                  decision_policy: object | None = None) -> dict:
    """Run the live gate on stored inputs. Reproducible only inside `pinned_profile`: the gate reads the profile."""
    try:
        bundle = bundle_from_contents({name: text.encode('utf-8') for name, text in snapshot['contents'].items()})
    except (CandidateError, KeyError, AttributeError, TypeError, UnicodeError):
        return {'error': 'evidence_snapshot_invalid'}
    try:
        checked = validate_model_payload(AgenticEvaluation, evaluation)
        run_key = RunKey.model_validate(snapshot['run_key'])
        ad_text = snapshot['full_ad']
        complete = snapshot['text_kind'] == 'full'
        posting = snapshot['posting']
        title, location = posting['title'], posting.get('location')
        company = posting['company'] if decision_policy is not None else posting.get('company')
    except Exception:  # noqa: BLE001 - any malformed stored input is the same fixed answer
        return {'error': 'invalid_gate_input'}
    from . import service
    try:
        decision = service.gate_current(
            checked, posting={'title': title, 'company': company, 'location': location}, ad_text=ad_text,
            decision_policy=decision_policy, policy=default_policy(), captured_complete=complete,
            expected_run_key=run_key, evidence_bundle=bundle,
            commute_km=None if commute_km is None else round(commute_km))
    except AgenticError as exc:
        return {'error': 'invalid_gate_input' if exc.code == 'invalid_gate_input' else 'decision_unavailable'}
    except Exception:  # noqa: BLE001 - a stored case the gate cannot judge is reported, never raised
        return {'error': 'decision_unavailable'}
    return decision.model_dump(mode='json')


# ----- freezing

def _check_arguments(limit: object, posting_ids: object) -> None:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise AgenticError('invalid_limit')
    if posting_ids is not None and (type(posting_ids) is not list or len(posting_ids) > 1000
                                    or any(type(i) is not int or i < 1 for i in posting_ids)):
        raise AgenticError('invalid_limit')


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _first(conn: sqlite3.Connection, sql: str, params: tuple) -> tuple | None:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:   # a table this database never created
        return None
    return None if row is None else tuple(row)


def _select_runs(conn: sqlite3.Connection, posting_ids: list[int] | None, limit: int) -> tuple[list[tuple], dict]:
    """Per posting, its newest run that has a stored snapshot and evaluation. Newest `limit` runs, by posting id."""
    skipped: dict[str, int] = {}
    if not _has_table(conn, 'agentic_runs'):
        return [], skipped
    wanted = None if posting_ids is None else set(posting_ids)
    complete = set()
    if _has_table(conn, 'agentic_artifacts'):
        complete = {row[0] for row in conn.execute(
            "SELECT run_key FROM agentic_artifacts WHERE kind IN ('snapshot','evaluation') "
            "GROUP BY run_key HAVING COUNT(DISTINCT kind)=2")}
    chosen: dict[int, tuple] = {}
    with_runs = set()
    for row in conn.execute('SELECT rowid,run_key,posting_id,generation,status,reason,checkpoint_json FROM agentic_runs '
                            'ORDER BY posting_id, generation DESC, rowid DESC'):
        row = tuple(row)
        if wanted is not None and row[2] not in wanted:
            continue
        with_runs.add(row[2])
        if row[2] not in chosen and row[1] in complete:
            chosen[row[2]] = row
    if len(with_runs) > len(chosen):
        skipped['no_evaluation'] = len(with_runs) - len(chosen)
    if wanted is not None and wanted - with_runs:
        skipped['no_run'] = len(wanted - with_runs)
    newest = sorted(chosen.values(), key=lambda r: r[0], reverse=True)[:limit]
    return sorted(newest, key=lambda r: r[2]), skipped


def _copy_profile(live: Path, staging: Path) -> dict[str, str]:
    """Copy the profile files that exist into the staging folder; the sha256 of each by its canonical name."""
    copied: dict[str, bytes] = {}
    for name in PROFILE_FILES:
        try:
            canonical, raw = read_profile_source(live, name, _MAX_SOURCE_BYTES)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, UnicodeError):
            raise AgenticError('profile_unreadable') from None
        if copied.get(canonical, raw) != raw:
            raise AgenticError('profile_unreadable')
        copied[canonical] = raw
    ensure_dir(staging)
    for name in sorted(copied):
        safe_write_bytes(staging / name, copied[name])
    return {name: _sha(copied[name]) for name in sorted(copied)}


def _load_artifact(artifacts: dict[str, tuple[str, str]], kind: str, shape: type) -> Any:
    """One stored artifact, read only when it still hashes to what the database recorded."""
    path, sha256 = artifacts[kind]
    raw = _read_artifact(path, sha256)
    try:
        value = json.loads(raw)
    except ValueError:
        raise AgenticError('artifact_invalid') from None
    if type(value) is not shape:
        raise AgenticError('artifact_invalid')
    return value


def _snapshot_ad_hash(snapshot: dict, run_key: str) -> str:
    """The advert hash the run was keyed on; anything blank or inconsistent makes the case unusable."""
    try:
        key = snapshot['run_key']
        ad_hash = key['ad_hash']
        posting = snapshot['posting']
        if (type(ad_hash) is not str or not _HEX64.fullmatch(ad_hash) or RunKey.model_validate(key).value != run_key
                or type(snapshot['full_ad']) is not str or type(snapshot['text_kind']) is not str
                or type(snapshot['contents']) is not dict
                or any(type(posting[f]) is not str for f in ('title', 'company', 'location'))):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise AgenticError('artifact_invalid') from None
    return ad_hash


def _stored(conn: sqlite3.Connection, run: tuple) -> dict:
    """What the live pipeline recorded about the run, the posting's stage and its application."""
    stage = _first(conn, 'SELECT stage,reason FROM pipeline_state WHERE posting_id=?', (run[2],))
    application = _first(conn, 'SELECT status FROM applications WHERE posting_id=?', (run[2],))
    return {'run_status': run[4], 'run_reason': run[5], 'generation': run[3],
            'stage': stage[0] if stage else None, 'stage_reason': stage[1] if stage else None,
            'application_status': application[0] if application else None}


def _charged_tokens(checkpoint_json: str | None) -> int | None:
    if not checkpoint_json:
        return None
    try:
        return parse_budget_checkpoint_json(checkpoint_json).job_charged or None
    except AgenticError:
        return None


def _latency_seconds(conn: sqlite3.Connection, run_key: str) -> float | None:
    total, started = None, None
    try:
        events = conn.execute("SELECT event,at FROM agentic_activity WHERE run_key=? "
                              "AND event IN ('started','finished') ORDER BY id", (run_key,)).fetchall()
    except sqlite3.OperationalError:
        return None
    for event, at in events:
        if event == 'started':
            started = at
        elif started is not None:
            total, started = (total or 0.0) + max(0.0, at - started), None
    return None if total is None else round(total, 3)


def _write_blob(staging: Path, value: Any, written: set[str]) -> str:
    raw = _canonical(value)
    sha256 = _sha(raw)
    if sha256 not in written:
        safe_write_bytes(staging / 'blobs' / f'{sha256}.json', raw)
        written.add(sha256)
    return sha256


def _prepare_case(conn: sqlite3.Connection, run: tuple, staging: Path, decision_policy: object | None,
                  written: set[str]) -> dict | str:
    """Everything one case needs, with its large fields already stored as blobs. A skip reason string when unusable."""
    run_key, posting_id = run[1], run[2]
    kinds = ','.join('?' * len(_ARTIFACT_KINDS))
    artifacts = {kind: (path, sha256) for kind, path, sha256 in conn.execute(
        f'SELECT kind,path,sha256 FROM agentic_artifacts WHERE run_key=? AND kind IN ({kinds})',
        (run_key, *_ARTIFACT_KINDS))}
    try:
        snapshot = _load_artifact(artifacts, 'snapshot', dict)
        raw_evaluation = _load_artifact(artifacts, 'evaluation', dict)
        structural = _load_artifact(artifacts, 'structural_inputs', dict) if 'structural_inputs' in artifacts else {}
        candidate = _load_artifact(artifacts, 'candidate', dict) if 'candidate' in artifacts else None
        insights = _load_artifact(artifacts, 'model_insights', dict) if 'model_insights' in artifacts else None
        ad_hash = _snapshot_ad_hash(snapshot, run_key)
    except (AgenticError, KeyError):
        return 'artifact_invalid'
    try:
        validate_model_payload(AgenticEvaluation, raw_evaluation)
    except AgenticError:
        return 'evaluation_invalid'
    posting = snapshot['posting']
    if decision_policy is not None:      # one commute definition: the policy's home, as the live run measures it
        from . import service
        km = service.commute_km_of(decision_policy, posting['location'])
    else:
        km = km_from_home(posting['location'] or '')
    commute_km = None if km is None else float(km)
    decision = decide_frozen(snapshot, raw_evaluation, commute_km=commute_km, decision_policy=decision_policy)
    cursor = conn.execute('SELECT * FROM postings WHERE id=?', (posting_id,))
    live = cursor.fetchone()
    posting_row = dict(zip((d[0] for d in cursor.description), live)) if live is not None else posting
    keys = group_keys_for(posting_row, ad_hash)
    refs: dict[str, str] = {}
    if candidate is not None:
        refs['candidate'] = _write_blob(staging, candidate, written)
    if type(structural.get('reference_utf8')) is str:
        refs['structural_inputs.reference_utf8'] = _write_blob(staging, structural['reference_utf8'], written)
        structural = {**structural, 'reference_utf8': None}
    if snapshot['contents']:
        refs['snapshot.contents'] = _write_blob(staging, snapshot['contents'], written)
        snapshot = {**snapshot, 'contents': {}}
    return {
        'case_id': f'c-{posting_id}-{run_key[:8]}', 'posting_id': posting_id, 'keys': keys,
        'fields': dict(
            snapshot=snapshot, structural_inputs=structural, evaluation=raw_evaluation, candidate=None,
            model_insights=insights, decision=decision, commute_km=commute_km, run_key=run_key, group_keys=keys,
            stored=_stored(conn, run), blob_refs=refs,
            usage={'charged_tokens': _charged_tokens(run[6]), 'actual_tokens': None,
                   'latency_seconds': _latency_seconds(conn, run_key)})}


def _evidence_hash(profile: Path) -> str | None:
    try:
        return snapshot_evidence(profile).bundle_hash
    except CandidateError:
        return None


def _freeze_into(conn: sqlite3.Connection, config, staging: Path, person: str, approved: dict,
                 selected: list[tuple], skipped: dict[str, int]) -> Baseline:
    from .matching import MATCHING_VERSION
    from .service import IMPLEMENTATION_VERSION, _config
    runtime_config_sha256 = digest(_config(config))
    ensure_dir(staging / 'blobs')
    ensure_dir(staging / 'cases')
    profile_sha256 = _copy_profile(apaths.profile_dir(), staging / 'profile')   # the live profile, read only
    approved_raw = _canonical(approved)
    safe_write_bytes(staging / 'approved.json', approved_raw)
    decision_policy = _active_decision_policy(config, approved)
    decision_policy_sha256 = None
    if decision_policy is not None:
        policy_raw = _canonical(decision_policy.model_dump(mode='json'))
        safe_write_bytes(staging / 'decision_policy.json', policy_raw)
        decision_policy_sha256 = _sha(policy_raw)
    skipped = dict(skipped)
    prepared = []
    written: set[str] = set()
    with pin_profile_dir(Path(os.path.abspath(staging / 'profile'))):
        policy = default_policy().model_dump(mode='json')
        evidence_bundle_hash = _evidence_hash(staging / 'profile')
        for run in selected:
            result = _prepare_case(conn, run, staging, decision_policy, written)
            if isinstance(result, str):
                skipped[result] = skipped.get(result, 0) + 1
            else:
                prepared.append(result)
    if not prepared:
        raise AgenticError('no_cases')
    groups = group_ids({p['case_id']: p['keys'] for p in prepared})
    case_sha256: dict[str, str] = {}
    cases = []
    for item in prepared:
        case = FrozenCase(case_id=item['case_id'], posting_id=item['posting_id'], group_id=groups[item['case_id']],
                          tags=(), **item['fields'])
        case = case.model_copy(update={'tags': tag_case(case)})
        raw = _canonical(case.model_dump(mode='json'))
        safe_write_bytes(staging / 'cases' / f"{case.case_id}.json", raw)
        case_sha256[case.case_id] = _sha(raw)
        cases.append(case)
    sizes = {}
    for case in cases:
        sizes[case.group_id] = sizes.get(case.group_id, 0) + 1
    routes = dict.fromkeys((*_ROUTES, 'error'), 0)
    for case in cases:
        route = case.decision.get('route')
        routes['error' if 'error' in case.decision or route not in _ROUTES else route] += 1
    summary = {
        'cases': len(cases), 'skipped': dict(sorted(skipped.items())), 'routes': routes,
        'tags': {tag: sum(tag in case.tags for case in cases) for tag in TAGS},
        'groups': len(sizes), 'largest_group': max(sizes.values()),
        'evidence_mismatch': sum(case.snapshot['run_key']['evidence_hash'] != evidence_bundle_hash for case in cases),
        'decision_errors': routes['error']}
    content_sha256 = digest({'cases': case_sha256, 'profile': profile_sha256, 'approved': _sha(approved_raw)})
    created_at = _utcnow()
    stamp = datetime.fromisoformat(created_at).astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')
    record = Baseline(
        baseline_id=f'bl-{stamp}-{content_sha256[:8]}', created_at=created_at, git_commit=_git_commit(),
        gate_version=GATE_VERSION, implementation_version=IMPLEMENTATION_VERSION, matching_version=MATCHING_VERSION,
        profile_version=int(approved['version']), profile_files_sha256=profile_sha256,
        case_ids=tuple(case.case_id for case in cases), gate_dependencies=gate_sources(), person=person,
        policy=policy, runtime_config_sha256=runtime_config_sha256, evidence_bundle_hash=evidence_bundle_hash,
        approved_sha256=_sha(approved_raw), decision_policy_sha256=decision_policy_sha256,
        case_sha256=case_sha256, content_sha256=content_sha256, summary=summary)
    safe_write_bytes(staging / 'baseline.json', _canonical(record.model_dump(mode='json')))
    return record


def freeze_baseline(conn: sqlite3.Connection, config, *, posting_ids: list[int] | None = None,
                    limit: int = 500) -> Baseline:
    """Freeze the stored inputs and outputs of the newest evaluated run per posting into a verified baseline.

    Reads the database and the live profile; writes only under the person's baselines folder, through a staging
    folder that is removed on any failure. No model is called and no database row is written."""
    _check_arguments(limit, posting_ids)
    person = users.current()
    approved = intake.current_version(person)
    if approved is None:
        raise AgenticError('no_profile_version')
    selected, skipped = _select_runs(conn, posting_ids, limit)
    if not selected:
        raise AgenticError('no_cases')
    root = _baselines_root()
    staging = root / f'.staging-{secrets.token_hex(8)}'
    try:
        ensure_dir(staging)
        record = _freeze_into(conn, config, staging, person, approved, selected, skipped)
        final = root / record.baseline_id
        if os.path.lexists(final):
            raise AgenticError('baseline_exists')
        try:
            os.rename(staging, final)
        except OSError:
            if os.path.lexists(final):
                raise AgenticError('baseline_exists') from None
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------- owner labels
#
# `baselines/<id>/labels.jsonl` is the one mutable file of a baseline: one JSON line per label, append only, the
# newest line per case wins. It is outside `content_sha256`, so labelling never invalidates a baseline. Only the
# owner's command-line tool calls `label_case` and `write_label`; no API, chat or tool surface imports this module.

_LABELS_FILE = 'labels.jsonl'
_LABELS_LOCK = 'labels.lock'
_MAX_LABELS_BYTES = 16 * 1024 * 1024
_NOTE_LIMIT = 2000


class OwnerLabel(StrictFrozen):
    case_id: str
    actor: Literal['owner']
    suitable: bool | None = None
    relevance: int | None = Field(default=None, ge=0, le=3)
    exclusion_violation: bool | None = None
    note: str = Field(default='', max_length=_NOTE_LIMIT)
    labelled_at: str
    tags: tuple[str, ...] = ()   # owner-added, each one of TAGS

    @field_validator('tags')
    @classmethod
    def _known_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        if any(tag not in TAGS for tag in tags):
            raise ValueError('unknown tag')
        return tags


def _labels_invalid() -> AgenticError:
    return AgenticError('labels_invalid')


def _parse_labels(raw: bytes) -> list[OwnerLabel]:
    """Every line, in order. A line that is not a valid owner label is an error, never skipped or repaired."""
    if not raw:
        return []
    if not raw.endswith(b'\n'):
        raise _labels_invalid()
    labels = []
    for line in raw[:-1].split(b'\n'):
        try:
            value = json.loads(line.decode('utf-8'))
            if type(value) is not dict or value.get('actor') != 'owner':
                raise ValueError
            labels.append(OwnerLabel.model_validate(value))
        except (ValueError, ValidationError):   # bad UTF-8, bad JSON and a failed model are all ValueErrors
            raise _labels_invalid() from None
    return labels


def _read_labels_file(folder: Path) -> bytes:
    try:
        return read_regular_file(folder / _LABELS_FILE, _MAX_LABELS_BYTES)
    except FileNotFoundError:
        return b''
    except (OSError, ValueError):   # a symlink, a non-regular file or an oversize file
        raise _labels_invalid() from None


def read_labels(baseline_id: str) -> list[OwnerLabel]:
    """Every label of the baseline in append order. No file is no labels; nothing is imputed."""
    return _parse_labels(_read_labels_file(_baseline_dir(baseline_id)))


def latest_labels(labels: Iterable[OwnerLabel]) -> dict[str, OwnerLabel]:
    """The last label per case, given labels in append order."""
    latest: dict[str, OwnerLabel] = {}
    for label in labels:
        latest[label.case_id] = label
    return latest


@contextlib.contextmanager
def _labels_locked(folder: Path) -> Iterator[None]:
    """One writer at a time per baseline. The lock is released when the file is closed, on any exit."""
    fd = os.open(folder / _LABELS_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def write_label(baseline_id: str, label: OwnerLabel) -> None:
    """Append one owner label. Human command-line use only: nothing the agent can reach calls this."""
    if getattr(label, 'actor', None) != 'owner':
        raise AgenticError('owner_required')
    folder = _baseline_dir(baseline_id)
    case_file = folder / 'cases' / f'{label.case_id}.json'
    if not _CASE_ID.fullmatch(label.case_id) or case_file.is_symlink() or not case_file.is_file():
        raise AgenticError('unknown_case')
    line = _canonical(label.model_dump(mode='json')) + b'\n'
    with _labels_locked(folder):
        existing = _read_labels_file(folder)
        _parse_labels(existing)   # never build on a file that is already corrupt
        safe_write_bytes(folder / _LABELS_FILE, existing + line)


def label_case(baseline_id: str, case_id: str, *, actor: Literal['owner'], suitable: bool | None = None,
               relevance: int | None = None, exclusion_violation: bool | None = None, note: str = '',
               tags: tuple[str, ...] = ()) -> OwnerLabel:
    """Validate and append the owner's label for one case. Checks run in a fixed order: owner_required,
    empty_label, invalid_tag, invalid_label, then the baseline and case checks of `write_label`."""
    if actor != 'owner':
        raise AgenticError('owner_required')
    if suitable is None and relevance is None and exclusion_violation is None and not tags:
        raise AgenticError('empty_label')   # a note alone is not a judgment
    if type(tags) not in (tuple, list) or any(type(tag) is not str or tag not in TAGS for tag in tags):
        raise AgenticError('invalid_tag')
    if ((suitable is not None and type(suitable) is not bool)
            or (exclusion_violation is not None and type(exclusion_violation) is not bool)
            or (relevance is not None and (type(relevance) is not int or not 0 <= relevance <= 3))
            or type(note) is not str or len(note) > _NOTE_LIMIT):
        raise AgenticError('invalid_label')
    label = OwnerLabel(case_id=case_id, actor='owner', suitable=suitable, relevance=relevance,
                       exclusion_violation=exclusion_violation, note=note, labelled_at=_utcnow(),
                       tags=tuple(dict.fromkeys(tags)))
    write_label(baseline_id, label)
    return label


def effective_tags(case: FrozenCase, labels: Mapping[str, OwnerLabel]) -> tuple[str, ...]:
    """The case's own tags plus the ones the owner added, in contract order."""
    label = labels.get(case.case_id)
    wanted = set(case.tags) | set(label.tags if label is not None else ())
    return tuple(tag for tag in TAGS if tag in wanted)
