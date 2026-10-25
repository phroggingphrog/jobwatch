"""Authenticated MCP entry point for the Jobwatch Career Ops chat agent.

The MCP identity is bound to a server-configured Jobwatch person. Model tool
arguments never select an account or supply approval decisions. Paused actions
are resumed only from MCP multi-round-trip input returned by the authenticated
client, and the protocol request state is encrypted, principal-bound, and short lived.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from mcp.server.request_state import RequestStateSecurity
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult

from jobwatch import users
from pipeline.agentic.chat import _career_ops_skill, dispatch
from pipeline.agentic.runtime import RuntimeErrorSafe

_MAX_QUESTION = 4000


class _JobwatchTokenVerifier(TokenVerifier):
    """One configured bearer token, scoped to one configured Jobwatch account."""

    def __init__(self, token: str, person: str):
        super().__init__(required_scopes=['jobwatch'])
        self._token, self._person = token, person

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id='jobwatch-chat', scopes=['jobwatch'],
                           subject=self._person, claims={'sub': self._person})


def _person_from_request() -> str:
    token = get_access_token()
    person = token.subject if token else None
    if not users.valid_name(person):
        raise RuntimeErrorSafe('mcp_auth_required')
    return person


def _input_request(interaction: dict, index: int) -> tuple[str, ElicitRequest]:
    kind = interaction.get('type')
    if kind == 'question':
        question = interaction.get('question')
        if type(question) is not str or not question.strip() or len(question) > _MAX_QUESTION:
            raise RuntimeErrorSafe('invalid_chat_interaction')
        key = f'interaction_{index}'
        req = ElicitRequest(params=ElicitRequestFormParams(
            message=question,
            requestedSchema={'type': 'object', 'properties': {
                'answer': {'type': 'string', 'description': 'Your answer to the question.',
                           'maxLength': _MAX_QUESTION}}, 'required': ['answer']}))
        return key, req
    if kind == 'approval':
        operation = interaction.get('operation', 'run_career_ops')
        actions = {'run_career_ops': 'evaluate and prepare job posting',
                   'assess_job': 'assess job posting',
                   'prepare_application': 'prepare an application for job posting',
                   'prepare_interview': 'prepare interview material for job posting',
                   'draft_followup': 'draft a follow-up for application',
                   'submit_application': 'press the employer\'s final Submit for job posting'}
        if operation not in actions:
            raise RuntimeErrorSafe('invalid_chat_interaction')
        identity = ((interaction.get('binding') or {}).get('arguments', {}).get('application_id')
                    if operation == 'draft_followup' else interaction.get('posting_id'))
        if type(identity) is not int or identity < 1:
            raise RuntimeErrorSafe('invalid_chat_interaction')
        key = f'interaction_{index}'
        req = ElicitRequest(params=ElicitRequestFormParams(
            message=(f"Allow Jobwatch to {actions[operation]} {identity}? This SENDS the application to the employer, "
                     "exactly as filled and reviewed; nothing is sent if the form changed."
                     if operation == 'submit_application' else
                     f"Allow Jobwatch Career Ops to {actions[operation]} {identity}? "
                     "This may use paid model calls and save career-work artifacts. It will not submit an application."),
            requestedSchema={'type': 'object', 'properties': {
                'approve': {'type': 'boolean', 'description': 'Allow this Career Ops run.'}},
                'required': ['approve']}))
        return key, req
    raise RuntimeErrorSafe('unsupported_chat_interaction')


def _resume_decisions(interactions: list[dict], responses: dict[str, Any] | None) -> list[dict]:
    decisions = []
    for index, interaction in enumerate(interactions):
        response = (responses or {}).get(f'interaction_{index}')
        if not isinstance(response, ElicitResult):
            raise RuntimeErrorSafe('human_response_required')
        accepted = response.action == 'accept'
        content = response.content or {}
        if interaction['type'] == 'approval':
            decisions.append({'type': 'approve' if accepted and content.get('approve') is True else 'reject'})
        elif interaction['type'] == 'question':
            answer = content.get('answer') if accepted else None
            if type(answer) is str and answer.strip() and len(answer) <= _MAX_QUESTION:
                decisions.append({'type': 'respond', 'message': answer})
            else:
                decisions.append({'type': 'respond',
                                  'message': 'The human declined to answer. Do not infer or invent the missing fact.'})
        else:
            raise RuntimeErrorSafe('unsupported_chat_interaction')
    return decisions


def _state(ctx: Context, *, person: str, operation: str, thread_id: str | None) -> dict | None:
    raw = ctx.request_state
    if raw is None:
        return None
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        raise RuntimeErrorSafe('invalid_chat_interaction_state') from None
    if (type(state) is not dict or state.get('version') != 1 or state.get('person') != person
            or state.get('operation') != operation or not isinstance(state.get('thread_id'), str)
            or (thread_id is not None and thread_id != state['thread_id'])
            or type(state.get('interactions')) is not list):
        raise RuntimeErrorSafe('invalid_chat_interaction_state')
    return state


def _requests(interactions: list[dict]) -> tuple[dict, list[str]]:
    """Elicitation requests for every interaction, or the operations this adapter has no wording for."""
    requests, unpresentable = {}, []
    for index, item in enumerate(interactions):
        try:
            key, request = _input_request(item, index)
        except RuntimeErrorSafe as exc:
            if getattr(exc, 'code', None) != 'invalid_chat_interaction':
                raise
            unpresentable.append(str(item.get('operation') or item.get('type')))
            continue
        requests[key] = request
    return requests, unpresentable


def _turn(*, person: str, operation: str, message: str, ctx: Context,
          thread_id: str | None = None) -> dict | InputRequiredResult:
    state = _state(ctx, person=person, operation=operation, thread_id=thread_id)
    if state is not None:
        thread_id = state['thread_id']
        decisions = _resume_decisions(state['interactions'], ctx.input_responses)
        result = dispatch(person=person, thread_id=thread_id, decisions=decisions, human_decision=True,
            expected_checkpoint=state.get('checkpoint_id'),
            approval_bindings=[i.get('binding') for i in state['interactions']])
    else:
        thread_id = thread_id or secrets.token_urlsafe(32)
        result = dispatch(person=person, thread_id=thread_id, message=message)

    refused: list[str] = []
    for _ in range(4):
        if result.get('status') != 'interrupted':
            break
        interactions = result.get('interactions') or []
        if not interactions or len(interactions) > 8:
            raise RuntimeErrorSafe('unsupported_chat_interaction')
        input_requests, unpresentable = _requests(interactions)
        if not unpresentable:
            request_state = json.dumps({'version': 1, 'person': person, 'operation': operation,
                                        'thread_id': thread_id, 'interactions': interactions,
                                        'checkpoint_id': result.get('checkpoint_id')},
                                       separators=(',', ':'), sort_keys=True)
            return InputRequiredResult(inputRequests=input_requests, requestState=request_state)
        # This adapter has no human wording for some of these operations, so it cannot put them to a person.
        # Reject the round rather than raising: a rejection authorizes nothing, while raising left the interrupt
        # checkpointed and no later message on this thread could get past it. The native HTTP API presents them.
        refused.extend(unpresentable)
        result = dispatch(person=person, thread_id=thread_id, human_decision=True,
            expected_checkpoint=result.get('checkpoint_id'),
            approval_bindings=[item.get('binding') for item in interactions],
            decisions=[{'type': 'reject'} if item['type'] == 'approval' else
                       {'type': 'respond', 'message': 'This client cannot ask the person for that. '
                        'Do not infer or invent the answer.'} for item in interactions])
    else:
        raise RuntimeErrorSafe('unsupported_chat_interaction')

    answer = {'schema_version': 1, 'type': 'assistant_message', 'status': 'complete',
              'thread_id': thread_id, 'answer': result.get('answer', ''),
              'todos': result.get('todos', []), 'tools': result.get('tools', [])}
    if refused:
        answer['refused_operations'] = sorted(set(refused))
    return answer


def create_server(*, token: str | None = None, person: str | None = None) -> FastMCP:
    """Create an authenticated MCP server. No unauthenticated mode is provided."""
    token = token if token is not None else os.environ.get('JOBWATCH_MCP_TOKEN')
    person = person if person is not None else os.environ.get('JOBWATCH_MCP_PERSON', users.DEFAULT_USER)
    if not token or len(token) < 32 or not users.valid_name(person):
        raise RuntimeErrorSafe('mcp_configuration_required')

    auth = _JobwatchTokenVerifier(token, person)
    oauth = None
    if os.environ.get('JOBWATCH_MCP_OAUTH') == '1':        # off by default; the bearer verifier stays valid either way
        from fastmcp.server.auth import MultiAuth
        from pipeline.agentic.mcp_oauth import JobwatchOAuth
        base_url, passphrase = os.environ.get('JOBWATCH_MCP_PUBLIC_URL'), os.environ.get('JOBWATCH_MCP_OAUTH_PASSPHRASE')
        if not base_url or not passphrase or len(passphrase) < 16:
            raise RuntimeErrorSafe('mcp_oauth_configuration_required')
        oauth = JobwatchOAuth(base_url=base_url, person=person, passphrase=passphrase)
        auth = MultiAuth(server=oauth, verifiers=[auth])

    state_key = hashlib.sha256(b'jobwatch-mcp-request-state\0' + token.encode()).digest()
    server = FastMCP('Jobwatch Career Ops',
        instructions=('Use career_ops_start_chat for a new natural-language Career Ops request. '
                      'Use career_ops_continue_chat with the opaque thread_id returned by the server. '
                      'Human questions and run approvals arrive as MCP elicitation requests; do not invent answers.'),
        auth=auth,
        request_state_security=RequestStateSecurity(keys=[state_key], ttl=86400),
        mask_error_details=True)

    @server.tool(name='career_ops_start_chat', title='Start a Jobwatch chat')
    def start_chat(message: str, ctx: Context) -> dict | InputRequiredResult:
        """Start a persistent Jobwatch Career Ops chat from a natural-language request."""
        return _turn(person=_person_from_request(), operation='start', message=message, ctx=ctx)

    @server.tool(name='career_ops_continue_chat', title='Continue a Jobwatch chat')
    def continue_chat(thread_id: str, message: str, ctx: Context) -> dict | InputRequiredResult:
        """Continue a chat using the opaque thread_id returned by career_ops_start_chat."""
        if not thread_id or len(thread_id) > 100:
            raise RuntimeErrorSafe('invalid_request')
        return _turn(person=_person_from_request(), operation='continue', thread_id=thread_id,
                     message=message, ctx=ctx)

    if oauth is not None:
        server.custom_route('/oauth/consent', methods=['GET', 'POST'])(oauth.consent)

    from pipeline.agentic import chatgpt_connector
    chatgpt_connector.register(server, lambda: _person_from_request())

    @server.resource('jobwatch://skills/career-ops', name='Career Ops skill',
                     description='Reusable Jobwatch Career Ops instructions and safety boundaries.')
    def career_ops_skill() -> str:
        """Return the packaged Career Ops skill instructions."""
        return _career_ops_skill()

    return server


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Jobwatch Career Ops MCP server')
    parser.add_argument('--host', default='127.0.0.1', help='Bind address (loopback by default)')
    parser.add_argument('--port', type=int, default=8914)
    args = parser.parse_args(argv)
    try:
        server = create_server()
    except RuntimeErrorSafe as exc:
        raise SystemExit(f'Jobwatch MCP not started: {exc.code}') from None
    server.run(transport='http', host=args.host, port=args.port)
    return 0
