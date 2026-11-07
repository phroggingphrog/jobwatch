"""Bounded liveness refresh for evaluated postings: unpaid when unchanged, evaluate-only when inputs change."""
from datetime import datetime, timezone
from types import SimpleNamespace

from jobwatch.candidate.contracts import content_hash
from jobwatch.models import canonical_url
from jobwatch.util.llm import LLM
from pipeline import screened
from pipeline.agentic import service
from pipeline.agentic.liveness import PostingObservation, latest_observation, observation_current
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401


def _evaluated(config, conn, bundle, add, ident=42):
    add(ident)
    gateway = SyntheticGateway(bundle)
    summary = service.agentic_batch_run([ident], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate')
    assert summary['evaluated'] == 1, summary
    conn.execute('DELETE FROM agentic_posting_observations')
    conn.commit()
    return gateway


def _observation(conn, posting_id, *, text=None, status='active', reason='visible_job_description'):
    posting, stored, _mode = service._capture(conn, posting_id)
    base = dict(status=status, reason=reason, posting_id=posting_id,
        url_hash=content_hash(canonical_url(posting['url']).encode()),
        checked_at=datetime.now(timezone.utc).isoformat())
    if status != 'active':
        return PostingObservation(**base)
    text = stored if text is None else text
    return PostingObservation(**base, title=posting.get('title', ''), text=text,
        ad_hash=content_hash(text.encode()), source_url=posting['url'])


def _batch_stub(monkeypatch):
    calls = []
    def fake(ids, config, conn, **kwargs):
        calls.append((list(ids), kwargs))
        return {'processed': len(ids), 'evaluated': len(ids)}
    monkeypatch.setattr('pipeline.agentic.service.agentic_batch_run', fake)
    return calls


def test_unchanged_ad_renews_liveness_without_a_model_call(world, monkeypatch):
    conn, config, bundle, add = world
    _evaluated(config, conn, bundle, add)
    monkeypatch.setattr('pipeline.agentic.liveness.observe_posting',
                        lambda posting, **kw: _observation(conn, posting['id']))
    calls = _batch_stub(monkeypatch)
    out = screened.refresh_evaluated(conn, config)
    assert out['checked'] == 1 and out['current'] == 1 and out['reevaluated'] == 0
    assert calls == []
    current = latest_observation(conn, 42)
    posting, stored, _mode = service._capture(conn, 42)
    assert observation_current(current, posting_id=42, url=posting['url'],
                               ad_hash=content_hash(stored.encode()))


def test_changed_ad_queues_evaluation_never_preparation(world, monkeypatch):
    conn, config, bundle, add = world
    _evaluated(config, conn, bundle, add)
    posting, stored, _mode = service._capture(conn, 42)
    monkeypatch.setattr('pipeline.agentic.liveness.observe_posting',
                        lambda p, **kw: _observation(conn, p['id'], text=stored + '\nNew requirement.'))
    calls = _batch_stub(monkeypatch)
    out = screened.refresh_evaluated(conn, config)
    assert out['checked'] == 1 and out['reevaluated'] == 1
    assert calls and calls[0][0] == [42] and calls[0][1]['operation'] == 'evaluate'


def test_changed_run_key_queues_evaluation(world, monkeypatch):
    conn, config, bundle, add = world
    _evaluated(config, conn, bundle, add)
    monkeypatch.setattr('pipeline.agentic.liveness.observe_posting',
                        lambda posting, **kw: _observation(conn, posting['id']))
    monkeypatch.setattr('pipeline.agentic.service._run_key',
                        lambda *args, **kwargs: SimpleNamespace(value='synthetic-different-key'))
    calls = _batch_stub(monkeypatch)
    out = screened.refresh_evaluated(conn, config)
    assert out['checked'] == 1 and out['reevaluated'] == 1
    assert calls[0][0] == [42] and calls[0][1]['operation'] == 'evaluate'


def test_closed_ad_queues_the_archive_path(world, monkeypatch):
    conn, config, bundle, add = world
    _evaluated(config, conn, bundle, add)
    monkeypatch.setattr('pipeline.agentic.liveness.observe_posting',
                        lambda posting, **kw: _observation(conn, posting['id'], status='closed', reason='posting_closed'))
    calls = _batch_stub(monkeypatch)
    out = screened.refresh_evaluated(conn, config)
    assert out['closed'] == 1 and out['reevaluated'] == 1
    assert calls[0][0] == [42] and calls[0][1]['operation'] == 'evaluate'


def test_refresh_is_bounded_per_run(world, monkeypatch):
    conn, config, bundle, add = world
    _evaluated(config, conn, bundle, add, 42)
    _evaluated(config, conn, bundle, add, 43)
    config.settings.setdefault('pipeline', {}).setdefault('screened', {})['refresh_per_run'] = 1
    seen = []
    def observe(posting, **kw):
        seen.append(posting['id'])
        return _observation(conn, posting['id'])
    monkeypatch.setattr('pipeline.agentic.liveness.observe_posting', observe)
    _batch_stub(monkeypatch)
    out = screened.refresh_evaluated(conn, config)
    assert out['checked'] == 1 and len(seen) == 1
