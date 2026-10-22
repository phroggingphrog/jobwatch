"""Versioned features; missing is not false, and rubric scores are not labels."""
from __future__ import annotations
import hashlib
import json
import math
import re
from pathlib import Path
from jobwatch.candidate.contracts import JOB_ROLE_FAMILIES, canonicalize_family

FEATURE_VERSION = 'choice-features-v4-observed-facts'
MODEL_VERSION = 'conditional-logit-outside-v2-neutral-families'
PRIOR_VERSION = 'neutral-zero-sd05-family-exchangeable-v2'
NAMES = ('hours_part_time','hours_flexible_full_time','exp_shortfall','exp_excess',
         'coverage','must_have_gaps','entry_signal','ring_inner','ring_r5_10','ring_outer',
         'ring_remote','pay_low_c','pay_high_c','status_held','rights_welcomes_visa',
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
    files = ('features.py', 'store.py', 'model.py', 'fit_choice_model.R', 'choice_model.jags', 'experience.py')
    return {'feature': FEATURE_VERSION, 'model': MODEL_VERSION, 'prior': PRIOR_VERSION,
            'families': list(FAMILIES), 'prior_means': list(PRIOR_MEANS),
            'source_hashes': {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}}

def context_hash(*identities):
    return digest({'identities': identities, 'versions': versions()})

def validate_alternatives(alternatives, *, size=3):
    if type(alternatives) is not list or (size is None and not 1 <= len(alternatives) <= 100) or (size is not None and (type(size) is not int or len(alternatives) != size)):
        raise PreferenceError('three_alternatives_required' if size == 3 else 'invalid_alternative_count')
    result = []
    for raw in alternatives:
        if type(raw) is not dict or raw.get('current') is not True:
            raise PreferenceError('current_eligible_evaluation_required')
        status = raw.get('status', 'eligible')
        if status == 'eligible':
            valid_status = raw.get('eligible') is True
        elif status == 'held':
            gate = raw.get('gate', {})
            valid_status = isinstance(gate, dict) and raw.get('eligible') is False and gate.get('route') == 'hold' and gate.get('reason') == 'insufficient_evidence' and gate.get('run_key') == raw.get('run_key')
        else:
            valid_status = False
        if not valid_status:
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
    if len({a['posting_id'] for a in result}) != len(result):
        raise PreferenceError('duplicate_alternative')
    if len({a['profile_hash'] for a in result}) != 1:
        raise PreferenceError('mixed_profiles')
    return result

def family_index(family):
    family = canonicalize_family(family)
    return FAMILIES.index(family if family in FAMILIES else 'other') + 1

def alternative_from_evaluation(evaluation, *, title, company, profile_hash, gate,
                                posting=None, ad_text=None, approved=None):
    """Caller must freshly gate against current ad, policy, evidence and expected run key."""
    from pipeline.agentic.contracts import AgenticEvaluation, AgenticGateDecision
    evaluation = AgenticEvaluation.model_validate(evaluation.model_dump())
    gate = AgenticGateDecision.model_validate(gate.model_dump())
    status = {('draft', 'eligible'): 'eligible', ('hold', 'insufficient_evidence'): 'held'}.get((gate.route, gate.reason))
    if gate.run_key != evaluation.run_key or status is None:
        raise PreferenceError('current_eligible_evaluation_required')
    if ad_text is not None and (type(ad_text) is not str or hashlib.sha256(ad_text.encode()).hexdigest() != evaluation.run_key.ad_hash):
        raise PreferenceError('ad_hash_mismatch')
    posting = dict(posting) if posting is not None else {}
    if posting.get('id', evaluation.run_key.posting_id) != evaluation.run_key.posting_id:
        raise PreferenceError('invalid_posting')
    f = dict.fromkeys(NAMES)
    sources = {}
    f['status_held'] = int(status == 'held')
    sources['status_held'] = {'kind': 'canonical_gate', 'route': gate.route, 'reason': gate.reason}
    f['pay_low_c'], f['pay_high_c'] = hourly_pay(posting, ad_text=ad_text)
    for name in ('pay_low_c', 'pay_high_c'):
        if f[name] is not None:
            sources[name] = {'kind': 'posting_salary_aud_hourly', 'unit': posting.get('salary_unit'),
                             'salary_text': posting.get('salary_text'), 'conversion_quote': _source_hours(ad_text, posting.get('salary_unit'))[1]}
    f['age_days'] = posting_age_days(posting)
    if f['age_days'] is not None:
        sources['age_days'] = {'kind': 'provider_age_at_first_seen', 'posted_at': posting.get('posted_at'), 'first_seen_at': posting.get('first_seen_at')}
    if evaluation.facts.hours == 'full_time_only' and ad_text is not None:
        value, quote = _flexible_hours(ad_text)
        f['hours_flexible_full_time'] = value
        if value is not None:
            sources['hours_flexible_full_time'] = {'kind': 'exact_ad_quote', 'quote': quote}
    if ad_text is not None:
        quote = _visa_welcome(ad_text)
        if quote:
            f['rights_welcomes_visa'] = 1
            sources['rights_welcomes_visa'] = {'kind': 'exact_ad_quote', 'quote': quote}
    tenure = _overall_experience(evaluation, ad_text, approved)
    if tenure is not None:
        years, source = tenure
        f['exp_shortfall'] = max(0, evaluation.facts.min_years-years)
        f['exp_excess'] = max(0, years-evaluation.facts.min_years)
        sources['exp_shortfall'] = source
        sources['exp_excess'] = source

    # Existing observed evaluation features retain their established units.
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
    for name, value in f.items():
        if value is not None and name not in sources:
            sources[name] = {'kind': 'current_evaluation', 'evaluation_hash': digest(evaluation.model_dump(mode='json'))}
    return {'posting_id':evaluation.run_key.posting_id, 'title':title, 'company':company,
            'family':evaluation.facts.role_family, 'features':f, 'status': status, 'eligible':status == 'eligible', 'current':True,
            'gate': {'route': gate.route, 'reason': gate.reason, 'run_key': gate.run_key.value},
            'ad_hash':evaluation.run_key.ad_hash, 'profile_hash':profile_hash,
            'run_key':evaluation.run_key.value, 'evaluation_hash':digest(evaluation.model_dump(mode='json')),
            'feature_version': FEATURE_VERSION, 'feature_sources': sources,
            'source_provenance': {'posting_hash': digest(posting) if posting else None,
                'approved_hash': digest(approved) if approved is not None else None,
                'evidence_hash': evaluation.run_key.evidence_hash, 'ad_hash': evaluation.run_key.ad_hash,
                'confirmed_at': approved.get('confirmed_at') if isinstance(approved, dict) else None},
            'missing_features': [name for name, value in f.items() if value is None]}


def _source_hours(ad_text, unit):
    """Only an explicit hours-per-salary-period fact permits conversion."""
    if not isinstance(ad_text, str) or unit not in ('day', 'week', 'month', 'year'):
        return None, None
    pattern = rf'\b(\d+(?:\.\d+)?)\s+(?:working\s+)?hours?\s+(?:per|a|each|/)\s*{unit}\b'
    hits = list(re.finditer(pattern, ad_text, re.I))
    for hit in hits:
        # A decimal point is not a sentence boundary (37.5–40 is a range).
        prefix = re.split(r'[!?\n]|\.(?!\d)', ad_text[:hit.start()])[-1]
        suffix = re.split(r'[!?\n]|\.(?!\d)', ad_text[hit.end():])[0]
        if (re.search(r'\b(?:not|no|up to|between|at least|at most|about|approximately|typically|normally|maximum|minimum|may|might)\b', prefix, re.I)
                or re.search(r'\d\s*[-–—]\s*$', prefix)
                or re.search(r'\b(?:open|opening|operating|hours of operation|business hours)\b', prefix, re.I)
                or re.search(r'\b(?:optional|during|except|or)\b', suffix, re.I)):
            return None, None
    values = {float(m[1]) for m in hits}
    # Conflicting hours (or no explicit fact) cannot identify a denominator.
    if len(values) != 1:
        return None, None
    hours = values.pop()
    if not 0 < hours <= {'day':24, 'week':168, 'month':744, 'year':8784}[unit]:
        return None, None
    return hours, hits[0][0]


def hourly_pay(posting, *, ad_text=None):
    """AUD per hour, with no inferred currency or standard working week."""
    currency = str(posting.get('salary_currency') or posting.get('currency') or '').upper()
    text = str(posting.get('salary_text') or '')
    if currency and currency != 'AUD':
        return None, None
    if not currency and not re.search(r'\bAUD\b|A\$', text, re.I):
        return None, None
    # Reject ambiguous mixed-currency text even if it also mentions AUD.
    if re.search(r'\b(?:USD|NZD|CAD|EUR|GBP)\b|US\$|NZ\$', text, re.I):
        return None, None
    unit = posting.get('salary_unit')
    divisor = 1 if unit == 'hour' else _source_hours(ad_text, unit)[0]
    if divisor is None:
        return None, None
    lo, hi = posting.get('salary_min'), posting.get('salary_max')
    if lo is None: lo = hi
    if hi is None: hi = lo
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 5 <= v/divisor <= 500 for v in (lo, hi)):
        return None, None
    if lo > hi:
        return None, None
    return lo/divisor, hi/divisor


