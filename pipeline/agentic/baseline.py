"""Frozen baseline: models, gate version, case grouping and tags.

A baseline freezes the live gate's inputs and decisions for a set of real postings so a later change can
be compared against it. This first part holds the data models, the gate-version digest, the grouping that
keeps related postings together and the review tags. Reading a person's records and freezing them live in
later sections of this module. Nothing here reads a profile or calls a model.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import ConfigDict

from jobwatch.dedupe import _COMPANY_NOISE, _norm

from .contracts import AgenticEvaluation, StrictFrozen
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
