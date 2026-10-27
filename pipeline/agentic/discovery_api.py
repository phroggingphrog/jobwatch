"""Typed discovery operations. Identity is selected by bearer authentication."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import users
from pipeline.agentic import discovery_settings
from pipeline.agentic.discovery_settings import DailySettings
from jobwatch.occupations.hypotheses import cached_hypotheses
from jobwatch.occupations.plan import load_plan
from pipeline.agentic import discovery
from pipeline.agentic.chat import job_database, job_connection

PREFIX = '/api/agent/discovery'
NOTE = 'Related occupations are search hypotheses, not qualification proof.'


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_id: str = Field(min_length=1, max_length=100)


class DiscoveryStartRequest(DiscoveryRequest):
    max_assessments: int | None = Field(default=None, ge=1, le=20)


class RetryRequest(DiscoveryRequest):
    incident_id: str = Field(min_length=1, max_length=100)
    posting_id: int = Field(gt=0)
    expected_context: str = Field(pattern=r'^[a-f0-9]{64}$')


def flags(config):
    values = discovery.settings(config)
    return {k: values[k] for k in ('search_plan','relevance','dedupe','ordering')}


def mount(app, require, get_config):
    read = require('read')
    write = require('run')

    @app.get(PREFIX + '/status')
    def status(principal=Depends(read)):
        from pipeline.agentic import discovery_ops
        return discovery_ops.status(principal.person, get_config(principal.person))

    @app.get(PREFIX + '/settings')
    def settings(principal=Depends(read)):
        from pipeline.agentic import discovery_ops
        return discovery_ops.get_settings(principal.person, get_config(principal.person))

    @app.post(PREFIX + '/settings')
    def save_settings(body: DailySettings, principal=Depends(write)):
        from pipeline.agentic import discovery_ops
        jobs = {k: getattr(body, k) for k in body.model_fields_set & set(discovery_settings.JOB_LIMITS)}
        return discovery_ops.set_settings(principal.person, get_config(principal.person),
                                          body.daily_token_ceiling, **jobs)

    @app.post(PREFIX + '/start', status_code=202)
    def start(body: DiscoveryStartRequest, principal=Depends(write)):
        from pipeline.agentic import discovery_ops
        return discovery_ops.start(principal.person, get_config(principal.person), body.request_id,
                                   max_assessments=body.max_assessments)

    @app.post(PREFIX + '/retry', status_code=202)
    def retry(body: RetryRequest, principal=Depends(write)):
        from pipeline.agentic import discovery_ops
        return discovery_ops.start(principal.person, get_config(principal.person), **body.model_dump())

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
