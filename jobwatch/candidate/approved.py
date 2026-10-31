"""Read the server-bound person's immutable approved inputs."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from . import intake
from ._private_io import read_regular_file
from .contracts import CandidateError
from .evidence import snapshot_evidence, verify_evidence_snapshot


def version(person: str) -> tuple[dict, Path]:
    try:
        approved = intake.current_version(person)
        if approved is None:
            raise CandidateError('no_profile_version')
        if not isinstance(approved, dict) or type(approved.get('version')) is not int:
            raise CandidateError('approved_profile_invalid')
        return approved, intake._versions_root(person) / str(approved['version'])
    except CandidateError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise CandidateError('approved_profile_invalid') from None


def evidence(person: str):
    approved, root = version(person)
    expected = approved.get('evidence_bundle_hash')
    if not expected:
        raise CandidateError('approved_evidence_missing')
    try:
        bundle = snapshot_evidence(root / 'evidence')
        verify_evidence_snapshot(bundle)
        if bundle.bundle_hash != expected:
            raise CandidateError('approved_evidence_changed')
        return bundle
    except CandidateError:
        raise
    except (OSError, ValueError, TypeError):
        raise CandidateError('approved_evidence_invalid') from None


def settings(person: str, name: str) -> dict:
    approved, root = version(person)
    if name not in ('profile.yaml', 'interests_and_criteria.yaml'):
        raise CandidateError('approved_restrictions_invalid')
    try:
        raw = read_regular_file(root / name, intake.MAX_JSON_BYTES)
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise CandidateError('approved_restrictions_invalid')
        # Projections are reproducible from the approved facts, not live input.
        from .projection import project
        expected = project(approved)[name].encode('utf-8')
        if hashlib.sha256(raw).digest() != hashlib.sha256(expected).digest():
            raise CandidateError('approved_restrictions_changed')
        return data
    except FileNotFoundError:
        raise CandidateError('approved_restrictions_missing') from None
    except CandidateError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise CandidateError('approved_restrictions_invalid') from None
