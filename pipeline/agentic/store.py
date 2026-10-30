"""Additive SQLite persistence for fenced agentic runs and budget checkpoints."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Literal

from .contracts import AgenticError, BudgetCheckpoint, RunKey, parse_budget_checkpoint_json


@dataclass(frozen=True)
class Claim:
    run_key: str
    posting_id: int
    owner: str
    generation: int
    lease_until: float


_KINDS = {"reserve", "dispatched", "settle", "failure", "research", "snapshot"}


def _fail(code: str):
    raise AgenticError(code) from None


def _parse_wire(value: BudgetCheckpoint) -> BudgetCheckpoint:
    if type(value) is not BudgetCheckpoint:
        _fail("invalid_checkpoint")
    try:
        payload = value.model_dump_json()
        parsed = parse_budget_checkpoint_json(payload)
    except Exception:
        parsed = None
    if parsed is None:
        _fail("invalid_checkpoint")
    return parsed


def _json(value: BudgetCheckpoint) -> str:
    return value.model_dump_json()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(model) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _checkpoint_equal(a: BudgetCheckpoint, b: BudgetCheckpoint, *, batch=True) -> bool:
    left, right = a.model_dump(mode="json"), b.model_dump(mode="json")
    if not batch:
        left.pop("batch_charged", None)
        right.pop("batch_charged", None)
    return left == right


class AgenticStore:
    def __init__(self, conn: sqlite3.Connection, *, clock: Callable[[], float] = time.time):
        self.conn = conn
        self.clock = clock

    def _begin(self):
        if self.conn.in_transaction:
            _fail("transaction_active")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            _fail("store_unavailable")

    def _commit(self):
        try:
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            _fail("store_unavailable")

    def _rollback(self):
        if self.conn.in_transaction:
            self.conn.rollback()

    def ensure(self) -> None:
        if self.conn.in_transaction:
            _fail("transaction_active")
        try:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS agentic_posting_observations (
                    id INTEGER PRIMARY KEY, posting_id INTEGER NOT NULL, run_key TEXT NOT NULL,
                    generation INTEGER NOT NULL, observation_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS agentic_observations_posting ON agentic_posting_observations(posting_id,id);
                CREATE TABLE IF NOT EXISTS agentic_draft_admissions (
                    run_key TEXT NOT NULL, generation INTEGER NOT NULL, batch_id TEXT NOT NULL,
                    admitted_at REAL NOT NULL, PRIMARY KEY(run_key,generation)
                );
                CREATE INDEX IF NOT EXISTS agentic_draft_time ON agentic_draft_admissions(admitted_at);
                CREATE TABLE IF NOT EXISTS agentic_quota_waits (
                    run_key TEXT PRIMARY KEY, offset_seconds REAL NOT NULL DEFAULT 0,
                    paused_at REAL
                );
                CREATE TABLE IF NOT EXISTS agentic_batches (
                    batch_id TEXT PRIMARY KEY, token_ceiling INTEGER NOT NULL,
                    charged INTEGER NOT NULL DEFAULT 0, deadline REAL NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS agentic_runs (
                    run_key TEXT PRIMARY KEY, posting_id INTEGER NOT NULL, owner TEXT,
                    generation INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
                    checkpoint_revision INTEGER NOT NULL DEFAULT 0, checkpoint_json TEXT,
                    status TEXT NOT NULL DEFAULT 'new', reason TEXT
                );
                CREATE INDEX IF NOT EXISTS agentic_runs_posting ON agentic_runs(posting_id);
                CREATE TABLE IF NOT EXISTS agentic_activity (
                    id INTEGER PRIMARY KEY, run_key TEXT, posting_id INTEGER,
                    collector_run_id INTEGER, batch_id TEXT, invocation_id TEXT,
                    event TEXT NOT NULL, at REAL NOT NULL, reason TEXT
                );
                CREATE TABLE IF NOT EXISTS agentic_budget_ops (
                    operation_id TEXT PRIMARY KEY, run_key TEXT NOT NULL, owner TEXT NOT NULL,
                    generation INTEGER NOT NULL, kind TEXT NOT NULL, digest TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agentic_artifacts (
                    run_key TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
                    sha256 TEXT NOT NULL, PRIMARY KEY(run_key,kind)
                );
                CREATE TABLE IF NOT EXISTS agentic_packages (
                    run_key TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL,
                    application_id INTEGER NOT NULL, draft_id INTEGER NOT NULL,
                    version INTEGER NOT NULL, package_dir TEXT NOT NULL,
                    phase TEXT NOT NULL DEFAULT 'prepared'
                );
                CREATE TABLE IF NOT EXISTS agentic_ledger_outbox (
                    id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
                    run_key TEXT NOT NULL, kind TEXT NOT NULL, record_json TEXT NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0
                );
            """)
        except sqlite3.Error:
            _fail("store_unavailable")

    def resume_quota_clock(self, claim: Claim) -> float:
        """Exclude only explicitly recorded scheduler waits, never execution failures."""
        self._begin()
        try:
            self._assert_live(claim)
            row = self.conn.execute("SELECT offset_seconds,paused_at FROM agentic_quota_waits WHERE run_key=?",
                                    (claim.run_key,)).fetchone()
            offset = row[0] if row else 0.0
            if row and row[1] is not None:
                offset += max(0.0, self.clock() - row[1])
                self.conn.execute("UPDATE agentic_quota_waits SET offset_seconds=?,paused_at=NULL WHERE run_key=?",
                                  (offset, claim.run_key))
            self._commit()
            return offset
        except Exception:
            self._rollback()
            raise

    def admit_draft(self, claim: Claim, batch_id: str, per_run: int, per_day: int) -> str | None:
        """Reserve a non-refundable attempt atomically across workers and restarts."""
        if any(type(v) is not int or v < 0 for v in (per_run, per_day)) or not batch_id:
            _fail("invalid_configuration")
        self._begin()
        try:
            self._assert_live(claim)
            now = self.clock()
            if self.conn.execute("SELECT 1 FROM agentic_draft_admissions WHERE run_key=? AND generation=?",
                                 (claim.run_key, claim.generation)).fetchone():
                self._commit()
                return None
            daily = self.conn.execute("SELECT COUNT(*) FROM agentic_draft_admissions WHERE admitted_at>?",
                                      (now - 86400,)).fetchone()[0]
            if self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone():
                daily += self.conn.execute("SELECT COUNT(*) FROM drafts d WHERE d.status='ready' "
                    "AND julianday(d.created_at)>julianday(?,'unixepoch') AND NOT EXISTS ("
                    "SELECT 1 FROM agentic_packages p JOIN agentic_draft_admissions a ON a.run_key=p.run_key "
                    "WHERE p.draft_id=d.id)", (now - 86400,)).fetchone()[0]
            count = self.conn.execute("SELECT COUNT(*) FROM agentic_draft_admissions WHERE batch_id=?",
                                      (batch_id,)).fetchone()[0]
            reason = 'draft_daily_limit' if daily >= per_day else 'draft_batch_limit' if count >= per_run else None
            if reason is None:
                self.conn.execute("INSERT INTO agentic_draft_admissions VALUES(?,?,?,?)",
                                  (claim.run_key, claim.generation, batch_id, now))
            else:
                row = self.conn.execute("SELECT checkpoint_json FROM agentic_runs WHERE run_key=?",
                                        (claim.run_key,)).fetchone()
                cp = parse_budget_checkpoint_json(row[0]) if row and row[0] else None
                wait = self.conn.execute("SELECT offset_seconds FROM agentic_quota_waits WHERE run_key=?",
                                         (claim.run_key,)).fetchone()
                offset = wait[0] if wait else 0.0
                # Unknown costs, exhausted retries and started drafts never receive more time.
                if cp and cp.failed_attempts < 6 and not cp.role_turns.get('drafter', 0) \
                        and not cp.role_turns.get('reviewer', 0) \
                        and all(r.state == 'settled' and r.actual_usage is not None for r in cp.reservations) \
                        and now - offset < min(cp.job_deadline, cp.batch_deadline):
                    self.conn.execute("INSERT INTO agentic_quota_waits VALUES(?,?,?) ON CONFLICT(run_key) "
                                      "DO UPDATE SET paused_at=excluded.paused_at", (claim.run_key, offset, now))
            self._commit()
            return reason
        except Exception:
            self._rollback()
            raise

    def create_batch(self, batch_id: str, token_ceiling: int, deadline: float) -> None:
        if type(batch_id) is not str or not batch_id or len(batch_id) > 128 \
                or type(token_ceiling) is not int or token_ceiling < 1 \
                or type(deadline) not in (int, float) or deadline <= 0:
            _fail("invalid_batch")
        self._begin()
        try:
            row = self.conn.execute("SELECT token_ceiling,deadline FROM agentic_batches WHERE batch_id=?",
                                    (batch_id,)).fetchone()
            if row:
                if row != (token_ceiling, float(deadline)) and not (row[0] == token_ceiling and row[1] == deadline):
                    _fail("batch_conflict")
            else:
                self.conn.execute("INSERT INTO agentic_batches(batch_id,token_ceiling,deadline) VALUES(?,?,?)",
                                  (batch_id, token_ceiling, float(deadline)))
            self._commit()
        except Exception:
            self._rollback()
            raise

    def sweep_expired_claims(self) -> int:
        """Mark claims whose lease ran out as failed.

        A worker that dies without a result leaves the row 'claimed'. The claim itself is self-healing because
        claim() takes over an expired lease, but nothing re-claims a posting that is no longer selected, so the
        row reports 'in progress' for days to the board and to latest_result. This makes the record truthful.
        """
        self._begin()
        try:
            changed = self.conn.execute(
                "UPDATE agentic_runs SET status='failed',reason='lease_expired',lease_until=0 "
                "WHERE status='claimed' AND lease_until<=?", (float(self.clock()),)).rowcount
            self._commit()
            return changed
        except Exception:
            self._rollback()
            raise

    def claim(self, key: RunKey, owner: str, lease_seconds: float) -> Claim | None:
        if type(key) is not RunKey or type(owner) is not str or not owner or len(owner) > 128 \
                or type(lease_seconds) not in (int, float) or lease_seconds <= 0:
            _fail("invalid_claim")
        run_key, posting = key.value, key.posting_id
        now = float(self.clock())
        self._begin()
        try:
            row = self.conn.execute("SELECT owner,generation,lease_until,status FROM agentic_runs WHERE run_key=?",
                                    (run_key,)).fetchone()
            if row and row[3] == "claimed" and row[2] > now:
                self._commit()
                return None
            prior_generation = self.conn.execute(
                "SELECT COALESCE(MAX(generation),0) FROM agentic_runs WHERE posting_id=?", (posting,)
            ).fetchone()[0]
            generation = max(int(row[1]) if row else 0, int(prior_generation)) + 1
            # Changing the captured input fences every formerly active key for this posting.
            self.conn.execute("UPDATE agentic_runs SET status='failed',reason='inputs_changed',lease_until=0 "
                              "WHERE posting_id=? AND run_key<>? AND status='claimed'", (posting, run_key))
            if row:
                self.conn.execute("UPDATE agentic_runs SET owner=?,generation=?,lease_until=?,status='claimed',reason=NULL "
                                  "WHERE run_key=?", (owner, generation, now + lease_seconds, run_key))
            else:
                self.conn.execute("INSERT INTO agentic_runs(run_key,posting_id,owner,generation,lease_until,status) "
                                  "VALUES(?,?,?,?,?,'claimed')", (run_key, posting, owner, generation, now + lease_seconds))
            self._commit()
            return Claim(run_key, posting, owner, generation, now + lease_seconds)
        except Exception:
            self._rollback()
            raise

    def _assert_live(self, claim: Claim):
        if type(claim) is not Claim or type(claim.run_key) is not str \
                or type(claim.posting_id) is not int or type(claim.owner) is not str \
                or type(claim.generation) is not int or type(claim.lease_until) is not float:
            _fail("stale_claim")
        try:
            row = self.conn.execute("SELECT posting_id,owner,generation,lease_until,status FROM agentic_runs WHERE run_key=?",
                                    (claim.run_key,)).fetchone()
        except sqlite3.Error:
            _fail("store_unavailable")
        now = float(self.clock())
        if not row or row[0] != claim.posting_id or row[1] != claim.owner or row[2] != claim.generation \
                or row[3] != claim.lease_until or row[3] <= now or row[4] != "claimed":
            _fail("stale_claim")

    def renew(self, claim: Claim, lease_seconds: float) -> Claim:
        if type(lease_seconds) not in (int, float) or lease_seconds <= 0:
            _fail("invalid_claim")
        self._begin()
        try:
            self._assert_live(claim)
            until = float(self.clock()) + lease_seconds
            changed = self.conn.execute("UPDATE agentic_runs SET lease_until=? WHERE run_key=? AND owner=? "
                                        "AND generation=? AND status='claimed' AND lease_until>?",
                                        (until, claim.run_key, claim.owner, claim.generation, self.clock())).rowcount
            if changed != 1:
                _fail("stale_claim")
            self._commit()
            return Claim(claim.run_key, claim.posting_id, claim.owner, claim.generation, until)
        except Exception:
            self._rollback()
            raise

    def release(self, claim: Claim, *, status: str = "held", reason: str | None = None) -> None:
        if status not in {"held", "ready", "archived", "failed"}:
            _fail("invalid_status")
        self._begin()
        try:
            self._assert_live(claim)
            changed = self.conn.execute("UPDATE agentic_runs SET status=?,reason=?,lease_until=0 WHERE run_key=? AND owner=? "
                                        "AND generation=? AND status='claimed' AND lease_until>?",
                                        (status, reason, claim.run_key, claim.owner, claim.generation, self.clock())).rowcount
            if changed != 1:
                _fail("stale_claim")
            self._commit()
        except Exception:
            self._rollback()
            raise

    def _batch(self, checkpoint: BudgetCheckpoint):
        row = self.conn.execute("SELECT token_ceiling,charged,deadline FROM agentic_batches WHERE batch_id=?",
                                (checkpoint.batch_id,)).fetchone()
        if row is None:
            _fail("unknown_batch")
        if row[0] != checkpoint.batch_token_ceiling or row[2] != checkpoint.batch_deadline:
            _fail("batch_conflict")
        return row

    def _save(self, claim, proposed, expected_revision, operation_id, kind):
        if kind not in _KINDS or type(operation_id) is not str or not operation_id or len(operation_id) > 128 \
                or type(expected_revision) is not int or expected_revision < 0:
            _fail("invalid_operation")
        value = _parse_wire(proposed)
        if value.run_key != claim.run_key:
            _fail("invalid_checkpoint")
        payload = _canonical(value)
        op_digest = _digest(json.dumps({"kind": kind, "payload": payload}, sort_keys=True))
        self._begin()
        try:
            self._assert_live(claim)
            oldrow = self.conn.execute("SELECT checkpoint_revision,checkpoint_json FROM agentic_runs WHERE run_key=?",
                                       (claim.run_key,)).fetchone()
            prior = self.conn.execute("SELECT owner,generation,kind,digest,result_json FROM agentic_budget_ops WHERE operation_id=?",
                                      (operation_id,)).fetchone()
            if prior:
                if prior[:4] != (claim.owner, claim.generation, kind, op_digest):
                    _fail("operation_conflict")
                replay = parse_budget_checkpoint_json(prior[4])
                batch = self._batch(replay)
                replay = BudgetCheckpoint(**{**replay.model_dump(), "batch_charged": batch[1]})
                self._commit()
                return replay
            oldrev, oldjson = oldrow
            if oldrev != expected_revision or value.revision != expected_revision + 1:
                _fail("revision_conflict")
            old = parse_budget_checkpoint_json(oldjson) if oldjson else None
            batch = self._batch(value)
            if old is None:
                if kind != "snapshot" or value.revision != 1 or value.reservations or value.job_charged \
                        or value.failed_attempts or any(value.role_turns.values()) or value.research_queries or value.research_pages:
                    _fail("invalid_transition")
                delta = 0
            else:
                self._validate_transition(old, value, kind)
                delta = value.job_charged - old.job_charged
                if value.job_deadline != old.job_deadline or value.job_token_ceiling != old.job_token_ceiling \
                        or value.batch_token_ceiling != old.batch_token_ceiling or value.batch_deadline != old.batch_deadline:
                    _fail("invalid_transition")
            total = batch[1] + delta
            if total < 0 or total > batch[0] or total < value.job_charged:
                _fail("budget_exceeded")
            actual = BudgetCheckpoint(**{**value.model_dump(), "batch_charged": total})
            self.conn.execute("UPDATE agentic_batches SET charged=? WHERE batch_id=?", (total, value.batch_id))
            self.conn.execute("UPDATE agentic_runs SET checkpoint_revision=?,checkpoint_json=? WHERE run_key=?",
                              (actual.revision, _json(actual), claim.run_key))
            self.conn.execute("INSERT INTO agentic_budget_ops VALUES(?,?,?,?,?,?,?)",
                              (operation_id, claim.run_key, claim.owner, claim.generation, kind, op_digest, _json(actual)))
            self._commit()
            return actual
        except Exception:
            self._rollback()
            raise

    @staticmethod
    def _validate_transition(old, new, kind):
        a, b = old.model_dump(mode="json"), new.model_dump(mode="json")
        a.pop("revision"); b.pop("revision")
        a.pop("batch_charged"); b.pop("batch_charged")
        if kind == "reserve":
            oldres, newres = a.pop("reservations"), b.pop("reservations")
            oldturn, newturn = a.pop("role_turns"), b.pop("role_turns")
            if len(newres) != len(oldres) + 1 or newres[:-1] != oldres:
                _fail("invalid_transition")
            added = newres[-1]
            if added["state"] != "reserved" or added["actual_usage"] is not None \
                    or added["charged_tokens"] != added["input_tokens"] + added["requested_output_tokens"]:
                _fail("invalid_transition")
            role = added["role"]
            expected = dict(oldturn); expected[role] = expected.get(role, 0) + 1
            if {k: v for k, v in newturn.items() if v} != {k: v for k, v in expected.items() if v} \
                    or b["job_charged"] != a["job_charged"] + added["charged_tokens"]:
                _fail("invalid_transition")
            a["role_turns"] = b["role_turns"] = newturn
            a["reservations"] = b["reservations"] = newres
            a["job_charged"] = b["job_charged"]
        elif kind in {"dispatched", "settle", "failure"}:
            oldres, newres = a.pop("reservations"), b.pop("reservations")
            if len(newres) != len(oldres):
                _fail("invalid_transition")
            changed = [i for i, (x, y) in enumerate(zip(oldres, newres)) if x != y]
            if len(changed) != (0 if kind == "failure" and newres == oldres else 1):
                _fail("invalid_transition")
            if changed:
                i = changed[0]; x, y = oldres[i], newres[i]
                if kind == "dispatched":
                    if x["state"] != "reserved" or y != {**x, "state": "dispatched"}:
                        _fail("invalid_transition")
                elif kind == "settle":
                    if x["state"] != "dispatched" or y["state"] != "settled" or any(
                            y[k] != x[k] for k in x if k not in {"state", "actual_usage", "charged_tokens"}):
                        _fail("invalid_transition")
                    if y["actual_usage"] is not None and (type(y["actual_usage"]) is not int or y["actual_usage"] > x["charged_tokens"]):
                        _fail("invalid_transition")
                    expected_charge = y["actual_usage"] if y["actual_usage"] is not None else x["charged_tokens"]
                    if y["charged_tokens"] != expected_charge or b["job_charged"] != a["job_charged"] + y["charged_tokens"] - x["charged_tokens"]:
                        _fail("invalid_transition")
                    a["job_charged"] = b["job_charged"]
                elif kind == "failure":
                    if x["state"] not in {"reserved", "dispatched"} or y != {**x, "state": "ambiguous"}:
                        _fail("invalid_transition")
            a["reservations"] = b["reservations"] = newres
            if kind == "failure":
                if b["failed_attempts"] != a["failed_attempts"] + 1:
                    _fail("invalid_transition")
                a["failed_attempts"] = b["failed_attempts"]
            for k in ("role_turns", "research_queries", "research_pages"):
                if a[k] != b[k]:
                    _fail("invalid_transition")
        elif kind == "research":
            changes = [f for f in ("research_queries", "research_pages") if a[f] != b[f]]
            if len(changes) != 1 or b[changes[0]] != a[changes[0]] + 1:
                _fail("invalid_transition")
            a[changes[0]] = b[changes[0]]
        # Snapshot has no changes besides revision and authoritative batch charge.
        if a != b:
            _fail("invalid_transition")

    def save_budget(self, claim: Claim, proposed: BudgetCheckpoint, *, expected_revision: int,
                    operation_id: str, kind: Literal["reserve", "dispatched", "settle", "failure", "research", "snapshot"]) -> BudgetCheckpoint:
        return self._save(claim, proposed, expected_revision, operation_id, kind)

    def checkpoint(self, claim: Claim, value: BudgetCheckpoint, *, expected_revision: int,
                   reservation_id: str | None = None, operation: str = "snapshot") -> BudgetCheckpoint:
        opid = _digest(json.dumps([claim.run_key, expected_revision, operation, reservation_id, _canonical(value)]))
        return self._save(claim, value, expected_revision, opid, operation)

    def discard_checkpoint(self, claim: Claim) -> None:
        """Forget saved progress whose deadline has passed, so the job restarts instead of failing forever."""
        self._begin()
        try:
            self._assert_live(claim)
            self.conn.execute("UPDATE agentic_runs SET checkpoint_json=NULL, checkpoint_revision=0 WHERE run_key=?",
                              (claim.run_key,))
            self._commit()
        except BaseException:
            self._rollback()
            raise

    def load_checkpoint(self, claim: Claim) -> BudgetCheckpoint | None:
        if self.conn.in_transaction:
            _fail("transaction_active")
        self._assert_live(claim)
        row = self.conn.execute("SELECT checkpoint_json FROM agentic_runs WHERE run_key=?", (claim.run_key,)).fetchone()
        if not row or row[0] is None:
            return None
        invalid = False
        try:
            value = parse_budget_checkpoint_json(row[0])
        except AgenticError:
            invalid = True
        if invalid:
            _fail("invalid_checkpoint")
        batch = self.conn.execute("SELECT charged FROM agentic_batches WHERE batch_id=?", (value.batch_id,)).fetchone()
        if batch is None:
            _fail("unknown_batch")
        return BudgetCheckpoint(**{**value.model_dump(), "batch_charged": batch[0]})
