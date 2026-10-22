"""Deterministic safety and policy admission for agentic evaluations."""
from __future__ import annotations

import hashlib
import re

from jobwatch.candidate.contracts import TargetPolicy, canonicalize_family, excluded_families
from jobwatch.candidate.policy import DecisionPolicy, exclusion_hit
from jobwatch.candidate.person import full_time_programs_ok, hours_limit_per_fortnight
from jobwatch.reader import blocking_quote, rights_backstop, unrestricted_backstop
from pipeline.agentic.location import CAPITALS, cited_victoria_location, location_verdict, regions_named
from pipeline.agentic.contracts import (
    AgenticError, AgenticEvaluation, AgenticGateDecision, RunKey, SourceCitation,
)


def _hold(evaluation: AgenticEvaluation, reason: str) -> AgenticGateDecision:
    return AgenticGateDecision(route="hold", reason=reason,
                               global_score=evaluation.global_score, run_key=evaluation.run_key)


MAX_COMMUTE_KM = 50  # straight-line km from the person's home


def _archive(evaluation: AgenticEvaluation, reason: str) -> AgenticGateDecision:
    return AgenticGateDecision(route="archive", reason=reason,
                               global_score=evaluation.global_score, run_key=evaluation.run_key)


def _draft(evaluation: AgenticEvaluation) -> AgenticGateDecision:
    return AgenticGateDecision(route="draft", reason="eligible",
                               global_score=evaluation.global_score, run_key=evaluation.run_key)


def _verified(citation: SourceCitation | None, ad_text: str, ad_hash: str) -> bool:
    if citation is None:
        return False
    try:
        checked = SourceCitation.model_validate(citation.model_dump())
        actual = hashlib.sha256(ad_text.encode("utf-8")).hexdigest()
        return (checked.source_id in {"ad", "jd"} and checked.content_hash == actual == ad_hash
                and checked.quote in ad_text)
    except Exception:
        return False


def _family_from_archetype(archetype: str, program: bool) -> str:
    """The model sometimes leaves role_family 'unknown' while naming the archetype; read the family from its words.
    A word-to-family table is only a classification; whether the family is wanted is the person's policy."""
    a = (archetype or "").casefold()
    if re.search(r"accountant|accounting|tax|audit|finance|financial", a):
        return "finance_program" if program else "accounting"
    if re.search(r"data analyst|analytics|data", a):
        return "analytics_program" if program else "data_analyst"
    if re.search(r"accounts|administration|admin", a):
        return "business_program" if program else "back_office_admin"
    return "unknown"


def _is_program(title: str, ad_text: str, claimed: bool) -> bool:
    if not claimed:
        return False
    if re.search(r"\bintern\b", title, re.I):
        return True
    sample = f"{title}\n{ad_text}".casefold()
    return bool(re.search(r"\bgraduate\s+(?:program|programme|role|position)\b|"
                          r"\b(?:internship|intern program|vacation program|vacation programme|cadetship|cadet program)\b", sample))


def _full_time_exempt(title: str, ad_text: str) -> bool:
    """Graduate and vacation roles may be full-time when the person's profile allows it
    (work_rights.full_time_programs_ok): they start after study or run in a uni break, so the person's hours limit
    (work_rights.hours_limit_per_fortnight) does not bite. Not allowed unless the person says so."""
    if hours_limit_per_fortnight() is None or not full_time_programs_ok():
        return False
    if re.search(r"\b(?:graduate|vacation(?:er|ers)?|vacationer)\b", title, re.I):
        return True
    return bool(re.search(r"\b(?:graduate|vacation|summer\s+vacation)\s+(?:program|programme|intake|role|position)s?\b",
                          ad_text, re.I))


