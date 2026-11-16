"""Ad-text helpers for the eligibility gate and the screening nodes: work-rights phrase scanning, prompt-injection defanging, sponsored-ad detection and not-target kinds.

Moved here from the retired AI ad reader (jobwatch/reader.py), unchanged."""
from __future__ import annotations

import html
import json
import re
import unicodedata
from bisect import bisect_right


# why a not_wanted job is not a target, judged by the model from the whole ad (the board groups the hidden jobs by it).
# too_senior = a family the person pursues, at a level they cannot take yet: hidden as "too_senior", not "not_target".
# This is only the vocabulary for naming a reason. WHICH kinds the person does not want is theirs:
# interests_and_criteria.yaml target_roles.not_wanted (see person_prefs()).
NOT_TARGET_KINDS = ("shop_retail", "hospitality", "events_venue", "customer_service", "reception", "sales", "too_senior",
                    "engineering_it", "health_care_teaching", "trades_manual", "other_field")

KIND_GUIDE = """- "not_target_kind" (only for "not_wanted"): the MAIN reason, by the day-to-day work: shop_retail (shop floor, checkout,
  pharmacy or supermarket), hospitality (cafe, bar, kitchen, fast food), events_venue, customer_service (customer service,
  contact or call centre as the main job), reception (front desk), sales (selling, business development, account
  management), too_senior (the work itself is a pursued or adjacent family, but the level is
  senior, lead or manager, or it needs years of experience the candidate does not have), engineering_it (software, AI,
  engineering, IT support), health_care_teaching (clinical, care, disability, childcare, teaching), trades_manual (trades,
  warehouse, driving, cleaning, security), other_field (any other profession: marketing, HR, legal, claims, research, policy...).
"""

# invisible characters: zero-width, soft hyphen, bidi, variation selectors and the Unicode tag block (U+E0000-E007F), which spells
# ASCII in characters a person cannot see but a model can read
_ZERO_WIDTH = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\ufe00-\ufe0f\U000e0000-\U000e007f\U000e0100-\U000e01ef]")

_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")

_ESCAPE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|([<>/]))")

# letters of the fence words that other alphabets (Cyrillic, Greek, small capitals) draw the same
_LOOKALIKES = {
    "a": "\u0430\u0251\u03b1\u1d00", "d": "\u0501\u1d05", "p": "\u0440\u03c1\u1d18", "r": "\u0433\u0280",
    "o": "\u043e\u03bf\u0585\u1d0f", "f": "\u0493\u0192\ua730", "i": "\u0456\u0131\u026a\u03b9",
    "l": "\u04cf\u029f", "e": "\u0435\u04bd\u03b5\u1d07", "c": "\u0441\u03f2\u1d04", "v": "\u0475\u03bd\u1d20"}

def _fence_regex() -> re.Pattern:
    word = lambda w: "".join(f"[{c}{_LOOKALIKES.get(c, '')}]" for c in w)
    return re.compile(r"[<\uff1c][\s/]{0,40}(?:" + "|".join(word(w) for w in ("ad", "profile", "cv")) + r")\b[^>\uff1e\n]{0,40}[>\uff1e]?",
                      re.I)

_FENCE = _fence_regex()

def _unescape_once(t: str) -> str:
    t = _ENTITY.sub(lambda m: html.unescape(m.group(0)), unicodedata.normalize("NFKC", _ZERO_WIDTH.sub("", t)))
    return _ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)) if (m.group(1) or m.group(2)) else m.group(3), t)

def _defang(s) -> str:
    """Untrusted text must not be able to close or open the <ad>, <profile> or <cv> fence, however the tag is spelled: zero-width
    characters, NFKC look-alikes (full-width, Cyrillic and Greek letters), HTML entities and backslash escapes are resolved first
    (until nothing changes, at most six layers deep), then every fence tag is replaced."""
    t = str(s or "")
    for _ in range(6):
        n = _unescape_once(t)
        if n == t:
            break
        t = n
    return _FENCE.sub("[tag]", t)

