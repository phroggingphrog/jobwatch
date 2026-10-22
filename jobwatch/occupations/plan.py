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
    data = dict(profile_version=policy.profile_version, policy_hash=policy.policy_hash,
        queries={key: queries for key in ('seek', 'jora', 'jobspy')},
        locations=_unique([location, *extra_locations]), hypotheses=tuple(h.id for h in hypotheses))
    return SearchPlan(**data, plan_hash=digest(data))


def searches_overlay(plan: SearchPlan, base: dict, policy=None) -> dict:
    out = deepcopy(base)
    for key in ('seek', 'jora'):
        out.setdefault(key, {})['keywords'] = list(plan.queries.get(key, ()))
    out.setdefault('jobspy', {})['searches'] = [{'term': q} for q in plan.queries.get('jobspy', ())]
    if plan.locations:
        out['location'] = plan.locations[0]
        for key in ('seek', 'jora'):
            out[key]['where'] = plan.locations[0]
        out['jobspy']['location'] = plan.locations[0]
    if policy and policy.remote_ok and (policy.home or {}).get('country'):
        country = policy.home['country']
        out['seek']['remote'] = {'enabled': True, 'keywords': list(plan.queries.get('seek', ())[:4]), 'where': country}
        out['jobspy']['searches'] += [{'term': q, 'location': country, 'is_remote': True}
                                     for q in plan.queries.get('jobspy', ())[:4]]
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
