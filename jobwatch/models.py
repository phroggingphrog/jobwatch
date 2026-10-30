"""The Posting model, URL canonicalisation and small text/date/location helpers."""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTC = timezone.utc

# Query parameters that only track the click; dropped from canonical URLs.
TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|fbclid|msclkid|mc_[a-z]+|_hs[a-z]+|ref|refid|referrer|source|src|"
    r"trk|trkinfo|trackingid|tracking|origin|campaign|cmp|cid|sid|lipi|position|pagenum|"
    r"searchrequesttoken|tk|from|vjk|advn|ad|sjdu|acatk|pub|xpse|xfps|xkcb)$",
    re.I,
)


@dataclass
class Posting:
    source: str                      # collector name, e.g. "seek", "ats_greenhouse"
    source_id: str                   # stable id within the source
    url: str
    title: str
    company: str = ""
    location: str = ""
    state: str | None = None         # AU state code (VIC, NSW, ...) when known
    remote: bool = False
    work_type: str | None = None     # FT | PT | casual | contract | temp | intern
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_unit: str | None = None   # hour | day | week | month | year
    posted_at: str | None = None     # ISO-8601 UTC
    posted_at_source: str = "observed"  # provider | observed
    description: str = ""            # plain text snippet, <= 2000 chars
    raw: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    origin: str = ""                 # employer / feed / search that produced it
    classification: str | None = None  # pay grade / classification (e.g. "VPS 3"); seniority input

    def __post_init__(self) -> None:
        self.url = canonical_url(self.url)
        self.title = clean_text(self.title)[:300]
        self.company = clean_text(self.company)[:200]
        self.location = clean_text(self.location)[:200]
        self.description = (self.description or "")[:2000]
        self.source_id = str(self.source_id)
        if self.state is None:
            self.state = state_of(self.location)
        if self.posted_at is None:
            self.posted_at = now_utc().isoformat(timespec="seconds")
            self.posted_at_source = "observed"

    def to_dict(self) -> dict:
        return asdict(self)

    def raw_json(self) -> str:
        return json.dumps(self.raw, default=str, ensure_ascii=False)[:200_000]


def now_utc() -> datetime:
    return datetime.now(UTC)


# URLs
def canonical_url(url: str) -> str:
    """Lower-case scheme/host, drop fragment and tracking params, sort the rest."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not TRACKING_PARAMS.match(k)]
    query.sort()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:32]


# Text
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|br|li|div|h[1-6]|tr|ul|ol)[^>]*>", re.I)
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)


def html_to_text(value: Any, limit: int = 2000) -> str:
    """Strip HTML (unescaping once or twice) into compact plain text."""
    if value is None:
        return ""
    text = str(value)
    if "&lt;" in text and "<" not in text:
        text = html.unescape(text)
    text = _SCRIPT.sub(" ", text)
    text = _BLOCK.sub("\n", text)
    text = html.unescape(_TAG.sub(" ", text))
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return text[:limit]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Lower-case and strip accents (café -> cafe)."""
    norm = unicodedata.normalize("NFD", text or "")
    return re.sub(r"[̀-ͯ]", "", norm).lower()