_PROFILE_FALLBACK = (
    "No profile has been set up for this candidate yet. Judge the ad only by its own requirements and by the CV if one is "
    "given. Do not assume a field, level, place or work rights; where the profile is silent, say so in the evidence.")

def person_prefs() -> dict:
    """Only confirmed evidence facts may describe a person's preferences."""
    from . import users
    from .candidate.policy import policy_for
    dp = policy_for(users.current())
    return {'not_wanted': [r.value for r in dp.exclusions] if dp else [],
            'programs_wanted': bool(dp and dp.work_rights.get('full_time_programs_ok') is True),
            'work_rights': str(dp.work_rights) if dp else '', 'reply_style': ''}

def load_interest() -> str:
    from . import users
    from .candidate.policy import policy_for
    dp = policy_for(users.current())
    if dp is None:
        return ''
    framing = dp.model_dump(mode='json', exclude={'policy_hash', 'profile_version'})
    framing['exclusions'] = [{'kind': r.kind, 'value': r.value} for r in dp.exclusions]
    return _defang(str(framing))

# Citizenship / PR / clearance wording. A pattern only FINDS a phrase; _scan decides per clause whether it counts.
_CIT = r"citizens?(?!\s+(?:engagement|science|panel|jury|participation|services?|centric|charter|advice|forum|assembl\w+))"

_PLACE = r"(?:australian|aus|aust|nz|new\s+zealand)"

_JOIN = r"(?:/|,|&|\+|or|and)"

_NATL = r"nationals?(?=\s*(?:$|[.,;:)]|only\b|required\b|mandatory\b|essential\b|to\b|who\b|with\b|and\b|or\b))"

_CITIZEN_PATTERNS = [re.compile(p, re.I) for p in (
    rf"\b{_PLACE}(?:\s*{_JOIN}\s*{_PLACE}){{0,4}}\s+(?:{_CIT}|citizenship|{_NATL})",
    rf"\b{_CIT}\s+(?:of|from)\s+(?:australia|new\s+zealand)\b",
    rf"\b(?:{_CIT}|citizenship)\s*{_JOIN}\s*(?:prs?\b|permanent\s+resid)",
    rf"\b(?:prs?|permanent\s+residen(?:t|ts|cy|ce))\s*{_JOIN}\s*(?:{_CIT}|citizenship)",
    r"\bprs?\s+(?:holders?|only|required|status|essential|mandatory)\b",
    r"\b(?:australian|aus|aust)\s+(?:prs?\b|permanent\s+residen\w+)",
    r"\bpermanent\s+residen(?:cy|ce)\b",
    r"\bpermanent\s+resident\s+(?:status|only|of\s+australia|visa|required|holders?)\b",
    r"\b(?:be|hold|holding|being|as|are)\s+(?:an?\s+)?(?:australian\s+)?permanent\s+residents?\b",
    rf"\b(?:must|need(?:s)?\s+to|required\s+to|have\s+to|should)\b[^.;\n]{{0,30}}?\b(?:be|hold|have|possess|obtain|being|holding)\s+"
    rf"(?:(?:an?|the|current|valid|full|australian|aus|aust|nz|new|zealand|or|and|/)\s+){{0,8}}(?:{_CIT}|citizenship|{_NATL}|prs?|permanent\s+residen\w+|{_PLACE}\s+passports?)\b",
    r"\bcitizenship\b[^.;\n]{0,25}\b(?:is|are|will\s+be)\b[^.;\n]{0,20}\b(?:requirement|required|mandatory|essential|necessary|needed|a\s+must)\b",
    r"\bcitizenship\s*[:\-–]?\s*\(?\s*(?:essential|required|mandatory|compulsory|necessary|a\s+must)\b",
    rf"\bcitizenship\s*:\s*\(?\s*{_PLACE}\b",
    rf"\b{_PLACE}\s+passport\s+holders?\b|\b{_PLACE}\s+passports?\s+(?:only|required|essential|mandatory)\b",
    r"\b(?:proof|evidence)\s+of\s+(?:australian\s+)?(?:citizenship|permanent\s+residen\w+)\b",
    r"\b(?:australian|aus|aust)\s+residen(?:t|ts|cy|ce)\b[^.;\n]{0,40}?\b(?:only|required|mandatory|essential|status|citizen\w*)\b",
    r"\bonly\s+(?:australian\s+)?residents?\s+(?:with|who|of)\b",
)]

