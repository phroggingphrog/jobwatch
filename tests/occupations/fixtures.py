"""Synthetic inputs only: no candidate records or network requests."""
import hashlib
import json
import re

import numpy as np

from jobwatch import model_choice, users
from jobwatch.apply.paths import safe_write_bytes
from jobwatch.candidate.contracts import digest
from jobwatch.candidate.policy import DecisionPolicy
from jobwatch.config import Config
from jobwatch.llm import LLM
from pipeline.agentic.execution import QWEN_EMBEDDING_MODEL


def hash_vector(text, dims=64):
    # Retrieval instructions are protocol metadata, not part of the synthetic semantic document.
    text = text.split('\nQuery:', 1)[-1]
    vector = np.zeros(dims, dtype=np.float32)
    for word in re.findall(r'\w+', text.casefold()):
        vector[int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], 'big') % dims] += 1
    if not np.any(vector):
        vector[0] = 1
    return (vector / np.linalg.norm(vector)).tolist()


def hash_transport(calls=None, *, chat=None, fail_after=None):
    calls = calls if calls is not None else []
    embeddings = 0
    def transport(url, headers, body, timeout):
        nonlocal embeddings
        if url.endswith('/embeddings'):
            if fail_after is not None and embeddings >= fail_after:
                from jobwatch.llm import SafeLLMError
                raise SafeLLMError('unavailable')
            embeddings += 1
            calls.append(body)
            return 200, {'data': [{'index': i, 'embedding': hash_vector(t)} for i, t in enumerate(body['input'])],
                         'usage': {'prompt_tokens': 10 * len(body['input'])}}
        assert chat is not None, 'unexpected synthetic chat call'
        return chat(body)
    return transport


def approved_llm(transport):
    return LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)


def make_config(settings=None):
    from pathlib import Path
    return Config(Path('/nonexistent'), settings or {'pipeline': {'agentic': {'embedding_model': QWEN_EMBEDDING_MODEL}}}, {}, {}, {}, [])


def fact(section, text, basis='evidence', fid=None):
    return {'id': fid or digest([section, text])[:12], 'section': section, 'value': text, 'basis': basis}


def write_approved(person, facts, version=1):
    value = {'schema': 1, 'version': version, 'facts': facts}
    safe_write_bytes(users.user_dir(person) / 'profile-versions' / str(version) / 'approved.json', json.dumps(value).encode())
    return value


def make_policy(**over):
    fields = dict(profile_version=1, strategy='employment_first', focus=(), exclusions=(), home=None,
                  max_commute_km=None, remote_ok=None, work_rights={}, seniority=(), open_questions=(), regions=())
    fields.update(over)
    return DecisionPolicy(**fields, policy_hash=digest(DecisionPolicy.model_construct(**fields, policy_hash='').model_dump(mode='json', exclude={'policy_hash'})))


def toy_reference():
    from jobwatch.occupations.loaders import OccupationRecord, Correspondence, LoadedReference
    values = [
        ('221111', 'Accountant', 'Reconciled supplier ledgers prepared journals bookkeeping ledgers journals accounts', 'accounting'),
        ('551111', 'Bookkeeper', 'bookkeeping ledgers journals reconciled supplier ledgers accounts', 'bookkeeping'),
        ('551311', 'Payroll Officer', 'payroll wages employees payslips', 'payroll'),
        ('431111', 'Barista', 'coffee cafe drinks customer service', None),
        ('261312', 'Software Developer', 'software developer programming design applications code', None),
        ('254411', 'Nurse', 'patients clinical nursing medication care', None),
        ('811111', 'Cleaner', 'clean offices bathrooms overnight cleaning', None),
    ]
    records = [OccupationRecord(scheme='anzsco2022', code=c, title=t, text=t + '. ' + text,
                                family=f, dataset_version='toy-1') for c, t, text, f in values]
    records.append(OccupationRecord(scheme='onet', code='13-2011.00', title='Accountants and Auditors',
        text='Accountants and Auditors. Reconciled supplier ledgers prepared journals bookkeeping accounts', dataset_version='toy-1'))
    return LoadedReference(records=tuple(records), correspondences=(Correspondence(a='onet:13-2011.00', b='anzsco2022:221111', kind='broad'),),
        versions={'anzsco2022': 'toy-1', 'onet': 'toy-1'}, skipped={}, records_hash=digest([(r.id, r.text) for r in records]))