def _logistics(requirement, hours_exempt: bool) -> bool:
    """A requirement about how to apply, where or when to work, rather than what the candidate can do or is
    eligible for. Work rights, citizenship, clearances, licences and qualifications are never logistics."""
    text = " ".join(filter(None, [requirement.id, requirement.text,
                                  requirement.jd_signal.quote if requirement.jd_signal else ""]))
    if re.search(r"citizen|permanent[ _-]resid|right[ _-]to[ _-]work|work(?:ing)?[ _-]rights|visa|clearance|licen[cs]e|"
                 r"degree|qualif|certif|registration|police|working with children|WWCC", text, re.I):
        return False
    if re.search(r"\b(?:application[ _-]documents?|resume|r[ée]sum[ée]|\bCV\b|cover[ _-]letter|apply via|"
                 r"no[ _-]agency|agencies)\b", text, re.I):
        return True
    if re.search(r"\b(?:location|located|commute|office|hybrid|on[ _-]?site|in[ _-]office|based in)\b", text, re.I):
        return True
    # Owner 2026-10-19: unstated part-time hours are shown with a note, and soft traits are not hard blockers.
    if re.search(r"part[ _-]?time|days and (?:weekly )?hours|professionalism|integrity|adaptab|attitude|"
                 r"openness to learn|willing(?:ness)? to learn|temporary|contract (?:term|length)|assignment|commenc|start[ _-]date",
                 text, re.I):
        return True
    return hours_exempt and bool(re.search(r"full[ _-]?time|hours|availability|start[ _-]date|intake", text, re.I))


def _general_work_rights(requirement) -> bool:
    """A plain right-to-work requirement (not citizenship, permanent residency or a security clearance)."""
    text = " ".join(filter(None, [requirement.id, requirement.text,
                                  requirement.jd_signal.quote if requirement.jd_signal else ""]))
    return bool(re.search(r"right[ _-]to[ _-]work|work(?:ing)?[ _-]rights|visa", text, re.I)) and not re.search(
        r"citizen|permanent[ _-]resid|\bPR\b|clearance|baseline|NV1|NV2", text, re.I)


def _hours_signals(ad_text: str) -> tuple[bool, bool]:
    """Return (supports compatible hours, requires more than half the person's fortnight limit per week).
    No limit set: nothing is excessive."""
    limit = hours_limit_per_fortnight()
    weekly = limit / 2 if limit else None
    compatible = bool(re.search(r"\b(?:part[ -]time|casual|job[ -]share)\b", ad_text, re.I))
    excessive = False
    for match in re.finditer(
        r"\b(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\s*hours?\s*(?:per|a|/)\s*week\b",
        ad_text, re.I,
    ):
        minimum = float(match.group(1))
        if weekly is not None:
            compatible |= 0 < minimum <= weekly
            excessive |= minimum > weekly
    full_time = bool(re.search(r"\bfull[ -]time\b", ad_text, re.I))
    return compatible, weekly is not None and (excessive or (full_time and not compatible))


def _entry_signals(title: str, ad_text: str) -> tuple[bool, bool]:
    sample = title + "\n" + ad_text
    entry_term = r"(?:entry[ -]level|junior|graduate|intern(?:ship)?|trainee|cadet(?:ship)?)"
    entry_matches = re.finditer(
        rf"\b{entry_term}\b|"
        r"\bno\s+(?:prior\s+|previous\s+|work\s+)?experience\s+(?:is\s+)?(?:required|necessary)\b",
        sample, re.I,
    )
    # A mention denied by the ad is not affirmative entry-level evidence.
    # Keep the scope local so "experience is not required. Junior ..." still counts.
    entry = any(not re.search(
        r"\b(?:not|rather\s+than)\s+(?:(?:a|an)\s+)?"
        r"(?:suitable\s+for\s+(?:(?:a|an)\s+)?)?"
        rf"(?:{entry_term}\s+(?:or|and|nor)\s+(?:(?:a|an)\s+)?)*$",
        sample[max(0, match.start()-64):match.start()], re.I,
    ) for match in entry_matches)
    senior = bool(re.search(r"\b(?:senior|lead|principal|director|head of)\b", title, re.I))
    senior |= bool(re.search(
        r"\b(?:seeking|hiring|recruiting|looking for)\s+(?:a\s+|an\s+)?(?:senior|lead|principal)\b|"
        r"^\s*(?:senior|lead|principal)\s+\w+|"
        r"\b(?:senior|lead|principal)\s+\w+\s+(?:role|position)\b", ad_text, re.I,
    ))
    for match in re.finditer(
        r"\b(?:at least\s+|minimum(?:\s+of)?\s+)?(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*years?['’]?\s+"
        r"(?:of\s+)?(?:relevant\s+|professional\s+|industry\s+|commercial\s+)?experience\b", ad_text, re.I,
    ):
        tail = ad_text[match.end():match.end()+40]
        if int(match.group(1)) >= 2 and not re.match(r"\s*(?:is\s+)?(?:preferred|desirable|a bonus|optional)", tail, re.I):
            senior = True
    return entry, senior