# a clearance, vetting, APS or EL requirement is closed to the owner whatever else the sentence says: no visa alternative cancels it
_CLEARANCE_PATTERNS = [re.compile(p, re.I) for p in (
    r"\b(?:negative|positive)\s+vetting\b",
    r"\bsecurity\s+(?:vetting|clearance)\b",
    r"\bbaseline\s+(?:security\s+)?(?:vetting|clearance)\b",
    r"\bnv\s*-?\s*[12]\b",
    r"\bpv\s+(?:clearance|vetting)\b",
    r"\bagsva\b",
    r"\btop\s+secret\b",
    r"\bcommonwealth\s+(?:government|public\s+(?:service|sector)|department|agency|entity|employee)\b"
    r"(?!\s+(?:funded|funding|grants?|programs?|legislation|regulations?|rebates?|benefits?|supported|clients?|customers?))",
    r"\bpublic\s+service\s+act\s+1999\b",
    r"\baustralian\s+public\s+service\b",
    r"\baps\s*(?:level\s*)?[1-6]\b",
    r"\bel\s?[12]\b(?!\s+(?:forklift|licen[cs]e|truck|class|certificate|tickets?|permits?|reporting))",
    r"\bexecutive\s+level\s*[12]\b",
    r"\bsenior\s+executive\s+service\b",
)]

_CLEARANCE_SET = frozenset(_CLEARANCE_PATTERNS)

_RW = r"(?:right\s+to\s+work|work(?:ing)?\s+rights?)"

_NOLIM = r"(?:restrictions?|limitations?|limits?|conditions?)"

_UNRESTRICTED_PATTERNS = [re.compile(p, re.I) for p in (
    r"\b(?:unrestricted|unlimited)\b[^.;\n]{0,25}\b(?:work|working|rights?)\b",
    r"\bright\s+to\s+work\s+in\s+australia\s+without\s+(?:any\s+)?(?:visa\s+)?restrictions?\b",
    r"\bwork(?:ing)?\b[^.;\n]{0,40}\bwithout\s+(?:any\s+)?(?:visa\s+|work\s+)?restrictions?\b",
    r"\bno\s+(?:(?:visa|work|working)\s+){1,2}(?:restrictions?|conditions?|limitations?)\b",
    r"\bfree\s+(?:of|from)\s+(?:any\s+)?(?:(?:visa|work|working)\s+)*(?:restrictions?|conditions?|limitations?)\b",
    r"\b(?:cannot|can\s?not|can't|must\s+not|should\s+not|not)\s+(?:have|hold|be\s+subject\s+to)\s+any\s+(?:visa|work|working)\s+"
    r"(?:conditions?|restrictions?|limitations?)\b",
    rf"\b{_RW}\b[^.;\n]{{0,40}}?\b(?:with|and|having|but)\s+no\s+(?:(?:visa|work|working|any)\s+){{0,2}}{_NOLIM}\b",
    rf"\b{_RW}\b[^.;\n]{{0,40}}?\bwithout\s+(?:any\s+)?(?:(?:visa|work|working)\s+)*{_NOLIM}\b",
    rf"\bno\s+(?:(?:visa|work|working|any)\s+)*{_NOLIM}\s+(?:on|to|upon|attached\s+to|applying\s+to)\s+(?:your\s+|their\s+|the\s+|a\s+)?"
    r"(?:right\s+to\s+work|work(?:ing)?\s+rights?|ability\s+to\s+work|work\s+in\s+australia)\b",
    rf"\b{_RW}\b\s*[:\-–]?\s*(?:unrestricted|unlimited)\b",
    rf"\bwithout\s+(?:any\s+)?(?:(?:visa|work|working)\s+)+{_NOLIM}\b",
    r"\b(?:must\s+not|cannot|can\s?not|can't|should\s+not|not)\s+(?:be\s+)?(?:on|holding|hold|have|having)\s+(?:an?\s+)?(?:\w+\s+){0,2}visa\b"
    rf"[^.;\n]{{0,25}}\b(?:work|working|visa)\s+{_NOLIM}\b",
)]

