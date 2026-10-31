"""Read side of the web board: filters, facet counts, the AI reading of each ad (ad_reviews) with the old
rule-based score as the fallback, job detail, applications, inbox, sources and insights. Plain SQL + a
little Python; no writes here except the UI-only marks (web_views, saved_searches, the board visit stamp
in `state`)."""
from __future__ import annotations

import functools
import html
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .. import db as dbm
from ..commands.state import SUBMITTED


def _tz() -> ZoneInfo:
    """The signed-in person's timezone (place.person_timezone), cached per person + profile.yaml version: absolute()
    runs once per board row and the lookup reads the profile."""
    from jobwatch import users
    from jobwatch.candidate import intake
    approved = intake.current_version(users.current())
    path = (intake._versions_root(users.current()) / str(approved['version']) / 'profile.yaml'
            if approved else None)
    try:
        mtime = path.stat().st_mtime_ns if path else 0
    except OSError:
        mtime = 0
    return _tz_for(users.current(), str(path or ''), mtime)


@functools.lru_cache(maxsize=64)
def _tz_for(person: str, profile: str, mtime: int) -> ZoneInfo:
    from jobwatch.util.place import person_timezone
    return person_timezone()


PAGE_SIZE = 30
TABLE_PAGE_SIZE = 50

WORK_TYPES = {"FT": "Full-time", "PT": "Part-time", "casual": "Casual", "contract": "Contract",
              "temp": "Temp", "intern": "Internship", "": "Not stated"}
WITHIN = [(1, "24 hours"), (3, "3 days"), (7, "7 days"), (14, "14 days"), (30, "30 days")]
WARN = {"rights": "Work rights", "fulltime": "Full-time only", "experience": "2+ yrs experience"}
TABS = [("all", "All"), ("new", "New"), ("saved", "Saved"), ("applied", "Applied"), ("hidden", "Hidden")]
STATUS_RAIL = [("all", "All (not hidden)"), ("new", "New (not opened)"), ("seen", "Seen"),
               ("saved", "Saved"), ("applied", "Applied"), ("hidden", "Hidden")]
SORTS = [("fit", "Best fit"), ("new", "Newest"), ("salary", "Salary"), ("company", "Company")]

# The AI reader (reader.py) writes one ad_reviews row per matched posting. A posting with no row is "pending".
# AI views: what the board lists. Default is Good (verdict show). Each posting is in exactly one of these.
WHOLE_SOURCE = "full"                    # the only text_source that means the AI read the whole ad; a teaser, a cut copy, NULL or
                                         # anything unknown is not proof, so a "show" from it is held back
AI_VIEWS = [("show", "Good"), ("review", "Not fully read"), ("hide", "Hidden by AI"), ("pending", "Waiting for AI")]
AI_ORDER = {k: i for i, (k, _) in enumerate(AI_VIEWS)}
HIDE_REASONS = [("sponsored_ad", "Sponsored ad"), ("not_a_real_job", "Not a real vacancy"),
                ("needs_citizen_or_pr", "Needs citizenship or PR"),
                ("needs_unrestricted_rights", "Needs unrestricted work rights"),
                ("full_time_only", "Full-time only: does not fit your hours"),
                ("out_of_area", "Outside your search area, not remote"), ("too_senior", "Too senior"),
                ("low_fit", "Not a fit"),
                # "not a target role", split by the AI's reading of the day-to-day work (reader.NOT_TARGET_KINDS)
                ("shop_retail", "Not wanted: shop or retail"), ("hospitality", "Not wanted: hospitality or food"),
                ("events_venue", "Not wanted: events or venues"),
                ("customer_service", "Not wanted: customer service or call centre"),
                ("reception", "Not wanted: reception or front desk"), ("sales", "Not wanted: sales"),
                ("engineering_it", "Other field: software, engineering or IT"),
                ("health_care_teaching", "Other field: health, care or teaching"),
                ("trades_manual", "Other field: trades or manual work"),
                ("other_field", "Other field: a different profession"),
                ("not_relevant", "Not relevant to your fields"),
                ("excluded_by_rule", "Excluded by your rule")]
NOT_TARGET_KEYS = frozenset(k for k, _ in HIDE_REASONS[HIDE_REASONS.index(("low_fit", "Not a fit")) + 1:])
HIDE_LABEL = {**dict(HIDE_REASONS), "not_target": "Not a target role (not sorted yet)", "other": "Other reason",
              "duplicate": "Same ad as another job", "prescreened": "Skipped by an early check (the reason is on the job)",
              "posting_closed": "The ad is closed",
              "hard_gate": "Ruled out by a hard requirement (work rights, level or years)"}
# the same reasons in running text where the label alone would read badly ("Hidden: full-time only: not possible...")
HIDE_SENTENCE = {"full_time_only": "full-time only, which does not fit your hours",
                 "out_of_area": "outside your search area, not remote"}
RIGHTS_TEXT = {
    "none_stated": "The ad does not mention work rights or citizenship",
    "valid_work_rights": "Needs the right to work in Australia (not citizenship)",
    "unrestricted_work_rights": "Needs unrestricted work rights",
    "citizen_or_pr": "Needs Australian citizenship or permanent residency",
    "citizen_only": "Needs Australian citizenship",
    "clearance": "Needs a security clearance (usually citizenship)",
}
BLOCKING_RIGHTS = ("unrestricted_work_rights", "citizen_or_pr", "citizen_only", "clearance")
SENIORITY_TEXT = {"entry": "Entry level", "junior": "Junior", "mid": "Mid level", "senior": "Senior"}
AD_KIND_LABEL = {"agency": "Agency", "talent_pool": "Talent pool", "scam": "Looks like a scam"}

# The career-ops style evaluation (reader prompt v3), stored in ad_reviews.report_json. Plain words for every code.
HOURS_TEXT = {"full_time_only": "Full-time only", "part_time_ok": "Part-time OK", "casual": "Casual", "unstated": "Not stated"}
WORK_MODE_TEXT = {"onsite": "On site", "hybrid": "Hybrid", "remote": "Remote", "unstated": "Not stated"}
LOCATION_TEXT = {"inner": "Location fit reported", "mid": "Location fit reported", "cbd_or_far_suburb": "Location fit reported",
                 "outer": "Location fit reported", "remote": "Remote", "out_of_scope": "Outside confirmed scope"}
IMPORTANCE_TEXT = {"critical": "Critical", "high": "High", "meaningful": "Meaningful", "preferred": "Preferred",
                   "low_signal": "Low signal"}
TIER_TEXT = {"stated": "Stated", "structural": "Structural", "inferred": "Inferred"}
TIER_WHY = {"stated": "The ad says this in so many words.", "structural": "Read from how the ad is laid out.",
            "inferred": "The AI's own judgement of the market, not something the ad says."}
MATCH_TEXT = {"strong": "Strong", "partial": "Partial", "missing": "Missing", "na": "Not relevant"}
REC_TEXT = {"apply": "Apply", "consider": "Consider", "skip": "Skip"}
REC_WORDS = {**REC_TEXT, "hold": "Hold"}
LEGIT_TEXT = {"high": "Looks genuine", "caution": "Worth a quick check", "suspicious": "Check this posting is real"}
DIM_LABEL = [("cv_match", "CV match"), ("north_star", "Fits the jobs you want"), ("comp", "Pay"), ("culture", "Culture"),
             ("red_flags", "Red flags")]
SCORE_FLOORS = (3.5, 4.0, 4.5)
SCORE_FLOOR_LABEL = {3.5: "3.5 and up: decent", 4.0: "4.0 and up: good", 4.5: "4.5 and up: strong"}
# canonical application states (applications schema comment), board order
APP_STATES = ("interested", "drafting", "drafted", "applied", "assessment", "interview", "offer",
              "rejected", "withdrawn", "skipped")
KANBAN = ("interested", "drafted", "applied", "assessment", "interview", "offer")
KANBAN_CLOSED = ("rejected", "withdrawn", "skipped")
STATE_LABEL = {"interested": "Saved", "drafting": "Drafting", "drafted": "Drafted", "applied": "Applied",
               "assessment": "Assessment", "interview": "Interview", "offer": "Offer",
               "rejected": "Rejected", "withdrawn": "Withdrawn", "skipped": "Hidden"}
SOURCE_LABEL = {
    "seek": "Seek", "jobspy_src": "JobSpy", "jora": "Jora", "careers_vic": "Careers.Vic",
    "ats_greenhouse": "Greenhouse", "ats_lever": "Lever", "ats_ashby": "Ashby", "ats_workable": "Workable",
    "ats_smartrecruiters": "SmartRecruiters", "ats_workday": "Workday", "ats_pageup": "PageUp",
    "ats_employmenthero": "Employment Hero", "ats_scouttalent": "Scout Talent", "ats_oracle": "Oracle",
    "ats_successfactors": "SuccessFactors", "ats_phenom": "Phenom", "ats_atlassian": "Atlassian",
    "jsonld_pages": "Careers page", "rss": "RSS", "reddit": "Reddit", "ats_pulse": "Pulse",
    "ats_recruitmenthub": "RecruitmentHub", "ats_jobs_search": "Council jobs", "ats_elmo": "ELMO",
    "ats_techone": "TechnologyOne",
}
FLAG_LABEL = {"work_rights_required": "Work rights", "full_time_only": "Full-time only",
              "entry_level": "Entry-level", "via_linkedin": "via LinkedIn", "via_indeed": "via Indeed",
              "via_google": "via Google", "reddit": "Reddit"}


def src_label(s: str) -> str:
    return SOURCE_LABEL.get(s, s.replace("ats_", "").replace("_", " ").title())


def arm_label(a: str | None) -> str:
    if not a:
        return "Not matched"
    return a.replace("_", " ").replace("ict ", "ICT ").capitalize().replace("Ict ", "ICT ")


