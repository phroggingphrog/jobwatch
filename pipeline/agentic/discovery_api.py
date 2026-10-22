"""Read-only discovery views. Identity is selected by bearer authentication."""
from fastapi import Depends, HTTPException

from jobwatch import users
from jobwatch.occupations.hypotheses import cached_hypotheses
from jobwatch.occupations.plan import load_plan
from pipeline.agentic import discovery
from pipeline.agentic.chat import job_database, job_connection

PREFIX = '/api/agent/discovery'
NOTE = 'Related occupations are search hypotheses, not qualification proof.'


def flags(config):
    values = discovery.settings(config)
    return {k: values[k] for k in ('search_plan','relevance','dedupe','ordering')}


def mount(app, require, get_config):
    read = require('read')

    @app.get(PREFIX + '/fields')
    def fields(principal=Depends(read)):
        with users.use(principal.person):
            items = cached_hypotheses(principal.person, config=get_config(principal.person))
            plan = load_plan(principal.person)
            return dict(status='ready' if items is not None else 'not_computed',
                profile_version=plan.profile_version if plan and items is not None else None,
                hypotheses=[h.model_dump(mode='json') for h in items or ()], note=NOTE)

    @app.get(PREFIX + '/plan')
    def plan(principal=Depends(read)):
        with users.use(principal.person):
            value = load_plan(principal.person)
            policy, current = discovery._current_plan(principal.person)
            valid = current is not None and cached_hypotheses(principal.person, config=get_config(principal.person)) is not None
            return dict(status=('ready' if valid else 'stale') if value is not None else 'not_computed',
                plan=value.model_dump(mode='json') if value else None, flags=flags(get_config(principal.person)))

    @app.get(PREFIX + '/postings/{posting_id}/relevance')
    def relevance(posting_id: int, principal=Depends(read)):
        with users.use(principal.person):
            config = get_config(principal.person)
            row = None
            if job_database(config).exists():
                with job_connection(config) as conn:
                    row = discovery.latest_judgment_row(conn,posting_id)
            if row is None:
                raise HTTPException(status_code=404,detail={'error':'not_found'})
            return dict(judgment=row['judgment'].model_dump(mode='json'),mode=row['mode'],created_at=row['created_at'])
