"""The generic prescreen engine. It knows how to PARSE a posting with stored terms and how to EVALUATE stored rules; it
holds no vocabulary, no field of work and no person. Everything it reads comes from the prescreen_* tables.

Parse: every active term is matched against the field it applies to (title, location, hours, ad_text) and becomes a Hit
carrying the term's value (what the term asserts: a level, a region, an employment type, a requirement, a family, years).
An 'allow' hit masks the text it matched (the clause, for ad text) from 'exclude' hits of the same category.

Evaluate: rules decide what the hits mean for this person. Only an 'obvious' hit under a 'skip' rule skips; 'weak' hits
and 'flag' rules only flag. A skip is a reversible recommendation to NOT spend a model on the posting, never a verdict
on the person's fit. Overrides (term, posting, employer) switch a skip off for that person only.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from . import store

_CLAUSE = re.compile(r"[.;\n•]+")


@dataclass
class PostingFields:
    title: str = ""
    location: str = ""
    hours: str = ""            # the source's employment-type field (e.g. Posting.work_type)
    ad_text: str = ""
    company: str = ""
    remote: bool = False
    classification: str = ""


@dataclass
class Hit:
    term_id: int
    category: str
    value: str | None
    applies_to: str
    strength: str
    polarity: str
    text: str
    start: int
    end: int
    n: int | None = None
    tag: str | None = None

    def brief(self) -> dict:
        d = {"term_id": self.term_id, "category": self.category, "value": self.value, "field": self.applies_to,
             "strength": self.strength, "text": self.text[:120]}
        if self.n is not None:
            d["n"] = self.n
        return d


@dataclass
class Outcome:
    outcome: str = "admit"           # admit | skip | flag
    rule_id: int | None = None
    term_id: int | None = None
    category: str | None = None
    matched_text: str = ""
    reason: str = ""
    legacy_reason: str = ""          # filters.Decision.reason vocabulary
    parsed: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    rules_hash: str = ""
    overridden: bool = False

    @property
    def skip(self) -> bool:
        return self.outcome == "skip"

    def summary(self) -> dict:
        d = {"outcome": self.outcome, "rules_hash": self.rules_hash, "parsed": self.parsed}
        if self.outcome != "admit":
            d.update(rule_id=self.rule_id, term_id=self.term_id, category=self.category, matched=self.matched_text, reason=self.reason)
        if self.flags:
            d["flags"] = self.flags
        return d


def fields_of_row(row, ad_text: str = "") -> PostingFields:
    keys = row.keys() if hasattr(row, "keys") else row
    g = lambda k: (row[k] if k in keys and row[k] is not None else "")  # noqa: E731
    return PostingFields(title=str(g("title")), location=str(g("location")), hours=str(g("work_type")), ad_text=ad_text or "",
                         company=str(g("company")), remote=bool(g("remote")), classification=str(g("classification")))


def fields_of_posting(p, ad_text: str | None = None) -> PostingFields:
    return PostingFields(title=p.title or "", location=p.location or "", hours=p.work_type or "",
                         ad_text=(p.description if ad_text is None else ad_text) or "", company=p.company or "",
                         remote=bool(p.remote), classification=p.classification or "")


class Engine:
    def __init__(self, terms, rules, overrides):
        self.terms = []
        for t in terms:
            try:
                self.terms.append((t, store.compile_term(t["term"], t["match_type"])))
            except ValueError:          # a bad row is skipped, never crashes a run (add_term validates, so this is a hand edit)
                continue
        self.rules = [dict(r, params=json.loads(r["params_json"] or "{}")) for r in rules]
        self.off_terms = {o["term_id"] for o in overrides if o["kind"] == "term"}
        self.off_postings = {o["posting_id"] for o in overrides if o["kind"] == "posting"}
        self.off_employers = {o["employer"] for o in overrides if o["kind"] == "employer"}
        self.rules_hash = hashlib.sha256(json.dumps(
            [[tuple(t[k] for k in ("id", "term", "match_type", "applies_to", "polarity", "strength", "value", "enabled")) for t, _ in self.terms],
             [(r["id"], r["kind"], r["params_json"], r["effect"]) for r in self.rules],
             sorted(self.off_terms), sorted(self.off_postings), sorted(self.off_employers)], default=str).encode()).hexdigest()[:16]

    # -- loading ---------------------------------------------------------------------
    @classmethod
    def load(cls, conn, policy=None) -> "Engine":
        """The active terms and rules for this person's database. A confirmed profile is written to rows first."""
        store.ensure_seeds(conn)
        from . import sync
        sync.sync_profile(conn, policy)
        return cls(conn.execute("SELECT * FROM prescreen_terms WHERE enabled=1 ORDER BY id").fetchall(),
                   conn.execute("SELECT * FROM prescreen_rules WHERE enabled=1 ORDER BY id").fetchall(),
                   conn.execute("SELECT * FROM prescreen_overrides").fetchall())

    # -- parse -----------------------------------------------------------------------
    def parse(self, p: PostingFields) -> list[Hit]:
        text_of = {"title": " | ".join(x for x in (p.title, p.classification) if x), "location": p.location,
                   "hours": p.hours, "ad_text": p.ad_text}
        hits: list[Hit] = []
        for t, pat in self.terms:
            if t["id"] in self.off_terms:
                continue
            text = text_of.get(t["applies_to"], "")
            if not text:
                continue
            for m in pat.finditer(text):
                n = None
                if "n" in pat.groupindex and m.group("n") is not None:
                    n = int(m.group("n"))
                hits.append(Hit(t["id"], t["category"], t["value"], t["applies_to"], t["strength"], t["polarity"],
                                m.group(0).strip(), m.start(), m.end(), n, t["field_tag"]))
        return self._inside_longer_hit(self._mask(hits, text_of))

    @staticmethod
    def _inside_longer_hit(hits: list[Hit]) -> list[Hit]:
        """A hit lying inside a longer hit of the same category and field is part of it ("Australia" inside "Western Australia")."""
        return [h for h in hits if not any(o is not h and o.category == h.category and o.applies_to == h.applies_to
                                           and o.start <= h.start and h.end <= o.end and (o.end - o.start) > (h.end - h.start)
                                           for o in hits)]

    @staticmethod
    def _mask(hits: list[Hit], text_of: dict) -> list[Hit]:
        allow = [h for h in hits if h.polarity == "allow"]
        spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for h in allow:
            if h.applies_to == "ad_text":      # a clause of ad text is neutral as a whole
                text = text_of["ad_text"]
                start = max([m.end() for m in _CLAUSE.finditer(text, 0, h.start)] or [0])
                nxt = _CLAUSE.search(text, h.end)
                spans.setdefault((h.category, h.applies_to), []).append((start, nxt.start() if nxt else len(text)))
            else:
                spans.setdefault((h.category, h.applies_to), []).append((h.start, h.end))
        out = []
        for h in hits:
            if h.polarity == "allow":
                continue
            if any(h.start < b and a < h.end for a, b in spans.get((h.category, h.applies_to), ())):
                continue
            out.append(h)
        return out

    # -- evaluate --------------------------------------------------------------------
    def evaluate(self, p: PostingFields, *, posting_id: int | None = None, categories: set[str] | None = None) -> Outcome:
        hits = self.parse(p)
        if categories is not None:
            hits = [h for h in hits if h.category in categories]
        parsed = self._parsed(p, hits)
        out = Outcome(parsed=parsed, rules_hash=self.rules_hash)
        flagged: list[Outcome] = []
        for rule in self.rules:
            found = self._apply(rule, hits, p)
            if found is None:
                continue
            strong, hit, reason = found
            if rule["effect"] == "skip" and strong:
                if posting_id in self.off_postings or (p.company and p.company.casefold() in self.off_employers):
                    out.overridden = True
                    continue
                out.outcome, out.rule_id, out.term_id = "skip", rule["id"], hit.term_id
                out.category, out.matched_text, out.reason = hit.category, hit.text, reason
                out.legacy_reason = rule["params"].get("legacy_reason", hit.category)
                return out
            f = Outcome(outcome="flag", rule_id=rule["id"], term_id=hit.term_id, category=hit.category,
                        matched_text=hit.text, reason=reason, legacy_reason=rule["params"].get("legacy_reason", hit.category))
            flagged.append(f)
        if flagged:
            f = flagged[0]
            out.outcome, out.rule_id, out.term_id, out.category = "flag", f.rule_id, f.term_id, f.category
            out.matched_text, out.reason, out.legacy_reason = f.matched_text, f.reason, f.legacy_reason
            out.flags = [f"prescreen:{x.category}:{x.matched_text[:40]}" for x in flagged]
        return out

    @staticmethod
    def _parsed(p: PostingFields, hits: list[Hit]) -> dict:
        d: dict = {"remote": p.remote}
        for cat in store.CATEGORIES:
            rows = [h.brief() for h in hits if h.category == cat]
            if rows:
                d[cat] = rows[:12]
        return d

    def _apply(self, rule: dict, hits: list[Hit], p: PostingFields):
        """(is_obvious, hit, reason) when the rule fires, else None."""
        params = rule["params"]
        unless = params.get("unless")
        if unless and any(h.category == unless["category"] and h.value in unless["values"] for h in hits):
            return None
        fn = {"term_hit": self._term_hit, "level_not_approved": self._level, "years_over": self._years,
              "region_outside": self._region}[rule["kind"]]
        res = fn(params, hits, p)
        if res is None:
            return None
        strong, hit, extra = res
        text = params.get("reason", "Matched \"{matched}\".")
        try:
            reason = text.format(**{**params, **extra, "matched": hit.text, "value": (hit.value or "").replace("_", " "), "n": hit.n})
        except (KeyError, IndexError, ValueError):
            reason = f"Matched \"{hit.text}\"."
        return strong, hit, reason

    # each returns (obvious, hit, extra-format-fields) or None
    @staticmethod
    def _term_hit(params, hits, p):
        cat, values = params["category"], params.get("values")
        mine = [h for h in hits if h.category == cat]
        if not mine:
            return None
        if values is None:
            hit = next((h for h in mine if h.strength == "obvious"), mine[0])
            return hit.strength == "obvious", hit, {}
        wanted = [h for h in mine if h.value in values]
        if not wanted:
            return None
        if params.get("match") == "all":
            strong_vals = {h.value for h in mine if h.strength == "obvious"}
            if strong_vals and strong_vals <= set(values) and not any(h.strength == "weak" and h.value not in values for h in mine):
                return True, next(h for h in wanted if h.strength == "obvious"), {}
            return False, wanted[0], {}
        strong = next((h for h in wanted if h.strength == "obvious"), None)
        return (True, strong, {}) if strong else (False, wanted[0], {})

    @staticmethod
    def _level(params, hits, p):
        ladder = params["ladder"]
        rank = {v: i for i, v in enumerate(ladder)}
        mine = [h for h in hits if h.category == "seniority_level" and h.value in rank]
        if not mine:
            return None
        approved = [rank[v] for v in params["approved"] if v in rank]
        if not approved:
            return None
        lo, hi = min(approved) - int(params.get("tolerance_below", 1)), max(approved) + int(params.get("tolerance_above", 0))
        if any(lo <= rank[h.value] <= hi for h in mine):
            return None
        strong = [h for h in mine if h.strength == "obvious"]
        pool = strong or mine
        hit = max(pool, key=lambda h: abs(rank[h.value] - (hi if rank[h.value] > hi else lo)))
        return bool(strong), hit, {"approved": ", ".join(params["approved"])}

    @staticmethod
    def _years(params, hits, p):
        cap, ceiling = int(params["max_years"]), int(params.get("ignore_over", 99))
        mine = [h for h in hits if h.category == "experience" and h.n is not None and 0 < h.n <= ceiling]
        over = [h for h in mine if h.n >= cap]
        if not over:
            return None
        hit = max(over, key=lambda h: h.n)
        return hit.strength == "obvious", hit, {"cap": cap}

    @staticmethod
    def _region(params, hits, p):
        mine = [h for h in hits if h.category == "location_outside" and h.value]
        if not mine:
            return None
        regions = set(params["regions"])
        remote_ok = params.get("remote_ok")
        if p.remote and remote_ok is not False:
            skip_tags = set(params.get("remote_exempt_tags", []))
            mine = [h for h in mine if h.tag not in skip_tags]
        by_loc = [h for h in mine if h.applies_to == "location"]
        pool = by_loc or [h for h in mine if h.applies_to == "title"]
        if not pool or any(h.value in regions for h in pool) or any(h.value in regions for h in mine if h.applies_to == "location"):
            return None
        strong = next((h for h in pool if h.strength == "obvious"), None)
        return (True, strong, {}) if strong else (False, pool[0], {})

    # -- convenience ---------------------------------------------------------------------
    def screen(self, conn, posting_id: int, p: PostingFields, *, stage: str, record: bool = True) -> Outcome:
        """Evaluate and write the audit row. A metadata-stage admit is not recorded (the full-ad stage will be)."""
        out = self.evaluate(p, posting_id=posting_id)
        if record and (out.outcome == "skip" or stage == "full"):
            store.record_decision(conn, posting_id, stage, out)
        return out
