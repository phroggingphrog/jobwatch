"""Canonical personal eligibility. No inherited home, level, rights or hours.

An explicit None policy is neutral for immutable comparisons. Omitted policy
reads only the current person's confirmed intake. Qualification evidence is
checked separately by the requirement matcher, never by a junior-years cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Mapping

from .policy import DecisionPolicy, exclusion_hit

_CURRENT = object()
_RANK = {'entry': 0, 'junior': 1, 'mid': 2, 'senior': 3}

@dataclass(frozen=True)
class EligibilityDecision:
    status: Literal['eligible', 'held', 'excluded']
    reason: str
    questions: tuple[str, ...] = ()

def _result(status, reason, *questions):
    return EligibilityDecision(status, reason, tuple(dict.fromkeys(questions)))


def _rights_text(text):
    """Repair only the established OCR split-keyword allowlist for scanning.

    Exact quote presence is checked against the original advertisement separately.
    """
    return re.sub(r'\b(?:f\s+ull|u\s+nrestricted|u\s+nlimited|p\s+ermanent|c\s+itizen(?:s|ship)?)\b',
                  lambda m: re.sub(r'\s+', '', m.group()), text, flags=re.I)


def _scan_requirements(text, title=''):
    """Use the reader's conservative ad-only scanner, including negation and alternatives."""
    from jobwatch.reader import (_scan_full, _resolve_ongoing, _CITIZEN_PATTERNS,
                                 _CLEARANCE_PATTERNS, _UNRESTRICTED_PATTERNS)
    text = _rights_text(text)
    requirements = []
    found, ongoing = _resolve_ongoing(text, title, _scan_full(text, _CITIZEN_PATTERNS))
    if ongoing:
        requirements.append(('unresolved', ''))
    for state, quote in dict.fromkeys(found):
        if state != 'hit':
            continue
        if re.search(r'\bor\s+(?:hold|have|possess|be\s+on)\s+(?:an?\s+)?(?:[\w-]+\s+){0,3}visa\b', quote, re.I):
            # A named visa is an alternative, but valid rights alone cannot prove
            # that the person's approved visa satisfies the specific alternative.
            kind = 'visa_alternative'
        elif re.search(r'permanent\s+residen|\bPRs?\b', quote, re.I):
            kind = 'citizen_or_pr'
        else:
            kind = 'citizen_only'
        requirements.append((kind, quote))
    # Scan requirement kinds separately: a sentence can demand both citizenship
    # and clearance; its clearance words must not relabel the citizenship hit.
    generic_clearance = re.compile(r'\bclearance\b[^.;\n]{0,25}\b(?:required|prerequisite|mandatory|essential)\b|'
        r'\b(?:must|requires?|required)\b[^.;\n]{0,35}\bclearance\b', re.I)
    for state, quote in dict.fromkeys(_scan_full(text, [*_CLEARANCE_PATTERNS, generic_clearance])):
        if state != 'hit':
            continue
        if not re.search(r'clearance|vetting|\b(?:NV\s*-?\s*[12]|PV|AGSVA)\b', quote, re.I):
            requirements.append(('unresolved', quote))
            continue
        obtaining = bool(re.search(r'\b(?:eligible|eligibility|ability|able)\b.{0,35}\b(?:obtain|gain|acquire)\b', quote, re.I))
        requirements.append(('clearance_eligibility' if obtaining else 'clearance', quote))
    for state, quote in dict.fromkeys(_scan_full(text, _UNRESTRICTED_PATTERNS, citizenship=False)):
        if state == 'hit':
            requirements.append(('unrestricted_work_rights', quote))
    valid_rights = re.compile(r'\bright\s+to\s+work\b|\b(?:valid|full|current|legal)\s+work(?:ing)?\s+rights\b', re.I)
    for state, quote in dict.fromkeys(_scan_full(text, [valid_rights], citizenship=False)):
        if state == 'hit' and not any(q == quote and kind == 'unrestricted_work_rights' for kind, q in requirements):
            requirements.append(('valid_work_rights', quote))
    # No-sponsorship wording is about the person's need, not their nationality.
    if re.search(r'\b(?:no\s+(?:visa\s+)?sponsorship(?!\s+(?:restrictions?|limitations?|conditions?)\b)|cannot\s+(?:provide\s+|offer\s+|sponsor\s+)?(?:visa\s+)?sponsor(?:ship|ing)?|'
                 r'unable\s+to\s+sponsor|sponsorship\s+(?:is\s+)?not\s+(?:available|provided))\b', text, re.I):
        requirements.append(('no_sponsorship', ''))
    return requirements


