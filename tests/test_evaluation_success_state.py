"""Synthetic evaluation completion must not imply application preparation."""
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
