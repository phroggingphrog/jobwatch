"""Offline geographic evidence for exact cited job locations.

Australia only for now. The bundled place data is Victorian; the person's state comes from their profile
(jobwatch.util.place.person_state). VIC: the place data is used. Another state: the state code/name in the text is
matched and distance is unknown. No state known: no area filter.

Locality names alone do not resolve interstate or metro/regional ambiguity.
The bundled government reference is versioned with each decision run.
"""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import re

_REFERENCE_BYTES = files('pipeline.agentic').joinpath('data/metro-localities.json').read_bytes()
LOCATION_REFERENCE_HASH = hashlib.sha256(_REFERENCE_BYTES).hexdigest()
_REFERENCE = json.loads(_REFERENCE_BYTES)
_METRO = frozenset(_REFERENCE['localities']) - frozenset(_REFERENCE['ambiguous_localities'])
_OTHER_JURISDICTION = re.compile(
    r'\b(?:NSW|QLD|WA|SA|TAS|(?-i:ACT)|NT|New South Wales|Queensland|Western Australia|'
    r'South Australia|Tasmania|Northern Territory|Australian Capital Territory|'
    r'Florida|FL|USA|(?-i:US)|United States|Canada|UK|United Kingdom|New Zealand)\b', re.I)
_LOCALITY = re.compile(
    r'(?:location\s*:\s*)?([a-z][a-z ’\'-]*?)\s*,?\s+(?:vic|victoria)'
    r'(?:\s*,?\s+(?:au|australia))?(?:\s*,?\s+3\d{3})?'
    r'(?:\s*,?\s+(?:au|australia))?\.?', re.I)


def _state() -> str | None:
    try:
        from jobwatch.util.place import person_state
        return person_state()
    except Exception:  # noqa: BLE001 - no profile: no area filter
        return None


def _names_state(text: str, codes) -> bool:
    from jobwatch.util.place import STATES
    return any(re.search(rf'(?-i:\b{c}\b)', text) or re.search(rf'\b{STATES[c]}\b', text, re.I) for c in codes)


def _own_state_cited(quote: str, state: str | None) -> bool:
    """Non-VIC person: True when the text names their state, or when no state is known (no filter)."""
    if state is None:
        return True
    from jobwatch.util.place import STATES
    text = ' '.join((quote or '').split())
    if not _names_state(text, [state]):
        return False
    if _names_state(text, [c for c in STATES if c != state]):
        return bool(re.search(r';|/|\||\bor\b', text, re.I))  # "Perth WA; Sydney NSW": open to either
    return True


def cited_melbourne_location(quote: str) -> bool:
    """Accept metro evidence; caller separately verifies quote/source hash.

    Preserve explicit Melbourne evidence, reject conflicting jurisdictions,
    and recognise structured locality+Victoria citations by exact membership.
    Postcodes are optional syntax, never an independent eligibility signal.
    """
    if _state() != 'VIC':
        return _own_state_cited(quote, _state())
    if _OTHER_JURISDICTION.search(quote) or re.search(r',\s*(?:us|act)\b', quote, re.I):
        # A list of alternatives that includes Melbourne ("Melbourne, VIC; Sydney, NSW") is open to Melbourne.
        return bool(re.search(r'\bMelbourne\b', quote, re.I) and re.search(r';|/|\||\bor\b', quote, re.I))
    if re.search(r'\bMelbourne\b', quote, re.I):
        return True
    matched = _LOCALITY.fullmatch(' '.join(quote.split()))
    if matched and matched.group(1).casefold().strip() in _METRO:
        return True
    # A metro suburb named in a sentence: "Based in Glen Iris, Victoria", "at Epworth Eastern in Box Hill",
    # "Sunningdale Avenue Children's Centre, Sunbury" (2026-10-12: these held real Melbourne jobs).
    return bool(_IN_SENTENCE.search(' '.join(quote.split())))


