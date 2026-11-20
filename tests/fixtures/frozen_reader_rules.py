"""The three work-rights rule functions of the retired AI ad reader, vendored for the frozen 2026-10-22 gate fixture
(tests/fixtures/frozen_person_gate_20261022.py). Frozen: do not change; the gate comparison depends on them."""
from __future__ import annotations

import re
import unicodedata
from jobwatch.models import fold
from jobwatch.adscan import _CITIZEN_PATTERNS, _CLEARANCE_PATTERNS, _UNRESTRICTED_PATTERNS, _resolve_ongoing, _scan_full


_NOT_TEXT = re.compile(r"[^a-z0-9]+")

def _tokens(text) -> list[str]:
    """Lower-case words with punctuation, markdown, curly quotes, dashes and ellipses ignored."""
    return _NOT_TEXT.sub(" ", fold(unicodedata.normalize("NFKC", str(text or "")))).split()

_RIGHTS_PATTERNS = _CITIZEN_PATTERNS + _CLEARANCE_PATTERNS

def _scan(text: str, patterns, citizenship: bool = True) -> list[tuple[str, str]]:
    return [(s, seg[:240]) for s, seg in _scan_full(text, patterns, citizenship)]

def rights_backstop(text: str, title: str = "") -> str | None:
    """A plain statement of citizenship/PR/clearance in the ad, found by regex. Returns the sentence."""
    haystack = f"{title}\n{text or ''}"
    found, _ = _resolve_ongoing(haystack, title, _scan_full(haystack, _RIGHTS_PATTERNS))
    return next((seg for status, seg in found if status == "hit" and not _VISA_WELCOME.search(seg)), None)

# "If you are not a citizen or permanent resident please provide details of your visa" invites visa holders: it is not
# a citizenship requirement (2026-10-12 one-off task: a casual Data Entry Clerk ad was archived on it).
_VISA_WELCOME = re.compile(r"\bif\s+you\s+are\s+not\s+(?:an?\s+)?(?:australian\s+)?citizen|\bnon[- ]citizens?\b[^.]{0,60}"
                           r"\b(?:welcome|encouraged|eligible|may apply)|\bprovide\s+(?:details\s+of\s+)?your\s+visa", re.I)

def unrestricted_backstop(text: str, title: str = "") -> str | None:
    for status, seg in _scan(f"{title}\n{text or ''}", _UNRESTRICTED_PATTERNS, citizenship=False):
        if status == "hit":
            return seg
    return None

# what makes a model's quote a rights claim when no rule corroborates it: a blocking construction, not just a word like "Commonwealth"
_BLOCKING_QUOTE = re.compile(
    r"\bcitizens?\b|\bcitizenship\b|\bpermanent\s+residen(?:t|ts|cy|ce)\b|\bprs?\b|\bnv\s*-?\s*[12]\b|\bbaseline\b|"
    r"\b(?:negative|positive)\s+vetting\b|\bsecurity\s+(?:clearance|vetting)\b|\bagsva\b|\btop\s+secret\b|\bpv\s+clearance\b|"
    r"\b(?:unrestricted|unlimited|full)\s+(?:\w+\s+){0,3}(?:work|working|rights?|residen\w+)\b|\bel\s?[12]\b|\baps\s*(?:level\s*)?[1-6]\b|"
    r"\baustralian\s+public\s+service\b|"
    # wordings the model catches in real ads that no rule does: "permanent right to work". "Only open to Australian residents"
    # is NOT one: it asks where the candidate lives, not for citizenship
    r"\bpermanent\s+(?:\w+\s+){0,2}(?:rights?\s+to\s+work|work(?:ing)?\s+rights?)\b", re.I)

def blocking_quote(quote: str) -> bool:
    """A quote that can carry a work-rights claim by itself: at least 12 characters after normalising, and one of the blocking
    constructions. 'Commonwealth Bank', 'permanent position' or 'Security Officer' are not."""
    q = " ".join(_tokens(quote))
    return len(q) >= 12 and bool(_BLOCKING_QUOTE.search(q))