_KIND_PATTERNS = (
        ('nationality', r'\bcitizens?(?:hip)?\b|\bpermanent\s+residen|\bPRs?\b'),
        ('clearance', r'\bclearance\b|\bvetting\b|\bNV\s*-?\s*[12]\b'),
        ('work', r'\bwork(?:ing)?\s+rights\b|\bright\s+to\s+work\b'),
        ('sponsorship', r'\bsponsorship\b'))


def _rights_kinds(text):
    return {kind for kind, pattern in _KIND_PATTERNS if re.search(pattern, text, re.I)}


def _partition_requirements(text):
    """Separate cross-kind clauses without splitting 'citizens or permanent residents'.

    Boolean alternatives stay alternatives. Unhandled wording continues through
    the conservative scanner, rather than manufacturing personal status evidence.
    """
    for sentence in re.finditer(r'[^.;\n]+', text):
        value = sentence.group()
        bounds = {}
        for kind, pattern in _KIND_PATTERNS:
            hits = list(re.finditer(pattern, value, re.I))
            if hits:
                bounds[kind] = (hits[0].end(), hits[-1].start())
        if len(bounds) < 2:
            continue
        without = re.search(r'\bwithout\b', value, re.I)
        for operator in ('or', 'and'):
            for split in re.finditer(r'\b' + operator + r'\b', value, re.I):
                a = {k for k, (first_end, _) in bounds.items() if first_end <= split.start()}
                b = {k for k, (_, last_start) in bounds.items() if last_start >= split.end()}
                if operator == 'or' and without and without.start() < split.start():
                    continue   # "without restrictions or requiring sponsorship" shares the negation
                if a and b and a != b and a - b and b - a:
                    left, right = value[:split.start()], value[split.end():]
                    rest = text[:sentence.start()] + text[sentence.end():]
                    return operator, left, right, rest
    return None


def _requirements(text, supplied, title='', *, _depth=0):
    if _depth >= 24:
        return [('unresolved', '')]  # complicated untrusted Boolean wording needs review
    text = _rights_text(text)
    split = _partition_requirements(text)
    if split:
        operator, left, right, rest = split
        branches = (_requirements(left, {}, title, _depth=_depth+1), _requirements(right, {}, title, _depth=_depth+1))
        if operator == 'or':
            branches = tuple(branch or [('unresolved', '')] for branch in branches)
        requirements = ([('any_of', branches)] if operator == 'or' else [*branches[0], *branches[1]])
        requirements += _requirements(rest, {}, title, _depth=_depth+1)
    else:
        requirements = _scan_requirements(text, title)
    requirement = supplied.get('requirement', 'none_stated')
    quote = _rights_text(supplied.get('quote', ''))
    if requirement != 'none_stated':
        if not quote or quote not in text:
            requirements.append(('unresolved', ''))
        else:
            quoted = _requirements(quote, {}, title, _depth=_depth+1)
            blocking = {'citizen_only', 'citizen_or_pr', 'clearance', 'clearance_eligibility',
                        'unrestricted_work_rights', 'any_of'}
            allowed = blocking | {'valid_work_rights', 'visa_alternative'} if requirement == 'valid_work_rights' else blocking
            if not any(kind in allowed for kind, _ in quoted):
                requirements.append(('unverified', quote))
    return requirements