# Suburb names that are also ordinary words never count inside a sentence (they still count as "Suburb, VIC").
_GENERIC = frozenset({'officer', 'plenty', 'research', 'reservoir', 'sunshine', 'waterways', 'emerald', 'clematis',
                      'cockatoo', 'bittern', 'rye', 'batman', 'skye', 'silvan', 'patterson', 'dallas', 'doreen'})
_IN_SENTENCE = re.compile(
    r'(?:\b(?:in|at)\s+|,\s*)(?:' + '|'.join(re.escape(name.title()) for name in
                                    sorted(_METRO - _GENERIC, key=len, reverse=True)) +
    r')(?=\s*(?:[,.;)]|$))')


# --- Victoria-wide scope and commute distance (owner, 2026-10-12: "just focus on Victoria and check about the KMs") ---
import functools
import math

_GEO = json.loads(files('pipeline.agentic').joinpath('data/vic-geo.json').read_bytes())
VIC_PLACES: dict = _GEO['localities']
_GENERIC_VIC = frozenset(_GEO['generic_words'])
_PLACE_NAMES = sorted(VIC_PLACES, key=len, reverse=True)
# "Glen Iris, VIC" / "Shepparton Victoria" / "Donvale, Victoria, Australia": any place, generic words included.
_VIC_STRUCTURED = re.compile(r'\b(' + '|'.join(re.escape(n) for n in _PLACE_NAMES) + r')\s*,?\s+(?:vic|victoria)\b', re.I)
# A place named in a sentence: "Based in Glen Iris", "at Epworth Eastern in Box Hill", "...Centre, Sunbury".
_VIC_IN_SENTENCE = re.compile(r'(?:\b(?:in|at)\s+|,\s*)(' + '|'.join(
    re.escape(n.title()) for n in _PLACE_NAMES if n not in _GENERIC_VIC) + r')(?=\s*(?:[,.;)|]|$))')
# A place named before a workplace word: "our vibrant Preston Support Office", "Box Hill campus".
_VIC_WORKPLACE = re.compile(r'\b(' + '|'.join(re.escape(n.title()) for n in _PLACE_NAMES if n not in _GENERIC_VIC) +
                            r')\s+(?:(?:Support|Head|Regional|Corporate|Main)\s+)?(?:Office|office|Campus|campus|'
                            r'Site|site|Store|store|Branch|branch|Hospital|hospital|Warehouse|warehouse|Depot|depot|'
                            r'Centre|centre|Clinic|clinic|Headquarters|HQ|'
                            r'residential|Residential|aged care|Aged Care|facility|Facility)\b')
# A place named as "the (outer-south eastern) suburb of Lyndhurst" / "the town of Wodonga" (2026-10-18: held
# the Lyndhurst Primary School ads as verification_required; the cited sentence names no "in"/"at" or ", VIC").
_VIC_SUBURB_OF = re.compile(r'\b(?:suburb|town|township|city|locality)\s+of\s+(' + '|'.join(
    re.escape(n.title()) for n in _PLACE_NAMES if n not in _GENERIC_VIC) + r')\b(?!\s+(?:City|Shire|Council)\b)')  # "a suburb of Logan City" is Queensland
# A labelled location: "Location: Bundoora", "Location: Hume - Wodonga" (2026-10-18: both held verification_required
# because the model cited that line and no pattern knew the label).
_VIC_LABELLED = re.compile(r'\b(?i:locations?)\s*:\s*(?:[A-Za-z\' ]{1,30}?\s+[-–]\s+)?(' + '|'.join(
    re.escape(n.title()) for n in _PLACE_NAMES) + r')\b')
# A short cited location line that names a Victorian place anywhere ("Part time role at Sunbury location!",
# "Barwon South West - Greater Geelong", "Peter James Centre/Lilydale"): 7 of the last 14 verification_required holds.
# Only used on short quotes, so a sentence about an interstate office never matches by accident.
_VIC_ANYWHERE = re.compile(r'\b(' + '|'.join(re.escape(n.title()) for n in _PLACE_NAMES if n not in _GENERIC_VIC) + r')\b(?!\s+(?:City|Shire|Council)\b)')
# Two-word-or-longer names are distinctive anywhere in a sentence: "our Bacchus Marsh quarry".
_VIC_MULTIWORD = re.compile(r'\b(' + '|'.join(re.escape(n.title()) for n in _PLACE_NAMES if ' ' in n) + r')\b')
_VIC_WORD = re.compile(r'\b(?:Melbourne|Victoria|VIC)\b')