def posting_age_days(posting):
    """Provider age frozen at ingestion, capped at ninety days."""
    from datetime import datetime, UTC
    if posting.get('posted_at_source') != 'provider':
        return None
    try:
        values = [datetime.fromisoformat(posting[k].replace('Z', '+00:00')) for k in ('posted_at', 'first_seen_at')]
        values = [d.replace(tzinfo=UTC) if d.tzinfo is None else d for d in values]
        return max(0, min(90, (values[1]-values[0]).days))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _flexible_hours(text):
    negative = re.search(
        r'\b(?:(?:no|without)\s+flexible\s+(?:working\s+)?hours|'
        r'(?:fixed|inflexible)\s+(?:working\s+)?hours|'
        r'(?:working\s+)?hours\s+(?:are\s+)?not\s+flexible|'
        r'flexible\s+(?:working\s+)?hours\s+(?:'
        r'(?:are\s+not|aren[\'’]t)\s+(?:available|offered|accommodated)|'
        r'(?:cannot|can[\'’]t)\s+be\s+(?:available|offered|accommodated)|'
        r'(?:are\s+)?unavailable))\b', text, re.I)
    positive = re.search(r'\bflexible\s+(?:working\s+)?hours\b|\bflexitime\b', text, re.I)
    if negative:
        prefix = re.split(r'[.!?\n]', text[:negative.start()])[-1]
        # A negated fixed-hours statement does not prove positive flexibility.
        if re.search(r'\b(?:not|no|never|without)\b', prefix, re.I):
            return None, None
        if positive and not negative.start() <= positive.start() < negative.end():
            return None, None
        return 0, negative[0]
    if positive:
        # Unrecognised negation/conditional wording stays unknown.
        prefix = text[max(0, positive.start()-60):positive.start()]
        suffix = text[positive.end():positive.end()+50]
        if re.search(r'\b(?:not|cannot|never|unable|may|might|potential|possible)\b', prefix, re.I) or re.match(r'\s+(?:are\s+)?(?:not|unavailable|may|might|could)', suffix, re.I):
            return None, None
        return 1, positive[0]
    return None, None


