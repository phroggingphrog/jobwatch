"""Synthetic evaluation completion must not imply application preparation."""
import pytest
from jobwatch.util.llm import LLM
from pipeline.agentic import service
from pipeline.agentic.persistence import latest_result
from pipeline.schemas import Stage
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401


def test_evaluation_completion_persists_artifacts_without_drafting(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    gateway = SyntheticGateway(bundle)
    def no_drafting(*args, **kwargs):
        raise AssertionError('drafting must not run')
    monkeypatch.setattr(service, 'draft_and_review', no_drafting)
    summary = service.agentic_batch_run([42], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate')
    result = latest_result(conn, 42)
    assert summary['evaluated'] == 1, (summary, result['reason'])
    assert summary['held'] == summary['ready'] == 0
    assert result['status'] == 'evaluated'
    assert result['reason'] == 'evaluation_complete'
    assert result['candidate'] is not None and result['evaluation'] is not None
    assert conn.execute('SELECT COUNT(*) FROM agentic_packages').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 0
    assert not {'submit_draft', 'submit_review'} & set(gateway.calls)
    assert str(Stage.EVALUATED) == 'evaluated'
    calls = len(gateway.calls)
    charged = conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0]
    replay = service.agentic_batch_run([42], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate')
    assert replay['evaluated'] == 1
    assert len(gateway.calls) == calls
    assert conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0] == charged


@pytest.mark.parametrize('blocker', ['profile_identity_missing', 'profile_contact_missing'])
def test_missing_document_identity_or_contact_does_not_block_evaluation(world, monkeypatch, blocker):
    conn, config, bundle, add = world
    add(43)
    monkeypatch.setattr('pipeline.agentic.draft.packaging_blocker', lambda profile: blocker)
    gateway = SyntheticGateway(bundle)
    summary = service.agentic_batch_run([43], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate')
    assert summary['evaluated'] == 1
    calls = len(gateway.calls)
    prepared = service.agentic_batch_run([43], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=gateway, keys=['synthetic']), operation='prepare')
    assert prepared['held'] == 1
    assert latest_result(conn, 43)['reason'] == blocker
    assert len(gateway.calls) == calls