# the last branch starts only at the first space of a run: an unanchored `\s+` makes a long run of spaces quadratic
_HARD_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'•*\-])|[\n\r;•·▪●◦]+|(?<!\s)\s+(?:but|however|although|though|whereas|except)\b[,\s]*", re.I)

_LINE_SEPS = re.compile("[\u2028\u2029\x85]")

_SPACE_RUN = re.compile(r"[^\S\n\r]+")

_CLAUSE_BREAK = re.compile(r"(?<!\d),|,(?!\d)|:|\(|\)|\s[-–—]\s")

# equal-opportunity boilerplate and "not required" phrases: they cancel a hit only inside the clause they stand in
_EQUAL_OPP = re.compile(
    r"without\s+regard\s+to|regardless\s+of|irrespective\s+of|\bnot\s+(?:be\s+)?(?:a\s+)?(?:requirement|required|necessary|essential|"
    r"mandatory|barrier|prerequisite)\b|\bno\s+(?:need|requirement)\b|\bnot\s+need\b|\bneed\s+not\b|\bdo(?:es)?\s+not\s+require\b|"
    r"\bno\s+(?:(?!(?:and|but|so|as|thus|hence|therefore|however|because|while)\b)\w+\s+){0,5}"
    r"(?:(?:is|are|will\s+be)\s+)?(?:required|needed|necessary|essential|mandatory)\b|"
    r"\bequal\s+opportunity\b|\bdiscriminat\w*|\bwelcome[sd]?\s+(?:applications|applicants)\b", re.I)

_CUE = re.compile(r"\b(?:must|only|requires?|required|requirement|mandatory|essential|eligib\w*|exclusively|compulsory|"
                  r"necessary|need(?:s|ed)?\s+to|obligatory)\b", re.I)

_PREFER = re.compile(r"\b(?:prefer\w*|desirable|desired|advantageous|an\s+advantage|highly\s+regarded|"
                     r"highly\s+valued|beneficial|nice\s+to\s+have|a\s+plus|would\s+be\s+an?\s+asset|favourable|"
                     r"(?:may|will|can)\s+be\s+given\s+(?:preference|priority)|(?:preference|priority)\s+(?:may|will|can)\s+be\s+given)\b", re.I)

# a check that is not a security clearance: the phrase itself is exempt, a real clearance named next to it still counts
_NOT_CLEARANCE = re.compile(r"\b(?:asic|msic)\b(?:\s+(?:security\s+)?(?:clearance|vetting|check|card))?|"
                            r"\b(?:national\s+)?police\s+(?:check|clearance|vetting)s?|\bworking\s+with\s+children(?:\s+check)?", re.I)

# an alternative that lets visa or work-rights holders in. Only a visa or work-rights phrase that IS the alternative counts
# ("or hold a valid visa"); the same words after "and" or "with" are the ordinary work-rights condition on top of citizenship.
_ADMIT_TERM = (r"(?:visas?|work(?:ing)?\s+(?:rights?|permits?|authori[sz]ations?|entitlements?)|right\s+to\s+work|"
               r"temporary\s+residents?|working\s+holiday(?:\s+makers?)?|(?:visa|permit)\s+holders?)")

_ADMIT_MOD = r"(?:valid|current|appropriate|relevant|temporary|full|unrestricted|equivalent|suitable|legal|lawful|other|work|working)"

_ADMIT_HOLDERS = (r"(?:visa\s+holders?|temporary\s+(?:visa\s+)?(?:holders?|residents?)|working\s+holiday(?:\s+makers?)?|"
                  r"international\s+students?|holders\s+of\s+(?:an?\s+)?(?:valid\s+)?(?:work\s+)?visas?)")

# the holder noun must be a DIRECT alternative: a separator, at most one of these filler words, then the noun. "and help visa
# holders" or "and enjoy supporting international students" is a duty, not an alternative.
_ADMIT_FILLER = r"(?:valid|eligible|other|temporary|current|relevant|appropriate|all|any|those)"

