from __future__ import annotations

import hashlib
import logging
import re
from typing import Iterable, Literal

from pydantic import model_validator

from .contracts import KNOWN_FAMILIES, StrictFrozen, TargetPolicy, canonicalize_family, default_allowed_families, digest

log = logging.getLogger(__name__)


def default_policy() -> TargetPolicy:
    """The current person's target projection: every known family except the ones they do not want.
    The version string is stored in run keys, so it keeps its original identifier."""
    return TargetPolicy(version="owner-targets-v1", allowed_families=default_allowed_families())


# ----------------------------------------------------------------------------- decision policy from the confirmed profile
# Only evidence-basis facts count. A fact the person confirmed in {"kind", "value"} form becomes an exclusion rule;
# free text stays prompt text and becomes an open question. Every function here is pure and total on odd input.
Strategy = Literal["employment_first", "career_focus", "balanced"]
RULE_KINDS = ("family", "employer", "title_term", "location", "work_type")
WORK_TYPES = ("remote", "casual", "full_time", "part_time")
_FOCUS_MAX, _FOCUS_CHARS = 20, 200


class ExclusionRule(StrictFrozen):
    rule_id: str
    kind: Literal["family", "employer", "title_term", "location", "work_type"]
    value: str
    source_fact_id: str | None = None
    actor: Literal["person"] = "person"


class DecisionPolicy(StrictFrozen):
    profile_version: int
    strategy: Strategy
    focus: tuple[str, ...]
    exclusions: tuple[ExclusionRule, ...]
    home: dict | None
    max_commute_km: float | None
    remote_ok: bool | None
    work_rights: dict
    seniority: tuple[str, ...]
    open_questions: tuple[str, ...]
    policy_hash: str
    regions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _hash_matches(self):
        if self.policy_hash != digest(self.model_dump(mode="json", exclude={"policy_hash"})):
            raise ValueError("policy_hash_mismatch")
        return self


def _text(value) -> str:
    from . import projection
    try:
        return projection._text(value)
    except Exception:
        return ""


def _evidence(facts, *sections: str) -> list[dict]:
    return [f for f in facts if isinstance(f, dict) and f.get("section") in sections and f.get("basis") == "evidence"
            and f.get("value")]


def _status_kinds(text: str) -> set[str]:
    from . import intake
    return intake._kinds(text, intake._STATUS_VALUE)


def strategy_for(facts: Iterable[dict]) -> Strategy:
    """career_focus when the person states one; employment_first when they are unemployed (and not also employed)."""
    facts = [f for f in (facts or ()) if isinstance(f, dict)]
    if any(_text(f["value"]) for f in _evidence(facts, "career_focus")):
        return "career_focus"
    kinds: set[str] = set()
    for f in _evidence(facts, "employment_status"):
        kinds |= _status_kinds(_text(f["value"]))
    return "employment_first" if "unemployed" in kinds and "employed" not in kinds else "balanced"


def _short_hash(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}|{value}".encode("utf-8", "replace")).hexdigest()[:12]


def _work_type(value: str) -> str:
    return re.sub(r"[\s\-_]+", "_", value.casefold()).strip("_")


def rules_from_fact(fact: dict) -> list[ExclusionRule]:
    """One rule for an evidence exclusion given as {"kind", "value"}; nothing for free text or a malformed dict."""
    if not isinstance(fact, dict) or fact.get("section") != "exclusion" or fact.get("basis") != "evidence":
        return []
    v = fact.get("value")
    if not isinstance(v, dict):
        return []
    kind, value = v.get("kind"), v.get("value")
    if kind not in RULE_KINDS or not isinstance(value, str) or not value.strip():
        return []
    value = value.strip()
    if kind == "family":
        value = canonicalize_family(value)
        if value not in KNOWN_FAMILIES:
            return []
    elif kind == "work_type":
        value = _work_type(value)
        if value not in WORK_TYPES:
            return []
    fid = fact.get("id")
    fid = fid if isinstance(fid, str) and fid else None
    return [ExclusionRule(rule_id=f"{fid}:{kind}" if fid else _short_hash(kind, value), kind=kind, value=value,
                          source_fact_id=fid)]


