"""Chat adapters for the same person-bound domain operations as native HTTP."""
from __future__ import annotations

import json
from langchain_core.tools import tool

from jobwatch import users, db
from jobwatch.candidate import intake, rules
from jobwatch.candidate.contracts import digest
from jobwatch.candidate.policy import rules_from_fact
from pipeline.agentic import feedback, shortlist, selection
from pipeline.agentic.chat import job_connection
from pipeline.agentic.runtime import RuntimeErrorSafe

WRITES=('reject_posting','restore_posting','propose_exclusion','confirm_exclusion',
        'pick_comparison','answer_question','dismiss_prompt','select_jobs','cancel_selection')
PREPARATION=('prepare_application','run_career_ops')


def _selection_args(conn,config,args):
    if 'posting_ids' in args:
        return {k:args[k] for k in ('posting_ids','expected_entry_ids','expected_run_keys')}
    entry=shortlist.load_entry(conn,args['posting_id'],config=config)
    if entry is None:
        raise RuntimeErrorSafe('inputs_changed')
    return dict(posting_ids=[entry.posting_id],expected_entry_ids={str(entry.posting_id):entry.entry_id},
                expected_run_keys={str(entry.posting_id):entry.run_key})


def preview(name,args,config):
    """Server-derived subject and full context shown in the human interrupt."""
    if name=='propose_exclusion':
        payload={k:args.get(k) for k in ('op','kind','value','rule_id')}
        payload['op']=payload['op'] or 'add'
        if payload['op']=='add' and not rules_from_fact(dict(id='draft',section='exclusion',basis='evidence',
                                                           value={'kind':payload['kind'],'value':payload['value']})):
            raise RuntimeErrorSafe('invalid_request')
        return dict(person=users.current(),change=payload,approved_hash=digest(intake.current_version(users.current())))
    if name=='confirm_exclusion':
        proposal=rules._load(args['proposal_id'])
        if proposal['digest']!=args['rule_digest'] or proposal['base_hash']!=digest(intake.current_version(users.current())):
            raise RuntimeErrorSafe('inputs_changed')
        return proposal
    with job_connection(config) as conn:
        if name in PREPARATION or name=='select_jobs':
            return selection.preview(conn,config,**_selection_args(conn,config,args))
        if name=='cancel_selection':
            return selection.status(conn,args['selection_id'])
        pin=shortlist._pin(conn,config)
        if name=='reject_posting':
            entry=shortlist.load_entry(conn,args['posting_id'],config=config)
            if entry is None or entry.entry_id!=args['expected_entry_id']:
                raise RuntimeErrorSafe('inputs_changed')
            subject=entry.model_dump(mode='json')
        elif name=='restore_posting':
            row=conn.execute('SELECT id,kind,detail_json FROM feedback_events WHERE person=? AND posting_id=? '
                             "AND kind IN ('reject','restore') ORDER BY id DESC LIMIT 1",(users.current(),args['posting_id'])).fetchone()
            if not row or row[0]!=args['expected_rejection_id'] or row[1]!='reject':
                raise RuntimeErrorSafe('inputs_changed')
            subject=dict(posting_id=args['posting_id'],rejection_id=row[0],original=json.loads(row[2]))
        else:
            row=conn.execute('SELECT subject_json,closed_at FROM feedback_prompts WHERE person=? AND id=?',
                             (users.current(),args['prompt_id'])).fetchone()
            if not row or row[1] is not None:
                raise RuntimeErrorSafe('inputs_changed')
            subject=json.loads(row[0])
        return dict(person=users.current(),input_context=pin,subject=subject)


def apply(name,args,config,*,binding):
    key='chat:'+binding['digest']
    if name=='propose_exclusion':
        return rules.propose(config,**binding['subject']['change'],request_id=key,actor='person')
    from pipeline.agentic.feedback_api import confirm_rule,rebuild
    with job_connection(config,write=True) as conn:
        db.migrate(conn)
        if name in PREPARATION or name=='select_jobs':
            return selection.request(conn,config,**binding['subject']['request'],request_id=key,actor='person',source='chat')
        if name=='cancel_selection':
            return selection.cancel(conn,args['selection_id'],actor='person')
        if name=='confirm_exclusion':
            return confirm_rule(conn,config,args['proposal_id'],args['rule_digest'],source='chat')
        if name in ('reject_posting','restore_posting'):
            event=feedback.record_feedback(conn,config,kind='reject' if name=='reject_posting' else 'restore',
                request_id=key,actor='person',source='chat',**args)
            return dict(event=event,shortlist=rebuild(conn,config))
        from pipeline.agentic import feedback_prompts as prompts
        if name=='pick_comparison':
            return prompts.answer_comparison(conn,config,args['prompt_id'],args['selected'],request_id=key,actor='person',source='chat')
        if name=='answer_question':
            return prompts.answer_question(conn,config,args['prompt_id'],args['text'],request_id=key,actor='person',source='chat')
        return prompts.dismiss_prompt(conn,args['prompt_id'],config=config,request_id=key,actor='person',source='chat')


