import sqlite3

import pytest

from pipeline.agentic.contracts import AgenticError, BudgetCheckpoint, Reservation, RunKey
from pipeline.agentic.store import AgenticStore, Claim

H = "a" * 64


def key(posting=1, ad="b"):
    return RunKey(posting_id=posting, ad_hash=ad * 64, evidence_hash="c" * 64,
                  rubric_version="r1", config_hash="d" * 64)


def empty(run_key, batch="batch", batch_deadline=500.0, batch_ceiling=1000):
    return BudgetCheckpoint(schema_version=1, run_key=run_key, batch_id=batch, revision=1,
                            job_token_ceiling=500, batch_token_ceiling=batch_ceiling,
                            job_charged=0, batch_charged=0, failed_attempts=0,
                            role_turns={}, research_queries=0, research_pages=0,
                            job_deadline=400.0, batch_deadline=batch_deadline, reservations=())


def reserve(base, rid="r1", *, role="evaluator", inp=10, out=20):
    item = Reservation(reservation_id=rid, role=role, input_tokens=inp,
                       requested_output_tokens=out, charged_tokens=inp + out,
                       state="reserved")
    turns = dict(base.role_turns)
    turns[role] = turns.get(role, 0) + 1
    return BudgetCheckpoint(**{**base.model_dump(), "revision": base.revision + 1,
                               "job_charged": base.job_charged + inp + out,
                               "batch_charged": max(base.batch_charged, base.job_charged + inp + out),
                               "reservations": (*base.reservations, item), "role_turns": turns})


class Harness:
    def __init__(self, path):
        self.path = str(path)
        self.now = 100.0
        self.a = sqlite3.connect(self.path, timeout=2, isolation_level="DEFERRED")
        self.b = sqlite3.connect(self.path, timeout=2, isolation_level="DEFERRED")
        self.store = AgenticStore(self.a, clock=lambda: self.now)
        self.other = AgenticStore(self.b, clock=lambda: self.now)
        self.store.ensure()
        self.store.create_batch("batch", 1000, 500.0)