def _rights_checks(evaluation: AgenticEvaluation, ad_text: str, title: str, *,
                   citizen_ok: bool = False) -> AgenticGateDecision | None:
    """The person-independent checks: a real job, and the ad's work-rights wording.
    `citizen_ok` is read by the policy path (Task 5); the legacy path never sets it."""
    facts = evaluation.facts
    if not facts.real_job:
        return _archive(evaluation, "hard_gate")

    rights = facts.work_rights
    quote_verified = bool(rights.quote and rights.quote in ad_text)
    if (rights.quote and not quote_verified) or (rights.requirement != "none_stated" and not rights.quote):
        return _hold(evaluation, "verification_required")
    quote_blocking = quote_verified and blocking_quote(rights.quote)
    rule = rights_backstop(ad_text, title) or unrestricted_backstop(ad_text, title)
    if quote_blocking or rule:
        return _archive(evaluation, "hard_gate")
    if rights.requirement in {"citizen_only", "citizen_or_pr", "clearance", "unrestricted_work_rights"}:
        return _hold(evaluation, "verification_required")
    if rights.quote and blocking_quote(rights.quote):
        return _hold(evaluation, "verification_required")
    if re.search(r"\b(?:requires? sponsorship|sponsorship required|sponsored applicants only)\b", ad_text, re.I):
        return _archive(evaluation, "hard_gate")
    return None


