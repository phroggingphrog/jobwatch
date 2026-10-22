"""Versioned features; missing is not false, and rubric scores are not labels."""
from __future__ import annotations
import hashlib
import json
import math
import re
from pathlib import Path
from jobwatch.candidate.contracts import JOB_ROLE_FAMILIES, canonicalize_family

FEATURE_VERSION = 'choice-features-v3-canonical-families'
MODEL_VERSION = 'conditional-logit-outside-v2-neutral-families'
PRIOR_VERSION = 'neutral-zero-sd05-family-exchangeable-v2'
NAMES = ('hours_part_time','hours_flexible_full_time','exp_shortfall','exp_excess',
         'coverage','must_have_gaps','entry_signal','ring_inner','ring_r5_10','ring_outer',
         'ring_remote','pay_low_c','pay_high_c','automation_angle','rights_welcomes_visa',
         'rights_full_rights_wording','age_days')
# Symmetric Normal(0, .5) regularization for observed and missingness coefficients.
# The same uncertainty applies to objective evidence features: none is a human taste label.
PRIOR_MEANS = (0.,) * len(NAMES)
# Exchangeable family intercepts: common Normal(0, 1), half-Normal(0, .5) spread;
# no occupation receives a cold-start advantage. Unknown remains a distinct category.
FAMILIES = JOB_ROLE_FAMILIES

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
            'families': list(FAMILIES), 'prior_means': list(PRIOR_MEANS),
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
        # Eligibility is freshly established by the canonical per-person gate upstream.
        # Validation never reads a legacy interest file or reinterprets stored owner choices.
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
    return FAMILIES.index(family if family in FAMILIES else 'other') + 1

def alternative_from_evaluation(evaluation, *, title, company, profile_hash, gate):
    """Caller must freshly gate against current ad, policy, evidence and expected run key."""
    from pipeline.agentic.contracts import AgenticEvaluation, AgenticGateDecision
    evaluation = AgenticEvaluation.model_validate(evaluation.model_dump())
    gate = AgenticGateDecision.model_validate(gate.model_dump())
    if gate.run_key != evaluation.run_key or gate.route != 'draft' or gate.reason != 'eligible':
        raise PreferenceError('current_eligible_evaluation_required')
    f = dict.fromkeys(NAMES)
    sources = {}
    # Missing pay, candidate years and explicit visa-welcoming facts stay missing.
    if evaluation.facts.hours == 'part_time_ok':
        f['hours_part_time'] = 1
    elif evaluation.facts.hours == 'full_time_only':
        f['hours_part_time'] = 0
    context = evaluation.matching_diagnostics or {}
    uncertainties = context.get('ad_uncertainties')
    if evaluation.facts.program:
        f['entry_signal'] = 1
    elif isinstance(uncertainties, list) and not any('seniority unknown' in str(u).casefold() for u in uncertainties):
        f['entry_signal'] = int(evaluation.facts.seniority in ('entry','junior'))
    if evaluation.location_fit == 'remote_accessible':
        f['ring_remote'] = 1
        for name in ('ring_inner', 'ring_r5_10', 'ring_outer'):
            f[name] = 0
        sources['commute'] = 'remote_accessible_evaluation'
    else:
        distance = context.get('commute_km_from_home')
        if type(distance) in (int, float) and math.isfinite(distance) and 0 <= distance <= 20_000:
            f['ring_inner'] = int(distance < 5)
            f['ring_r5_10'] = int(5 <= distance <= 10)
            f['ring_outer'] = int(distance > 10)
            sources['commute'] = 'snapshot_straight_line_km_not_travel_time'
    quote = evaluation.facts.work_rights.quote
    if quote:
        f['rights_full_rights_wording'] = int(bool(re.search(r'\bfull (?:working|work) rights\b', quote, re.I)))
        sources['rights_full_rights_wording'] = 'exact_ad_work_rights_quote_not_candidate_status'
    must_haves = {r.id for r in evaluation.requirements.requirements
                  if r.tier == 'stated' and r.importance in ('critical','high','meaningful')}
    applicable = [m for m in evaluation.matches if m.requirement_id in must_haves and m.match != 'not_applicable']
    if applicable:
        f['coverage'] = sum(m.match == 'strong' for m in applicable) / len(applicable)
        f['must_have_gaps'] = sum(m.match != 'strong' for m in applicable)
    sources['qualification_coverage'] = 'model_evidence_judgments_not_owner_labels'
    return {'posting_id':evaluation.run_key.posting_id, 'title':title, 'company':company,
            'family':evaluation.facts.role_family, 'features':f, 'eligible':True, 'current':True,
            'ad_hash':evaluation.run_key.ad_hash, 'profile_hash':profile_hash,
            'run_key':evaluation.run_key.value, 'evaluation_hash':digest(evaluation.model_dump(mode='json')),
            'feature_version': FEATURE_VERSION, 'feature_sources': sources,
            'missing_features': [name for name, value in f.items() if value is None]}