def flag_label(f: str) -> str:
    if f.startswith("experience_years>="):
        return f"{f.split('>=')[1]}+ yrs exp"
    return FLAG_LABEL.get(f, f.replace("_", " "))


def hide_label(reason: str | None) -> str:
    """Plain label for why the AI hid a posting ('Needs citizenship or PR')."""
    r = (reason or "other").strip()
    return HIDE_LABEL.get(r) or r.replace("_", " ").capitalize()


def hide_sentence(reason: str | None) -> str:
    """The same reason in running text ('needs citizenship or PR')."""
    r = (reason or "other").strip()
    if r in HIDE_SENTENCE:
        return HIDE_SENTENCE[r]
    t = hide_label(reason)
    return t[:1].lower() + t[1:]


def score_display(score, fit=None) -> str:
    """The AI score as shown, '4.1' (out of 5). When the career-ops score is missing (a row read with the older
    prompt) it is the old 0-100 fit divided by 20. '' when there is neither."""
    v = score if isinstance(score, (int, float)) else (fit / 20 if isinstance(fit, (int, float)) else None)
    if v is None:
        return ""
    return f"{int(max(0.0, min(5.0, float(v))) * 10 + 0.5 + 1e-9) / 10:.1f}"


def score_label(v) -> str:
    """career-ops wording for a 1-5 score."""
    if not isinstance(v, (int, float)):
        return ""
    return ("Strong match" if v >= 4.5 else "Good match" if v >= 4.0 else "Decent match" if v >= 3.5
            else "Recommend against")


def score_class(v) -> str:
    return "fit-hi" if isinstance(v, (int, float)) and v >= 4.0 else \
        ("fit-mid" if isinstance(v, (int, float)) and v >= 3.5 else "fit-lo")


def ai_view_text(ai: str, why: str = "") -> str:
    """Name of an AI view, with the hide reason when one is chosen ('Hidden by AI: Too senior')."""
    name = dict(AI_VIEWS, worth="Worth a look").get(ai, "Good")
    return f"{name}: {hide_label(why)}" if ai == "hide" and why else name


def row_ai_text(r: dict) -> str:
    """One short phrase for a row's AI state (table cell and CSV): 'Good', 'Hidden: too senior' ..."""
    st = r.get("ai_state") or "pending"
    if st == "hide":
        return f"Hidden: {hide_sentence((r.get('ai') or {}).get('hide_reason'))}"
    return dict(AI_VIEWS).get(st, st)


# -- time ------------------------------------------------------------------------------------
def parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def ago(value, now: datetime | None = None) -> str:
    dt = value if isinstance(value, datetime) else parse_ts(value)
    if dt is None:
        return "—"
    secs = max(0, int(((now or datetime.now(UTC)) - dt).total_seconds()))
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 48 * 3600:
        return f"{secs // 3600}h ago"
    if secs < 60 * 86400:
        return f"{secs // 86400}d ago"
    return f"{secs // (30 * 86400)}mo ago"


def absolute(value) -> str:
    dt = value if isinstance(value, datetime) else parse_ts(value)
    if dt is None:
        return ""
    return dt.astimezone(_tz()).strftime("%a %-d %b %Y, %-I:%M %p %Z")


def days_since(value, now=None) -> int | None:
    dt = value if isinstance(value, datetime) else parse_ts(value)
    if dt is None:
        return None
    return max(0, ((now or datetime.now(UTC)) - dt).days)


