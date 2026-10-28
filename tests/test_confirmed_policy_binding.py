"""Policy and run key must bind the same immutable approved profile."""
from copy import deepcopy
import pytest

from tests.test_agentic_service import world  # noqa: F401

def test_confirmation_between_policy_capture_and_key_aborts_before_paid_work(world, monkeypatch):
    from jobwatch import users
    from jobwatch.candidate import intake
    from pipeline.agentic import service
    from pipeline.agentic.contracts import AgenticError
    conn, config, bundle, add = world
    add(42)
    first = intake.current_version(users.current())
    changed = deepcopy(first)
    changed['version'] += 1
    reads = []
    def current(person):
        reads.append(person)
        return first if len(reads) == 1 else changed
    monkeypatch.setattr(intake, 'current_version', current)
    monkeypatch.setattr(service, 'configured_llm', lambda *_: pytest.fail('paid work before coherent snapshot'))
    with pytest.raises(AgenticError, match='snapshot_changed'):
        service.run_agentic_job(42, config, conn, evidence_bundle=bundle)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='agentic_runs'").fetchone()[0] == 0


def test_cached_ready_does_not_survive_confirmation_during_public_recheck(world, monkeypatch):
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.util.llm import LLM
    from pipeline.agentic import service
    from pipeline.agentic.persistence import latest_result
    from pipeline.schemas import Stage
    from tests.test_agentic_service import SyntheticGateway
    conn, config, bundle, add = world
    add(42)
    llm = LLM(transport=SyntheticGateway(bundle), keys=['synthetic'])
    assert service.run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm) == Stage.READY
    approved = intake.current_version(users.current())
    changed = deepcopy(approved)
    changed['version'] += 1
    original = service.observe_posting
    def recheck(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(intake, 'current_version', lambda _: changed)
        return result
    monkeypatch.setattr(service, 'observe_posting', recheck)
    assert service.run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm) == Stage.DLQ
    assert latest_result(conn, 42)['reason'] == 'snapshot_changed'