_AUSTRALIA_WIDE = re.compile(r"\b(?:australia[- ]?wide|nationwide|anywhere\s+in\s+australia)\b", re.I)
_REMOTE_YES = re.compile(r"\bremote\b|\bwork(?:ing)?\s+from\s+home\b|\bwfh\b", re.I)
_REMOTE_NO = re.compile(r"\bno\s+remote\b|\bnot\s+remote\b|\bon-?site\s+only\b|\bin-?person\s+only\b", re.I)
_NEGATION = re.compile(r"\b(?:no|not|never|avoid|without|except|excluding|outside)\b", re.I)
_HOME = re.compile(r"(?:\blive[sd]?\s+in|\bbased\s+in|\breside[sd]?\s+in|\bhome\s*:)\s*(.+?)"
                   r"(?=\s*;|\s*\.(?:\s|$)|\s+and\s+|\s+but\s+|$)", re.I | re.S)
_KM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:km|kilomet\w+)", re.I)
_COMMUTE_WORDS = re.compile(r"\bcommute|\btravel|\bwithin\b|\bfrom\s+home\b", re.I)
_CITIZEN_NO = re.compile(r"\b(?:not|non|never|no)[\s-]+(?:an?\s+)?(?:australian\s+)?(?:citizen|permanent\s+resident|(?-i:PR))\b", re.I)
_CITIZEN_YES = re.compile(r"\baustralian\s+citizen\b|\bpermanent\s+resident\b", re.I)
_LADDER = ("entry", "junior", "mid", "senior")
_LEVELS = re.compile(
    r"\b(entry(?:[- ]level)?|graduates?|interns?(?:hips?)?|trainees?|cadets?|early[- ]career|junior|mid[- ]?level|"
    r"intermediate|senior|lead|principal|manager|director)\b", re.I)
_LEVEL_OF = {"entry": "entry", "graduate": "entry", "intern": "entry", "trainee": "entry", "cadet": "entry",
             "early": "entry", "junior": "junior", "mid": "mid", "intermediate": "mid", "senior": "senior",
             "lead": "senior", "principal": "senior", "manager": "senior", "director": "senior"}
_NEG_WORDS = frozenset({"no", "not", "never", "avoid", "without"})


def _clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[.;\n]+", text) if c.strip()]


def _regions_in(text: str) -> set[str]:
    from pipeline.agentic.location import regions_named
    found: set[str] = set()
    for clause in _clauses(text):
        if not _NEGATION.search(clause):          # "never in Sydney" is not a place the person will work
            found |= set(regions_named(clause))
    return found


def _levels_in(text: str) -> set[str]:
    out: set[str] = set()
    for m in _LEVELS.finditer(text):
        before = re.findall(r"[\w'-]+", text[:m.start()].casefold())[-3:]
        if _NEG_WORDS & set(before):
            continue
        word = re.match(r"[a-z]+", m.group(1).casefold()).group(0)
        key = next((k for k in _LEVEL_OF if word.startswith(k)), None)
        if key:
            out.add(_LEVEL_OF[key])
    return out