# -- text --------------------------------------------------------------------------------------
_BLOCK_TAGS = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6]|/tr|/ul|/ol)\b[^>]*>", re.I)
_LI = re.compile(r"<\s*li\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]*>")
_BULLET = re.compile(r"^\s*(?:[•·▪●◦\-–*]|\d{1,2}[.)])\s+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def plain_text(s: str | None) -> str:
    """Strip any HTML to plain text (block tags become line breaks). Output is text, never markup:
    Jinja autoescape renders it."""
    s = s or ""
    if "<" in s and ">" in s:
        s = _BLOCK_TAGS.sub("\n", s)
        s = _LI.sub("\n• ", s)
        s = _TAG.sub("", s)
    s = html.unescape(s).replace("\r", "").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", s).strip()


def teaser(s: str | None, n: int = 260) -> str:
    t = re.sub(r"\s+", " ", plain_text(s)).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def desc_blocks(s: str | None) -> list[dict]:
    """Plain paragraphs and bullet lists: [{'p': text} | {'ul': [items]}]."""
    text = plain_text(s)
    if not text:
        return []
    text = re.sub(r"\s+[•·▪●]\s+", "\n• ", text)       # inline bullets -> own lines
    blocks: list[dict] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if blocks and "p" in blocks[-1]:
                blocks.append({"gap": True})
            continue
        if _BULLET.match(line):
            item = _BULLET.sub("", line)
            if blocks and "ul" in blocks[-1]:
                blocks[-1]["ul"].append(item)
            else:
                blocks.append({"ul": [item]})
        elif len(line) > 700:                           # one long blob -> paragraphs of ~3 sentences
            sents = _SENT.split(line)
            for i in range(0, len(sents), 3):
                blocks.append({"p": " ".join(sents[i:i + 3])})
        else:
            blocks.append({"p": line})
    return [b for b in blocks if "gap" not in b]


def commute_km(loc: str | None) -> str:
    """' · 13 km' from the owner's suburb for a Victorian location, else '' (owner, 2026-10-12: "check about the KMs")."""
    from pipeline.agentic.location import km_from_home
    km = km_from_home(loc or "")
    return f" · {km} km" if km is not None else ""


def short_location(loc: str | None) -> str:
    s = (loc or "").strip()
    s = re.sub(r",?\s*(Australia|AU|AUS)$", "", s, flags=re.I).strip(" ,")
    return s or "Location not stated"


def annual_salary(r) -> float | None:
    v = r["salary_max"] or r["salary_min"]
    if not v:
        return None
    unit = (r["salary_unit"] or "year").lower()
    mult = {"hour": 1976, "day": 260, "week": 52, "month": 12}.get(unit, 1)
    return float(v) * mult


_MACHINE_SALARY = re.compile(r"^(?:[A-Z]{3}\s+)?[\d.,]+(?:\s*-\s*[\d.,]+)?\s+(?:yearly|monthly|weekly|daily|hourly)$", re.I)


def salary_display(r) -> str:
    # Collectors sometimes store a raw "AUD 12000.0-50000.0 yearly"; show those from the numbers instead.
    if r["salary_text"] and not (_MACHINE_SALARY.match(r["salary_text"].strip()) and (r["salary_min"] or r["salary_max"])):
        return re.sub(r"\s+", " ", r["salary_text"]).strip()[:60]
    lo, hi = r["salary_min"], r["salary_max"]
    if not (lo or hi):
        return ""
    unit = {"hour": "/hr", "day": "/day", "week": "/wk", "month": "/mo", "year": ""}.get((r["salary_unit"] or "year").lower(), "")
    fmt = (lambda v: f"${v:,.2f}") if unit == "/hr" else (
        lambda v: f"${v:,.0f}") if unit in ("/wk", "/mo") else (          # "$2k/wk" would round $1,500 away
        lambda v: f"${v / 1000:,.0f}k" if v >= 1000 else f"${v:,.0f}")
    if lo and hi and lo != hi:
        return f"{fmt(lo)} – {fmt(hi)}{unit}"
    return f"{fmt(lo or hi)}{unit}"


# -- employer registry (sector map) -------------------------------------------------------------
class Registry:
    """employers.yaml, reloaded when the file changes. Read-only."""

    def __init__(self, config_loader):
        self._load = config_loader
        self._mtime = None
        self.employers: list[dict] = []
        self.sector_by_name: dict[str, str] = {}

    def refresh(self) -> "Registry":
        cfg = self._load()
        path = cfg.employers_path
        mtime = path.stat().st_mtime if path and Path(path).exists() else None
        if mtime != self._mtime or not self.employers:
            self._mtime = mtime
            self.employers = cfg.employers
            self.sector_by_name = {str(e.get("name", "")).strip().lower(): str(e.get("sector") or "other")
                                   for e in cfg.employers if e.get("name")}
        return self

    def sector(self, origin: str | None, company: str | None) -> str:
        for n in (origin, company):
            if n:
                s = self.sector_by_name.get(n.strip().lower())
                if s:
                    return s
        return ""

    def sectors(self) -> list[str]:
        return sorted(set(self.sector_by_name.values()))


# -- filters -------------------------------------------------------------------------------------
MULTI = ("arm", "tier", "src", "sector", "arr", "wt", "hide", "arch")


@dataclass
class Filters:
    scope: str = "matches"
    q: str = ""
    x: str = ""
    arm: list[str] = field(default_factory=list)
    tier: list[str] = field(default_factory=list)
    src: list[str] = field(default_factory=list)
    sector: list[str] = field(default_factory=list)
    within: int | None = None
    arr: list[str] = field(default_factory=list)
    wt: list[str] = field(default_factory=list)
    sal: bool = False
    salmin: int | None = None
    entry: bool = False
    hide: list[str] = field(default_factory=list)
    st: str = "all"
    sort: str = "fit"
    dir: str = ""
    minscore: float | None = None   # the AI score floor, one of SCORE_FLOORS (3.5, 4.0, 4.5)
    arch: list[str] = field(default_factory=list)   # AI archetypes (free text from the model, never comma-split)
    ai: str = "show"            # AI view: show | review | hide | pending (see AI_VIEWS)
    why: str = ""               # with ai=hide: one hide reason (HIDE_REASONS), else ""

    @classmethod
    def from_params(cls, params) -> "Filters":
        """params: a Starlette QueryParams/FormData or a plain dict (lists allowed)."""
        def many(k):
            if hasattr(params, "getlist"):
                vals = params.getlist(k)
            else:
                v = params.get(k)
                vals = v if isinstance(v, list) else ([v] if v not in (None, "") else [])
            out = []
            for v in vals:
                for part in ([str(v)] if k == "arch" else str(v).split(",")):
                    part = re.sub(r"\s+", " ", part).strip()
                    if part and part not in out and len(part) <= (80 if k == "arch" else 60):
                        out.append(part)
            return out[:40]

        def one(k, default=""):
            v = params.get(k) if hasattr(params, "get") else None
            if isinstance(v, list):
                v = v[-1] if v else None
            return str(v).strip()[:200] if v not in (None, "") else default

        def num(k):
            v = one(k)
            return int(v) if v.isascii() and v.isdigit() and len(v) < 7 else None

        f = cls(scope="all" if one("scope") == "all" else "matches", q=one("q"), x=one("x"),
                within=num("within"), sal=one("sal") in ("1", "on", "true"), salmin=num("salmin"),
                entry=one("entry") in ("1", "on", "true"), st=one("st", "all"), sort=one("sort", "fit"),
                dir=one("dir") if one("dir") in ("asc", "desc") else "")
        for k in MULTI:
            setattr(f, k, many(k))
        if f.st not in dict(STATUS_RAIL):
            f.st = "all"
        ai, why = one("ai", "show").lower(), one("why").lower()
        if ":" in ai:                                   # the form's radio value 'hide:too_senior'
            ai, _, w = ai.partition(":")
            why = why or w
        try:
            ms = round(float(one("minscore")), 1) if one("minscore") else None
        except ValueError:
            ms = None
        f.minscore = ms if ms in SCORE_FLOORS else None
        f.ai = ai if ai in dict(AI_VIEWS) or ai == "worth" else "show"
        f.why = why if f.ai == "hide" and re.fullmatch(r"[a-z_]{1,40}", why) else ""
        if f.within not in dict(WITHIN):
            f.within = None
        return f

    def as_dict(self) -> dict:
        d = {"scope": self.scope if self.scope != "matches" else "", "q": self.q, "x": self.x,
             "within": self.within or "", "sal": "1" if self.sal else "", "salmin": self.salmin or "",
             "entry": "1" if self.entry else "", "st": self.st if self.st != "all" else "",
             "sort": self.sort if self.sort != "fit" else "", "dir": self.dir,
             "ai": self.ai if self.ai != "show" else "", "why": self.why,
             "minscore": f"{self.minscore:.1f}" if self.minscore else ""}
        for k in MULTI:
            d[k] = list(getattr(self, k))
        return {k: v for k, v in d.items() if v not in ("", [], None)}

    def query(self, **over) -> str:
        d = self.as_dict()
        for k, v in over.items():
            if v in (None, "", []):
                d.pop(k, None)
            else:
                d[k] = v
        if d.get("ai") == "show":                       # the default view is never written to a URL
            d.pop("ai")
        if d.get("ai") != "hide":                       # a hide reason only means something with ai=hide
            d.pop("why", None)
        pairs = []
        for k, v in d.items():
            for item in (v if isinstance(v, list) else [v]):
                pairs.append((k, item))
        return urlencode(pairs)

    def active_count(self) -> int:
        n = sum(1 for k in MULTI if getattr(self, k))
        return n + sum(bool(v) for v in (self.within, self.sal or self.salmin, self.entry, self.minscore))

    def clear_over(self) -> dict:
        """query() overrides that drop every facet filter (not the words, the tab or the AI view): Clear all."""
        return {**{k: "" for k in MULTI}, "within": "", "sal": "", "salmin": "", "entry": "", "minscore": ""}

    def summary(self) -> str:
        bits = []
        if self.ai != "show":
            bits.append(ai_view_text(self.ai, self.why))
        if self.q:
            bits.append(f"“{self.q}”")
        if self.x:
            bits.append(f"not “{self.x}”")
        for k, lab in (("arm", None), ("tier", None), ("src", None), ("sector", None), ("arch", None), ("arr", None),
                       ("wt", None)):
            vals = getattr(self, k)
            if vals:
                fmt = {"arm": arm_label, "src": src_label, "wt": lambda v: WORK_TYPES.get(v, v)}.get(k, lambda v: v)
                bits.append(", ".join(fmt(v) for v in vals[:3]) + ("…" if len(vals) > 3 else ""))
        if self.minscore:
            bits.append(f"score {self.minscore:.1f}+")
        if self.within:
            bits.append(f"last {dict(WITHIN)[self.within]}")
        if self.salmin:
            bits.append(f"≥ ${self.salmin}k")
        elif self.sal:
            bits.append("salary listed")
        if self.entry:
            bits.append("entry-level")
        return " · ".join(bits) or ("Good matches" if self.scope == "matches" else "Good jobs")


def _terms(s: str) -> list[str]:
    out = []
    for quoted, word in re.findall(r'"([^"]+)"|([^\s,]+)', s or ""):
        t = (quoted or word).strip()
        if t:
            out.append(t)
    return out[:8]


def _like(t: str) -> str:
    return "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


_COLS = """p.id, p.title, p.company, p.location, p.state, p.remote, p.work_type, p.salary_text,
  p.salary_min, p.salary_max, p.salary_unit, p.posted_at, p.posted_at_source, p.first_seen_at,
  p.last_seen_at, p.source, p.origin, p.url, p.flags_json AS pflags,
  m.id AS match_id, m.arm, m.arm_tier, m.flags_json AS mflags, m.matched_at,
  a.id AS app_id, a.status AS app_status, a.applied_at, v.first_viewed_at,
  (SELECT group_concat(s.source, ',') FROM sightings s WHERE s.posting_id=p.id) AS sources,
  ar.posting_id AS ai_pid, ar.verdict AS ai_verdict, ar.hide_reason AS ai_hide_reason, ar.fit AS ai_fit,
  ar.reason AS ai_reason, ar.pros_json AS ai_pros, ar.cons_json AS ai_cons, ar.rights AS ai_rights,
  ar.rights_quote AS ai_quote, ar.seniority AS ai_seniority, ar.min_years AS ai_min_years,
  ar.role_match AS ai_role_match, ar.ad_kind AS ai_ad_kind, ar.text_source AS ai_text_source,
  ar.flags_json AS ai_flags, ar.model AS ai_model, ar.reviewed_at AS ai_reviewed_at, ar.score AS ai_score,
  ar.archetype AS ai_archetype, ar.legitimacy AS ai_legit, ar.report_json AS ai_report, ar.model_json AS ai_model_json,
  ps.stage AS pl_stage, ps.data_json AS pl_data, ps.reason AS pl_reason, ps.updated_at AS pl_at"""


def load_rows(conn, scope: str, q: str = "", x: str = "", ids: list[int] | None = None,
              reg: Registry | None = None, now: datetime | None = None) -> list[dict]:
    if scope == "matches":
        base = "FROM matches m JOIN postings p ON p.id=m.posting_id"
    else:
        base = "FROM postings p LEFT JOIN matches m ON m.posting_id=p.id"
    sql = (f"SELECT {_COLS} {base} LEFT JOIN applications a ON a.posting_id=p.id "
           "LEFT JOIN web_views v ON v.posting_id=p.id LEFT JOIN ad_reviews ar ON ar.posting_id=p.id "
           "LEFT JOIN pipeline_state ps ON ps.posting_id=p.id "
           "WHERE (p.closed_at IS NULL OR a.id IS NOT NULL)")  # closed jobs leave the board unless applied/saved
    args: list = []
    for t in _terms(q):
        sql += (" AND (p.title LIKE ? ESCAPE '\\' OR COALESCE(p.company,'') LIKE ? ESCAPE '\\' "
                "OR COALESCE(p.description,'') LIKE ? ESCAPE '\\' OR COALESCE(p.location,'') LIKE ? ESCAPE '\\')")
        args += [_like(t)] * 4
    for t in _terms(x):
        sql += " AND NOT (p.title LIKE ? ESCAPE '\\' OR COALESCE(p.company,'') LIKE ? ESCAPE '\\')"
        args += [_like(t)] * 2
    if ids is not None:
        sql += f" AND p.id IN ({','.join('?' for _ in ids) or 'NULL'})"
        args += list(ids)
    now = now or datetime.now(UTC)
    rows = [dict(r) for r in conn.execute(sql, args)]
    agentic_rows = [r for r in rows if '"agentic"' in (r.get('pl_data') or '')]
    if agentic_rows:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'agentic_runs', 'agentic_packages', 'agentic_artifacts'} <= tables:
            from pipeline.agentic.persistence import latest_result
            for row in agentic_rows:
                # The same hash-checked immutable source drives detail and list
                # views, including readiness after a missing/corrupt PDF.
                row['_agentic_result'] = latest_result(conn, row['id'], parse=frozenset({'evaluation'}))
    return [enrich(r, reg, now) for r in rows]


_VIC = re.compile(r"\b(vic|victoria|melbourne|geelong|ballarat|bendigo)\b", re.I)


def ui_status(app_status: str | None, viewed: bool) -> str:
    if app_status == "skipped":
        return "hidden"
    if app_status in ("interested", "drafting", "drafted"):
        return "saved"
    if app_status in SUBMITTED:
        return "applied"
    if app_status in ("rejected", "withdrawn"):
        return "closed"
    return "seen" if viewed else "new"