def _legacy_person_checks(evaluation: AgenticEvaluation, ad_text: str, title: str, policy: TargetPolicy,
                          commute_km: int | None) -> AgenticGateDecision | None:
    # legacy baseline; delete after the owner switches the policy flag to profile
    facts = evaluation.facts
    ad_hash = hashlib.sha256(ad_text.encode("utf-8")).hexdigest()
    # The person's region is Victoria: - any cited Victorian place is in scope, regional included.
    if evaluation.location_fit == "outside" and not (
            _verified(evaluation.location_evidence, ad_text, ad_hash)
            and cited_victoria_location(evaluation.location_evidence.quote)):
        return _archive(evaluation, "hard_gate")
    # A national program where the candidate nominates their office ("nominate your KPMG office location") is
    # open to a Melbourne office (2026-10-12 one-off task: KPMG Vacationer was held for having no place name).
    nominate_office = (evaluation.location_fit == "unknown" and _is_program(title, ad_text, facts.program)
                       and _verified(evaluation.location_evidence, ad_text, ad_hash)
                       and re.search(r"\bnominate\b[^.\n]{0,40}\b(?:office|location|city)\b",
                                     evaluation.location_evidence.quote, re.I))
    if evaluation.location_fit not in {"melbourne", "remote_accessible", "outside"} and not nominate_office:
        return _hold(evaluation, "insufficient_evidence")
    if not _verified(evaluation.location_evidence, ad_text, ad_hash):
        return _hold(evaluation, "insufficient_evidence")
    location_quote = evaluation.location_evidence.quote
    if evaluation.location_fit in {"melbourne", "outside"} and not cited_victoria_location(location_quote):
        return _hold(evaluation, "verification_required")
    if evaluation.location_fit == "remote_accessible" and not re.search(
        r"\b(?:remote|work from home|anywhere in Australia)\b", location_quote, re.I
    ):
        return _hold(evaluation, "verification_required")
    if re.search(r"\b(?:US|USA|United States|UK|United Kingdom|Canada|New Zealand)\s+(?:residents?\s+)?only\b|"
                 r"\bmust\s+(?:be\s+)?(?:based|reside|live)\s+in\s+(?:the\s+)?"
                 r"(?:US|USA|United States|UK|United Kingdom|Canada|New Zealand)\b", ad_text, re.I):
        return _archive(evaluation, "hard_gate")
    if evaluation.location_fit == "remote_accessible" and not re.search(
        r"\b(?:Australia|Australian|Melbourne|Victoria|worldwide|anywhere|globally)\b", location_quote, re.I
    ):
        return _hold(evaluation, "insufficient_evidence")
    onsite_interstate = re.search(
        r"\b(?:based|located|work|onsite|on-site|office)\b[^.\n]{0,100}\b(?:Sydney|Brisbane|Perth|Adelaide|Canberra|Hobart|Darwin)\b[^.\n]{0,60}\b(?:onsite|on-site|office|attendance|based)\b|"
        r"\b(?:Sydney|Brisbane|Perth|Adelaide|Canberra|Hobart|Darwin)\b[^.\n]{0,60}\b(?:onsite|on-site|office|attendance|based)\b",
        ad_text, re.I,
    )
    if onsite_interstate:
        return _archive(evaluation, "hard_gate")
    # Owner 2026-10-15: "50 km is fine" - a Victorian job further than 50 km from home is archived unless remote.
    if commute_km is not None and commute_km > MAX_COMMUTE_KM and evaluation.location_fit != "remote_accessible":
        return _archive(evaluation, "hard_gate")

    family = canonicalize_family(facts.role_family)
    if family == "unknown":
        family = _family_from_archetype(evaluation.archetype, _is_program(title, ad_text, facts.program))
    if family in excluded_families() or family not in policy.allowed_families:
        return _archive(evaluation, "policy_excluded")

    program = _is_program(title, ad_text, facts.program)
    entry_evidenced, senior_evidenced = _entry_signals(title, ad_text)
    if senior_evidenced:
        return _archive(evaluation, "hard_gate")
    if facts.seniority in {"mid", "senior"}:
        return _archive(evaluation, "hard_gate")
    if facts.min_years is not None and facts.min_years >= 2:
        return _archive(evaluation, "hard_gate")
    # Owner 2026-10-19: an ad that does not say entry/junior/graduate passes when it asks for under 2 years and is not
    # senior (both archived above); the card says "level not stated".
    if not entry_evidenced and re.search(r"\bnot\b[^.]{0,40}\b(?:entry|junior)|rather than an? (?:entry|junior)",
                                         f"{title}\n{ad_text}", re.I):
        return _hold(evaluation, "insufficient_evidence")  # the ad says it is NOT entry level

    _, hours_excessive = _hours_signals(ad_text)
    ft_exempt = _full_time_exempt(title, ad_text)
    if hours_limit_per_fortnight() is not None:  # no limit set: hours never archive a job
        if hours_excessive and not ft_exempt:
            return _archive(evaluation, "hard_gate")
        if facts.hours == "full_time_only" and not ft_exempt:
            return _archive(evaluation, "hard_gate")
    # Owner 2026-10-19: an ad that does not state its hours is shown as Good with a "check the hours fit"
    # note (queries._ai_from_agentic), not held. Hours that are stated and too many are still archived above.
    return None


