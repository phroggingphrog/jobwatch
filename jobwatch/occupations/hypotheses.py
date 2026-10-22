"""Approved evidence to occupational search hypotheses; never qualification proof."""
from __future__ import annotations

import json
import math
import os
import re
from typing import Literal

import numpy as np
from pydantic import Field

from jobwatch import db, users
from jobwatch.apply.paths import ensure_dir, safe_write_bytes
from jobwatch.candidate import intake
from jobwatch.candidate._private_io import read_regular_file
from jobwatch.candidate.contracts import StrictFrozen, canonicalize_family, digest
from jobwatch.candidate.policy import policy_for
from jobwatch.candidate.projection import _text
from jobwatch.config import load_config
from pipeline.agentic.contracts import AgenticError

from . import ALGORITHM_VERSION, DiscoveryError, loaders
from .embeddings import discovery_budget, embed_cached, make_embedder, normalise, reference_store, text_key

EVIDENCE_SECTIONS = ('experience', 'education', 'skill', 'transferable_skill', 'career_focus')


class FieldHypothesis(StrictFrozen):
    scheme: str
    code: str
    title: str
    similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    supporting_facts: tuple[str, ...]
    rationale: str
    is_qualification_proof: Literal[False] = False
    related: tuple[str, ...] = ()

    @property
    def id(self):
        return f'{self.scheme}:{self.code}'


def _id(item):
    return getattr(item, 'id', item)


def select(strategy, evidence_ranked, focus_ranked, limit):
    if type(limit) is not int or limit < 0 or strategy not in {'employment_first', 'career_focus', 'balanced'}:
        raise DiscoveryError('invalid_configuration')
    if strategy == 'employment_first' or not focus_ranked:
        candidates = evidence_ranked
    elif strategy == 'career_focus':
        candidates = [*focus_ranked[:math.ceil(2 * limit / 3)], *evidence_ranked, *focus_ranked]
    else:
        candidates = []
        for index in range(max(len(evidence_ranked), len(focus_ranked))):
            for ranked in (evidence_ranked, focus_ranked):
                if index < len(ranked):
                    candidates.append(ranked[index])
    result, seen = [], set()
    for item in candidates:
        if len(result) >= limit:
            break
        identity = _id(item)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def _usable(approved):
    result = []
    for value in approved.get('facts', ()):
        try:
            fact = intake.ProfileFact.model_validate_json(json.dumps(value))
        except (ValueError, TypeError):
            continue
        text = _text(fact.value).strip()
        if fact.section in EVIDENCE_SECTIONS and fact.basis in ('evidence', 'inference') and text:
            result.append((fact.id, fact.section, text))
    return result


def _cache_key(approved, policy, reference, model, limit):
    return digest({'algorithm': ALGORITHM_VERSION, 'policy_hash': policy.policy_hash,
                   'profile_version': approved['version'], 'model': model, 'limit': limit,
                   'datasets': sorted(reference.versions.items()), 'bundled_reference_hash': reference.records_hash,
                   # Same-version replacements must not resurrect a stale private result.
                   'approved_hash': digest(approved)})


def _folder(person):
    return users.user_dir(person) / 'discovery' / 'hypotheses'


def _load(person, *, approved=None, policy=None, reference=None, model=None, key=None, config=None):
    """Read and validate a cache against today's approved inputs, without a model call."""
    try:
        with users.use(person):
            approved = approved if approved is not None else intake.current_version(person)
            policy = policy if policy is not None else policy_for(person)
            if not approved or policy is None or policy.profile_version != approved['version']:
                return None
            reference = reference if reference is not None else loaders.load_reference_records()
            if model is None:
                from pipeline.agentic.service import _config
                model = _config(config if config is not None else load_config())['embedding_model']
            if not model:
                return None
            folder = _folder(person)
            if key is None:
                pointer = json.loads(read_regular_file(folder / 'latest.json', 2048))
                key = pointer['key']
            if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
                return None
            payload = json.loads(read_regular_file(folder / f'{key}.json', 4_000_000))
            limit = payload['limit']
            if type(limit) is not int or not 1 <= limit <= 1000:
                return None
            if payload['key'] != key or _cache_key(approved, policy, reference, model, limit) != key:
                return None
            if payload['algorithm'] != ALGORITHM_VERSION or payload['profile_version'] != approved['version']:
                return None
            if payload['policy_hash'] != policy.policy_hash or payload['datasets'] != reference.versions:
                return None
            if payload['payload_hash'] != digest({k: v for k, v in payload.items() if k != 'payload_hash'}):
                return None
            got = tuple(FieldHypothesis.model_validate_json(json.dumps(h)) for h in payload['hypotheses'])
            ids = {r.id: r for r in reference.records}
            fact_ids = {f[0] for f in _usable(approved)}
            doc_keys = payload['doc_keys']
            if len(got) > limit or len({h.id for h in got}) != len(got) or set(doc_keys) != {h.id for h in got}:
                return None
            for h in got:
                if (h.id not in ids or ids[h.id].title != h.title or not set(h.supporting_facts) <= fact_ids
                        or doc_keys[h.id] != text_key(ids[h.id].text) or not set(h.related) <= set(ids)):
                    return None
            return got, doc_keys
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def cached_hypotheses(person, *, config=None):
    cached = _load(person, config=config)
    return cached[0] if cached else None


def cached_doc_keys(person, *, config=None):
    cached = _load(person, config=config)
    return dict(cached[1]) if cached else {}


def _excluded(record, policy):
    for rule in policy.exclusions:
        if rule.kind == 'title_term' and rule.value.casefold() in record.title.casefold():
            return True
        if rule.kind == 'family' and record.family:
            try:
                if canonicalize_family(record.family) == canonicalize_family(rule.value):
                    return True
            except ValueError:
                continue
    return False


