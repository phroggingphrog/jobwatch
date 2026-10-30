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
import logging
import os
import secrets
from contextlib import contextmanager
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from mcp.server.request_state import RequestStateSecurity
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult

from jobwatch import users
from pipeline.agentic.chat import _career_ops_skill, dispatch
from pipeline.agentic.runtime import RuntimeErrorSafe
from pipeline.agentic import connector_http

log = logging.getLogger(__name__)

_MAX_QUESTION = 4000
_READ_PARSE = frozenset({'evaluation', 'model_insights', 'company_research'})


class _JobwatchTokenVerifier(TokenVerifier):
    """Two proofs: a Cloudflare Access assertion, or the configured static token.

    The static token is the local path (stdio, a loopback client). The Access assertion is the public path and is
    verified against the team key set; the person comes from the verified email claim, never from a guess.
    """

    def __init__(self, token: str | None, person: str, access=None):
        super().__init__(required_scopes=['jobwatch'])
        self._token, self._person, self._access = token, person, access

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._token and token and hmac.compare_digest(token, self._token):
            return AccessToken(token=token, client_id='jobwatch-chat', scopes=['jobwatch'],
                               subject=self._person, claims={'sub': self._person})
        if self._access is not None and self._access.enabled:
            from pipeline.agentic import mcp_access
            try:
                identity = mcp_access.verify_access_jwt(token, keys=self._access.keys,
                                                        audience=self._access.audience,
                                                        issuer=self._access.issuer)
                person = mcp_access.person_for_email(identity.email, self._access.mapping)
            except mcp_access.AccessError as exc:
                log.warning('mcp: access refused: %s', exc.code)
                return None
            return AccessToken(token=token, client_id='cloudflare-access', scopes=['jobwatch'],
                               subject=person, claims={'sub': person, 'email': identity.email})
        return None


def _person_from_request() -> str:
    token = get_access_token()
    person = token.subject if token else None
    if not users.valid_name(person):
        raise RuntimeErrorSafe('mcp_auth_required')
    return person


@contextmanager
def _read():
    """A read-only, person-scoped connection for one read tool. Identity comes from the verified token only.

    A read never starts a chat turn: no model call, no ledger charge and no approval prompt.
    """
    from jobwatch.config import load_config
    from pipeline.agentic.chat import job_connection
    person = _person_from_request()
    with users.use(person):
        with job_connection(load_config()) as conn:
            yield conn

def _identifier(value) -> int:
    if type(value) is not int or value < 1:
        raise RuntimeErrorSafe('invalid_request')
    return value

def _day(value) -> str | None:
    return value.isoformat() if value is not None else None

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