def _policy_checks(evaluation: AgenticEvaluation, ad_text: str, title: str, company: str,
                   dp: DecisionPolicy, commute_km: int | None) -> AgenticGateDecision | None:
    """Exclusions, location and commute from the person's confirmed decision policy.

    Reads no profile file and no Victoria constant: the regions, the commute limit and the exclusion rules all come
    from `dp`. The stored location_fit values 'melbourne' and 'outside' are ignored; only 'remote_accessible' and
    the verified quote matter. TargetPolicy.allowed_families is not consulted. Level and hours follow in Task 5."""
    facts = evaluation.facts
    ad_hash = hashlib.sha256(ad_text.encode("utf-8")).hexdigest()
    verified = _verified(evaluation.location_evidence, ad_text, ad_hash)
    quote = evaluation.location_evidence.quote if verified else ""
    remote_fit = evaluation.location_fit == "remote_accessible"

    # (1) exclusion rules
    if exclusion_hit(dp, family=canonicalize_family(facts.role_family), company=company, title=title,
                     location_text=quote, remote=remote_fit, hours=facts.hours) is not None:
        return _archive(evaluation, "policy_excluded")

    # (2) location, only when the policy has a place to hold the job to
    regions = frozenset(dp.regions)
    verdict = None
    if regions or dp.max_commute_km is not None or any(r.kind == "location" for r in dp.exclusions):
        if not verified:
            return _hold(evaluation, "insufficient_evidence")
        verdict = location_verdict(quote, regions, remote_fit=remote_fit, remote_ok=dp.remote_ok)
        if verdict == "outside":
            return _archive(evaluation, "hard_gate")
        if verdict == "unknown":
            # A national program where the candidate nominates their office is open to the person's office.
            nominate_office = (evaluation.location_fit == "unknown" and _is_program(title, ad_text, facts.program)
                               and re.search(r"\bnominate\b[^.\n]{0,40}\b(?:office|location|city)\b", quote, re.I))
            if not nominate_office:
                return _hold(evaluation, "insufficient_evidence")

    # (3) the product is Australia-only
    if re.search(r"\b(?:US|USA|United States|UK|United Kingdom|Canada|New Zealand)\s+(?:residents?\s+)?only\b|"
                 r"\bmust\s+(?:be\s+)?(?:based|reside|live)\s+in\s+(?:the\s+)?"
                 r"(?:US|USA|United States|UK|United Kingdom|Canada|New Zealand)\b", ad_text, re.I):
        return _archive(evaluation, "hard_gate")

    # (4) on-site in a capital outside the person's regions
    others = [name for name, state in CAPITALS.items() if state not in regions]
    if regions and others:
        names = "|".join(others)
        keyword = r"(?:onsite|on-site|office|attendance|based)"
        pattern = (rf"\b(?:based|located|work|onsite|on-site|office)\b[^.\n]{{0,100}}\b(?:{names})\b[^.\n]{{0,60}}\b{keyword}\b|"
                   rf"\b(?:{names})\b[^.\n]{{0,60}}\b{keyword}\b")
        for match in re.finditer(pattern, ad_text, re.I):
            if not regions_named(match.group(0)) & regions:
                return _archive(evaluation, "hard_gate")

    # (5) commute: no default distance, the limit is the person's own
    if (dp.max_commute_km is not None and commute_km is not None and commute_km > dp.max_commute_km
            and verdict != "remote"):
        return _archive(evaluation, "hard_gate")
    return None


