"""Real graph interrupts keep model suggestions separate from human writes."""
import json
import pytest
from jobwatch import users
from jobwatch.util import model_choice as model_choice
from jobwatch.util.llm import LLM
from pipeline.agentic import chat,shortlist
from pipeline.agentic.service import agentic_batch_run
from pipeline.agentic.runtime import RuntimeErrorSafe
from tests.baseline_support import world
from tests.test_agentic_service import SyntheticGateway


@pytest.fixture
def prepared(world,monkeypatch):
    conn,config,bundle,add=world
    add(42)
    gateway=SyntheticGateway(bundle)
    monkeypatch.setattr(model_choice,'get_model',lambda role,user=None:'openai/sol')
    agentic_batch_run([42],config,conn,evidence_bundle=bundle,llm=LLM(transport=gateway,keys=['synthetic']),operation='evaluate')
    entry=shortlist.build_shortlist(conn,config)[0]
    def model(actions):
        def transport(url,headers,body,timeout):
            if body['messages'][-1]['content'].startswith('Allowed tool schemas: '):
                answer=actions.pop(0) if actions else {'answer':'Finished.'}
                return 200,{'choices':[{'message':{'content':json.dumps(answer)}}],'usage':{'prompt_tokens':10,'completion_tokens':10}}
            return gateway(url,headers,body,timeout)
        return LLM(transport=transport,keys=['synthetic'],base_url=model_choice.SERVER_URL)
    return conn,config,entry,model


@pytest.mark.parametrize('include_text',[True,False])
def test_model_rejection_waits_for_exact_human_confirmation(prepared,include_text):
    conn,config,entry,model=prepared
    args=dict(posting_id=42,expected_entry_id=entry.entry_id,reason_code='not_this_employer',reason_text='My reason')
    if not include_text:
        args.pop('reason_text')
    llm=model([dict(tool='reject_posting',arguments=args)])
    pending=chat.dispatch(person=users.current(),thread_id='feedback',message='Reject42: My reason',config=config,llm=llm)
    assert pending['status']=='interrupted'
    assert pending['interactions'][0]['binding']['arguments']==args
    assert conn.execute('SELECT count(*) FROM feedback_events').fetchone()[0]==0
    with pytest.raises(RuntimeErrorSafe,match='human_decision_required'):
        chat.dispatch(person=users.current(),thread_id='feedback',decisions=[{'type':'approve'}],config=config,llm=llm)
    result=chat.dispatch(person=users.current(),thread_id='feedback',decisions=[{'type':'approve'}],human_decision=True,
        approval_bindings=[pending['interactions'][0]['binding']],config=config,llm=llm)
    assert result['status']=='complete'
    event=conn.execute('SELECT source,kind,reason_text FROM feedback_events').fetchone()
    assert tuple(event)==('chat','reject','My reason' if include_text else '')
    assert shortlist.load_entry(conn,42,config=config) is None


def test_selected_chat_job_is_durable_preparation_only(prepared):
    conn,config,entry,model=prepared
    llm=model([dict(tool='prepare_application',arguments={'posting_id':42})])
    pending=chat.dispatch(person=users.current(),thread_id='selection',message='Prepare42',config=config,llm=llm)
    shown=pending['interactions'][0]['binding']['subject']
    assert shown['request']['posting_ids']==[42] and shown['authorises']=='preparation_only'
    result=chat.dispatch(person=users.current(),thread_id='selection',decisions=[{'type':'approve'}],human_decision=True,
        approval_bindings=[pending['interactions'][0]['binding']],config=config,llm=llm)
    assert result['outcomes'][0]['status']=='selected'
    assert conn.execute("SELECT state FROM selection_requests").fetchone()[0]=='pending_dispatch'
    assert conn.execute("SELECT count(*) FROM feedback_events WHERE kind='select'").fetchone()[0]==1
    assert conn.execute("SELECT count(*) FROM agentic_packages WHERE phase='complete'").fetchone()[0]==0


def test_model_generated_question_answer_cannot_become_human_feedback(prepared):
    from pipeline.agentic import feedback_prompts
    conn,config,entry,model=prepared
    prompt=feedback_prompts.next_prompt(conn,config)['prompt']
    assert prompt['type']=='question'
    llm=model([dict(tool='answer_question',arguments={'prompt_id':prompt['prompt_id'],'text':'Invented answer'})])
    pending=chat.dispatch(person=users.current(),thread_id='answer',message='I can work two days.',config=config,llm=llm)
    with pytest.raises(RuntimeErrorSafe):
        chat.dispatch(person=users.current(),thread_id='answer',decisions=[{'type':'approve'}],human_decision=True,
            approval_bindings=[pending['interactions'][0]['binding']],config=config,llm=llm)
    assert conn.execute("SELECT count(*) FROM feedback_events WHERE kind='answer'").fetchone()[0]==0


def test_chat_exclusion_proposal_with_omitted_defaults_uses_exact_human_binding(prepared):
    from jobwatch.candidate import rules
    conn,config,entry,model=prepared
    llm=model([dict(tool='propose_exclusion',arguments={'kind':'employer','value':'Example Employer'})])
    pending=chat.dispatch(person=users.current(),thread_id='rule-defaults',message='Exclude Example Employer',config=config,llm=llm)
    result=chat.dispatch(person=users.current(),thread_id='rule-defaults',decisions=[{'type':'approve'}],human_decision=True,
        approval_bindings=[pending['interactions'][0]['binding']],config=config,llm=llm)
    assert result['status']=='complete'
    proposed=rules.listing()['pending']
    assert len(proposed)==1 and proposed[0]['payload']['value']=='Example Employer'
    assert not any(r['value']=='Example Employer' for r in rules.listing()['rules'])
