"""An unstarted quota deferral must not inherit yesterday's tiny batch allocation."""
import time

from jobwatch.util.llm import LLM
from pipeline.agentic import incidents, service
from pipeline.agentic.persistence import latest_result
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401


def test_unstarted_daily_deferral_can_resume_in_fresh_batch_preserving_prior_spend(world):
    conn, config, bundle, add = world
    add(42)
    store = service.AgenticStore(conn)
    store.ensure()
    store.create_batch('legacy-small-allocation', 10, time.time()+600)
    conn.execute("UPDATE agentic_batches SET charged=3 WHERE batch_id='legacy-small-allocation'")
    conn.commit()
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    first = service.agentic_batch_run([42], config, conn, batch_id='legacy-small-allocation',
        evidence_bundle=bundle, llm=llm, operation='evaluate', token_allowance=1)
    assert first['skipped_reasons'] == {'daily_budget': 1} and not gateway.calls
    second = service.agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=llm,
                                      operation='evaluate', token_allowance=100_000)
    assert latest_result(conn, 42)['reason'] == 'evaluation_complete'
    assert second['processed'] == 1 and gateway.calls
    assert incidents.list_incidents(conn) == []
    assert conn.execute("SELECT charged FROM agentic_batches WHERE batch_id='legacy-small-allocation'").fetchone()[0] == 3