def decide(
    evaluation: AgenticEvaluation,
    *,
    ad_text: str,
    title: str = "",
    policy: TargetPolicy,
    captured_complete: bool = True,
    expected_run_key: RunKey | None = None,
    evidence_bundle=None,
    commute_km: int | None = None,
    decision_policy: DecisionPolicy | None = None,
    company: str = "",
) -> AgenticGateDecision:
    """Validate and route an evaluation using deterministic checks only.

    Public errors intentionally carry only fixed codes; malformed nested inputs never leak
    validation payloads or source text.
    """
    valid = True
    try:
        if type(evaluation) is not AgenticEvaluation or type(policy) is not TargetPolicy:
            valid = False
        else:
            evaluation = AgenticEvaluation.model_validate(evaluation.model_dump())
            policy = TargetPolicy.model_validate(policy.model_dump())
            if expected_run_key is not None:
                if type(expected_run_key) is not RunKey:
                    valid = False
                else:
                    expected_run_key = RunKey.model_validate(expected_run_key.model_dump())
        if decision_policy is not None:
            if type(decision_policy) is not DecisionPolicy:
                valid = False
            else:
                decision_policy = DecisionPolicy.model_validate(decision_policy.model_dump())
        if (type(ad_text) is not str or type(title) is not str or type(company) is not str
                or type(captured_complete) is not bool):
            valid = False
    except Exception:
        valid = False
    if not valid:
        raise AgenticError("invalid_gate_input") from None

    if not captured_complete or not ad_text:
        return _hold(evaluation, "insufficient_evidence")

    ad_hash = hashlib.sha256(ad_text.encode("utf-8")).hexdigest()
    if ad_hash != evaluation.run_key.ad_hash or ad_hash != evaluation.requirements.ad_hash:
        return _hold(evaluation, "verification_required")
    if expected_run_key is not None and expected_run_key != evaluation.run_key:
        return _hold(evaluation, "verification_required")

    for requirement in evaluation.requirements.requirements:
        if requirement.jd_signal and not _verified(requirement.jd_signal, ad_text, ad_hash):
            return _hold(evaluation, "verification_required")
    requirements = {r.id: r for r in evaluation.requirements.requirements}
    unverified_blocker = False
    for match in evaluation.matches:
        if any(c.source_id not in {"master_resume.md", "cv.md", "profile.yaml"} for c in match.evidence):
            return _hold(evaluation, "verification_required")
        if match.match == "partial" and not match.evidence:
            return _hold(evaluation, "verification_required")
        if match.match in {"missing", "not_applicable"} and match.evidence:
            return _hold(evaluation, "verification_required")
        if match.match == "not_applicable" and requirements[match.requirement_id].importance in {"critical", "high"}:
            return _hold(evaluation, "verification_required")
        if requirements[match.requirement_id].blocker and match.match != "strong":
            # "missing" means not demonstrated, not proven incompatible.
            # Preserve confirmed policy exclusions below before holding unknowns.
            if _logistics(requirements[match.requirement_id], _full_time_exempt(title, ad_text)):
                # Logistics are not candidate gaps (2026-10-12: Sol marked "application documents", "location" and
                # "full time" as blockers on Morrows). Jobwatch writes the CV and letter itself, and location and
                # hours have their own rules below; graduate/vacation roles may bypass the hours limit (see _full_time_exempt).
                continue
            if (match.match == "partial" and match.evidence and _full_time_exempt(title, ad_text)
                    and _general_work_rights(requirements[match.requirement_id])):
                # Graduate/vacation roles bypass the visa hours limit when the profile says so, so a general right-to-work
                # requirement met only "partially" by the person's visa does not hold them. Citizenship, PR and
                # clearance demands are hard-gated elsewhere and never reach this line as a pass.
                continue
            unverified_blocker = True
    missing_candidate_evidence = bool(evaluation.matches) and not any(
        m.match in {"strong", "partial"} and m.evidence for m in evaluation.matches
    )
    if evidence_bundle is not None:
        try:
            from jobwatch.candidate.evidence import verify_evidence_snapshot
            from jobwatch.candidate.assessment import verify_candidate_citations
            verify_evidence_snapshot(evidence_bundle)
            if evidence_bundle.bundle_hash != evaluation.run_key.evidence_hash:
                raise ValueError
            for match in evaluation.matches:
                verify_candidate_citations(match.evidence, evidence_bundle)
                if match.judgment is not None:
                    verify_candidate_citations(match.judgment.contradiction_evidence, evidence_bundle)
                    if not set(match.judgment.reviewed_evidence_ids) <= {item.id for item in evidence_bundle.items}:
                        raise ValueError
        except Exception:
            return _hold(evaluation, "verification_required")

    early = _rights_checks(evaluation, ad_text, title)
    if early is None and decision_policy is None:
        early = _legacy_person_checks(evaluation, ad_text, title, policy, commute_km)
    elif early is None:
        early = _policy_checks(evaluation, ad_text, title, company, decision_policy, commute_km)
    if early is not None:
        return early


    if unverified_blocker or missing_candidate_evidence:
        return _hold(evaluation, "insufficient_evidence")

    # Owner 2026-10-19: an employer the AI could not verify is shown with an "employer not verified" note, not held.
    if evaluation.legitimacy == "suspicious":
        return _hold(evaluation, "verification_required")

    # Thresholds tuned on real jobs: a role scoring overall 3.0 is worth applying to only when it also fits the
    # jobs the person wants (north_star >= 3); a 3.0 whose "fits the jobs you want" is 2/5 is not.
    if evaluation.global_score < 3.0 or evaluation.dimensions["north_star"].score < 3:
        return _archive(evaluation, "score_below_threshold")
    return _draft(evaluation)