_ADMIT_SEP = r"(?:\b(?:and|or|alongside|plus|including|also|as\s+well\s+as)\b|,|/|&)"

# a visa that is a topic of the job ("or have a visa processing background"), not a status the applicant holds
_ADMIT_TOPIC = (r"(?!\s+(?:process\w*|applications?|officers?|cases?|claims?|assess\w*|knowledge|experience|background|"
                r"compliance|advice|agents?|consult\w*|migration))")

_ADMIT = [re.compile(p, re.I) for p in (
    rf"\bor\s+(?:(?:be\s+)?(?:hold(?:ing)?|have|having|on|with|possess(?:ing)?)\s+|(?:those|people|persons|candidates|applicants)\s+"
    rf"(?:with|on|holding|who\s+(?:hold|have))\s+)?(?:(?:an?|the)\s+)?(?:{_ADMIT_MOD}\s+)*{_ADMIT_TERM}{_ADMIT_TOPIC}",
    rf"{_ADMIT_SEP}(?:\s*{_ADMIT_SEP}){{0,2}}\s*(?:{_ADMIT_FILLER}\s+)?{_ADMIT_HOLDERS}",
    rf"\b{_ADMIT_TERM}\w*\s*(?:holders?)?\s*,?\s*\bor\b\s*(?:be\s+|are\s+)?(?:an?\s+)?(?:australian|aus|aust|nz|new\s+zealand|citizens?|prs?\b|permanent|holding|hold)",
    rf"\b(?:visa\s+holders?|temporary\s+(?:visa\s+)?(?:holders?|residents?)|working\s+holiday(?:\s+makers?)?)\s*(?:,|/|&|\band\b|\bor\b)\s*"
    rf"(?:(?:and|or)\s+)?(?:(?:australian|aus|aust|nz|new\s+zealand)\s+)*(?:citizens?|prs?\b|permanent)",
)]

_ADMIT_NEG = re.compile(
    r"\b(?:not|no|nor|never|cannot|can't|unable|without|ineligible|excluding|excluded|exclude|except|unless)\b[^.;\n]{0,40}"
    r"\b(?:visa|work|temporary|sponsor|permit)\w*|\b(?:visa|work(?:ing)?\s+rights?|temporary)\w*\b[^.;\n]{0,50}"
    r"\b(?:not|cannot|can't|ineligible|excluded|unable|won't)\b", re.I)

# "appointment to an ongoing role is only available to a citizen": the ongoing role is restricted, a casual or fixed-term one may not be
_ONG = r"(?:ongoing|continuing|permanent(?!\s+resid))"

_ONG_ROLE = re.compile(
    rf"\b{_ONG}(?:\s*(?:/|,|or|and|&)\s*{_ONG})?\s+(?:(?:full|part)[\s-]?time\s+)?"
    r"(?:roles?|positions?|appointments?|employment|vacanc(?:y|ies)|jobs?|opportunit(?:y|ies)|offers?|basis|status|contracts?)\b|"
    rf"\bappointments?\s+(?:to|on|in)\s+(?:an?\s+|the\s+)?{_ONG}\b", re.I)

_ONG_CUE = re.compile(r"\b(?:only|exclusively|restricted\s+to|limited\s+to|reserved\s+for|open\s+to|available\s+(?:only\s+)?to|"
                      r"offered\s+(?:only\s+)?to)\b", re.I)

_THIS_ONG = re.compile(rf"\b(?:this|the\s+advertised|our)\s+(?:\w+\s+){{0,2}}{_ONG}\b", re.I)

_ONG_SAYS = re.compile(rf"\(\s*{_ONG}\s*\)|\b(?:employment|work|job|position)\s+type\s*[:\-]?\s*{_ONG}\b|\b{_ONG}\s+only\b", re.I)

_SOFTER = re.compile(r"\b(?:casual|temporary|fixed[\s-]?term|contract(?:ors?)?|non[\s-]?ongoing)\b", re.I)