def _rank(records, queries, query_facts, documents):
    scores, supports = {}, {}
    matrix = np.array([documents[text_key(r.text)] for r in records], dtype=np.float32)
    similarities = normalise(queries) @ matrix.T
    for index, record in enumerate(records):
        best = sorted(range(len(queries)), key=lambda q: (-float(similarities[q, index]), q))[:min(3, len(queries))]
        scores[record.id] = float(np.mean([similarities[q, index] for q in best]))
        supports[record.id] = tuple(dict.fromkeys(fid for q in best for fid in query_facts[q]))
    return sorted(records, key=lambda r: (-scores[r.id], r.id)), scores, supports


def field_hypotheses(person, *, limit=15, llm=None, config=None, policy=None, conn=None, seconds=240.0):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise DiscoveryError('invalid_configuration')
    with users.use(person):
        config = config if config is not None else load_config()
        approved = intake.current_version(person)
        policy = policy if policy is not None else policy_for(person)
        if policy is None or not approved or policy.profile_version != approved.get('version'):
            raise DiscoveryError('no_policy')
        facts = _usable(approved)
        if not facts:
            raise DiscoveryError('no_profile_facts')
        reference = loaders.load_reference_records()
        if not reference.records:
            raise DiscoveryError('reference_unavailable')
        from pipeline.agentic.service import _config, configured_llm
        model = _config(config)['embedding_model']
        if model is None:
            raise DiscoveryError('embedding_not_configured')
        key = _cache_key(approved, policy, reference, model, limit)
        cached = _load(person, approved=approved, policy=policy, reference=reference, model=model, key=key)
        if cached is not None:
            return cached[0]
        # Reuse the discovery settings validator; configuration never enters a RunKey.
        from pipeline.agentic.discovery import settings
        ceiling = settings(config)['embedding_token_ceiling']
        llm = llm if llm is not None else configured_llm(config)
        owns_connection = conn is None
        if owns_connection:
            database_path = config.db_path
            ensure_dir(database_path.parent)
            # SQLite inherits this mode for its WAL too; establish it before opening a new DB.
            try:
                descriptor = os.open(database_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            conn = db.connect(database_path)
        try:
            with discovery_budget(conn, 'reference-index', token_ceiling=ceiling, seconds=seconds) as budget:
                embedder = make_embedder(llm, config, budget)
                store = reference_store(model)
                try:
                    documents = embed_cached(embedder, store, {text_key(r.text): r.text for r in reference.records})
                except AgenticError as exc:
                    if exc.code in {'token_limit', 'deadline_exceeded', 'invocation_budget_exhausted', 'daily_budget'}:
                        raise DiscoveryError('reference_index_incomplete') from None
                    raise
                queries, query_facts = [f[2] for f in facts], [(f[0],) for f in facts]
                skills = [f for f in facts if f[1] in ('skill', 'transferable_skill')]
                if skills:
                    queries.append(('skills: ' + '; '.join(f[2] for f in skills))[:1500])
                    query_facts.append(tuple(f[0] for f in skills[:8]))
                query_vectors = embedder.embed_queries(queries, kind='field_from_evidence')
                records = [r for r in reference.records if not _excluded(r, policy)]
                if not records:
                    ranked, scores, supports = [], {}, {}
                else:
                    ranked, scores, supports = _rank(records, query_vectors, query_facts, documents)
                focus_ranked = []
                if policy.focus and records:
                    focus_vectors = normalise(embedder.embed_queries(list(policy.focus), kind='field_from_evidence'))
                    matrix = np.array([documents[text_key(r.text)] for r in records], dtype=np.float32)
                    focus_scores = (focus_vectors @ matrix.T).max(axis=0)
                    focus_ranked = [r for _, r in sorted(zip(focus_scores, records), key=lambda p: (-float(p[0]), p[1].id))]
        finally:
            if owns_connection:
                conn.close()
        selected = select(policy.strategy, ranked, focus_ranked, limit)
        links = {}
        for link in reference.correspondences:
            links.setdefault(link.a, set()).add(link.b)
            links.setdefault(link.b, set()).add(link.a)
        hypotheses = []
        for record in selected:
            representative = next((i for i, h in enumerate(hypotheses) if h.id in links.get(record.id, ())), None)
            if representative is not None:
                existing = hypotheses[representative]
                hypotheses[representative] = existing.model_copy(update={'related': (*existing.related, record.id)})
                continue
            similarity = round(max(-1., min(1., scores[record.id])), 4)
            supporting = supports[record.id]
            rationale = (f"Closest approved facts: {', '.join(supporting)}. Similarity {similarity:.4f}. "
                         f'Strategy {policy.strategy}. A search hypothesis only; it is not evidence that you qualify.')
            hypotheses.append(FieldHypothesis(scheme=record.scheme, code=record.code, title=record.title,
                similarity=similarity, supporting_facts=supporting, rationale=rationale))
        payload = {'key': key, 'profile_version': approved['version'], 'policy_hash': policy.policy_hash,
                   'algorithm': ALGORITHM_VERSION, 'datasets': reference.versions, 'limit': limit,
                   'hypotheses': [h.model_dump(mode='json') for h in hypotheses],
                   'doc_keys': {h.id: text_key(next(r.text for r in reference.records if r.id == h.id)) for h in hypotheses}}
        payload['payload_hash'] = digest(payload)
        folder = _folder(person)
        safe_write_bytes(folder / f'{key}.json', json.dumps(payload, sort_keys=True, allow_nan=False).encode())
        safe_write_bytes(folder / 'latest.json', json.dumps({'key': key}).encode())
        return tuple(hypotheses)