def _rights(requirements, approved):
    questions = []
    for kind, quote in requirements:
        if kind == 'any_of':
            results = [_rights(branch, approved) for branch in quote]
            if any(result is None for result in results):
                continue
            if all(result.status == 'excluded' for result in results):
                return _result('excluded', 'work_rights_incompatible')
            questions.extend(q for result in results if result.status == 'held' for q in result.questions)
            continue
        if kind == 'unresolved':
            questions.append('work_rights_requirement')
            continue
        if kind == 'unverified':
            questions.append('work_rights_quote')
            continue
        value = approved.get(kind)
        if kind == 'citizen_only':
            value = approved.get('citizen')
        elif kind == 'citizen_or_pr':
            if approved.get('citizen') is True or approved.get('permanent_resident') is True:
                value = True
            elif 'citizen' in approved or 'permanent_resident' in approved:
                value = False if approved.get('citizen') is False and approved.get('permanent_resident') is False else None
            else:
                value = approved.get('citizen_or_pr')
        elif kind == 'visa_alternative':
            value = True if approved.get('citizen') is True or approved.get('permanent_resident') is True else None
        elif kind in ('valid_work_rights', 'unrestricted_work_rights'):
            if approved.get('citizen') is True or approved.get('permanent_resident') is True:
                value = True if kind not in approved or value is True else None
        elif kind == 'no_sponsorship':
            needed = approved.get('requires_sponsorship')
            value = not needed if type(needed) is bool else None
            if approved.get('citizen') is True or approved.get('permanent_resident') is True:
                value = True if 'requires_sponsorship' not in approved or needed is False else None
        elif kind in ('clearance', 'clearance_eligibility'):
            levels = approved.get('clearances')
            wanted = {re.sub(r'[\s-]', '', x).casefold() for x in re.findall(r'\b(NV\s*-?\s*[12]|PV|baseline)\b', quote, re.I)}
            if isinstance(levels, list):
                if wanted:
                    # Different clearance levels do not imply equivalence.
                    held = {re.sub(r'[\s-]', '', s).casefold() for s in levels}
                    value = bool(wanted & held) if re.search(r'\bor\b', quote, re.I) else wanted <= held
                    if not value and levels:
                        value = None
                else:
                    value = bool(levels)
                if kind == 'clearance_eligibility' and value is not True:
                    # No current clearance says nothing about ability to obtain one.
                    value = None
            else:
                value = None
        if value is False:
            return _result('excluded', 'work_rights_incompatible')
        if value is not True:
            questions.append(kind)
    return _result('held', 'verification_required' if 'work_rights_quote' in questions else 'work_rights_unknown',
                   *questions) if questions else None


def _onsite_locations(text):
    """Explicit attendance requirements outrank a generic list of office alternatives.

    Unresolved place wording remains a question. Neither an office list nor a
    candidate's own home constitutes attendance evidence.
    """
    from pipeline.agentic.location import regions_named
    locations = []
    for sentence in re.split(r'[.;\n]', text):
        mandatory = re.search(r'\b(?:must|required?|requires|mandatory|expected)\b', sentence, re.I)
        attendance = re.search(r'\b(?:attend(?:ance)?|on[ -]?site|in[ -]?office|office|based|'
                               r'(?:reside|live|residing|living)\s+(?:in|within|near)|'
                               r'be\s+(?:(?:an?|current|legal|permanent)\s+)?residents?\s+(?:of|in)|'
                               r'residen(?:ce|cy)\s+in)\b', sentence, re.I)
        if mandatory and attendance:
            if re.search(r'\b(?:not|never)\s+(?:\w+\s+){0,2}(?:required|expected|mandatory)\b|'
                         r'\b(?:no|without)\s+(?:\w+\s+){0,3}(?:attendance|requirement)\b|'
                         r'\b(?:must|should|shall)\s+not\b|\b(?:required|expected)\s+not\s+to\b|'
                         r'\bnot\s+(?:to\s+)?(?:be\s+)?(?:based|attend|reside|live)\b', sentence, re.I):
                continue
            # The requirement's clause, not all offices previously mentioned.
            clause = sentence
            locations.append((clause, regions_named(clause)))
    return locations


def _offers_australian_alternative(clause):
    """An explicit Australian option prevents a foreign-only classification."""
    from pipeline.agentic.location import regions_named
    alternatives = re.split(r'\bor\b|\|', clause, flags=re.I)
    return len(alternatives) > 1 and any(regions_named(option) or re.search(r'\bAustralia\b|\bAU\b', option, re.I)
                                         for option in alternatives)


def _advertised_hours(text):
    """Return bounded weekly/fortnightly requirements without lowering total hours
    to a training component or an unrelated facility's opening hours.

    Ambiguous multiple figures are held by the caller; explicit alternatives are
    supported, and an inclusive range supplies its advertised minimum.
    """
    pattern = re.compile(r'\b(\d+(?:\.\d+)?)(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*hours?\s*(?:per|a|/)\s*(week|fortnight)\b', re.I)
    values = []
    for sentence in re.split(r'[;\n]|\.(?!\d)', text):
        matches = list(pattern.finditer(sentence))
        if not matches:
            continue
        if re.search(r'\b(?:cafeteria|reception|store|shop|facility|office)\s+(?:opens?|opening)\b', sentence, re.I):
            continue
        totals = []
        for match in matches:
            before = sentence[:match.start()]
            after = sentence[match.end():]
            if re.search(r'\b(?:with|including|includes?)\s*$', before, re.I) and re.search(r'\b(?:included|training|breaks?)\b', after, re.I):
                continue
            totals.append(float(match.group(1)) * (2 if match.group(2).casefold() == 'week' else 1))
        if totals:
            values.append(min(totals) if re.search(r'\bor\b', sentence, re.I) else max(totals))
    return values

