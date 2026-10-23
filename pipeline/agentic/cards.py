"""Fixed presentation choices over native state; no model-authored executable UI."""
from typing import Literal

CardKind = Literal['auto','profile','models','jobs','progress','documents','application']
TITLES = {'auto':'Jobwatch','profile':'Your profile','models':'Your AI models','jobs':'Your job matches',
          'progress':'Work in progress','documents':'Your documents','application':'Review your application'}


def resolve(run, *, requested='auto', has_profile=False):
    if requested not in TITLES:
        raise ValueError('invalid_card')
    if requested != 'auto':
        return requested
    if any(not item['answered'] for item in run.get('interactions',[])):
        return 'progress'
    if run['state'] in ('queued','running','interrupted','deferred','failed'):
        return 'progress'
    outcomes = (run.get('result') or {}).get('outcomes') or []
    intent = next((v for v in reversed(outcomes) if v.get('status')=='view' and v.get('card') in TITLES),None)
    if intent:
        return intent['card']
    if run.get('artifacts') or any(v.get('status')=='selected' for v in outcomes):
        return 'documents'
    return 'profile' if not has_profile else 'jobs'