def _number(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    return float(v) if isinstance(v, (int, float)) and v > 0 and v == v and v != float("inf") else None


def _home(facts: list[dict]) -> dict | None:
    from pipeline.agentic.location import regions_named
    for f in facts:
        v = f["value"]
        place = None
        if isinstance(v, dict) and v.get("home"):
            h = v["home"]
            place = _text(h.get("place") if isinstance(h, dict) else h)
        elif not isinstance(v, dict) and (m := _HOME.search(_text(v))):
            place = m.group(1).strip(" ,")
        if place:
            place = place[:120]
            named = sorted(regions_named(place))
            return {"place": place, "state": named[0] if named else None, "country": "AU"}
    return None


def build_policy(approved: dict) -> DecisionPolicy:
    """The decision policy for one approved.json payload (pure)."""
    facts = [f for f in approved.get("facts", ()) if isinstance(f, dict)]
    strategy = strategy_for(facts)
    focus = tuple(dict.fromkeys(t[:_FOCUS_CHARS] for t in (_text(f["value"]) for f in _evidence(facts, "career_focus")) if t))
    focus = focus[:_FOCUS_MAX] if strategy == "career_focus" else ()

    exclusions, unresolved = [], []
    for f in _evidence(facts, "exclusion"):
        rules = rules_from_fact(f)
        exclusions += rules
        if not rules:
            unresolved.append(f.get("id") if isinstance(f.get("id"), str) and f.get("id") else _short_hash("exclusion", _text(f["value"])))

    spatial = _evidence(facts, "location", "constraint", "preference")
    regions: set[str] = set()
    anywhere = remote_yes = remote_no = False
    explicit_remote: bool | None = None
    for f in spatial:
        v = f["value"]
        text = _text(v)
        if isinstance(v, dict) and isinstance(v.get("regions"), (list, tuple, str)):
            listed = [v["regions"]] if isinstance(v["regions"], str) else list(v["regions"])
            regions |= {c for x in listed if isinstance(x, str) for c in _regions_in(x)}
        else:
            regions |= _regions_in(text)
        anywhere = anywhere or bool(_AUSTRALIA_WIDE.search(text))
        remote_yes = remote_yes or bool(_REMOTE_YES.search(text))
        remote_no = remote_no or bool(_REMOTE_NO.search(text))
        if isinstance(v, dict) and isinstance(v.get("remote_ok"), bool):
            explicit_remote = v["remote_ok"] if explicit_remote is None else (explicit_remote and v["remote_ok"])
    if anywhere:
        regions = set()
    remote_ok = False if remote_no or explicit_remote is False else (True if remote_yes or explicit_remote else None)
    home = _home(_evidence(facts, "location"))

    kms = []
    for f in _evidence(facts, "constraint", "location"):
        v = f["value"]
        if isinstance(v, dict) and _number(v.get("max_commute_km")) is not None:
            kms.append(_number(v["max_commute_km"]))
            continue
        for sentence in _clauses(_text(v)):
            if _COMMUTE_WORDS.search(sentence):
                kms += [float(m.group(1)) for m in _KM.finditer(sentence) if float(m.group(1)) > 0]
    max_commute_km = min(kms) if kms else None

    from . import projection
    work_rights = dict(projection._work_rights(approved))
    right_facts = _evidence(facts, "work_rights")
    citizen = None
    for f in right_facts:
        v = f["value"]
        if isinstance(v, dict) and isinstance(v.get("citizen_or_pr"), bool):
            citizen = v["citizen_or_pr"] if citizen is None else (citizen and v["citizen_or_pr"])
            continue
        text = _text(v)
        if _CITIZEN_NO.search(text):
            citizen = False
        elif _CITIZEN_YES.search(text) and citizen is None:
            citizen = True
    if citizen is not None:
        work_rights["citizen_or_pr"] = citizen

    levels: set[str] = set()
    for f in _evidence(facts, "preference", "career_focus", "constraint"):
        v = f["value"]
        if isinstance(v, dict) and v.get("seniority"):
            s = v["seniority"]
            levels |= _levels_in(" ".join(_text(x) for x in (s if isinstance(s, (list, tuple)) else [s])))
        else:
            levels |= _levels_in(_text(v))
    seniority = tuple(x for x in _LADDER if x in levels)

    questions = []
    if not _evidence(facts, "employment_status"):
        questions.append("employment_status")
    if not right_facts:
        questions.append("work_rights")
    if not regions and home is None and not anywhere:
        questions.append("location")
    if strategy == "balanced":
        questions.append("career_focus")
    questions += [f"exclusion:{i}" for i in unresolved]

    fields = dict(profile_version=int(approved["version"]), strategy=strategy, focus=focus, exclusions=tuple(exclusions),
                  home=home, max_commute_km=max_commute_km, remote_ok=remote_ok, work_rights=work_rights,
                  seniority=seniority, open_questions=tuple(questions), regions=tuple(sorted(regions)))
    shown = DecisionPolicy.model_construct(**fields, policy_hash="").model_dump(mode="json", exclude={"policy_hash"})
    return DecisionPolicy(**fields, policy_hash=digest(shown))


def _current(person: str) -> dict | None:
    from . import intake
    try:
        return intake.current_version(person)
    except Exception as exc:
        log.warning("approved profile unreadable (%s)", type(exc).__name__)
        return None


def _policy_from(approved) -> DecisionPolicy | None:
    if not isinstance(approved, dict) or not (approved.get("scope") and approved.get("scope_digest") and approved.get("facts")):
        return None
    try:
        return build_policy(approved)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        log.warning("decision policy could not be built (%s)", type(exc).__name__)
        return None


def policy_for(person: str, *, approved: dict | None = None) -> DecisionPolicy | None:
    """The policy for a person's latest confirmed profile, or for a pinned approved.json payload; None without one."""
    return _policy_from(approved if approved is not None else _current(person))


def _questions(policy: DecisionPolicy, approved: dict) -> list[dict]:
    from . import intake
    values = {f.get("id"): _text(f.get("value")) for f in _evidence(approved.get("facts", ()), "exclusion")}
    out = []
    for code in policy.open_questions:
        if code.startswith("exclusion:"):
            shown = values.get(code.split(":", 1)[1], "")[:80]
            out.append({"code": code, "why": "Only an exclusion given with its kind is applied as a rule.",
                        "question": f"Is '{shown}' an employer, a kind of work, a place, a job family or a title word? "
                                    "Until you say, it is not applied as a rule."})
        else:
            question, why = intake._ASK_TEXT[code]
            out.append({"code": code, "question": question, "why": why})
    return out


def describe(person: str, *, mode: str) -> dict:
    """The read-only policy view for the API and the chat tool; mode is 'legacy' or 'profile'."""
    if mode not in ("legacy", "profile"):
        raise ValueError("mode")
    approved = _current(person)
    policy = _policy_from(approved)
    head = {"mode": mode, "enabled": mode == "profile"}
    if policy is None:
        return {"policy": None, **head, "open_questions": [], "reason": "no_confirmed_profile"}
    return {"policy": policy.model_dump(mode="json"), **head, "open_questions": _questions(policy, approved)}


def _word_in(value: str, text: str) -> bool:
    value = value.casefold().strip()
    return bool(value) and re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text.casefold()) is not None