_SOFTER_ALSO = re.compile(
    r"\b(?:casual|temporary|fixed[\s-]?term|contract(?:ors?)?|non[\s-]?ongoing)\b[^.;\n]{0,100}?\b(?:require[sd]?|need(?:s|ed)?|only|"
    r"restricted|limited)\b[^.;\n]{0,40}?\b(?:it|this|citizen\w*|prs?|permanent|residen\w+|clearance|the\s+same|too|also)\b", re.I)

_NEGATED_NEAR = re.compile(r"\b(?:not|no|never|without)\b|n't", re.I)

def _segments(text: str):
    # every kind of Unicode space becomes one plain space (a run of em-spaces must not slip past the linear scans)
    t = _SPACE_RUN.sub(" ", _LINE_SEPS.sub("\n", text or ""))
    t = re.sub(r"\b(aus|aust)\.", r"\1", t, flags=re.I)             # "Aust. citizen" is not a sentence end
    for part in _HARD_BREAK.split(t):
        part = (part or "").strip(" \t*#>-")
        if part:
            yield part

def _clause_starts(seg: str) -> list[int]:
    """Offsets where each clause of the segment begins. Compute once per segment: bisect finds the clause of any position."""
    return [0] + [m.end() for m in _CLAUSE_BREAK.finditer(seg)]

def _clause_at(seg: str, pos: int, starts: list[int] | None = None) -> str:
    starts = starts if starts is not None else _clause_starts(seg)
    i = bisect_right(starts, pos) - 1
    end = starts[i + 1] if i + 1 < len(starts) else len(seg)
    return seg[starts[i]:end]

def _admits(seg: str, starts: list[int] | None = None) -> bool:
    """The segment offers the job to visa or work-rights holders as an alternative to citizenship/PR."""
    starts = starts if starts is not None else _clause_starts(seg)
    negated: dict[int, bool] = {}
    for rx in _ADMIT:
        for a in rx.finditer(seg):
            i = bisect_right(starts, max(0, a.end() - 1)) - 1
            if i not in negated:
                negated[i] = bool(_ADMIT_NEG.search(_clause_at(seg, starts[i], starts)))
            if not negated[i]:
                return True
    return False

def _clause_facts(clause: str) -> tuple[bool, bool, str | None]:
    """(negated, only preferred, the clause without its exempt checks or None): judged once per clause, whatever the hit count."""
    negated = bool(_EQUAL_OPP.search(clause)) and not _CUE.search(_EQUAL_OPP.sub(" ", clause))
    preferred = bool(_PREFER.search(clause)) and not _CUE.search(_PREFER.sub(" ", clause))
    exempt = _NOT_CLEARANCE.sub(" ", clause) if _NOT_CLEARANCE.search(clause) else None
    return negated, preferred, exempt

def _classify(facts: tuple[bool, bool, str | None], hit: str) -> str:
    """'hit' = a real requirement; otherwise why the phrase does not count: negated, preferred, other."""
    negated, preferred, exempt = facts
    if exempt is not None and re.search(r"clearance|security", hit, re.I) and not re.search(re.escape(hit), exempt, re.I):
        return "other"                          # the "clearance" is an ASIC, police or children's check
    if negated:
        return "negated"
    if preferred:
        return "preferred"
    return "hit"

def _scan_full(text: str, patterns, citizenship: bool = True) -> list[tuple[str, str]]:
    """Every phrase of `patterns` in the text as (status, whole segment): each phrase is judged inside its own clause. The clause
    breaks and the segment-wide facts are computed once per segment, so a stuffed ad costs linear time. `citizenship` = the
    patterns are citizenship/PR/clearance wording: an alternative for visa holders or an ongoing-role-only sentence changes
    the status (admit, ongoing_only) of a citizenship/PR hit only; a clearance, vetting, APS or EL hit and unrestricted work
    rights are never cancelled by such an alternative."""
    found: list[tuple[str, str]] = []
    for seg in _segments(text):
        hits = [(m.start(), m.group(0), rx in _CLEARANCE_SET) for rx in patterns for m in rx.finditer(seg)]
        if not hits:
            continue
        starts = _clause_starts(seg)
        facts: dict[int, tuple] = {}
        admit = ongoing = None
        for pos, hit, closed in hits:
            i = bisect_right(starts, pos) - 1
            if i not in facts:
                facts[i] = _clause_facts(_clause_at(seg, pos, starts))
            status = _classify(facts[i], hit)
            if status == "hit" and citizenship and not closed:
                if admit is None:
                    admit = _admits(seg, starts)
                if admit:
                    status = "admit"
                else:
                    if ongoing is None:
                        role, cue = _ONG_ROLE.search(seg), _ONG_CUE.search(seg)
                        ongoing = role.start() if role and cue else -1
                    if 0 <= ongoing < pos:
                        status = "ongoing_only"
            found.append((status, seg))
    return found