def enrich(r: dict, reg: Registry | None, now: datetime) -> dict:
    flags = json.loads(r.get("mflags") or r.get("pflags") or "[]")
    r["flags"] = flags
    warn = set()
    for f in flags:
        if f == "work_rights_required":
            warn.add("rights")
        elif f == "full_time_only":
            warn.add("fulltime")
        elif f.startswith("experience_years>="):
            warn.add("experience")
    r["warn"] = warn
    r["entry"] = "entry_level" in flags
    srcs = set(filter(None, (r.get("sources") or "").split(","))) | {r["source"]}
    r["srcs"] = sorted(srcs, key=lambda s: (s != r["source"], s))
    listed = parse_ts(r["posted_at"]) or parse_ts(r["first_seen_at"])
    r["listed_dt"] = listed
    r["age_days"] = (now - listed).total_seconds() / 86400 if listed else 9999
    r["added_at"] = r["matched_at"] or r["first_seen_at"]
    r["sal_year"] = annual_salary(r)
    r["has_salary"] = bool(r["salary_text"] or r["salary_min"] or r["salary_max"])
    r["sector"] = reg.sector(r["origin"], r["company"]) if reg else ""
    r["is_remote"] = bool(r["remote"])
    r["is_vic"] = r["state"] == "VIC" or bool(_VIC.search(r["location"] or ""))
    r["wt"] = r["work_type"] or ""
    r["tier"] = r["arm_tier"] or ("other" if not r["match_id"] else "core")
    r["status"] = ui_status(r["app_status"], bool(r["first_viewed_at"]))
    old = ai_from_row(r)                                       # pops the ai_* columns
    r["ai"] = ai_from_pipeline(r) or old                       # pops the pl_* columns; the pipeline's verdict wins
    r["ai_state"] = ai_state(r["ai"])
    r["archetype"] = r["ai"]["archetype"] if r["ai"] else ""
    r["rule_score"], r["rule_why"] = fit_score(r)               # the old keyword score, kept as a fallback
    ai = r["ai"]
    # what the AI read wins. score5 = the career-ops score (1-5); rows read with the older prompt have no score, so
    # it is their 0-100 fit divided by 20. `score` stays on the 0-100 scale (sorting, the old bars, pending rows).
    s5 = ai["score"] if ai and ai["score"] is not None else (ai["fit"] / 20 if ai and ai["fit"] is not None else None)
    r["score5"] = s5
    r["score_text"] = score_display(s5)
    if s5 is not None:
        r["score"], r["score_why"], r["score_src"] = int(round(s5 * 20)), [ai["reason"] or "Read by the AI"], "ai"
    elif ai and ai.get('model') == 'Deep Agents':
        r['score'], r['score_why'], r['score_src'] = 0, [ai['reason']], 'pending'
    else:
        r["score"], r["score_why"], r["score_src"] = r["rule_score"], r["rule_why"], "rules"
    return r


def _text_list(raw, n: int = 12, width: int = 300) -> list[str]:
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        t = re.sub(r"\s+", " ", str(x)).strip() if x is not None else ""
        if t:
            out.append(t[:width])
    return out[:n]


def ai_from_row(r: dict) -> dict | None:
    """The AI reader's review of this posting (from the ad_reviews columns joined by load_rows), or None when
    it has not been read. Removes the raw ai_* columns from the row. Lists are decoded; text is untrusted."""
    cols = {k: r.pop(k, None) for k in ("ai_pid", "ai_verdict", "ai_hide_reason", "ai_fit", "ai_reason", "ai_pros",
                                        "ai_cons", "ai_rights", "ai_quote", "ai_seniority", "ai_min_years",
                                        "ai_role_match", "ai_ad_kind", "ai_text_source", "ai_flags", "ai_model",
                                        "ai_reviewed_at", "ai_score", "ai_archetype", "ai_legit", "ai_report", "ai_model_json")}
    if cols["ai_pid"] is None:
        return None
    fit = cols["ai_fit"]
    score = cols["ai_score"]
    report = _report(cols["ai_report"])
    # Older sorter output lives in model_json, while report_json can predate the kind field.
    # A valid report wins; only a generic not_target reason may use this compatibility fallback.
    hide = cols["ai_hide_reason"] or ""
    if hide == "not_target":
        kind = report["not_target_kind"] if report else ""
        if not kind:
            try:
                model = json.loads(cols["ai_model_json"] or "{}")
            except (ValueError, TypeError):
                model = {}
            if isinstance(model, dict):
                kind = _enum_or(model.get("not_target_kind"), NOT_TARGET_KEYS, "")
        hide = kind or hide
    archetype = _line(cols["ai_archetype"], 80) or (report["archetype"] if report else "")
    legit = cols["ai_legit"] if cols["ai_legit"] in LEGIT_TEXT else (report["legitimacy"]["tier"] if report else "")
    return {"score": round(max(1.0, min(5.0, float(score))), 1) if isinstance(score, (int, float)) else None,
            "archetype": archetype, "legitimacy": legit or "", "report": report,
            "verdict": cols["ai_verdict"] or "review",
            "hide_reason": hide,
            "fit": max(0, min(100, int(fit))) if isinstance(fit, (int, float)) else None,
            "reason": re.sub(r"\s+", " ", cols["ai_reason"] or "").strip(),
            "pros": _text_list(cols["ai_pros"]), "cons": _text_list(cols["ai_cons"]),
            "rights": cols["ai_rights"] or "none_stated", "rights_quote": re.sub(r"\s+", " ", cols["ai_quote"] or "").strip(),
            "seniority": cols["ai_seniority"] or "", "min_years": cols["ai_min_years"],
            "role_match": cols["ai_role_match"] or "", "ad_kind": cols["ai_ad_kind"] or "",
            "text_source": cols["ai_text_source"] or "", "flags": _text_list(cols["ai_flags"], 20, 60),
            "model": cols["ai_model"] or "", "reviewed_at": cols["ai_reviewed_at"] or ""}


# The deterministic pipeline (pipeline/, BUI-97/98) judges a job at its gate. Its verdict is shown in the same slots as
# the reader's: passed the gate = Good, archived = Hidden with the gate's reason, dead-lettered = held back. A job the
# pipeline has not judged yet (ingested / extracted / scored) keeps the reader's review, or waits.
PL_SHOW = ("shortlisted", "draft_queued", "drafted", "ready")
PL_HIDE_REASON = {"not_a_real_job": "not_a_real_job", "sponsored_ad": "sponsored_ad", "too_senior": "too_senior",
                  "not_relevant": "not_relevant", "excluded_by_rule": "excluded_by_rule", "prescreened": "prescreened",
                  "posting_closed": "posting_closed", "full_time_only": "full_time_only", "low_score": "low_fit", "not_target": "not_target",
                  "work_rights:citizen_or_pr": "needs_citizen_or_pr", "work_rights:citizen_only": "needs_citizen_or_pr",
                  "work_rights:clearance": "needs_citizen_or_pr",
                  "work_rights:unrestricted_work_rights": "needs_unrestricted_rights",
                  "work_rights:found_by_rule": "needs_unrestricted_rights"}
PL_MARKS = (("technical_skills", "Skills"), ("experience", "Experience"), ("domain", "Field"))


def ai_from_pipeline(r: dict) -> dict | None:
    """The pipeline's gate verdict in the shape ai_from_row returns, or None when the pipeline has not judged this
    job. Removes the raw pl_* columns from the row. data_json is untrusted text like any model output."""
    stage, raw, reason, at = (r.pop(k, None) for k in ("pl_stage", "pl_data", "pl_reason", "pl_at"))
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    part = lambda k: data.get(k) if isinstance(data.get(k), dict) else {}        # noqa: E731
    agentic = r.pop('_agentic_result', None)
    if agentic is not None or part('agentic'):
        return _ai_from_agentic(agentic, r['id'], at)
    if stage not in PL_SHOW and stage not in ("archived", "dlq"):
        return None
    facts, ev, form = part("extract"), part("evaluate"), part("form_map")
    rights = facts.get("work_rights") if isinstance(facts.get("work_rights"), dict) else {}
    marks = []
    for k, label in PL_MARKS:
        m = ev.get(k) if isinstance(ev.get(k), dict) else {}
        if isinstance(m.get("score"), int) and not isinstance(m.get("score"), bool):
            marks.append(f"{label} {m['score']}/5: {_line(m.get('evidence'), 280)}")
    why = (reason or "").strip()
    if stage in PL_SHOW:
        verdict, hide = "show", ""
    elif stage == "archived":
        verdict = "hide"
        hide = "duplicate" if why.startswith("duplicate_of:") else PL_HIDE_REASON.get(why, "other")
        kind = part("sort").get("not_target_kind")
        if hide == "not_target" and isinstance(kind, str) and (kind in NOT_TARGET_KEYS or kind == "too_senior"):
            hide = kind                                       # named by pipeline/nodes/sort.py (BUI-96)
    else:
        verdict, hide = "review", ""
    text = _line(ev.get("justification"), 600)
    if stage == "ready":
        left = form.get("owner_to_answer")
        text = ("Ready for you to submit by hand: CV, letter and form answers are drafted"
                + (f" ({left} for you to answer)" if isinstance(left, int) and left > 0 else "") + ". " + text)
    elif stage == "dlq":
        text = f"Held for a person to check ({_line(why, 120) or 'a step failed'}). " + text
    mn = facts.get("min_years")
    return {"score": _num(ev.get("overall")), "archetype": _line(facts.get("role_family"), 80), "legitimacy": "",
            "report": None, "verdict": verdict, "hide_reason": hide, "fit": None, "reason": text.strip(),
            "pros": marks, "cons": [],
            "rights": _enum_or(rights.get("requirement"), RIGHTS_TEXT, "none_stated"),
            "rights_quote": _line(rights.get("quote"), 400), "seniority": _enum_or(facts.get("seniority"), SENIORITY_TEXT, ""),
            "min_years": mn if isinstance(mn, int) and not isinstance(mn, bool) and mn > 0 else None,
            "role_match": "", "ad_kind": "", "text_source": WHOLE_SOURCE, "flags": [],
            "model": "pipeline", "reviewed_at": at or "", "stage": stage}


