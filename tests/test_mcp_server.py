"""The optional MCP adapter: what it can put to a person, and what it does with the rest.

These tests pin documented behaviour rather than asserting it is the behaviour we want. On this
path the connected MCP host is the human-approval boundary: there is one bearer token, it carries
no scope separation, and an accepted elicitation becomes an approval. CHAT.md says so; the native
HTTP API is the path with a separate approve-scoped credential.
"""
import json
import types

import pytest

pytest.importorskip('fastmcp')

from mcp.types import ElicitResult                                              # noqa: E402

from pipeline.agentic import mcp_server                                         # noqa: E402
from pipeline.agentic.chat import GATED                                         # noqa: E402
from pipeline.agentic.runtime import RuntimeErrorSafe                           # noqa: E402

PRESENTABLE = ('run_career_ops', 'assess_job', 'prepare_application', 'prepare_interview',
               'draft_followup', 'submit_application')


def approval(operation, index=0):
    return {'type': 'approval', 'interaction_id': f'approval-{index}', 'operation': operation,
            'posting_id': 42, 'binding': {'operation': operation, 'arguments': {'application_id': 42}},
            'summary': 'Tool execution requires approval'}


def test_the_adapter_words_six_operations_and_names_the_rest():
    requests, unpresentable = mcp_server._requests([approval(op, i) for i, op in enumerate(GATED)])
    assert sorted(unpresentable) == sorted(set(GATED) - set(PRESENTABLE))
    assert len(requests) == len(PRESENTABLE)
    for operation in PRESENTABLE:
        _, request = mcp_server._input_request(approval(operation), 0)
        assert '42' in request.params.message


def test_an_operation_it_cannot_word_is_rejected_so_the_thread_stays_usable(monkeypatch):
    """Raising left the interrupt checkpointed, and every later message on the thread hit it again."""
    calls = []

    def fake_dispatch(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {'status': 'interrupted', 'checkpoint_id': 'cp-1', 'interactions': [approval('profile_confirm')]}
        return {'status': 'complete', 'answer': 'I cannot confirm your profile from this client.',
                'todos': [], 'tools': ['profile_confirmation']}

    monkeypatch.setattr(mcp_server, 'dispatch', fake_dispatch)
    ctx = types.SimpleNamespace(request_state=None, input_responses=None)
    result = mcp_server._turn(person='owner', operation='start', message='Confirm my profile', ctx=ctx)
    assert result['status'] == 'complete' and result['refused_operations'] == ['profile_confirm']
    assert calls[1]['decisions'] == [{'type': 'reject'}] and calls[1]['human_decision'] is True
    assert calls[1]['expected_checkpoint'] == 'cp-1'


def test_a_turn_that_only_offers_unpresentable_work_does_not_loop_forever(monkeypatch):
    monkeypatch.setattr(mcp_server, 'dispatch', lambda **kwargs: {
        'status': 'interrupted', 'checkpoint_id': 'cp', 'interactions': [approval('select_jobs')]})
    ctx = types.SimpleNamespace(request_state=None, input_responses=None)
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server._turn(person='owner', operation='start', message='Select everything', ctx=ctx)
    assert exc.value.code == 'unsupported_chat_interaction'


def test_a_presentable_approval_is_still_handed_to_the_host(monkeypatch):
    monkeypatch.setattr(mcp_server, 'dispatch', lambda **kwargs: {
        'status': 'interrupted', 'checkpoint_id': 'cp', 'interactions': [approval('submit_application')]})
    ctx = types.SimpleNamespace(request_state=None, input_responses=None)
    result = mcp_server._turn(person='owner', operation='start', message='Submit it', ctx=ctx, thread_id='t1')
    state = json.loads(result.request_state)
    assert list(result.input_requests) == ['interaction_0']
    assert state['person'] == 'owner' and state['thread_id'] == 't1' and state['checkpoint_id'] == 'cp'
    assert 'SENDS the application to the employer' in result.input_requests['interaction_0'].params.message


def test_whatever_the_host_returns_decides_the_approval():
    """Documented limitation: this adapter has no second credential, so the host's bit is the approval."""
    interactions = [approval('submit_application')]
    accepted = mcp_server._resume_decisions(interactions, {'interaction_0': ElicitResult(action='accept', content={'approve': True})})
    assert accepted == [{'type': 'approve'}]
    for response in (ElicitResult(action='accept', content={'approve': False}),
                     ElicitResult(action='decline', content={'approve': True}),
                     ElicitResult(action='cancel', content=None)):
        assert mcp_server._resume_decisions(interactions, {'interaction_0': response}) == [{'type': 'reject'}]
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server._resume_decisions(interactions, {})
    assert exc.value.code == 'human_response_required'


def test_a_declined_question_never_becomes_an_answer():
    question = [{'type': 'question', 'interaction_id': 'q', 'question': 'Which days can you work?'}]
    answered = mcp_server._resume_decisions(question, {'interaction_0': ElicitResult(action='accept', content={'answer': 'Tuesdays'})})
    assert answered == [{'type': 'respond', 'message': 'Tuesdays'}]
    for content in ({'answer': '   '}, {'answer': 7}, {}):
        declined = mcp_server._resume_decisions(question, {'interaction_0': ElicitResult(action='accept', content=content)})
        assert declined[0]['type'] == 'respond' and 'declined to answer' in declined[0]['message']


@pytest.mark.parametrize('bad', [
    {'version': 2}, {'person': 'someone-else'}, {'operation': 'start'}, {'thread_id': 7}, {'interactions': {}}])
def test_request_state_is_bound_to_this_person_thread_and_operation(bad):
    good = {'version': 1, 'person': 'owner', 'operation': 'continue', 'thread_id': 't1', 'interactions': []}
    ctx = types.SimpleNamespace(request_state=json.dumps(good | bad), input_responses=None)
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server._state(ctx, person='owner', operation='continue', thread_id='t1')
    assert exc.value.code == 'invalid_chat_interaction_state'
