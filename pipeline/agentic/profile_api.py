"""Native HTTP surface for profile intake and approval. The person always comes from the bearer token."""
from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import users
from jobwatch.candidate import intake
from jobwatch.candidate.intake import IntakeError

PREFIX = '/api/agent/profile'
UPLOAD_PATH = PREFIX + '/uploads'
UPLOAD_BODY_CAP = intake.MAX_UPLOAD_BYTES + 64 * 1024     # file cap plus multipart framing; the exact file cap is intake's
STATUS = {'proposal_in_progress': 409, 'proposal_parsing': 409, 'proposal_changed': 409, 'scope_changed': 409, 'adopt_first': 409, 'proposal_not_draft': 409,
          'already_adopted': 409, 'profile_incomplete': 409, 'profile_edited_by_hand': 409,
          'too_large': 413, 'unsupported_type': 415,
          'no_extractable_text': 422, 'invalid_edit': 422, 'parse_failed': 422, 'unreadable_document': 422,
          'nothing_to_adopt': 422,
          'upload_not_found': 404, 'proposal_not_found': 404, 'fact_not_found': 404, 'question_not_found': 404,
          'extractor_unavailable': 503, 'person_required': 403}


class _Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ProposalRequest(_Body):
    upload_ids: list[str] = Field(min_length=1, max_length=20)
    base_version: int | None = None


class UploadsRequest(_Body):
    upload_ids: list[str] = Field(min_length=1, max_length=20)


class EditRequest(_Body):
    expected_revision: int
    edits: list[dict] = Field(max_length=100)


class AnswerRequest(_Body):
    expected_revision: int
    question_id: str = Field(max_length=64)
    text: str = Field(max_length=4000)


class ScopeConfirmRequest(_Body):
    base_version: int
    scope_digest: str = Field(max_length=128)


class ConfirmRequest(_Body):
    proposal_digest: str = Field(max_length=128)
    scope_digest: str = Field(max_length=128)


def mount(app, require, get_config, llm_factory):
    read, run, interact, approve = (require(s) for s in ('read', 'run', 'interact', 'approve'))

    @app.exception_handler(IntakeError)
    async def intake_failed(request, exc):
        return JSONResponse({'error': exc.code}, status_code=STATUS[exc.code])

    def dump(proposal):
        return proposal.model_dump(mode='json')

    def call(person, fn, *args, **kwargs):
        with users.use(person):                      # same per-person context the other handlers run in
            return fn(person, *args, **kwargs)

    @app.post(UPLOAD_PATH, status_code=201)
    async def upload(request: Request, principal=Depends(run)):
        try:
            form = await request.form()
            file, kind = form.get('file'), form.get('kind')
        except Exception:
            raise HTTPException(422, 'invalid_upload') from None
        if not hasattr(file, 'read') or not isinstance(kind, str):
            raise HTTPException(422, 'invalid_upload')
        data = await file.read(intake.MAX_UPLOAD_BYTES + 1)
        return await asyncio.to_thread(call, principal.person, intake.save_upload, file.filename or '', data, kind)

    def model(person):
        llm = llm_factory(person) if llm_factory else None
        if llm is None:
            from jobwatch.llm import LLM
            llm = LLM()
        return llm

    @app.post(PREFIX + '/proposals', status_code=202)
    def propose(body: ProposalRequest, principal=Depends(run)):
        # Returns the pending draft at once; the one paid parse (intake's per-person slot, 180 s) runs in the background.
        return dump(call(principal.person, intake.start_proposal, body.upload_ids, model(principal.person),
                         base_version=body.base_version))

    @app.post(PREFIX + '/proposals/{proposal_id}/uploads', status_code=202)
    def add_uploads(proposal_id: str, body: UploadsRequest, principal=Depends(run)):
        return dump(call(principal.person, intake.add_uploads, proposal_id, body.upload_ids, model(principal.person)))

    @app.get(PREFIX + '/proposals/{proposal_id}')
    def get_proposal(proposal_id: str, principal=Depends(read)):
        return dump(call(principal.person, intake.load_proposal, proposal_id))

    @app.patch(PREFIX + '/proposals/{proposal_id}')
    def edit(proposal_id: str, body: EditRequest, principal=Depends(interact)):
        return dump(call(principal.person, intake.edit, proposal_id, expected_revision=body.expected_revision, edits=body.edits))

    @app.post(PREFIX + '/proposals/{proposal_id}/answers')
    def answer(proposal_id: str, body: AnswerRequest, principal=Depends(interact)):
        return dump(call(principal.person, intake.answer, proposal_id, expected_revision=body.expected_revision,
                         question_id=body.question_id, text=body.text))

    @app.get(PREFIX + '/proposals/{proposal_id}/confirmation')
    def confirmation(proposal_id: str, principal=Depends(read)):
        result = call(principal.person, intake.confirmation, proposal_id, get_config(principal.person))
        return {**result, 'scope': result['scope'].model_dump(mode='json')}

    @app.post(PREFIX + '/proposals/{proposal_id}/confirm', status_code=201)
    def confirm(proposal_id: str, body: ConfirmRequest, principal=Depends(approve)):
        # The scope token is the approval; actor is fixed here, never read from the body or from model text.
        n = call(principal.person, intake.confirm, proposal_id, proposal_digest=body.proposal_digest,
                 scope_digest=body.scope_digest, actor='person', config=get_config(principal.person))
        return {'version': n}

    @app.get(PREFIX + '/scope-confirmation')
    def scope_confirmation(principal=Depends(read)):
        # For a person with an approved version but no confirmed scope (e.g. adopted files): what discovery would cover.
        result = call(principal.person, intake.scope_confirmation, get_config(principal.person))
        return {**result, 'scope': result['scope'].model_dump(mode='json')}

    @app.post(PREFIX + '/scope-confirm', status_code=201)
    def scope_confirm(body: ScopeConfirmRequest, principal=Depends(approve)):
        n = call(principal.person, intake.confirm_scope, base_version=body.base_version, scope_digest=body.scope_digest,
                 actor='person', config=get_config(principal.person))
        return {'version': n}

    @app.get(PREFIX + '/')
    def current(principal=Depends(read)):
        return call(principal.person, intake.current_version) or {'version': None}

    @app.get(PREFIX + '/versions')
    def versions(principal=Depends(read)):
        return {'versions': call(principal.person, intake.versions)}
