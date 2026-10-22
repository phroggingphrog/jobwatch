"""Config-driven matching (rules.yaml). Every decision records which arm and rules fired."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Posting, fold

_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+|•|·")
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to)?\s*(?:\d{1,2}\s*)?\+?\s*(?:years?|yrs?)", re.I)


def _phrase(keyword: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(fold(keyword).strip()) + r"(?![a-z0-9])")


def _regexes(values) -> list[re.Pattern]:
    return [re.compile(v, re.I) for v in (values or []) if isinstance(v, str) and v.strip()]


@dataclass
class Arm:
    id: str
    tier: str
    anzsco: str
    keywords: list[tuple[str, re.Pattern]]
    exclude: list[re.Pattern]


@dataclass
class Decision:
    matched: bool
    reason: str = ""                  # why it failed: title | location | seniority | off_target | experience
    arm: str | None = None
    arm_tier: str | None = None
    arms: list[str] = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


class Rules:
    def __init__(self, rules: dict, employers: list[dict] | None = None):
        from . import users
        from .candidate.policy import policy_for
        self.profile_policy = policy_for(users.current())
        self.arms = [
            Arm(id=a["id"], tier=a.get("tier", "core"), anzsco=str(a.get("anzsco", "")),
                keywords=[(k, _phrase(k)) for k in a.get("keywords", []) if str(k).strip()],
                exclude=_regexes(a.get("exclude")))
            for a in rules.get("arms", []) if a.get("enabled", True) is not False   # an arm can be switched off
        ]
        loc = rules.get("location", {})
        self.vic = _regexes(loc.get("vic_patterns"))
        self.remote = _regexes(loc.get("remote_patterns"))
        self.allow_unknown_vic = bool(loc.get("allow_unknown_from_vic_employer", True))
        self.other_state = _regexes(loc.get("other_state_patterns"))
        self.vic_locality = None
        lf = loc.get("vic_localities_file")
        if lf:
            import os
            path = lf if os.path.isabs(lf) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), lf)
            try:
                names = [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]
            except OSError:
                names = []
            if names:
                alt = "|".join(re.escape(fold(n)) for n in sorted(names, key=len, reverse=True))
                self.vic_locality = re.compile(r"(?<![a-z0-9])(?:" + alt + r")(?![a-z0-9])")
        sen = rules.get("seniority", {})
        self.senior = _regexes(sen.get("exclude_title"))
        self.off_target = _regexes(sen.get("exclude_title_global"))
        self.exempt = [fold(p) for p in sen.get("exempt_phrases", [])]
        self.exclude_years = int(sen.get("exclude_min_years", 5))
        self.senior_class = _regexes(sen.get("exclude_classification"))
        fl = rules.get("flags", {})
        self.work_rights = _regexes(fl.get("work_rights_required"))
        self.work_rights_ignore = _regexes(fl.get("work_rights_ignore"))
        ft = fl.get("full_time_only", {})
        self.ft = _regexes(ft.get("title_or_type"))
        self.ft_unless = _regexes(ft.get("unless"))
        self.flag_years = int(fl.get("experience_flag_min_years", 2))
        self.entry = _regexes(fl.get("entry_level"))
        self.entry_class = _regexes(fl.get("entry_classification"))
        # Registry (brief) arm names -> rules.yaml arm ids. Reporting only; never used to match.
        loaded = {a.id for a in self.arms}       # an arm switched off with enabled: false is dropped here too
        self.registry_arm_map = {str(k): [i for i in (v or []) if i in loaded]
                                 for k, v in (rules.get("registry_arm_map") or {}).items()}
        self.vic_employers = {
            fold(str(e.get("name", ""))) for e in (employers or [])
            if str(e.get("state", "")).upper() == "VIC" or e.get("vic") is True
        }

    # -- pieces -----------------------------------------------------------------
    def arm_hits(self, title: str) -> list[tuple[Arm, str]]:
        low = fold(title)
        hits = []
        for arm in self.arms:
            if any(x.search(low) for x in arm.exclude):
                continue
            for word, pattern in arm.keywords:
                if pattern.search(low):
                    hits.append((arm, word))
                    break
        return hits

    def seniority_hit(self, title: str) -> str | None:
        low = fold(title)
        for phrase in self.exempt:
            low = low.replace(phrase, " ")
        for pattern in self.senior:
            if pattern.search(low):
                return pattern.pattern
        return None

    def off_target_hit(self, title: str) -> str | None:
        low = fold(title)
        return next((p.pattern for p in self.off_target if p.search(low)), None)

    def title_relevant(self, title: str) -> bool:
        """Cheap pre-check collectors use to decide whether a detail fetch is worth it."""
        return bool(self.arm_hits(title)) and not self.seniority_hit(title) and not self.off_target_hit(title)

    def location_rule(self, p: Posting) -> str | None:
        if self.profile_policy is not None:
            from .discovery_gate import profile_location_rule
            return profile_location_rule(p, self.profile_policy)
        text = p.location or ""
        if p.state == "VIC" or any(x.search(text) for x in self.vic):
            return "melbourne_vic"
        if (self.vic_locality is not None and text.strip()
                and not any(x.search(text) for x in self.other_state)
                and self.vic_locality.search(fold(text))):
            return "vic_locality"
        remote_text = f"{text} | {p.title}"          # " | " marks where the location ends (see fieldgen.NATIONAL)
        if p.remote or any(x.search(remote_text) for x in self.remote):
            return "remote_au"
        unknown = not text.strip() or fold(text).strip() in ("australia", "au", "multiple locations")
        if unknown and self.allow_unknown_vic:
            if any(x.search(fold(p.title)) for x in self.other_state):
                return None                     # "... - bp Mackay, QLD": the title names another state
            if fold(p.company) in self.vic_employers or fold(p.origin) in self.vic_employers:
                return "unknown_location_vic_employer"
        return None

    def classification_hit(self, classification: str | None) -> str | None:
        low = fold(classification or "")
        return next((p.pattern for p in self.senior_class if p.search(low)), None) if low else None

    def rule_arms_for(self, registry_arms) -> list[str]:
        """Map registry arm names (employers.yaml `arms`) to rules.yaml arm ids, for reporting.
        Names that already are rules.yaml ids pass through; unknown names are dropped."""
        known = {a.id for a in self.arms}
        out: list[str] = []
        for name in registry_arms or []:
            ids = self.registry_arm_map.get(str(name)) or ([name] if name in known else [])
            out += [i for i in ids if i not in out]
        return out

    @staticmethod
    def experience_years(text: str) -> int | None:
        best = None
        for sentence in _SENTENCES.split(text or ""):
            if not re.search(r"experience|exp\.", sentence, re.I):
                continue
            for m in _YEARS.finditer(sentence):
                n = int(m.group(1))
                if 0 < n <= 20:
                    best = n if best is None else max(best, n)
        return best

    def work_rights_required(self, text: str) -> str | None:
        for sentence in _SENTENCES.split(text or ""):
            if any(x.search(sentence) for x in self.work_rights_ignore):
                continue
            for pattern in self.work_rights:
                if pattern.search(sentence):
                    return pattern.pattern
        return None

    def full_time_only(self, p: Posting) -> bool:
        blob = f"{p.title} {p.description}"
        if p.work_type in ("PT", "casual"):
            return False
        if any(x.search(blob) or x.search(p.work_type or "") for x in self.ft_unless):
            return False
        return p.work_type == "FT" or any(x.search(p.title) for x in self.ft) or \
            any(x.search(p.description or "") for x in self.ft)

    # -- main -------------------------------------------------------------------
    def evaluate(self, p: Posting) -> Decision:
        hits = self.arm_hits(p.title)
        if not hits:
            return Decision(False, "title")
        off = self.off_target_hit(p.title)
        if off:
            return Decision(False, "off_target", rules={"off_target": off})
        senior = self.seniority_hit(p.title)
        if senior:
            return Decision(False, "seniority", rules={"seniority": senior})
        grade = self.classification_hit(p.classification)
        if grade:
            return Decision(False, "seniority", rules={"classification": p.classification})
        loc = self.location_rule(p)
        if not loc:
            return Decision(False, "location", rules={"location": p.location})
        years = self.experience_years(p.description)
        if years is not None and years >= self.exclude_years:
            return Decision(False, "experience", rules={"experience_years": years})

        flags = list(dict.fromkeys(p.flags))
        rights = self.work_rights_required(f"{p.title}\n{p.description}")
        if rights:
            flags.append("work_rights_required")
        if self.full_time_only(p):
            flags.append("full_time_only")
        if years is not None and years >= self.flag_years:
            flags.append(f"experience_years>={self.flag_years}")
        if any(x.search(p.title) for x in self.entry) or \
                (p.classification and any(x.search(p.classification) for x in self.entry_class)):
            flags.append("entry_level")
        primary, keyword = hits[0]
        rules = {"title_keyword": keyword, "location": loc}
        if p.classification:
            rules["classification"] = p.classification
        if rights:
            rules["work_rights_pattern"] = rights
        if years is not None:
            rules["experience_years"] = years
        return Decision(True, arm=primary.id, arm_tier=primary.tier,
                        arms=[a.id for a, _ in hits], rules=rules,
                        flags=list(dict.fromkeys(flags)))