def victorian_place(text: str) -> str | None:
    """The first Victorian place named in text (lower case), or None. 'Melbourne' alone gives 'melbourne'."""
    text = ' '.join((text or '').split())
    found = sorted((m.start(1), m.group(1).lower()) for pattern in (_VIC_STRUCTURED, _VIC_IN_SENTENCE, _VIC_WORKPLACE, _VIC_SUBURB_OF, _VIC_LABELLED,
                                                                      _VIC_MULTIWORD)
                   for m in pattern.finditer(text))
    if not found and len(text) <= 120:
        found = sorted((m.start(1), m.group(1).lower()) for m in _VIC_ANYWHERE.finditer(text)
                       if m.group(1).lower() != text.strip(' .,;').lower())  # a bare place name with no state is not proof
    specific = [name for _, name in found if name != 'melbourne']  # "Glen Iris, Melbourne VIC" is Glen Iris
    if specific:
        return specific[0]
    return 'melbourne' if re.search(r'\bMelbourne\b', text, re.I) else None


def cited_victoria_location(quote: str) -> bool:
    """In scope: a Victorian place (any, not only metro), or Melbourne/Victoria named; another state alone is not."""
    if _state() != 'VIC':
        return _own_state_cited(quote, _state())
    quote = ' '.join((quote or '').split())
    vic = victorian_place(quote) is not None or bool(_VIC_WORD.search(quote))
    if _OTHER_JURISDICTION.search(quote) or re.search(r',\s*(?:us|act)\b', quote, re.I):
        # "Melbourne, VIC; Sydney, NSW" / "Brisbane | Melbourne | Sydney": open to a Victorian location.
        return vic and bool(re.search(r';|/|\||\bor\b', quote, re.I))
    return vic


def _km(a, b) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


@functools.lru_cache(maxsize=32)
def _home_for(person: str, profile: str, mtime_ns: int) -> str:
    return home_place('')


def _profile_home() -> str:
    """Home suburb of the current person; cached per person + profile file version (a process serves many people)."""
    from jobwatch import users
    from jobwatch.apply.paths import profile_dir
    try:
        path = profile_dir() / 'profile.yaml'
        mtime = path.stat().st_mtime_ns
    except Exception:  # noqa: BLE001 - no profile: home_place gives ''
        path, mtime = '', 0
    return _home_for(users.current(), str(path), mtime)


def home_place(profile_location: str | None = None) -> str:
    if not profile_location and profile_location is not None:
        profile_location = None
    if profile_location is None:
        try:
            import yaml
            from jobwatch.apply.paths import profile_dir
            cand = (yaml.safe_load((profile_dir() / 'profile.yaml').read_text(encoding='utf-8')) or {}).get('candidate') or {}
            profile_location = str(cand.get('location') or '')
        except Exception:
            profile_location = ''
    return victorian_place(profile_location) or ''  # no profile suburb: distance is unknown, never a guessed home


def km_from_home(location_text: str, home: str | None = None) -> int | None:
    """Straight-line km from the person's suburb (profile candidate.location) to the first Victorian place in location_text; None if unknown."""
    if home is None and _state() != 'VIC':
        return None  # distance needs the Victorian place data; other states: unknown
    place = victorian_place(location_text) if cited_victoria_location(location_text) else None
    if place is None:
        return None
    home = home or _profile_home()
    if place not in VIC_PLACES or home not in VIC_PLACES:
        return None
    return round(_km(VIC_PLACES[home], VIC_PLACES[place]))