def _agentic_hold_reason(reason):
    return {"artifact_invalid": "The saved CV or letter files failed their check; they need to be made again.",
            "evaluation_unavailable": "The AI has not judged this ad yet.",
            "posting_closed": "This vacancy is closed.",
            "posting_unavailable": "Vacancy availability could not be verified.",
            "posting_identity_unverified": "The vacancy page could not be matched to this job.",
            "posting_check_required": "This vacancy needs a fresh availability check.",
            "snapshot_changed": "The job description changed; a fresh evaluation is needed.",
            "ad_has_ai_instructions": "Jev found hidden instructions aimed at AI in this ad. Not sent to the AI; check it yourself.",
            "draft_daily_limit": "Daily drafting limit reached. The evaluation is saved.",
            "draft_batch_limit": "Drafting limit for this run reached. The evaluation is saved."}.get(reason, reason)


def hold_words(reason):
    """A hold reason in words: the mapped sentence, else the code with its underscores removed."""
    said = _agentic_hold_reason(reason)
    return said if said != reason else str(reason or "").replace("_", " ").capitalize()


def _ai_from_agentic(result: dict | None, posting_id: int, at: str | None) -> dict:
    """Adapt a validated immutable evaluation to the existing cards/filter API."""
    from pipeline.agentic.contracts import AgenticEvaluation
    from pipeline.agentic.runtime import validate_model_payload
    result = result or {'status': 'held', 'reason': 'evaluation_unavailable'}
    evaluation = None
    if result.get('evaluation') is not None:
        try:
            checked = validate_model_payload(AgenticEvaluation, result['evaluation'])
            if checked.run_key.value == result.get('run_key') and checked.run_key.posting_id == posting_id:
                evaluation = checked
        except Exception:
            pass
    status, why = result.get('status'), result.get('reason')
    if evaluation is None:
        status = 'held'
        why = ('artifact_invalid' if result.get('evaluation') is not None else
               why if why and why != 'agentic_package_ready' else 'evaluation_unavailable')
    verdict = 'show' if status == 'ready' else 'hide' if status == 'archived' else 'review'
    package_ready = status == 'ready'
    text = _line(evaluation.report['A'], 600) if evaluation else ''
    if package_ready:
        text = 'Documents ready; open preparation to check the form. ' + text
    elif verdict == 'review':
        said = _agentic_hold_reason(why)
        if said != why:          # a raw code ("insufficient_evidence") says nothing; the AI's own words below do
            text = f"Held: {_line(said, 180).rstrip('.')}. " + text
    elif verdict == 'hide':
        text = f"Archived ({_line(why, 120)}). " + text
    if evaluation and verdict != 'hide':  # owner 2026-10-19: shown with a note instead of held
        notes = [n for n, on in (('Hours not stated: check they fit your availability', evaluation.facts.hours == 'unstated'),
                                 ('Level not stated', any('seniority unknown' in str(u).casefold() for u in
                                     (evaluation.matching_diagnostics or {}).get('ad_uncertainties', ()))),
                                 ('Employer not verified', evaluation.legitimacy != 'verified')) if on]
        if notes:
            text = '. '.join(notes) + '. ' + text
    facts = evaluation.facts.model_dump(mode='json') if evaluation else {}
    rights = facts.get('work_rights', {})
    marks = []
    if evaluation:
        for key, label in DIM_LABEL:
            dimension = evaluation.dimensions['compensation' if key == 'comp' else key]
            marks.append(f'{label} {dimension.score}/5: {_line(dimension.reason, 280)}')
    hide = {'score_below_threshold': 'low_fit', 'policy_excluded': 'not_target'}.get(why, why or 'other')
    return {'score': evaluation.global_score if evaluation else None,
            'archetype': _line(evaluation.archetype, 128) if evaluation else '',
            'legitimacy': {'verified': 'high', 'uncertain': 'caution', 'suspicious': 'suspicious'}.get(
                evaluation.legitimacy, '') if evaluation else '',
            'report': None, 'verdict': verdict, 'hide_reason': hide if verdict == 'hide' else '',
            'fit': None, 'reason': text.strip(), 'pros': marks, 'cons': [],
            'rights': _enum_or(rights.get('requirement'), RIGHTS_TEXT, 'none_stated'),
            'rights_quote': _line(rights.get('quote'), 400),
            'seniority': _enum_or(facts.get('seniority'), SENIORITY_TEXT, ''),
            'min_years': facts.get('min_years'), 'role_match': '', 'ad_kind': '',
            'text_source': WHOLE_SOURCE if evaluation else '', 'flags': [], 'model': 'Deep Agents',
            'reviewed_at': at or '', 'stage': 'ready' if package_ready else 'archived' if verdict == 'hide' else 'dlq',
            'package_ready': package_ready, 'form_ready': False, 'run_key': result.get('run_key')}


def _line(v, width: int = 300) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()[:width] if v is not None else ""


def _num(v):
    return round(max(1.0, min(5.0, float(v))), 1) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _enum_or(v, allowed, default):
    return v if isinstance(v, str) and v in allowed else default


def _report(raw) -> dict | None:
    """ad_reviews.report_json (the career-ops evaluation) as a clean dict for the templates, or None when there is
    none (rows read with the older prompt) or it is not an object. Whatever the JSON holds is treated as untrusted:
    every value is coerced to a plain string, number or listed code, so a bad row can never break a page."""
    try:
        d = json.loads(raw) if isinstance(raw, str) and raw.strip() else None
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    role = d.get("role") if isinstance(d.get("role"), dict) else {}
    leg = d.get("legitimacy") if isinstance(d.get("legitimacy"), dict) else {}
    comp = d.get("comp") if isinstance(d.get("comp"), dict) else {}
    auth = d.get("authorization") if isinstance(d.get("authorization"), dict) else {}
    dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
    reqs, gaps = [], []
    for x in (d.get("requirements") if isinstance(d.get("requirements"), list) else [])[:8]:
        if isinstance(x, dict) and _line(x.get("requirement"), 200):
            tier = _enum_or(x.get("tier"), TIER_TEXT, "inferred")
            reqs.append({"requirement": _line(x.get("requirement"), 200),
                         "importance": _enum_or(x.get("importance"), IMPORTANCE_TEXT, "meaningful"), "tier": tier,
                         "jd_signal": _line(x.get("jd_signal"), 300) if tier == "stated" else "",
                         "match": _enum_or(x.get("match"), MATCH_TEXT, "na"), "evidence": _line(x.get("evidence"), 300)})
    for x in (d.get("gaps") if isinstance(d.get("gaps"), list) else [])[:3]:
        if isinstance(x, dict) and _line(x.get("gap"), 200):
            gaps.append({"gap": _line(x.get("gap"), 200), "risk": _line(x.get("risk"), 300),
                         "mitigation": _line(x.get("mitigation"), 300)})
    signals = leg.get("signals") if isinstance(leg.get("signals"), list) else []
    mn = role.get("min_years")
    return {"archetype": _line(d.get("archetype"), 80), "tldr": _line(d.get("tldr"), 240),
            "not_target_kind": _enum_or(d.get("not_target_kind"), NOT_TARGET_KEYS, ""),
            "role": {"seniority": _enum_or(role.get("seniority"), SENIORITY_TEXT, ""),
                     "work_mode": _enum_or(role.get("work_mode"), WORK_MODE_TEXT, "unstated"),
                     "hours": _enum_or(role.get("hours"), HOURS_TEXT, "unstated"),
                     "location_fit": _enum_or(role.get("location_fit"), LOCATION_TEXT, ""),
                     "min_years": mn if isinstance(mn, int) and not isinstance(mn, bool) and mn > 0 else None},
            "requirements": reqs, "gaps": gaps,
            "dimensions": {k: _num(dims.get(k)) for k, _ in DIM_LABEL},
            "recommendation": _enum_or(d.get("recommendation"), REC_TEXT, ""),
            "legitimacy": {"tier": _enum_or(leg.get("tier"), LEGIT_TEXT, ""),
                           "signals": [t for t in (_line(g, 200) for g in signals[:6]) if t][:4]},
            "comp": {"company_type": _line(comp.get("company_type"), 80),
                     "reliability": _enum_or(comp.get("reliability"), ("High", "Medium", "Low", "Unknown"), "Unknown")},
            "authorization": {"requirement": _line(auth.get("requirement"), 40), "quote": _line(auth.get("quote"), 300)}}


def ai_state(ai: dict | None) -> str:
    """show | review | hide | pending. An unknown verdict is held back (review), never shown."""
    if ai is None:
        return "pending"
    if ai["verdict"] == "show" and ai.get("text_source") != WHOLE_SOURCE:    # a show from an ad not read whole is unproven
        return "review"
    return ai["verdict"] if ai["verdict"] in ("show", "hide") else "review"


def rec_key(r: dict) -> str:
    """The AI's recommendation for a row as a key of REC_WORDS, or ''. A held-back job (Not fully read) is never 'apply' or
    'consider': it shows 'hold' until the AI has read the whole ad."""
    rec = (((r.get("ai") or {}).get("report") or {}).get("recommendation")) or ""
    return "hold" if r.get("ai_state") == "review" and rec in ("apply", "consider") else rec if rec in REC_TEXT else ""


def dropped_by_title(conn, days: int = 7) -> list[dict]:
    """Postings the metadata prescreen skipped in the last `days` days (newest decision per posting, newest first)."""
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT p.id AS posting_id, p.title, p.company, d.reason, d.at AS decided_at FROM prescreen_decisions d "
        "JOIN postings p ON p.id = d.posting_id WHERE d.stage = 'metadata' AND d.outcome = 'skip' AND d.at >= ? "
        "AND d.id = (SELECT MAX(id) FROM prescreen_decisions WHERE posting_id = d.posting_id AND stage = 'metadata') "
        "ORDER BY d.at DESC, d.id DESC", (since,)).fetchall()
    return [dict(r) for r in rows]


