"""Versioned features; missing is not false, and rubric scores are not labels."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from jobwatch.candidate.contracts import excluded_families, canonicalize_family

FEATURE_VERSION = 'choice-features-v1'
MODEL_VERSION = 'conditional-logit-outside-v1'
PRIOR_VERSION = 'archived-directions-sd05-missing-sd05-v1'
NAMES = ('hours_part_time','hours_flexible_full_time','exp_shortfall','exp_excess',
         'coverage','must_have_gaps','entry_signal','ring_inner','ring_r5_10','ring_outer',
         'ring_remote','pay_low_c','pay_high_c','automation_angle','rights_welcomes_visa',
         'rights_full_rights_wording','age_days')
PRIOR_MEANS = (.8,-.8,-.7,-.1,2.,-.5,.6,.4,.2,-.4,.2,.2,.2,.3,.3,-.2,-.02)
# Stored model dimensions (part of the saved model's digest): other families map to 'other'.
FAMILIES = ('accounting','data','admin','ai_automation','other')

class PreferenceError(ValueError):
    """Fixed public error codes only."""

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def versions():
    root = Path(__file__).parent
    files = ('features.py', 'store.py', 'model.py', 'fit_choice_model.R', 'choice_model.jags')
    return {'feature': FEATURE_VERSION, 'model': MODEL_VERSION, 'prior': PRIOR_VERSION,
            'source_hashes': {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}}

def context_hash(*identities):
    return digest({'identities': identities, 'versions': versions()})

def validate_alternatives(alternatives):
    if type(alternatives) is not list or len(alternatives) != 3:
        raise PreferenceError('three_alternatives_required')
    result = []
    for raw in alternatives:
        if type(raw) is not dict or raw.get('eligible') is not True or raw.get('current') is not True:
            raise PreferenceError('current_eligible_evaluation_required')
        if type(raw.get('posting_id')) is not int or raw['posting_id'] < 1:
            raise PreferenceError('invalid_posting')
        for key in ('ad_hash', 'profile_hash', 'run_key', 'evaluation_hash'):
            value = raw.get(key)
            if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise PreferenceError('invalid_provenance')
        if any(type(raw.get(k)) is not str or not raw[k].strip() or len(raw[k]) > 500 for k in ('title', 'company', 'family')):
            raise PreferenceError('invalid_alternative')
        if canonicalize_family(raw['family']) in excluded_families():
            raise PreferenceError('excluded_family')
        features = raw.get('features')
        if type(features) is not dict or set(features) != set(NAMES):
            raise PreferenceError('invalid_features')
        if any(v is not None and (type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e6) for v in features.values()):
            raise PreferenceError('invalid_features')
        result.append(json.loads(canonical(raw)))
    if len({a['posting_id'] for a in result}) != 3:
        raise PreferenceError('duplicate_alternative')
    if len({a['profile_hash'] for a in result}) != 1:
        raise PreferenceError('mixed_profiles')
    return result

def family_index(family):
    family = canonicalize_family(family)
    mapping = {'data_analyst':'data', 'back_office_admin':'admin'}
    return FAMILIES.index(mapping.get(family, family) if mapping.get(family, family) in FAMILIES else 'other') + 1

def alternative_from_evaluation(evaluation, *, title, company, profile_hash, gate):
    """Caller must freshly gate against current ad, policy, evidence and expected run key."""
    from pipeline.agentic.contracts import AgenticEvaluation, AgenticGateDecision
    evaluation = AgenticEvaluation.model_validate(evaluation.model_dump())
    gate = AgenticGateDecision.model_validate(gate.model_dump())
    if gate.run_key != evaluation.run_key or gate.route != 'draft' or gate.reason != 'eligible':
        raise PreferenceError('current_eligible_evaluation_required')
    f = dict.fromkeys(NAMES)
    # Current schema has no pay, commute ring, candidate years or visa-welcoming field.
    if evaluation.facts.hours == 'part_time_ok':
        f['hours_part_time'] = 1
    elif evaluation.facts.hours == 'full_time_only':
        f['hours_part_time'] = 0
    f['entry_signal'] = int(evaluation.facts.seniority in ('entry','junior') or evaluation.facts.program)
    if evaluation.location_fit == 'remote_accessible':
        f['ring_remote'] = 1
    must_haves = {r.id for r in evaluation.requirements.requirements
                  if r.tier == 'stated' and r.importance in ('critical','high','meaningful')}
    applicable = [m for m in evaluation.matches if m.requirement_id in must_haves and m.match != 'not_applicable']
    if applicable:
        f['coverage'] = sum(m.match == 'strong' for m in applicable) / len(applicable)
        f['must_have_gaps'] = sum(m.match != 'strong' for m in applicable)
    return {'posting_id':evaluation.run_key.posting_id, 'title':title, 'company':company,
            'family':evaluation.facts.role_family, 'features':f, 'eligible':True, 'current':True,
            'ad_hash':evaluation.run_key.ad_hash, 'profile_hash':profile_hash,
            'run_key':evaluation.run_key.value, 'evaluation_hash':digest(evaluation.model_dump(mode='json'))}