class _AccessHeaderMiddleware:
    """Promote Cloudflare's forwarded assertion to the bearer the verifier already understands.

    Cloudflare adds `Cf-Access-Jwt-Assertion` to every request that passed the Access application. A browser login
    therefore already proves identity, and the client need not obtain a token of its own. Nothing is trusted here:
    the assertion is only moved into the Authorization header, where verify_access_jwt checks its signature, issuer
    and expiry exactly as before.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            forwarded = next((v for k, v in scope.get("headers", [])
                              if k.lower() == b"cf-access-jwt-assertion"), None)
            if forwarded:                          # only an edge-authenticated request is rewritten
                headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"authorization"]
                headers.append((b"authorization", b"Bearer " + forwarded))
                scope = dict(scope, headers=headers)
        await self.app(scope, receive, send)

def create_server(*, token: str | None = None, person: str | None = None, access=None) -> FastMCP:
    """Create an authenticated MCP server. No unauthenticated mode is provided."""
    if access is None:
        from pipeline.agentic import mcp_access
        try:
            access = mcp_access.settings_from_env()
        except mcp_access.AccessError as exc:
            log.warning('mcp: access key set unavailable (%s); falling back to the static token', exc.code)
            access = mcp_access.settings_from_env({'JOBWATCH_MCP_ACCESS': 'off'}, fetch=False)
    token = token if token is not None else os.environ.get('JOBWATCH_MCP_TOKEN')
    person = person if person is not None else os.environ.get('JOBWATCH_MCP_PERSON', users.DEFAULT_USER)
    # A static token stays mandatory unless Access is the front door; without either, no server starts.
    if not users.valid_name(person) or (not access.enabled and (not token or len(token) < 32)) \
            or (access.enabled and not access.requires_jwt and token and len(token) < 32):
        raise RuntimeErrorSafe('mcp_configuration_required')

    auth = _JobwatchTokenVerifier(token, person, access)
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
                      'Use career_reader for the stored advertisement and followup_history for follow-up cadence. '
                      'Both are read-only and spend nothing. '
                      'Human questions and run approvals arrive as MCP elicitation requests; do not invent answers.'),
        auth=auth,
        request_state_security=RequestStateSecurity(keys=[state_key], ttl=86400),
        mask_error_details=True)

    from pipeline.agentic import chatgpt_connector
    read_only = chatgpt_connector.READ_ONLY      # clients can tell a read from work before they call it

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

    @server.tool(name='career_reader', title='Read a saved job advertisement', annotations=read_only)
    def career_reader(posting_id: int) -> dict:
        """Read the stored advertisement and its identity for one posting. No model call, no host path."""
        posting_id = _identifier(posting_id)
        from pipeline.agentic.service import _capture
        with _read() as jobs:
            captured = _capture(jobs, posting_id)
        if captured is None:
            return {'posting_id': posting_id, 'status': 'missing'}
        identity, text, kind = captured
        return {'posting_id': posting_id, 'status': 'ok', 'posting': identity, 'full_ad': text, 'text_kind': kind}

    @server.tool(name='followup_history', title='Read follow-up cadence', annotations=read_only)
    def followup_history(application_id: int) -> dict:
        """Read recorded follow-up events and cadence for one application. Counts and dates only; sends nothing."""
        application_id = _identifier(application_id)
        from jobwatch.followup import events as followup_events
        try:
            with _read() as jobs:
                hist = followup_events.history(jobs, application_id)
                due = followup_events.application_cadence(jobs, application_id)
        except followup_events.FollowupEventError as exc:
            if str(exc) == 'application_missing':
                return {'application_id': application_id, 'status': 'missing'}
            return {'application_id': application_id, 'status': 'unknown', 'reason': str(exc)}
        return {'application_id': application_id, 'status': 'ok', 'application_status': hist.status,
                'applied_on': _day(hist.applied_on), 'response_on': _day(hist.response_on),
                'interview_completed_on': _day(hist.interview_completed_on),
                'sent_on': [_day(d) for d in hist.sent_on], 'pin_active': bool(hist.pin_active),
                'pin_due_on': _day(hist.pin.due_on) if hist.pin else None,
                'cadence': {'state': due.state, 'kind': due.kind, 'due_on': _day(due.due_on),
                            'sent_count': due.sent_count,
                            'followups_since_response': due.followups_since_response,
                            'draft_allowed': due.draft_allowed, 'reason': due.reason}}

    if oauth is not None:
        server.custom_route('/oauth/consent', methods=['GET', 'POST'])(oauth.consent)

    chatgpt_connector.register(server, lambda: _person_from_request())

    @server.tool(name='onboarding_status', title='Read onboarding status')
    def onboarding_status() -> dict:
        """Read the authenticated person's onboarding status."""
        return connector_http.onboarding_status_operation(_person_from_request())

    @server.tool(name='onboarding_start', title='Start onboarding')
    def onboarding_start(upload_ids: list[str], base_version: int) -> dict:
        """Start onboarding from the authenticated person's saved uploads."""
        body = connector_http.OnboardingStart(upload_ids=upload_ids, base_version=base_version)
        return connector_http.onboarding_start_operation(_person_from_request(), body)

    @server.tool(name='onboarding_update', title='Update onboarding draft')
    def onboarding_update(proposal_id: str, expected_revision: int, edits: list[dict]) -> dict:
        """Apply typed edits to the authenticated person's onboarding draft."""
        body = connector_http.OnboardingUpdate(proposal_id=proposal_id, expected_revision=expected_revision, edits=edits)
        return connector_http.onboarding_update_operation(_person_from_request(), body)

    @server.tool(name='onboarding_answer', title='Answer onboarding question')
    def onboarding_answer(proposal_id: str, expected_revision: int, question_id: str, text: str) -> dict:
        """Record an answer to a question in the authenticated person's onboarding draft."""
        body = connector_http.OnboardingAnswer(proposal_id=proposal_id, expected_revision=expected_revision,
                                               question_id=question_id, text=text)
        return connector_http.onboarding_answer_operation(_person_from_request(), body)

    @server.tool(name='onboarding_review', title='Review onboarding draft')
    def onboarding_review(proposal_id: str) -> dict:
        """Review the authenticated person's onboarding proposal."""
        body = connector_http.OnboardingProposal(proposal_id=proposal_id)
        return connector_http.onboarding_review_operation(_person_from_request(), body)

    @server.tool(name='onboarding_confirm', title='Confirm onboarding profile')
    def onboarding_confirm(proposal_id: str, proposal_digest: str, scope_digest: str,
                           confirmed: bool) -> dict:
        """Confirm the exact reviewed onboarding profile for the authenticated person."""
        body = connector_http.OnboardingConfirm(proposal_id=proposal_id, proposal_digest=proposal_digest,
                                                 scope_digest=scope_digest, confirmed=confirmed)
        return connector_http.onboarding_confirm_operation(_person_from_request(), body)

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
    import uvicorn
    app = server.http_app(path='/mcp')
    uvicorn.run(_AccessHeaderMiddleware(app), host=args.host, port=args.port, log_level='info')
    return 0
