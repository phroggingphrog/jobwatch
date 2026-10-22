"""Private, deterministic collector plans derived from occupational hypotheses."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from pydantic import model_validator

from jobwatch import users
from jobwatch.apply.paths import ensure_dir, safe_write_bytes
from jobwatch.candidate.contracts import StrictFrozen, digest


class SearchPlan(StrictFrozen):
    profile_version: int
    policy_hash: str
    queries: dict[str, tuple[str, ...]]
    locations: tuple[str, ...]
    hypotheses: tuple[str, ...]
    plan_hash: str

    @model_validator(mode='after')
    def verify_hash(self):
        if self.plan_hash != digest(self.model_dump(mode='json', exclude={'plan_hash'})):
            raise ValueError('plan_hash_mismatch')
        return self


def query_for(title: str) -> str:
    text = re.sub(r'\([^)]*\)', '', title.casefold())
    text = re.sub(r'\bn\.?e\.?c\.?|\bnfd\b', '', text)
    return ' '.join(text.strip(' ,.;-').split())[:80]


def _unique(items):
    seen, out = set(), []
    for item in items:
        item = item.strip()
        if item and item.casefold() not in seen:
            out.append(item); seen.add(item.casefold())
    return tuple(out)


def search_plan(policy, hypotheses, *, extra_locations=(), max_queries=12) -> SearchPlan:
    queries = _unique([q.casefold()[:80] for q in policy.focus] + [query_for(h.title) for h in hypotheses])[:max_queries]
    home = policy.home or {}
    location = ', '.join(str(home[k]) for k in ('place', 'state') if home.get(k))
    from pipeline.agentic.location import regions_named
    locations = _unique([location, *extra_locations])
    covered = set().union(*(regions_named(loc) for loc in locations)) if locations else set()
    locations = _unique([*locations, *(r for r in getattr(policy, 'regions', ()) if r not in covered)])
    data = dict(profile_version=policy.profile_version, policy_hash=policy.policy_hash,
        queries={key: queries for key in ('seek', 'jora', 'jobspy')},
        locations=locations, hypotheses=tuple(h.id for h in hypotheses))
    return SearchPlan(**data, plan_hash=digest(data))


def searches_overlay(plan: SearchPlan, base: dict, policy=None) -> dict:
    """Replace personal search inputs, preserving only acquisition controls from shared config.

    Explicit query/location pairs share each collector's existing rotation and request
    allowance. Locations alternate before advancing to the next query.
    """
    out = deepcopy(base)
    location = plan.locations[0] if plan.locations else ''
    out['location'] = location
    for key in ('seek', 'jora'):
        out.setdefault(key, {})['keywords'] = list(plan.queries.get(key, ()))
        out[key]['where'] = location
    out.setdefault('jobspy', {})['location'] = location
    for key in ('seek', 'jora', 'jobspy'):
        out[key]['searches'] = [{'term': q, 'location': loc}
            for q in plan.queries.get(key, ()) for loc in (plan.locations or ('',))]
        # Technical defaults keep an expanded scope bounded even with sparse config.
        out[key].setdefault('searches_per_run', 4)
    out['seek']['remote'] = {'enabled': False}
    if policy and policy.remote_ok is True:
        country = (policy.home or {}).get('country') or ('Australia' if getattr(policy, 'regions', ()) else '')
        if country:
            for key in ('seek', 'jobspy'):
                out[key]['searches'] += [{'term': q, 'location': country, 'is_remote': True}
                    for q in plan.queries.get(key, ())[:4]]
    return out


def feeds_overlay(plan: SearchPlan, base: dict, policy) -> dict:
    """Scope existing Reddit feeds without inventing or enabling a new source."""
    from pipeline.agentic.location import regions_named
    from jobwatch.place import STATES
    out = deepcopy(base)
    conf = out.setdefault('reddit', {})
    regions = set(getattr(policy, 'regions', ()))
    conf['_profile_scope'] = list(plan.locations)
    conf['_profile_regions'] = sorted(regions)
    conf['_remote_ok'] = policy.remote_ok
    labels = [*plan.locations, *regions, *(STATES[r] for r in regions if r in STATES)]
    conf['hiring_location'] = [r'\b' + re.escape(s) + r'\b' for s in _unique(labels)]
    if policy.remote_ok is True:
        conf['hiring_location'].append(r'\bremote\b|\bwork from home\b')
    terms = plan.queries.get('seek', ())
    feeds = []
    for entry in conf.get('feeds') or []:
        entry = deepcopy(entry)
        # Local sources outside the approved regions cannot become implicit location facts.
        local = entry.get('location')
        if local and regions and not (regions_named(local) & regions):
            continue
        # Shared keyword queries must not import another person's career or home.
        if entry.get('q'):
            entry['q'] = ' OR '.join('"' + q.replace('"', '') + '"' for q in terms)
        feeds.append(entry)
    conf['feeds'] = feeds
    return out


_STOP = set('a an and at for in of the to with senior junior graduate assistant officer'.split())


def title_matches_plan(title: str, plan: SearchPlan) -> bool:
    words = set(re.findall(r'\w+', title.casefold()))
    for query in plan.queries.get('seek', ()):
        tokens = set(re.findall(r'\w+', query.casefold()))
        if tokens and ((len(tokens) <= 2 and tokens <= words) or
                       (len(tokens) > 2 and len((tokens - _STOP) & (words - _STOP)) >= 2)):
            return True
    return False


def save_plan(person, plan):
    root = ensure_dir(users.user_dir(person) / 'discovery')
    safe_write_bytes(root / 'search-plan.json', plan.model_dump_json().encode())


def load_plan(person) -> SearchPlan | None:
    path = users.user_dir(person) / 'discovery/search-plan.json'
    try:
        return SearchPlan.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None