def ai_progress(conn) -> dict:
    """How far the reader has got: matches read / all matches (the reader only reads matched postings)."""
    total = conn.execute("SELECT COUNT(DISTINCT posting_id) FROM matches").fetchone()[0]
    read = conn.execute("SELECT COUNT(DISTINCT m.posting_id) FROM matches m WHERE m.posting_id IN "
                        "(SELECT posting_id FROM ad_reviews UNION SELECT posting_id FROM pipeline_state "
                        "WHERE stage IN ('shortlisted','draft_queued','drafted','ready','archived','dlq'))").fetchone()[0]
    return {"read": read, "total": total, "left": max(0, total - read)}


def fit_score(r: dict) -> tuple[int, list[str]]:
    """Provisional keyword score (0-100). No LLM: arm tier, freshness, salary listed,
    warning flags, seen on several sources. Used only when the AI has not scored the ad (see enrich)."""
    pts, why = 0, []
    if r["arm_tier"] == "core":
        pts += 30
        why.append("core arm +30")
    elif r["arm_tier"] == "fallback":
        pts += 12
        why.append("fallback arm +12")
    age = r["age_days"]
    fresh = 20 if age <= 1 else 15 if age <= 3 else 10 if age <= 7 else 5 if age <= 14 else 0
    if fresh:
        pts += fresh
        why.append(f"fresh +{fresh}")
    if r["has_salary"]:
        pts += 10
        why.append("salary listed +10")
    if not r["warn"]:
        pts += 15
        why.append("no warning flags +15")
    else:
        pts -= 5 * len(r["warn"])
        why.append(f"{len(r['warn'])} warning flag(s) −{5 * len(r['warn'])}")
    extra = min(10, 5 * (len(r["srcs"]) - 1))
    if extra:
        pts += extra
        why.append(f"{len(r['srcs'])} sources +{extra}")
    return max(0, min(100, pts)), why


# predicates per facet (a row must pass all of them)
def _preds(f: Filters):
    """One predicate per active facet. Every lambda binds its own value as a default argument:
    a closure over a shared local would see whatever a later facet assigned to it."""
    p = {}
    if f.arm:
        p["arm"] = lambda r, s=frozenset(f.arm): (r["arm"] or "none") in s
    if f.tier:
        p["tier"] = lambda r, s=frozenset(f.tier): r["tier"] in s
    if f.src:
        p["src"] = lambda r, s=frozenset(f.src): bool(s.intersection(r["srcs"]))
    if f.sector:
        p["sector"] = lambda r, s=frozenset(f.sector): (r["sector"] or "unlisted") in s
    if f.within:
        p["within"] = lambda r, w=f.within: r["age_days"] <= w
    if f.arr:
        p["arr"] = lambda r, rem="remote" in f.arr, vic="vic" in f.arr: (rem and r["is_remote"]) or (vic and r["is_vic"])
    if f.wt:
        p["wt"] = lambda r, s=frozenset(f.wt): r["wt"] in s
    if f.sal or f.salmin:
        p["sal"] = lambda r, sal_floor=(f.salmin or 0) * 1000: (
            r["has_salary"] and (not sal_floor or (r["sal_year"] or 0) >= sal_floor))
    if f.entry:
        p["entry"] = lambda r: r["entry"]
    if f.hide:
        p["hide"] = lambda r, s=frozenset(f.hide): not (r["warn"] & s)
    if f.arch:
        p["arch"] = lambda r, s=frozenset(f.arch): r["archetype"] in s
    if f.minscore:
        p["minscore"] = lambda r, score_floor=f.minscore - 1e-9: r["score5"] is not None and r["score5"] >= score_floor
    if f.ai == "hide" and f.why:
        p["ai"] = lambda r, why=f.why: r["ai_state"] == "hide" and (r["ai"]["hide_reason"] or "other") == why
    else:
        p["ai"] = ((lambda r: r["ai_state"] in ("show", "review")) if f.ai == "worth"
                   else (lambda r, ai=f.ai: r["ai_state"] == ai))
    if f.st == "all":
        p["st"] = lambda r: r["status"] != "hidden"
    else:
        p["st"] = lambda r, st=f.st: r["status"] == st
    return p


def _tab_ok(r, st):
    return r["status"] != "hidden" if st == "all" else r["status"] == st


FACET_KEYS = ("arm", "tier", "src", "sector", "within", "arr", "wt", "sal", "entry", "hide", "st", "ai", "arch", "minscore")


def apply_filters(rows: list[dict], f: Filters) -> tuple[list[dict], dict[str, Counter]]:
    """Filtered rows + per-facet counts (each facet counted with every *other* filter applied)."""
    preds = _preds(f)
    counts = {k: Counter() for k in FACET_KEYS}
    counts["why"] = Counter()          # hidden-by-AI reasons (counted together with the "ai" facet)
    out = []
    names = list(preds)
    for r in rows:
        failed = [k for k in names if not preds[k](r)]
        if len(failed) > 1:
            continue
        if not failed:
            out.append(r)
            targets = FACET_KEYS
        else:
            targets = (failed[0],)
        for k in targets:
            c = counts[k]
            if k == "arm":
                c[r["arm"] or "none"] += 1
            elif k == "tier":
                c[r["tier"]] += 1
            elif k == "src":
                for s in r["srcs"]:
                    c[s] += 1
            elif k == "sector":
                c[r["sector"] or "unlisted"] += 1
            elif k == "within":
                for d, _ in WITHIN:
                    if r["age_days"] <= d:
                        c[d] += 1
            elif k == "arr":
                if r["is_remote"]:
                    c["remote"] += 1
                if r["is_vic"]:
                    c["vic"] += 1
            elif k == "wt":
                c[r["wt"]] += 1
            elif k == "sal":
                if r["has_salary"]:
                    c["sal"] += 1
            elif k == "entry":
                if r["entry"]:
                    c["entry"] += 1
            elif k == "hide":
                for w in r["warn"]:
                    c[w] += 1
            elif k == "st":
                c[r["status"]] += 1
                if r["status"] != "hidden":
                    c["all"] += 1
            elif k == "arch":
                if r["archetype"]:
                    c[r["archetype"]] += 1
            elif k == "minscore":
                for t in SCORE_FLOORS:
                    if r["score5"] is not None and r["score5"] >= t - 1e-9:
                        c[t] += 1
            elif k == "ai":
                c[r["ai_state"]] += 1
                if r["ai_state"] == "hide":
                    counts["why"][r["ai"]["hide_reason"] or "other"] += 1
    return out, counts


TABLE_SORT = {
    "fit": lambda r: r["score"], "title": lambda r: (r["title"] or "").lower(),
    "company": lambda r: (r["company"] or "").lower(), "location": lambda r: short_location(r["location"]).lower(),
    "arm": lambda r: r["arm"] or "", "tier": lambda r: r["tier"], "sector": lambda r: r["sector"],
    "sources": lambda r: len(r["srcs"]), "wt": lambda r: r["wt"], "salary": lambda r: r["sal_year"] or -1,
    "listed": lambda r: r["listed_dt"] or datetime.min.replace(tzinfo=UTC),
    "first_seen": lambda r: r["first_seen_at"] or "", "flags": lambda r: len(r["warn"]),
    "status": lambda r: r["status"], "id": lambda r: r["id"],
    "ai_fit": lambda r: r["score5"] if r["score5"] is not None else -1,
    "archetype": lambda r: (r["archetype"] or "~").lower(),
    "ai_view": lambda r: (AI_ORDER[r["ai_state"]], (r["ai"] or {}).get("hide_reason") or ""),
}
DEFAULT_DIR = {"fit": "desc", "ai_fit": "desc", "salary": "desc", "listed": "desc", "first_seen": "desc", "sources": "desc",
               "flags": "desc", "id": "desc"}


def sort_rows(rows: list[dict], sort: str, direction: str = "") -> list[dict]:
    if sort == "new":
        sort = "listed"
    key = TABLE_SORT.get(sort, TABLE_SORT["fit"])
    if sort not in TABLE_SORT:
        sort = "fit"
    desc = (direction or DEFAULT_DIR.get(sort, "asc")) == "desc"
    newest = TABLE_SORT["listed"]
    rows = sorted(rows, key=newest, reverse=True)                # stable tie-break: newest first
    return sorted(rows, key=key, reverse=desc)


def add_teasers(conn, rows: list[dict]) -> None:
    """r['teaser']: the first words of the description, only for rows the AI has not described (a card shows
    the AI's own reason when there is one)."""
    for r in rows:
        r["teaser"] = ""
    need = [r for r in rows if not (r.get("ai") and r["ai"]["reason"])]
    if not need:
        return
    ids = [r["id"] for r in need]
    got = {i: d for i, d in conn.execute(
        f"SELECT id, substr(description, 1, 600) FROM postings WHERE id IN ({','.join('?' for _ in ids)})", ids)}
    for r in need:
        r["teaser"] = teaser(got.get(r["id"]))


# -- board visit (NEW since last visit) ----------------------------------------------------------
VISIT_KEY = "web:board_visit"


def board_visit(conn, touch: bool = True, now: datetime | None = None) -> str | None:
    """Returns the previous visit stamp. A visit counts once per 30 minutes of inactivity."""
    now = now or datetime.now(UTC)
    v = dbm.get_state(conn, VISIT_KEY, {}) or {}
    prev, cur = v.get("prev"), v.get("cur")
    if touch:
        cur_dt = parse_ts(cur)
        if cur_dt is None or now - cur_dt > timedelta(minutes=30):
            prev = cur or dbm.ts(now - timedelta(days=1))
        dbm.set_state(conn, VISIT_KEY, {"prev": prev, "cur": dbm.ts(now)})
        conn.commit()
    return prev or dbm.ts(now - timedelta(days=1))


