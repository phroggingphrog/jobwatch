"""Synthetic approved-profile helpers for the decision policy tests (person "Alex Example"; no real data)."""
from __future__ import annotations

import hashlib
import json

from jobwatch.candidate.policy import DecisionPolicy, build_policy


def fact(section, value, basis='evidence', fid=None, actor='person') -> dict:
    if fid is None:      # deterministic, so the same fact always yields the same policy hash
        fid = 'f' + hashlib.sha256(json.dumps([section, value, basis], sort_keys=True).encode()).hexdigest()[:8]
    return {'id': fid, 'section': section, 'value': value, 'basis': basis, 'note': '',
            'actor': actor, 'sources': []}


def approved(*facts, version=2) -> dict:
    """An approved.json payload that carries a confirmed scope."""
    return {'version': version, 'facts': list(facts), 'scope': {'authorises': ['discovery', 'assessment']},
            'scope_digest': 'd' * 64, 'uploads': ['a' * 64]}


def policy_of(*facts, version=2) -> DecisionPolicy:
    return build_policy(approved(*facts, version=version))