def flexible_hours(ad_text):
    """Explicit full-time hours flexibility: 1, 0, or unknown."""
    return _flexible_hours(ad_text)[0]


def _visa_welcome(text):
    for sentence in re.split(r'[.!?\n]', text):
        if re.search(r'\b(?:not|no|cannot|unable|never|only)\b', sentence, re.I):
            continue
        match = re.search(r'\b(?:visa holders?|international (?:students?|applicants?|candidates?))\s+(?:are\s+)?(?:welcome(?:\s+to apply)?|encouraged to apply|may apply)\b', sentence, re.I)
        if match:
            return match[0]
    return None


def _overall_experience(evaluation, ad_text, approved):
    """A narrow explicit total-work requirement can use approved total tenure.

    Specialist or mixed scopes never use this feature. The entire frozen ad quote
    must match the grammar; occupation classification and paraphrase cannot supply
    the scope or the number. Unknown dates make total tenure unknown.
    """
    if not isinstance(ad_text, str) or not isinstance(approved, dict) or evaluation.facts.min_years is None:
        return None
    grammar = re.compile(
        r'\s*(?:[-*•]\s*)?(?:(?:a\s+)?minimum(?:\s+of)?\s+|at\s+least\s+)?'
        r'(\d{1,2})\+?\s+years?[\'’]?(?:\s+of)?\s+'
        r'(?:overall|total|general)\s+(?:professional|work)\s+experience'
        r'(?:\s+(?:(?:is|are)\s+)?(?:required|essential))?\s*[.!]?\s*', re.I)
    supported = []
    for requirement in evaluation.requirements.requirements:
        signal = requirement.jd_signal
        text = signal.quote if signal is not None else requirement.text
        general = grammar.fullmatch(text)
        if general is None:
            # Another years-bearing requirement makes the aggregate scope mixed.
            if re.search(r'\b\d+\+?\s+years?\b', text, re.I):
                return None
            continue
        if (requirement.tier != 'stated' or signal is None or signal.source_id not in ('ad', 'jd')
                or signal.content_hash != evaluation.run_key.ad_hash
                or signal.quote not in ad_text or int(general[1]) != evaluation.facts.min_years):
            return None
        requirement_scope = grammar.fullmatch(requirement.text)
        if requirement_scope is None or int(requirement_scope[1]) != evaluation.facts.min_years:
            return None
        # A valid substring citation can omit a specialist qualifier. Verify the
        # complete containing source sentence as well as the frozen requirement.
        # Newlines are not boundaries: an occupation qualifier may wrap a line.
        clauses = []
        for occurrence in re.finditer(re.escape(signal.quote), ad_text):
            start = max(ad_text.rfind(mark, 0, occurrence.start()) for mark in '.!?')+1
            ends = [ad_text.find(mark, occurrence.start()) for mark in '.!?']
            end = min((pos for pos in ends if pos >= 0), default=len(ad_text)-1)+1
            clause = ad_text[start:end].strip()
            source_scope = grammar.fullmatch(clause)
            if (occurrence.end() > end or source_scope is None
                    or int(source_scope[1]) != evaluation.facts.min_years):
                return None
            clauses.append(clause)
        if not clauses:
            return None
        supported.append((requirement, clauses[0]))
    if not supported:
        return None
    from .experience import candidate_years
    years = candidate_years(approved)
    if years is None:
        return None
    requirement, source_clause = supported[0]
    return years, {'kind':'approved_exact_role_date_union',
        'scope':'explicit_overall_work_experience_v1', 'requirement_id':requirement.id,
        'quote':requirement.jd_signal.quote, 'ad_hash':evaluation.run_key.ad_hash,
        'source_clause':source_clause,
        'approved_hash':digest(approved), 'confirmed_at':approved.get('confirmed_at'),
        'role_fact_ids':[f.get('id') for f in approved.get('facts', [])
                         if isinstance(f, dict) and f.get('section') == 'experience' and f.get('basis') == 'evidence'],
        'observed_years':years, 'required_years':evaluation.facts.min_years}