def mark_viewed(conn, posting_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO web_views(posting_id, first_viewed_at) VALUES(?, ?)",
                 (posting_id, dbm.ts()))
    conn.commit()


# -- saved searches ------------------------------------------------------------------------------
def saved_searches(conn, reg: Registry, cache: dict | None = None) -> list[dict]:
    cache = cache if cache is not None else {}
    out = []
    for s in conn.execute("SELECT * FROM saved_searches ORDER BY id").fetchall():
        try:
            params = json.loads(s["query_json"] or "{}")
        except ValueError:
            params = {}
        f = Filters.from_params(params)
        key = (f.scope, f.q, f.x)
        if key not in cache:
            cache[key] = load_rows(conn, f.scope, f.q, f.x, reg=reg)
        rows, _ = apply_filters(cache[key], f)
        since = s["last_visit_at"] or s["created_at"]
        new = sum(1 for r in rows if (r["added_at"] or "") > since)
        out.append({"id": s["id"], "name": s["name"], "query": f.query(), "total": len(rows), "new": new,
                    "summary": f.summary()})
    return out


# -- job detail ------------------------------------------------------------------------------------
def job_detail(conn, posting_id: int, reg: Registry) -> dict | None:
    rows = load_rows(conn, "all", ids=[posting_id], reg=reg)
    if not rows:
        return None
    r = rows[0]
    p = conn.execute("SELECT description, raw_json FROM postings WHERE id=?", (posting_id,)).fetchone()
    r["blocks"] = desc_blocks(p["description"])
    r["desc_truncated"] = len(p["description"] or "") >= 1990
    r["sightings"] = [dict(s) for s in conn.execute(
        "SELECT source, url, first_seen_at, last_seen_at, times_seen FROM sightings WHERE posting_id=? "
        "ORDER BY first_seen_at", (posting_id,))]
    m = conn.execute("SELECT * FROM matches WHERE posting_id=?", (posting_id,)).fetchone()
    r["rules"] = json.loads(m["rules_json"] or "{}") if m else {}
    r["arms"] = json.loads(m["arms_json"] or "[]") if m else []
    r["flag_reasons"] = flag_reasons(r, p["description"] or "")
    app = conn.execute("SELECT * FROM applications WHERE posting_id=?", (posting_id,)).fetchone()
    r["app"] = dict(app) if app else None
    r["events"] = [dict(e) for e in conn.execute(
        "SELECT at, kind, from_status, to_status, actor, source FROM application_events "
        "WHERE application_id=? ORDER BY at DESC, id DESC LIMIT 12", (app["id"],))] if app else []
    r["agentic"] = agentic_models(conn, [posting_id]).get(posting_id)
    return r


def _snippet(text: str, pattern: str | None, width: int = 90) -> str:
    if not pattern:
        return ""
    try:
        m = re.search(pattern, text, re.I)
    except re.error:
        return ""
    if not m:
        return ""
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if a else "") + re.sub(r"\s+", " ", text[a:b]).strip() + ("…" if b < len(text) else "")


def flag_reasons(r: dict, description: str) -> list[dict]:
    rules = r.get("rules") or {}
    text = plain_text(description)
    out = []
    for f in r["flags"]:
        kind = "warn" if f in ("work_rights_required", "full_time_only") or f.startswith("experience_years>=") \
            else ("good" if f == "entry_level" else "info")
        if f == "work_rights_required":
            pat = rules.get("work_rights_pattern")
            why = "The ad asks for specific work rights (citizenship, PR or a clearance)."
            snip = _snippet(text, pat)
        elif f == "full_time_only":
            why = ("Work type is listed as full-time" if r["wt"] == "FT"
                   else "The ad says full-time and offers no part-time, casual or job-share option") + "."
            snip = _snippet(text, r"\bfull[- ]?time\b")
        elif f.startswith("experience_years>="):
            yrs = rules.get("experience_years")
            why = f"The ad asks for {yrs} years' experience." if yrs else "The ad asks for 2+ years' experience."
            snip = _snippet(text, rf"\b{yrs}\s*\+?\s*(?:years?|yrs?)" if yrs else None)
        elif f == "entry_level":
            why = "Title or pay grade looks entry-level (graduate, junior, trainee, assistant, VPS 1-3…)."
            snip = ""
        elif f.startswith("via_"):
            why = f"Found through {f[4:].title()} (JobSpy)."
            snip = ""
        else:
            why, snip = "", ""
        out.append({"flag": f, "label": flag_label(f), "kind": kind, "why": why, "snippet": snip})
    return out