# Dates
def parse_date(value: Any) -> datetime | None:
    """ISO strings, RFC-822 strings, epoch seconds/ms -> aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, UTC)
    text = str(value).strip()
    if re.fullmatch(r"\d{10,13}", text):
        return parse_date(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" +", "+"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        parsed = parsedate_to_datetime(text)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%d %b %Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            continue
    return None


def iso(value: Any) -> str | None:
    parsed = parse_date(value)
    return parsed.isoformat(timespec="seconds") if parsed else None


def relative_posted(text: str, now: datetime | None = None) -> datetime | None:
    """'Posted Today' / 'Posted 3 Days Ago' / '18h ago' -> approximate datetime."""
    now = now or now_utc()
    low = (text or "").lower()
    if "today" in low or "just" in low:
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(m|min|minute|h|hr|hour|d|day|w|week|mo|month)s?\b", low)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit in ("m", "min", "minute"):
        return now - timedelta(minutes=n)
    if unit in ("h", "hr", "hour"):
        return now - timedelta(hours=n)
    if unit in ("d", "day"):
        return now - timedelta(days=n)
    if unit in ("w", "week"):
        return now - timedelta(weeks=n)
    return now - timedelta(days=30 * n)


# Location: AU gate and state detection
AU_CITIES = (
    "Melbourne|Sydney|Brisbane|Perth|Adelaide|Canberra|Darwin|Hobart|Gold Coast|Geelong|"
    "Newcastle|Wollongong|Townsville|Cairns|Ballarat|Bendigo|Launceston|Toowoomba|"
    "Sunshine Coast|Shepparton|Mildura|Warrnambool|Wodonga|Albury|Traralgon|Parramatta"
)
AU_STATE_NAMES = (
    "Victoria|New South Wales|Queensland|Tasmania|Western Australia|South Australia|"
    "Australian Capital Territory|Northern Territory"
)
_AU_TEXT = re.compile(rf"\b(Australia|Australian|{AU_CITIES}|{AU_STATE_NAMES})\b", re.I)
# A state code counts when it follows a comma/space and/or precedes a postcode.
_AU_STATE_CODE = re.compile(r"(?:,\s*|\s)(VIC|NSW|QLD|WA|SA|TAS|ACT|NT)\b(?:\s+\d{4})?|\b(VIC|NSW|QLD|TAS)\b")
_NOT_AU = re.compile(r"\b(Florida|FL|British Columbia|BC|Canada|USA|United States|U\.S\.)\b|"
                     r"\b(?i:Nigeria|Lagos|Seychelles|Nova Scotia|Scotland(?! Island)|(?<!New )England|Newcastle[ -]upon[ -]Tyne)\b")
COUNTRY_AU = {"au", "aus", "australia"}

_STATE_PATTERNS = [
    ("VIC", re.compile(r"\b(VIC|Melbourne|Geelong|Ballarat|Bendigo|Shepparton|Mildura|"
                       r"Warrnambool|Wodonga|Traralgon|Mornington|Dandenong|Frankston|Footscray|"
                       r"Richmond VIC|Docklands|Southbank|Carlton|Clayton|Box Hill|Ringwood|"
                       r"Sunshine(?! Coast)|Werribee|Craigieburn|Epping VIC|Heidelberg|Melton|Pakenham)\b", re.I)),
    ("NSW", re.compile(r"\b(NSW|New South Wales|Sydney|Newcastle|Wollongong|Parramatta|Albury)\b", re.I)),
    ("QLD", re.compile(r"\b(QLD|Queensland|Brisbane|Gold Coast|Sunshine Coast|Townsville|Cairns|Toowoomba)\b", re.I)),
    ("WA", re.compile(r"\b(WA|Western Australia|Perth)\b")),
    ("SA", re.compile(r"\b(SA|South Australia|Adelaide)\b")),
    ("TAS", re.compile(r"\b(TAS|Tasmania|Hobart|Launceston)\b", re.I)),
    ("ACT", re.compile(r"\b(ACT|Australian Capital Territory|Canberra)\b")),
    ("NT", re.compile(r"\b(NT|Northern Territory|Darwin)\b")),
]
# Weak VIC evidence, used only when no other state is named: "Victoria" ("Victoria Park WA") and a bare 3xxx
# postcode (not "MH 3000", not NZ).
_VIC_WEAK = re.compile(r"\bVictoria\b|(?<![\w$.,/-])3\d{3}\b(?![.,]?\d)", re.I)
_FOREIGN_POSTCODE = re.compile(r"(?<![A-Za-z])(?!VIC\b)[A-Z]{2} 3\d{3}\b|\b(?:New Zealand|NZ)\b")


def state_of(location: str | None) -> str | None:
    """First AU state code evidenced by the location text, else None."""
    text = location or ""
    if not text or _NOT_AU.search(text):
        return None
    for code, pattern in _STATE_PATTERNS:
        if pattern.search(text):
            return code
    return "VIC" if _VIC_WEAK.search(text) and not _FOREIGN_POSTCODE.search(text) else None


def is_australian(country: Any = None, *texts: Any) -> bool:
    """AU gate: a structured country must be AU; otherwise text must show AU evidence."""
    if isinstance(country, dict):
        country = country.get("alpha2Code") or country.get("code") or country.get("name") or country.get("descriptor")
    if country not in (None, ""):
        return str(country).strip().lower() in COUNTRY_AU
    blob = " ".join(str(t) for t in texts if t)
    if not blob or _NOT_AU.search(blob):
        return False
    return bool(_AU_TEXT.search(blob) or _AU_STATE_CODE.search(blob))


# Work type and salary
def work_type_of(*values: Any) -> str | None:
    text = " ".join(str(v) for v in values if v).lower().replace("_", " ")
    if not text:
        return None
    if re.search(r"\bcasuals?\b", text):
        return "casual"
    if re.search(r"\bpart[ -]?time\b", text):
        return "PT"
    if re.search(r"\bintern(?:ship)?s?\b", text):
        return "intern"
    if re.search(r"\bcontract(?:or|ing)?\b|\bfixed[ -]?term\b", text):
        return "contract"
    if re.search(r"\btemp(?:s|orary)?\b", text):
        return "temp"
    if re.search(r"\b(?:full[ -]?time|permanent)\b", text):
        return "FT"
    return None


def salary_from_text(text: str | None) -> tuple[float | None, float | None, str | None]:
    """'$70,000 - $80,000 + super' -> (70000, 80000, 'year'); '$32 per hour' -> hour."""
    if not text:
        return None, None, None
    nums = []
    for raw, k in re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?", text, re.I):
        value = float(raw.replace(",", ""))
        nums.append(value * 1000 if k else value)
    if not nums:
        return None, None, None
    low = text.lower()
    if re.search(r"per hour|p/h|/hr|an hour|hourly|\bp\.?h\b", low):
        unit = "hour"
    elif re.search(r"per day|daily|p/d", low):
        unit = "day"
    elif re.search(r"per week|weekly", low):
        unit = "week"
    elif re.search(r"per month|\d[\d,.]*k?\s*a month|/mth|/month|\bp/m\b|\bpcm\b", low):   # "a month" only after an amount
        unit = "month"
    elif max(nums) < 200:
        unit = "hour"
    else:
        unit = "year"
    return min(nums), max(nums), unit
