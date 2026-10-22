"""Human native operations over the shared feedback and selection services."""
from contextlib import contextmanager
from typing import Literal

from fastapi import Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import db, users
from jobwatch.candidate import rules
from pipeline.agentic import feedback, shortlist, selection
from pipeline.agentic.chat import job_connection, job_database


class Body(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Rejection(Body):
    expected_entry_id:str
    reason_code:str
    reason_text:str=Field(default='',max_length=2000)


class Restoration(Body):
    expected_rejection_id:int


class RuleProposal(Body):
    op:Literal['add','withdraw']='add'
    kind:str|None=None
    value:str|None=None
    rule_id:str|None=None


class RuleConfirmation(Body):
    rule_digest:str


class Comparison(Body):
    selected:int|None


class Answer(Body):
    text:str=Field(min_length=1,max_length=4000)


class Selected(Body):
    posting_ids:list[int]=Field(min_length=1,max_length=10)
    expected_entry_ids:dict[str,str]
    expected_run_keys:dict[str,str]


def rebuild(conn,config):
    shortlist.build_shortlist(conn,config)
    return shortlist.load_latest(conn,config=config)


def confirm_rule(conn,config,proposal_id,rule_digest,*,source='api'):
    result=rules.confirm(config,proposal_id,rule_digest=rule_digest,actor='person')
    from pipeline.agentic import discovery
    if 'pipeline_state' in shortlist._tables(conn):
        discovery.enforce_exclusions(conn,config)
    conn.execute('BEGIN IMMEDIATE')
    try:
        feedback.append_event(conn,kind='exclude',request_id='rule:'+proposal_id,actor='person',source=source,
            profile_version=result['version'],detail={'proposal_id':proposal_id,'rule_digest':rule_digest})
        conn.commit()
    except BaseException:
        conn.rollback(); raise
    return dict(result,shortlist=rebuild(conn,config))


def mount(app,require,get_config):
    read,interact,approve=(require(s) for s in ('read','interact','approve'))

    @app.exception_handler(feedback.FeedbackError)
    async def feedback_failed(request,exc):
        return JSONResponse({'error':exc.code},status_code=feedback.STATUS.get(exc.code,409))

    @app.exception_handler(rules.RuleError)
    @app.exception_handler(selection.SelectionError)
    async def domain_failed(request,exc):
        status=403 if exc.code=='person_required' else 404 if exc.code in ('not_found','rule_not_found') else 422 if exc.code.startswith('invalid_') else 409
        return JSONResponse({'error':exc.code},status_code=status)

    @contextmanager
    def jobs(principal,*,write=False):
        with users.use(principal.person):
            config=get_config(principal.person)
            if not job_database(config).exists():
                raise HTTPException(404,detail={'error':'not_found'})
            with job_connection(config,write=write) as conn:
                if write:
                    db.migrate(conn)
                yield conn,config

    def request_key(key):
        if not key or len(key)>200 or not key.strip():
            raise HTTPException(422,detail={'error':'invalid_request'})
        return key

    @app.get('/api/agent/feedback')
    def history(limit:int=Query(default=100,ge=1,le=200),principal=Depends(read)):
        with users.use(principal.person):
            if not job_database(get_config(principal.person)).exists():
                return dict(events=[],reasons={k:v.model_dump(mode='json') for k,v in feedback.REJECTION_REASONS.items()})
        with jobs(principal) as (conn,config):
            return dict(events=feedback.list_events(conn,limit=limit),
                        reasons={k:v.model_dump(mode='json') for k,v in feedback.REJECTION_REASONS.items()})

    @app.post('/api/agent/shortlist/{posting_id}/feedback')
    def reject(posting_id:int,body:Rejection,key:str=Header(alias='Idempotency-Key'),principal=Depends(interact)):
        with jobs(principal,write=True) as (conn,config):
            event=feedback.record_feedback(conn,config,posting_id=posting_id,kind='reject',request_id=request_key(key),
                actor='person',**body.model_dump())
            return dict(event=event,shortlist=rebuild(conn,config))

    @app.post('/api/agent/shortlist/{posting_id}/restore')
    def restore(posting_id:int,body:Restoration,key:str=Header(alias='Idempotency-Key'),principal=Depends(interact)):
        with jobs(principal,write=True) as (conn,config):
            event=feedback.record_feedback(conn,config,posting_id=posting_id,kind='restore',request_id=request_key(key),
                actor='person',**body.model_dump())
            return dict(event=event,shortlist=rebuild(conn,config))

    @app.get('/api/agent/profile/rules')
    def rule_list(principal=Depends(read)):
        with users.use(principal.person):
            return rules.listing()

    @app.post('/api/agent/profile/rules',status_code=201)
    def rule_proposal(body:RuleProposal,key:str=Header(alias='Idempotency-Key'),principal=Depends(interact)):
        with users.use(principal.person):
            return rules.propose(get_config(principal.person),**body.model_dump(),request_id=request_key(key),actor='person')

    @app.post('/api/agent/profile/rules/{proposal_id}/confirm')
    def rule_confirm(proposal_id:str,body:RuleConfirmation,principal=Depends(approve)):
        with jobs(principal,write=True) as (conn,config):
            return confirm_rule(conn,config,proposal_id,body.rule_digest)

    @app.post('/api/agent/selections',status_code=202)
    def select(body:Selected,key:str=Header(alias='Idempotency-Key'),principal=Depends(approve)):
        with jobs(principal,write=True) as (conn,config):
            row=selection.request(conn,config,**body.model_dump(),request_id=request_key(key),actor='person')
            return row

    @app.get('/api/agent/selections/{selection_id}')
    def selection_status(selection_id:str,principal=Depends(read)):
        with jobs(principal) as (conn,config):
            result=selection.status(conn,selection_id)
            if result['run_id']:
                from pipeline.agentic.api_store import APIStore
                with APIStore(principal.person) as store:
                    result['run']=store.public_run(result['run_id'])
            return result

    @app.post('/api/agent/selections/{selection_id}/cancel',status_code=202)
    def selection_cancel(selection_id:str,principal=Depends(approve)):
        with jobs(principal,write=True) as (conn,config):
            return selection.cancel(conn,selection_id,actor='person')

    # Prompt implementation shares the same canonical choice store and validation.
    from pipeline.agentic import feedback_prompts as prompts

    @app.exception_handler(prompts.PromptError)
    async def prompt_failed(request,exc):
        return JSONResponse({'error':exc.code},status_code=prompts.STATUS.get(exc.code,409))

    @app.post('/api/agent/prompts/next')
    def next_prompt(principal=Depends(read)):
        with jobs(principal,write=True) as (conn,config):
            return prompts.next_prompt(conn,config)

    @app.get('/api/agent/prompts/next')
    def outstanding_prompt(principal=Depends(read)):
        with jobs(principal) as (conn,config):
            current=prompts.outstanding_prompt(conn)
            if current:
                try:
                    valid=prompts._is_current(prompts._get(conn,current['prompt_id']),prompts._snapshot(conn,config))
                except (ValueError,OSError):
                    valid=False
                if not valid:
                    return {'prompt':None,'reason':'stale'}
            return {'prompt':current,'reason':None}

    @app.get('/api/agent/prompts')
    def prompt_history(principal=Depends(read)):
        with jobs(principal) as (conn,config):
            return {'prompts':prompts.list_prompts(conn)}

    @app.post('/api/agent/prompts/{prompt_id}/pick')
    def pick(prompt_id:str,body:Comparison,key:str=Header(alias='Idempotency-Key'),principal=Depends(interact)):
        with jobs(principal,write=True) as (conn,config):
            return prompts.answer_comparison(conn,config,prompt_id,body.selected,request_id=request_key(key),actor='person')

    @app.post('/api/agent/prompts/{prompt_id}/answer')
    def answer(prompt_id:str,body:Answer,key:str=Header(alias='Idempotency-Key'),principal=Depends(interact)):
        with jobs(principal,write=True) as (conn,config):
            return prompts.answer_question(conn,config,prompt_id,body.text,request_id=request_key(key),actor='person')

    @app.post('/api/agent/prompts/{prompt_id}/dismiss')
    def dismiss(prompt_id:str,key:str=Header(alias='Idempotency-Key'),principal=Depends(interact)):
        with jobs(principal,write=True) as (conn,config):
            return prompts.dismiss_prompt(conn,prompt_id,config=config,request_id=request_key(key),actor='person')