_ALTERNATIVE = re.compile(r"[;/|]|\bor\b", re.I)


def _location_hit(value: str, location_text: str) -> bool:
    from jobwatch.place import STATES
    from pipeline.agentic.location import regions_named
    code = value.strip().upper()
    if code not in STATES:
        code = next((c for c, name in STATES.items() if name.casefold() == value.strip().casefold()), "")
    if code:
        return set(regions_named(location_text)) == {code}
    return _word_in(value, location_text) and not _ALTERNATIVE.search(location_text)


def _str(x) -> str:
    return x if isinstance(x, str) else ""


def exclusion_hit(policy: DecisionPolicy, *, family: str | None, company: str, title: str, location_text: str,
                  remote: bool, hours: str) -> ExclusionRule | None:
    """The first rule the job breaks, or None. Pure and total: odd or missing text never raises."""
    fam, company, title, location_text, hours = _str(family), _str(company), _str(title), _str(location_text), _str(hours)
    try:
        fam = canonicalize_family(fam) if fam else ""
    except ValueError:
        fam = ""
    for rule in policy.exclusions:
        v = rule.value
        if rule.kind == "family":
            hit = bool(fam) and fam == v
        elif rule.kind == "employer":
            hit = _word_in(v, company)
        elif rule.kind == "title_term":
            hit = _word_in(v, title)
        elif rule.kind == "location":
            hit = _location_hit(v, location_text)
        else:
            w = _work_type(v)
            hit = ((w == "remote" and bool(remote)) or (w == "casual" and hours == "casual")
                   or (w == "full_time" and hours == "full_time_only")
                   or (w == "part_time" and re.search(r"part[- ]?time", title, re.I) is not None))
        if hit:
            return rule
    return None