def tools(config,scope,identity,approval_binding):
    def write(name,args):
        args={k:v for k,v in args.items() if k!='write'}
        from pipeline.agentic.chat import _tool_arguments
        binding=scope.approvals.get((name,identity(args,name))) if scope else None
        if (binding is None or _tool_arguments(name,args)!=_tool_arguments(name,binding['arguments'])
                or binding!=approval_binding(name,binding['arguments'],config)):
            raise RuntimeErrorSafe('approval_inputs_changed')
        if name=='answer_question' and not any(args['text'] in text for text in scope.human_texts):
            raise RuntimeErrorSafe('not_person_words')
        # All strings are the literal payload in the approved interrupt. They
        # remain human answers/preferences, never authoritative profile facts.
        return apply(name,args,config,binding=binding)

    @tool
    def ranked_shortlist() -> dict:
        """Read/rebuild the current explained shortlist without model calls."""
        with job_connection(config,write=True) as conn:
            db.migrate(conn)
            shortlist.build_shortlist(conn,config)
            result=shortlist.load_latest(conn,config=config)
            if result['status']=='ok':
                shortlist.record_impressions(conn,result['entries'],'chat')
                checked=shortlist.load_latest(conn,config=config)
                if checked.get('shortlist_id')!=result.get('shortlist_id') or checked['status']!='ok':
                    conn.rollback()
                    return shortlist._empty('stale')
            return result

    @tool
    def feedback_history() -> dict:
        """Read the person's immutable feedback history and reason vocabulary."""
        with job_connection(config) as conn:
            return dict(events=feedback.list_events(conn),reasons={k:v.model_dump(mode='json') for k,v in feedback.REJECTION_REASONS.items()})

    @tool
    def exclusion_rules() -> dict:
        """Read active approved exclusions and pending amendments."""
        return rules.listing()

    @tool
    def next_feedback_prompt() -> dict:
        """Show the next bounded human comparison/question. No model call or inferred answer."""
        from pipeline.agentic import feedback_prompts
        with job_connection(config,write=True) as conn:
            db.migrate(conn)
            return feedback_prompts.next_prompt(conn,config)

    @tool
    def selection_status(selection_id:str) -> dict:
        """Read preparation selection and its durable queued run identity."""
        with job_connection(config) as conn:
            return selection.status(conn,selection_id)

    @tool
    def reject_posting(posting_id:int,expected_entry_id:str,reason_code:str,reason_text:str='') -> dict:
        """Hide only this posting with the displayed reason, after exact human confirmation."""
        return write('reject_posting',locals())

    @tool
    def restore_posting(posting_id:int,expected_rejection_id:int) -> dict:
        """Restore the posting subject to current eligibility; preserve the original rejection."""
        return write('restore_posting',locals())

    @tool
    def propose_exclusion(op:str='add',kind:str|None=None,value:str|None=None,rule_id:str|None=None) -> dict:
        """Propose the literal exclusion amendment after human confirmation; does not yet approve policy."""
        return write('propose_exclusion',locals())

    @tool
    def confirm_exclusion(proposal_id:str,rule_digest:str) -> dict:
        """Approve exactly the shown exclusion amendment as a new profile version."""
        return write('confirm_exclusion',locals())

    @tool
    def pick_comparison(prompt_id:str,selected:int|None) -> dict:
        """Record the human's displayed option or none after exact confirmation; never infer a choice."""
        return write('pick_comparison',locals())

    @tool
    def answer_question(prompt_id:str,text:str) -> dict:
        """Confirm the literal human answer verbatim. Does not make it an approved profile fact."""
        return write('answer_question',locals())

    @tool
    def dismiss_prompt(prompt_id:str) -> dict:
        """Dismiss the displayed prompt after human confirmation; records no choice."""
        return write('dismiss_prompt',locals())

    @tool
    def select_jobs(posting_ids:list[int],expected_entry_ids:dict[str,str],expected_run_keys:dict[str,str]) -> dict:
        """Approve preparation only for 1–10 shown current shortlist entries. Never Submit."""
        return write('select_jobs',locals())

    @tool
    def cancel_selection(selection_id:str) -> dict:
        """Cancel this preparation selection after human confirmation."""
        return write('cancel_selection',locals())

    return [ranked_shortlist,feedback_history,exclusion_rules,next_feedback_prompt,selection_status,
            reject_posting,restore_posting,propose_exclusion,confirm_exclusion,pick_comparison,
            answer_question,dismiss_prompt,select_jobs,cancel_selection]
