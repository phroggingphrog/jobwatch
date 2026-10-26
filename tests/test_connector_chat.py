"""Chat pass-through on the loopback JSON front: same _turn()/dispatch as the Python MCP server, but a human question is
plain structured content ("needs your answer"), approvals are never answered here, and nothing is invented."""
import pytest
from fastapi.testclient import TestClient

from pipeline.agentic import chatgpt_connector, connector_http, mcp_server
from tests.test_mcp_server import approval, two_people  # noqa: F401

TOKEN = 'x' * 40
H = {'Authorization': 'Bearer ' + TOKEN}


def question(text='Which city do you want to work in?', options=None, index=0):
    item = {'type': 'question', 'interaction_id': f'q{index}', 'question': text}
    return item | ({'options': options} if options else {})


@pytest.fixture
def client(two_people):
    return TestClient(connector_http.create_app(token=TOKEN, person='owner'))


@pytest.fixture
def agent(monkeypatch):
    """A scripted dispatch shared by the MCP adapter and the connector. Records every call."""
    calls, script = [], []

    def fake(**kwargs):
        calls.append(kwargs)
        return script.pop(0)
    monkeypatch.setattr(mcp_server, 'dispatch', fake)
    monkeypatch.setattr(chatgpt_connector, 'dispatch', fake)
    fake.calls, fake.script = calls, script
    return fake


def done(answer='Done.'):
    return {'status': 'complete', 'answer': answer, 'todos': [], 'tools': ['jobs_overview']}


def interrupted(*items, checkpoint='cp1'):
    return {'status': 'interrupted', 'checkpoint_id': checkpoint, 'interactions': list(items)}


def test_chat_needs_the_bearer(client):
    assert client.post('/connector/chat/start', json={'message': 'hi'}).status_code == 401
    assert client.post('/connector/chat/continue', json={'thread_id': 't', 'message': 'hi'}).status_code == 401


def test_start_runs_one_turn_as_the_configured_person_with_an_opaque_thread(agent, client):
    agent.script.append(done('Three jobs need you.'))
    body = client.post('/connector/chat/start', headers=H, json={'message': 'What needs me?'}).json()
    assert body['status'] == 'complete' and body['answer'] == 'Three jobs need you.'
    assert len(body['thread_id']) >= 32
    call = agent.calls[0]
    assert call['person'] == 'owner' and call['thread_id'] == body['thread_id'] and call['message'] == 'What needs me?'


def test_the_person_is_never_an_argument(agent, client):
    agent.script.append(done())
    assert client.post('/connector/chat/start', headers=H, json={'message': 'hi', 'person': 'guest'}).status_code == 422
    assert agent.calls == []


def test_a_question_comes_back_as_plain_content_and_is_never_answered_for_the_person(agent, client):
    agent.script.append(interrupted(question(options=['Melbourne', 'Sydney'])))
    body = client.post('/connector/chat/start', headers=H, json={'message': 'Tailor my letter'}).json()
    assert body['status'] == 'needs_answer'
    assert body['questions'] == [{'question': 'Which city do you want to work in?', 'options': ['Melbourne', 'Sydney']}]
    assert 'Do not answer' in body['note'] and body['thread_id']
    assert len(agent.calls) == 1          # no decision was sent on the person's behalf


def test_the_answer_goes_back_through_continue_on_the_same_thread(agent, client):
    agent.script.append(interrupted(question()))
    first = client.post('/connector/chat/start', headers=H, json={'message': 'Tailor my letter'}).json()
    agent.script.append(done('Letter tailored for Melbourne.'))
    second = client.post('/connector/chat/continue', headers=H,
                         json={'thread_id': first['thread_id'], 'message': 'Melbourne'}).json()
    assert second['status'] == 'complete' and second['answer'].startswith('Letter tailored')
    call = agent.calls[-1]
    assert call['thread_id'] == first['thread_id'] and call['message'] == 'Melbourne' and call['person'] == 'owner'


def test_an_approval_is_declined_not_approved_and_points_to_the_app(agent, client):
    agent.script.append(interrupted(approval('submit_application')))
    agent.script.append(done('Understood, nothing was sent.'))
    body = client.post('/connector/chat/start', headers=H, json={'message': 'Submit job 42 for me'}).json()
    assert body['status'] == 'complete' and body['declined'] == ['submit_application']
    resume = agent.calls[1]
    assert resume['human_decision'] is True and resume['decisions'] == [{'type': 'reject'}]
    assert resume['expected_checkpoint'] == 'cp1' and resume['approval_bindings'] == [approval('submit_application')['binding']]


def test_a_question_next_to_an_approval_is_shown_and_the_approval_is_left_unanswered(agent, client):
    agent.script.append(interrupted(approval('prepare_application', 0), question(index=1)))
    body = client.post('/connector/chat/start', headers=H, json={'message': 'Prepare it'}).json()
    assert body['status'] == 'needs_answer' and len(body['questions']) == 1
    assert body['approvals_not_answerable_here'] == ['prepare_application']
    assert len(agent.calls) == 1


def test_continue_validates_the_thread_id_and_message(agent, client):
    for payload in ({'thread_id': '', 'message': 'x'}, {'thread_id': 'a' * 101, 'message': 'x'},
                    {'thread_id': 'bad id!', 'message': 'x'}, {'thread_id': 't1', 'message': '   '}):
        assert client.post('/connector/chat/continue', headers=H, json=payload).status_code in (400, 422)
    assert agent.calls == []


def test_a_long_message_is_refused_not_truncated(agent, client):
    assert client.post('/connector/chat/start', headers=H, json={'message': 'x' * 16001}).status_code == 422
    assert agent.calls == []


def test_chat_cannot_reach_another_persons_threads(monkeypatch, client):
    """The thread belongs to the configured person: dispatch is always called with that person, whatever the id."""
    seen = []
    monkeypatch.setattr(mcp_server, 'dispatch', lambda **k: seen.append(k) or done())
    monkeypatch.setattr(chatgpt_connector, 'dispatch', lambda **k: seen.append(k) or done())
    client.post('/connector/chat/continue', headers=H, json={'thread_id': 'someone-elses-thread', 'message': 'hi'})
    assert [k['person'] for k in seen] == ['owner']