# --- Person-independent region and commute evidence (decision policy from the confirmed profile) ---
# These helpers take the regions and home place as arguments; none reads a person's profile or assumes a home state.
CAPITALS: dict[str, str] = {'sydney': 'NSW', 'melbourne': 'VIC', 'brisbane': 'QLD', 'perth': 'WA', 'adelaide': 'SA',
                            'hobart': 'TAS', 'canberra': 'ACT', 'darwin': 'NT'}
_CAPITAL_WORD = re.compile(r'\b(' + '|'.join(CAPITALS) + r')\b', re.I)
_REMOTE_WORDS = re.compile(r'\b(?:remote|work from home|anywhere in australia)\b', re.I)
# "Sydney Road" or "Victoria Street" names a street, not a place: those words are dropped before places are looked for.
_STREET_NAME = re.compile(r"\b[A-Z][a-z]+\s+(?i:street|st|road|rd|avenue|ave|lane|drive|dr|terrace|parade|boulevard|"
                          r"highway|hwy|way|place|court|crescent)\b\.?")


def regions_named(text: str) -> frozenset[str]:
    """State codes the text names: a state code (upper case word), a full state name or a capital city.

    Only when the text names no state does a Victorian place from the bundled data count as VIC, so a state
    named in the text always wins over place data ("Richmond NSW" is NSW, never VIC)."""
    from jobwatch.util.place import STATES
    text = _STREET_NAME.sub(' ', ' '.join((text or '').split()))
    found = {code for code, name in STATES.items()
             if re.search(rf'(?-i:\b{code}\b)', text) or re.search(rf'\b{re.escape(name)}\b', text, re.I)}
    found |= {CAPITALS[m.group(1).lower()] for m in _CAPITAL_WORD.finditer(text)}
    if not found and victorian_place(text) is not None:
        found.add('VIC')
    return frozenset(found)


def location_verdict(quote: str, regions: frozenset[str], *, remote_fit: bool, remote_ok: bool | None):
    """'in', 'outside', 'remote' or 'unknown' for a cited location against the regions the person accepts.

    No regions given: no area filter ('in'). A named region in `regions` is 'in' (alternatives such as
    "Melbourne VIC or Sydney NSW" count). Named regions all outside are 'outside', unless the role is a fit
    for remote work, the quote says so and remote work is not ruled out. No region named: 'remote' on remote
    words when the role fits remote work, else 'unknown'."""
    if not regions:
        return 'in'
    named = regions_named(quote)
    remote = remote_fit and bool(_REMOTE_WORDS.search(quote or ''))
    if named & regions:
        return 'in'
    if named:
        return 'remote' if remote and remote_ok is not False else 'outside'
    return 'remote' if remote else 'unknown'


def _names_other_state(text: str) -> bool:
    """Conservative commute guard: True when the text may name a state other than Victoria.

    Matches non-VIC state codes case-insensitively with optional dots ("nsw", "N.S.W.") and full state names,
    on top of regions_named. Ordinary words that equal a code ("act") also match: withholding a distance on
    ambiguous text is the accepted failure mode. regions_named itself stays case-sensitive."""
    from jobwatch.util.place import STATES
    text = ' '.join((text or '').split())
    if regions_named(text) - {'VIC'}:
        return True
    return any(re.search(r'(?<![A-Za-z])' + r'\.?'.join(code) + r'\.?(?![A-Za-z])', text, re.I)
               or re.search(rf'\b{re.escape(name)}\b', text, re.I)
               for code, name in STATES.items() if code != 'VIC')


def commute_km_for(home_place: str | None, location_text: str) -> int | None:
    """Straight-line km between two Victorian places, or None.

    Documented limit: distance data exists for Victoria only, so a home or a job place outside it has no
    distance, and neither does any text that names another state ("Richmond NSW" is not the Victorian Richmond)."""
    home_text, place_text = home_place or '', location_text or ''
    if _names_other_state(home_text) or _names_other_state(place_text):
        return None
    home, place = victorian_place(home_text), victorian_place(place_text)
    if home not in VIC_PLACES or place not in VIC_PLACES:
        return None
    return round(_km(VIC_PLACES[home], VIC_PLACES[place]))