def test_two_connections_fence_live_claims_and_expired_generations(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    rk = key()
    first = h.store.claim(rk, "worker-a", 10)
    assert isinstance(first, Claim)
    assert first.generation == 1 and first.lease_until == 110
    assert h.other.claim(rk, "worker-b", 10) is None

    h.now = 111
    second = h.other.claim(rk, "worker-b", 10)
    assert second.generation == 2
    with pytest.raises(AgenticError) as caught:
        h.store.renew(first, 10)
    assert caught.value.code == "stale_claim"
    h.other.renew(second, 20)
    with pytest.raises(AgenticError):
        h.store.release(first)


def test_claim_rejects_boolean_generation_even_when_equal_to_one(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    claim = h.store.claim(key(), "worker", 60)
    copied = Claim(claim.run_key, claim.posting_id, claim.owner, True, claim.lease_until)
    with pytest.raises(AgenticError) as caught:
        h.store.load_checkpoint(copied)
    assert caught.value.code == "stale_claim"


def test_claim_copy_must_match_database_lease_fence(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    claim = h.store.claim(key(), "worker", 60)
    copied = Claim(claim.run_key, claim.posting_id, claim.owner, claim.generation, claim.lease_until + 1)
    with pytest.raises(AgenticError) as caught:
        h.store.load_checkpoint(copied)
    assert caught.value.code == "stale_claim"


def test_checkpoint_cas_and_operation_replay_keep_authoritative_batch_totals(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    claim = h.store.claim(key(), "worker", 60)
    initial = empty(claim.run_key)
    saved = h.store.save_budget(claim, initial, expected_revision=0,
                                operation_id="snapshot-1", kind="snapshot")
    assert saved.revision == 1

    proposed = reserve(saved)
    charged = h.store.save_budget(claim, proposed, expected_revision=1,
                                  operation_id="reserve-r1", kind="reserve")
    assert charged.job_charged == 30 and charged.batch_charged == 30
    replay = h.other.save_budget(claim, proposed, expected_revision=1,
                                 operation_id="reserve-r1", kind="reserve")
    assert replay.revision == charged.revision and replay.job_charged == 30
    with pytest.raises(AgenticError) as caught:
        h.store.save_budget(claim, reserve(saved, "r2"), expected_revision=1,
                            operation_id="reserve-r1", kind="reserve")
    assert caught.value.code in {"operation_conflict", "invalid_transition"}
    with pytest.raises(AgenticError):
        h.store.save_budget(claim, proposed, expected_revision=1,
                            operation_id="different-id", kind="reserve")


def test_changed_input_uses_posting_wide_monotonic_generation(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    first = h.store.claim(key(1, "b"), "worker-a", 60)
    changed = h.other.claim(key(1, "e"), "worker-b", 60)
    assert changed.generation > first.generation


def test_changed_input_uses_posting_wide_monotonic_generation(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    first = h.store.claim(key(1, "b"), "worker-a", 60)
    changed = h.other.claim(key(1, "e"), "worker-b", 60)
    assert changed.generation > first.generation


def test_two_jobs_share_atomic_batch_ceiling_and_keep_history_on_changed_input(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    h.store.create_batch("tight", 35, 500.0)
    c1 = h.store.claim(key(1), "w1", 60)
    c2 = h.other.claim(key(2), "w2", 60)
    one = empty(c1.run_key, "tight", 500, 35)
    two = empty(c2.run_key, "tight", 500, 35)
    one = h.store.save_budget(c1, one, expected_revision=0, operation_id="s1", kind="snapshot")
    two = h.other.save_budget(c2, two, expected_revision=0, operation_id="s2", kind="snapshot")
    h.store.save_budget(c1, reserve(one, inp=10, out=20), expected_revision=1,
                        operation_id="r1", kind="reserve")
    with pytest.raises(AgenticError):
        h.other.save_budget(c2, reserve(two, inp=10, out=20), expected_revision=1,
                            operation_id="r2", kind="reserve")

    new_claim = h.other.claim(key(1, "e"), "w3", 60)
    assert new_claim.generation > c1.generation
    with pytest.raises(AgenticError) as caught:
        h.store.save_budget(c1, reserve(one), expected_revision=1,
                            operation_id="old-worker", kind="reserve")
    assert caught.value.code == "stale_claim"
    # New inputs get a clean per-run checkpoint; the previous run's batch charge remains spent.
    assert h.other.load_checkpoint(new_claim) is None
    assert h.b.execute("SELECT charged FROM agentic_batches WHERE batch_id='tight'").fetchone()[0] == 30
    assert h.store.load_checkpoint(c2).job_charged == 0


def test_reservation_settlement_failure_research_and_snapshots_are_monotone(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    claim = h.store.claim(key(), "worker", 60)
    current = h.store.save_budget(claim, empty(claim.run_key), expected_revision=0,
                                  operation_id="s", kind="snapshot")
    current = h.store.save_budget(claim, reserve(current), expected_revision=1,
                                  operation_id="r", kind="reserve")
    dispatched = current.reservations[0].model_copy(update={"state": "dispatched"})
    proposal = BudgetCheckpoint(**{**current.model_dump(), "revision": 3, "reservations": (dispatched,)})
    current = h.store.save_budget(claim, proposal, expected_revision=2,
                                  operation_id="d", kind="dispatched")
    settled = current.reservations[0].model_copy(update={"state": "settled", "actual_usage": 12,
                                                        "charged_tokens": 12})
    proposal = BudgetCheckpoint(**{**current.model_dump(), "revision": 4, "job_charged": 12, "batch_charged": 30,
                                   "reservations": (settled,)})
    current = h.store.save_budget(claim, proposal, expected_revision=3,
                                  operation_id="t", kind="settle")
    assert current.job_charged == current.batch_charged == 12

    tampered = BudgetCheckpoint(**{**current.model_dump(), "revision": 5,
                                   "reservations": (), "job_charged": 0})
    with pytest.raises(AgenticError):
        h.store.save_budget(claim, tampered, expected_revision=4,
                            operation_id="refund", kind="snapshot")
    reset = BudgetCheckpoint(**{**current.model_dump(), "revision": 5, "role_turns": {}})
    with pytest.raises(AgenticError):
        h.store.save_budget(claim, reset, expected_revision=4,
                            operation_id="reset", kind="snapshot")


def test_expiry_malformed_stored_data_and_external_transaction_are_safe(tmp_path):
    h = Harness(tmp_path / "store.sqlite")
    claim = h.store.claim(key(), "worker", 5)
    saved = h.store.save_budget(claim, empty(claim.run_key), expected_revision=0,
                                operation_id="s", kind="snapshot")
    h.now = 106
    with pytest.raises(AgenticError) as caught:
        h.store.load_checkpoint(claim)
    assert caught.value.code == "stale_claim"
    refreshed = h.other.claim(key(), "worker-2", 20)
    assert h.other.load_checkpoint(refreshed).revision == saved.revision
    h.b.execute("UPDATE agentic_runs SET checkpoint_json=? WHERE run_key=?", ("{bad", refreshed.run_key))
    h.b.commit()
    with pytest.raises(AgenticError) as caught:
        h.other.load_checkpoint(refreshed)
    assert caught.value.code == "invalid_checkpoint"
    assert "bad" not in str(caught.value) and caught.value.__context__ is None
    h.a.execute("INSERT INTO unrelated_table VALUES (1)") if False else None
    h.a.execute("BEGIN")
    with pytest.raises(AgenticError):
        h.store.renew(refreshed, 10)
    h.a.rollback()


def test_worker_research_checkpoint_preserves_claim_fence_before_search(tmp_path):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pipeline.agentic.runtime import BatchBudget, RuntimeErrorSafe
    from pipeline.agentic.service import _budget
    from pipeline.agentic.research import PublicSnapshot, ResearchCapability, ResearchIntent
    conn = sqlite3.connect(str(tmp_path / 'worker-checkpoint.sqlite'))
    store = AgenticStore(conn); store.ensure()
    batch = BatchBudget('worker-research', token_ceiling=100000, deadline=time.time()+1800)
    store.create_batch(batch.batch_id, batch._state.token_ceiling, batch.deadline)
    claim = store.claim(key(), 'first', 900)
    budget = _budget(store, claim, {'job_seconds': 900, 'job_token_ceiling': 100000}, batch)
    store.release(claim, status='held', reason='test')
    replacement = store.claim(key(), 'replacement', 900)
    assert replacement.generation > claim.generation
    queries = []
    class Search:
        def search(self, query, **kwargs):
            queries.append(query)
            return []
    research = ResearchCapability(PublicSnapshot('Public Employer', 'Analyst', 'https://example.com/job'),
                                  budget=budget, search_provider=Search())
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(research.search, ResearchIntent.EMPLOYER_IDENTITY)
        with pytest.raises(RuntimeErrorSafe, match='checkpoint_unavailable'):
            future.result()
    assert not queries
    row = conn.execute('SELECT generation, checkpoint_json FROM agentic_runs').fetchone()
    import json
    assert row[0] == replacement.generation
    assert json.loads(row[1])['research_queries'] == 0
    assert conn.execute('SELECT charged FROM agentic_batches').fetchone()[0] == 0
    conn.close()