def _ongoing_hides(haystack: str, title: str, ongoing: set[str]) -> bool:
    """An ongoing-role-only sentence is a real requirement when the ad also says casual, temporary, fixed-term or contract roles need
    it, or when it mentions no such role and itself says the advertised job is ongoing or permanent. Otherwise the ad may be
    open to a casual role: the owner decides."""
    for m in _SOFTER_ALSO.finditer(haystack):
        if not _NEGATED_NEAR.search(m.group(0)):
            return True
    if _SOFTER.search(haystack):
        return False
    rest = " ".join(s for s in _segments(haystack) if s not in ongoing)
    return bool(re.search(_ONG, title or "", re.I) or any(_THIS_ONG.search(s) for s in ongoing) or
                _ONG_ROLE.search(rest) or _ONG_SAYS.search(rest))

def _resolve_ongoing(haystack: str, title: str, scanned: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], bool]:
    """(statuses, held): the ongoing-role-only sentences become hits when the ad confirms the requirement; otherwise `held` is true."""
    ongoing = {seg for s, seg in scanned if s == "ongoing_only"}
    hide = bool(ongoing) and _ongoing_hides(haystack, title, ongoing)
    return [("hit" if hide and s == "ongoing_only" else s, seg[:240]) for s, seg in scanned], bool(ongoing) and not hide

def _clean(v, n: int) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or "")).strip()[:n]

_NO_VALUES = {"", "false", "none", "null", "0", "no", "n/a", "nan"}

_SPONSORED_HREF = re.compile(r"[?&]sponsored=true\b|[?&]sp=sserp\b|/pagead/", re.I)

_PAID_KEYS = ("sponsored", "is_sponsored", "issponsored", "promoted", "is_promoted", "ispromoted", "paid", "is_paid", "ad", "is_ad",
              "isad", "promotion", "is_promotion", "featured", "is_featured", "isfeatured")

_PAID_WORDS = ("SPONSORED", "FEATURED", "PROMOTED", "PAID", "ADVERT", "AD")

def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in _NO_VALUES
    return bool(v)

def is_sponsored(raw_json: str | None) -> bool:
    """Paid placements. Seek: displayType 'promoted', isFeatured, jobAdType 'SPONSORED'. Jora: the card link carries its own
    flag (sponsored=true, sp=sserp). Any other source: a truthy sponsored/promoted/featured key or a paid listing_type."""
    try:
        d = json.loads(raw_json or "{}")
    except ValueError:
        return False
    if not isinstance(d, dict):
        return False
    sol = d.get("solMetadata") if isinstance(d.get("solMetadata"), dict) else {}
    if _truthy(d.get("isFeatured")) or d.get("displayType") == "promoted" \
            or str(sol.get("jobAdType") or "").upper() in ("SPONSORED", "FEATURED", "PROMOTED"):
        return True
    for key in ("href", "job_url", "job_url_direct", "url", "link"):
        if isinstance(d.get(key), str) and _SPONSORED_HREF.search(d[key]):
            return True
    if any(k.lower() in _PAID_KEYS and _truthy(v) for k, v in d.items()):
        return True
    if str(d.get("listing_type") or "").strip().upper() in _PAID_WORDS:
        return True
    for key in ("badges", "tags"):
        for item in d.get(key) if isinstance(d.get(key), list) else []:
            label = item.get("type") or item.get("label") if isinstance(item, dict) else item
            if str(label or "").strip().upper() in _PAID_WORDS:
                return True
    return False
