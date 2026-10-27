"""Direct, account-bound onboarding operations for an authenticated MCP client.

The client handles the person's conversation and explicit approval. Jobwatch checks
the exact draft and search-scope digests through its canonical intake operations.
"""
from __future__ import annotations

from jobwatch import users
from jobwatch.candidate import intake
from jobwatch.config import load_config
from pipeline.agentic import service


def _status(person, proposal=None):
    proposal = proposal if proposal is not None else intake.open_proposal(person)
    current = intake.current_version(person)
    return {'status': proposal.status if proposal is not None else 'confirmed' if current else 'not_started',
            'proposal': proposal.model_dump(mode='json') if proposal is not None else None,
            'current_version': current}


def status(person):
    with users.use(person):
        return _status(person)


def start(person, upload_ids, base_version=None):
    with users.use(person):
        config = load_config()
        proposal = intake.start_proposal(person, upload_ids, service.configured_llm(config),
                                         base_version=base_version)
        return _status(person, proposal)


def update(person, proposal_id, expected_revision, edits):
    with users.use(person):
        return _status(person, intake.edit(person, proposal_id, expected_revision=expected_revision, edits=edits))


def answer(person, proposal_id, expected_revision, question_id, text):
    with users.use(person):
        return _status(person, intake.answer(person, proposal_id, expected_revision=expected_revision,
                                            question_id=question_id, text=text))


def review(person, proposal_id):
    with users.use(person):
        proposal = intake.load_proposal(person, proposal_id)
        shown = intake.confirmation(person, proposal_id, load_config())
        if intake.digest(proposal) != shown['proposal_digest']:
            raise intake.IntakeError('proposal_changed')
        return {'status': 'ready', 'proposal': proposal.model_dump(mode='json'),
                **shown, 'scope': shown['scope'].model_dump(mode='json')}


def confirm(person, proposal_id, proposal_digest, scope_digest):
    with users.use(person):
        version = intake.confirm(person, proposal_id, proposal_digest=proposal_digest,
                                 scope_digest=scope_digest, actor='person', config=load_config())
        scope = intake.discovery_scope(person)
        return {'status': 'confirmed', 'version': version,
                'discovery': scope.model_dump(mode='json') if scope is not None else None,
                'discovery_enabled': scope is not None,
                'authorises': list(intake.AUTHORISES), 'does_not_authorise': list(intake.DOES_NOT_AUTHORISE)}
