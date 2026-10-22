"""Authenticated, unpaid shortlist views; identity is never a request parameter."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Query
from jobwatch import users, db
from jobwatch.preferences import PreferenceError
from pipeline.agentic import shortlist
from pipeline.agentic.chat import job_database, job_connection

PREFIX='/api/agent/shortlist'
LABELS=['stronger_match','stretch','needs_clarification']


def mount(app, require, get_config):
    read,run=require('read'),require('run')

    @app.get(PREFIX)
    def listing(label:Literal['stronger_match','stretch','needs_clarification']|None=None,
                limit:int=Query(default=20,ge=1,le=50),offset:int=Query(default=0,ge=0),principal=Depends(read)):
        with users.use(principal.person):
            config=get_config(principal.person)
            if not job_database(config).exists():
                return shortlist._empty('not_built')
            with job_connection(config,write=True) as conn:
                result=shortlist.load_latest(conn,config=config,label=label,limit=limit,offset=offset)
                if result['status']=='ok':
                    shortlist.record_impressions(conn,result['entries'],'api')
                    checked=shortlist.load_latest(conn,config=config,label=label,limit=limit,offset=offset)
                    if checked['status']!='ok' or checked['shortlist_id']!=result['shortlist_id']:
                        conn.rollback()
                        return shortlist._empty('stale')
                return result

    @app.post(PREFIX+'/refresh')
    def refresh(principal=Depends(run)):
        with users.use(principal.person):
            config=get_config(principal.person)
            if not job_database(config).exists():
                return dict(shortlist._empty('not_built'),rebuilt=False)
            with job_connection(config,write=True) as conn:
                db.migrate(conn)
                previous=shortlist.load_latest(conn,config=config)
                if previous['status']=='ok':
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(previous['built_at'])).total_seconds()
                    if 0<=age<60:
                        return dict(previous,rebuilt=False)
                try:
                    shortlist.build_shortlist(conn,config)
                except PreferenceError as exc:
                    if str(exc)=='snapshot_changed':
                        raise HTTPException(409,detail={'error':'snapshot_changed'}) from None
                    raise
                current=shortlist.load_latest(conn,config=config)
                return dict(current,rebuilt=current['status']=='ok' and current.get('shortlist_id')!=previous.get('shortlist_id'))

    @app.get(PREFIX+'/{posting_id}')
    def detail(posting_id:int,principal=Depends(read)):
        with users.use(principal.person):
            config=get_config(principal.person)
            if not job_database(config).exists():
                raise HTTPException(404,detail={'error':'not_found'})
            with job_connection(config,write=True) as conn:
                entry=shortlist.load_entry(conn,posting_id,config=config)
                if entry is None:
                    raise HTTPException(404,detail={'error':'not_found'})
                shortlist.record_impressions(conn,[entry],'api_detail')
                checked=shortlist.load_entry(conn,posting_id,config=config)
                if checked is None or checked.entry_id!=entry.entry_id:
                    conn.rollback()
                    raise HTTPException(404,detail={'error':'not_found'})
                return entry.model_dump(mode='json')