def evaluate_eligibility(job: Mapping, *, policy: DecisionPolicy | None = _CURRENT,
                         ad_text: str | None = None, commute_km: float | None = None) -> EligibilityDecision:
    if policy is _CURRENT:
        from jobwatch import users
        from .policy import policy_for
        policy = policy_for(users.current())
    text = ad_text or ''
    # Supported-country scope is a product boundary, independent of a person's
    # Australia-wide or missing regional preferences. Only an actual attendance
    # or residency requirement establishes this restriction.
    for clause, _ in _onsite_locations(text):
        if re.search(r'\b(?:USA|United States|UK|United Kingdom|Canada|New Zealand)\b|\b(?-i:US)\b', clause, re.I) \
                and not _offers_australian_alternative(clause):
            return _result('excluded', 'outside_product_scope')
    title = str(job.get('title') or '')
    supplied = job.get('work_rights') or {}
    if not isinstance(supplied, Mapping):
        supplied = {}
    # Ad validation is independent of whether personal preferences are known.
    if supplied.get('quote') and supplied['quote'] not in text:
        return _result('held', 'verification_required', 'work_rights_quote')
    requirements = _requirements(text, supplied, title)
    if any(kind == 'unverified' for kind, _ in requirements):
        return _result('held', 'verification_required', 'work_rights_quote')
    rights = _rights(requirements, policy.work_rights if policy else {})
    pending = []
    if rights and rights.status == 'excluded':
        return rights
    if rights and rights.reason == 'verification_required':
        return rights
    if rights:
        pending.extend(rights.questions)
    if policy is not None:
        location = str(job.get('location') or '')
        remote = bool(job.get('remote')) or bool(re.search(r'\bremote|work from home\b', location, re.I))
        onsite = _onsite_locations(text)
        if onsite:
            remote = False
            # A mandatory location in full-ad evidence outranks generic metadata.
            location = ' | '.join(clause for clause, _ in onsite)
        if exclusion_hit(policy, family=job.get('role_family'), company=str(job.get('company') or ''),
                         title=title, location_text=location, remote=remote, hours=str(job.get('hours') or '')):
            return _result('excluded', 'policy_excluded')
        if remote and policy.remote_ok is False:
            return _result('excluded', 'remote_excluded')
        if remote:
            from jobwatch.models import is_australian
            if not is_australian(None, location):
                # A remote flag or generic work-rights boilerplate does not show
                # that the advertised remote arrangement is available in AU.
                pending.append('remote_work_location')
        from pipeline.agentic.location import location_verdict
        if policy.regions:
            verdict = location_verdict(location, frozenset(policy.regions), remote_fit=remote, remote_ok=policy.remote_ok)
            if verdict == 'outside':
                return _result('excluded', 'location_outside_scope')
            if verdict == 'unknown':
                pending.append('location')
            if onsite and any(not named for _, named in onsite):
                pending.append('onsite_location')
        if policy.max_commute_km is not None and not remote:
            if commute_km is None:
                pending.append('commute_distance')
            elif commute_km > policy.max_commute_km:
                return _result('excluded', 'commute_exceeded')
        level = job.get('seniority')
        if policy.seniority and level in _RANK and level not in policy.seniority:
            return _result('excluded', 'seniority_outside_scope')
        if policy.seniority and level not in _RANK:
            pending.append('seniority')
        from .contracts import KNOWN_FAMILIES, canonicalize_family
        if any(r.kind == 'family' for r in policy.exclusions) and canonicalize_family(job.get('role_family') or '') not in KNOWN_FAMILIES:
            pending.append('role_family')
        limit = policy.work_rights.get('hours_limit_per_fortnight')
        if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0:
            # A program preference has no hours-period evidence and cannot waive
            # a numeric limit. No title or employment label establishes exemption.
            stated = _advertised_hours(text)
            if stated and min(stated) > limit:
                return _result('excluded', 'hours_exceeded')
            if not stated or max(stated) > limit:
                pending.append('advertised_hours')
    for clause in re.split(r'[.;\n]', text):
        if re.search(r'\b(?:US|USA|United States|UK|United Kingdom|Canada|New Zealand)\s+(?:residents?\s+)?only\b', clause, re.I) \
                and not _offers_australian_alternative(clause):
            return _result('excluded', 'outside_product_scope')
    return _result('held', 'eligibility_unknown', *pending) if pending else _result('eligible', 'eligible')