# -- agentic board models -------------------------------------------------------------------------
def _table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _json_object(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def agentic_models(conn, posting_ids: list[int] | None = None) -> dict[int, dict]:
    """Small display-only models from optional agentic tables. Never return prompt, profile, form values or file paths."""
    allowed = set(posting_ids) if posting_ids is not None else None
    rows = []
    if _table_exists(conn, "pipeline_state"):
        try:
            rows.extend(conn.execute("SELECT posting_id,stage,stage AS status,reason,data_json AS checkpoint_json FROM pipeline_state"))
        except Exception:
            pass
    if _table_exists(conn, "agentic_runs"):
        try:
            rows.extend(conn.execute("SELECT posting_id,status,reason,checkpoint_json FROM agentic_runs ORDER BY rowid"))
        except Exception:
            pass
    out = {}
    for row in rows:
        pid = row["posting_id"]
        if allowed is not None and pid not in allowed:
            continue
        checkpoint = _json_object(row["checkpoint_json"])
        # Pipeline state contains the last node's payload; synthesize stage-safe status without exposing it.
        if "stage" in row.keys():
            if row["status"] in ("draft_queued", "drafted", "ready"):
                status = "ready" if row["status"] == "ready" else "held"
            elif row["status"] in ("archived", "dlq"):
                status = "held"
            else:
                status = "claimed"
        else:
            status = row["status"] if row["status"] in ("ready", "held", "failed", "claimed", "new") else "held"
        evaluation = checkpoint.get("evaluate") if isinstance(checkpoint.get("evaluate"), dict) else {}
        dimensions = {}
        for key in ("technical_skills", "experience", "domain"):
            dim = evaluation.get(key)
            score = dim.get("score") if isinstance(dim, dict) else None
            if isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5:
                dimensions[key] = score
        reason = _line(evaluation.get("justification"), 600)
        # Avoid leaking contact details if a generated reason accidentally repeats them.
        reason = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[redacted]", reason, flags=re.I)
        reason = re.sub(r"(?:\+?\d[\d ()-]{7,}\d)", "[redacted]", reason)
        draft = checkpoint.get("draft") if isinstance(checkpoint.get("draft"), dict) else {}
        hold = _line(draft.get("hold"), 240)
        claims = draft.get("claims") if isinstance(draft.get("claims"), list) else []
        verified = sum(1 for claim in claims if isinstance(claim, dict) and claim.get("verified") is True)
        form = checkpoint.get("form_map") if isinstance(checkpoint.get("form_map"), dict) else {}
        hold = hold or (_line(row["reason"], 240) if row["status"] in ("held", "dlq", "failed") else "")
        hold = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[redacted]", hold, flags=re.I)
        out[pid] = {"status": status, "reason": reason, "dimensions": dimensions, "hold": hold,
                    "verified_claims": verified, "claim_count": len(claims),
                    "hold_count": int(form.get("owner_to_answer", 0)) if isinstance(form.get("owner_to_answer", 0), int) else 0}
    # New runs store budget checkpoints separately from immutable evaluation artifacts.
    if _table_exists(conn, "agentic_artifacts") and _table_exists(conn, "agentic_packages"):
        from pipeline.agentic.persistence import latest_result
        ids = allowed if allowed is not None else {r[0] for r in conn.execute("SELECT DISTINCT posting_id FROM agentic_runs")}
        for pid in ids:
            try:
                result = latest_result(conn, pid)
            except Exception:
                continue
            if not result:
                continue
            evaluation = result.get("evaluation") or {}
            report = evaluation.get("report") or {}
            reason = _line(report.get("A"), 600)
            reason = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[redacted]", reason, flags=re.I)
            reason = re.sub(r"(?:\+?\d[\d ()-]{7,}\d)", "[redacted]", reason)
            dimensions = {k: d["score"] for k, d in (evaluation.get("dimensions") or {}).items()
                          if isinstance(d, dict) and type(d.get("score")) in (int, float) and 1 <= d["score"] <= 5}
            hold = hold_words(result["reason"])
            out[pid] = {"status": result["status"], "reason": reason, "dimensions": dimensions,
                        "hold": hold if result["status"] != "ready" else "", "claim_count": 0,
                        "verified_claims": 0, "hold_count": (result.get("manifest") or {}).get("owner_to_answer", 0),
                        "global_score": evaluation.get("global_score"), "has_evaluation": bool(evaluation)}
    return out


# -- applications ----------------------------------------------------------------------------------
def applications(conn, drafts_root: Path, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    rows = conn.execute(
        """SELECT a.*, p.title, p.company, p.location, p.url,
                  (SELECT MAX(e.at) FROM application_events e WHERE e.application_id=a.id) AS last_event_at,
                  (SELECT e.kind || '|' || COALESCE(e.to_status,'') || '|' || COALESCE(e.from_status,'')
                     FROM application_events e WHERE e.application_id=a.id ORDER BY e.at DESC, e.id DESC LIMIT 1)
                     AS last_event,
                  (SELECT d.status || '|' || COALESCE(d.dir,'') || '|' || d.version FROM drafts d
                     WHERE d.application_id=a.id ORDER BY d.version DESC LIMIT 1) AS draft
           FROM applications a JOIN postings p ON p.id=a.posting_id
           ORDER BY a.updated_at DESC""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        kind, to_s, from_s = (d["last_event"] or "||").split("|")[:3]
        d["event_text"] = _event_text(kind, from_s, to_s)
        last = d["last_event_at"] or d["updated_at"]
        d["last_at"] = last
        d["days_applied"] = days_since(d["applied_at"], now) if d["applied_at"] else None
        from jobwatch.followup.events import application_cadence, recent_events, FollowupEventError
        import uuid
        d['followup_history'] = {'total': 0, 'items': []}
        try:
            followup = application_cadence(conn, d['id'], now=now)
            d['followup_history'] = recent_events(conn, d['id'])
            d['followup'] = {'state': followup.state, 'kind': followup.kind,
                'due_on': followup.due_on.isoformat() if followup.due_on else None,
                'sent_count': followup.sent_count, 'reason': followup.reason}
        except FollowupEventError:
            d['followup'] = {'state': 'unknown', 'kind': 'application', 'due_on': None,
                             'sent_count': None, 'reason': 'history_unverified'}
        d['followup_operation'] = uuid.uuid4().hex
        d["files"] = draft_files(d["draft"], drafts_root)
        d["draft_state"] = (d["draft"] or "").split("|")[0] or None
        out.append(d)
    models = agentic_models(conn, [d["posting_id"] for d in out])
    for d in out:
        d["agentic"] = models.get(d["posting_id"])
    return out


def _event_text(kind, from_s, to_s) -> str:
    followup_labels = {'followup_sent': 'Follow-up sent', 'followup_pin': 'Reminder date set',
                       'followup_clear_pin': 'Standard reminder timing restored',
                       'followup_response': 'Reply received',
                       'followup_interview_completed': 'Interview completed',
                       'followup_applied_confirmed': 'Application date confirmed'}
    if kind in followup_labels:
        return followup_labels[kind]
    if kind in ("status", "outcome_decided") and to_s:
        lab = STATE_LABEL.get(to_s, to_s)
        return f"{'Mail outcome: ' if kind == 'outcome_decided' else ''}→ {lab}"
    if kind == "command":
        return "Draft requested"
    if kind == "draft":
        return "Draft update"
    if kind == "outcome_proposed":
        return "Outcome proposed"
    return kind or "Created"


def draft_files(draft: str | None, drafts_root: Path) -> dict:
    if not draft:
        return {}
    status, ddir, _ = (draft.split("|") + ["", ""])[:3]
    if status != "ready" or not ddir:
        return {}
    out = {}
    root = drafts_root.resolve()
    for key, name in (("cv", "cv.pdf"), ("letter", "letter.pdf"), ("summary", "summary.md")):
        p = Path(ddir) / name
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            continue
        if p.is_file():
            out[key] = "/files/drafts/" + rel.as_posix()
    return out


# -- inbox -------------------------------------------------------------------------------------------
def proposals(conn, open_only: bool = True) -> list[dict]:
    where = "o.status='proposed'" if open_only else "o.status<>'proposed'"
    rows = conn.execute(
        f"""SELECT o.*, a.status AS app_status, a.posting_id, p.title, p.company FROM outcome_proposals o
            LEFT JOIN applications a ON a.id=o.application_id LEFT JOIN postings p ON p.id=a.posting_id
            WHERE {where} ORDER BY COALESCE(o.received_at, o.decided_at) DESC LIMIT 50""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            ev = json.loads(d.get("evidence_json") or "{}")
        except ValueError:
            ev = {}
        d["evidence"] = (ev.get("snippet") or ev.get("evidence") or "")[:200] if isinstance(ev, dict) else ""
        d["ev_flags"] = ev.get("flags") or [] if isinstance(ev, dict) else []
        d["method"] = ev.get("method") or ev.get("classifier") or "" if isinstance(ev, dict) else ""
        out.append(d)
    return out


# -- sources -----------------------------------------------------------------------------------------
def health_rows(conn, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    out = []
    for r in conn.execute("SELECT * FROM source_health ORDER BY collector"):
        d = dict(r)
        last_ok = parse_ts(d["last_ok_at"])
        hours = (now - last_ok).total_seconds() / 3600 if last_ok else None
        fails = d["consecutive_failures"] or 0
        if fails >= 3 or last_ok is None or (hours is not None and hours > 48):
            d["rag"] = "bad"
        elif fails or (hours is not None and hours > 6) or d["last_status"] == "partial":
            d["rag"] = "warn"
        else:
            d["rag"] = "ok"
        d["label"] = src_label(d["collector"])
        out.append(d)
    order = {"bad": 0, "warn": 1, "ok": 2}
    return sorted(out, key=lambda d: (order[d["rag"]], d["collector"]))


def employer_rows(conn, reg: Registry, sector: str = "", enabled: str = "") -> list[dict]:
    since = dbm.ts(datetime.now(UTC) - timedelta(days=7))
    live = {r[0]: (r[1], r[2]) for r in conn.execute(
        """SELECT p.origin, COUNT(*), COUNT(m.id) FROM postings p LEFT JOIN matches m ON m.posting_id=p.id
           WHERE p.last_seen_at>=? GROUP BY p.origin""", (since,))}
    out = []
    for e in reg.employers:
        if sector and str(e.get("sector") or "other") != sector:
            continue
        en = bool(e.get("enabled", True))
        if enabled == "1" and not en or enabled == "0" and en:
            continue
        vc = e.get("verified_counts") or {}
        now_n, match_n = live.get(e.get("name"), (0, 0))
        out.append({"name": e.get("name"), "sector": e.get("sector") or "other",
                    "provider": e.get("provider") or e.get("platform") or "—", "enabled": en,
                    "vc_total": vc.get("total"), "vc_au": vc.get("au"), "vc_vic": vc.get("vic"),
                    "live": now_n, "matches": match_n, "notes": str(e.get("notes") or "")[:400],
                    "verified_at": str(e.get("verified_at") or "")[:10], "scope": e.get("au_scope") or ""})
    return out


# -- nav badges ---------------------------------------------------------------------------------------
def nav_counts(conn) -> dict:
    inbox = conn.execute("SELECT COUNT(*) FROM outcome_proposals WHERE status='proposed'").fetchone()[0]
    apps = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status NOT IN ('skipped','rejected','withdrawn')").fetchone()[0]
    rows = health_rows(conn)                     # the same rule the Sources page uses, so the badge and the page agree
    bad = sum(1 for r in rows if r["rag"] == "bad")
    seen = len(rows)
    try:
        paused = conn.execute("SELECT COUNT(*) FROM agentic_incidents WHERE state='paused'").fetchone()[0]
    except sqlite3.Error:
        paused = 0
    from jobwatch.notify import unread
    return {"inbox": inbox, "applications": apps, "sources_bad": bad, "sources_seen": seen, "paused": paused, "chat": unread(conn)}


# -- insights -------------------------------------------------------------------------------------------
def insights(conn, reg: Registry, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since30 = dbm.ts(now - timedelta(days=30))
    # new matches per day in the person's timezone, last 30 days
    tz = _tz()
    per_day = Counter()
    for (at,) in conn.execute("SELECT matched_at FROM matches WHERE matched_at>=?", (since30,)):
        dt = parse_ts(at)
        if dt:
            per_day[dt.astimezone(tz).date()] += 1
    today = now.astimezone(tz).date()
    days = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
    series = [(d, per_day.get(d, 0)) for d in days]
    by_arm = conn.execute("SELECT arm, arm_tier, COUNT(*) FROM matches GROUP BY arm ORDER BY 3 DESC").fetchall()
    by_src = conn.execute("SELECT p.source, COUNT(*) FROM matches m JOIN postings p ON p.id=m.posting_id "
                          "GROUP BY p.source ORDER BY 2 DESC").fetchall()
    sec = Counter()
    for o, c in conn.execute("SELECT p.origin, p.company FROM matches m JOIN postings p ON p.id=m.posting_id"):
        sec[reg.sector(o, c) or "not in registry"] += 1
    top = conn.execute(
        """SELECT COALESCE(NULLIF(p.origin,''), p.company, '?') AS emp, COUNT(*) AS n, COUNT(m.id) AS mn
           FROM postings p LEFT JOIN matches m ON m.posting_id=p.id
           WHERE p.last_seen_at>=? GROUP BY emp ORDER BY n DESC LIMIT 15""", (since30,)).fetchall()
    rem_m = conn.execute("SELECT COUNT(*), COALESCE(SUM(p.remote),0) FROM matches m JOIN postings p "
                         "ON p.id=m.posting_id").fetchone()
    rem_a = conn.execute("SELECT COUNT(*), COALESCE(SUM(remote),0) FROM postings").fetchone()
    totals = {"postings": rem_a[0], "matches": rem_m[0],
              "matches_30d": sum(per_day.values()),
              "matches_7d": sum(n for d, n in series[-7:]),
              "employers_live": conn.execute("SELECT COUNT(DISTINCT origin) FROM postings WHERE last_seen_at>=?",
                                             (dbm.ts(now - timedelta(days=7)),)).fetchone()[0]}
    from ..digest import gather
    from ..outcomes.callback import PRIOR_A, PRIOR_B, callback_stats
    g = gather(conn, days=30, now=now)
    cb = callback_stats(conn)
    return {"series": series, "by_arm": [(a, t, n) for a, t, n in by_arm], "by_src": [tuple(r) for r in by_src],
            "by_sector": sec.most_common(), "top": [tuple(r) for r in top],
            "remote": {"matches": (rem_m[1], rem_m[0]), "all": (rem_a[1], rem_a[0])},
            "themes": g["themes"], "by_subreddit": g["by_subreddit"], "reddit_top": g["top"][:5],
            "chatter_total": g["chatter_total"], "hiring_posts": g["hiring_posts"],
            "callbacks": cb, "prior_mean": PRIOR_A / (PRIOR_A + PRIOR_B), "totals": totals}
