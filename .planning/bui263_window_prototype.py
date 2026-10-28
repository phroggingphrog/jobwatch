"""Offline bounded-window orchestration model for BUI-263.

Pure fake-controller model only: no systemd/SQLite/process operations, and no
production authorization. Proposed real gate: deny writes at shared DB connect /
write boundary, including dbm.connect and direct sqlite3 paths, plus OS-level
access restriction for processes that bypass that code. Unknown coverage refuses.
"""
from dataclasses import dataclass
from typing import Callable


class Refuse(RuntimeError):
    pass


@dataclass(frozen=True)
class UnitState:
    name: str
    active: bool
    enabled: str
    one_shot: bool = False


@dataclass
class FakeController:
    """Injected fake operations; every transition is recorded for tests."""
    units: dict[str, UnitState]
    events: list[str]
    failures: set[str]
    gate_covered: bool = True
    gate_closed: bool = False
    changed: list[str] = None

    def __post_init__(self):
        self.changed = []

    def op(self, event: str):
        self.events.append(event)
        if event in self.failures:
            raise Refuse(f"injected failure: {event}")


def bounded_window(controller: FakeController, *, writers: set[str], inflight: bool,
                   manifest_ok: Callable[[], bool], now: Callable[[], float],
                   timeout: float = 120.0, cleanup_reserve: float = 20.0):
    """Attempt bounded exclusion/check; always restore only journaled changes.

    Active one-shot units are rejected before any operation (stopping and
    restarting could replay a job). Timer/service units are never implicitly
    started; restoration only reactivates initially-active non-one-shots.
    """
    if not controller.gate_covered or writers or inflight:
        raise Refuse("unknown or in-flight writer / incomplete access coverage")
    if any(u.active and u.one_shot for u in controller.units.values()):
        raise Refuse("active one-shot cannot be safely quiesced or restored")
    start = now()
    deadline = start + timeout
    try:
        controller.op("gate_close")
        controller.gate_closed = True
        for name, unit in controller.units.items():
            if unit.active:
                if now() >= deadline - cleanup_reserve:
                    raise Refuse("insufficient bounded time before cleanup reserve")
                controller.op(f"stop:{name}")
                controller.changed.append(name)
        if now() >= deadline - cleanup_reserve:
            raise Refuse("insufficient bounded time for guarded operation")
        controller.op("fresh_manifest")
        if not manifest_ok():
            raise Refuse("fresh exact manifest / approval mismatch")
        controller.op("authorized_correction")
        return "applied"
    finally:
        cleanup_errors = []
        for name in reversed(controller.changed):
            unit = controller.units[name]
            if unit.active and not unit.one_shot:
                try:
                    controller.op(f"start:{name}")
                except Refuse as exc:
                    cleanup_errors.append(str(exc))
        controller.changed.clear()
        if controller.gate_closed:
            try:
                controller.op("gate_open")
                controller.gate_closed = False
            except Refuse as exc:
                cleanup_errors.append(str(exc))
        # Never hide cleanup failure, including when an earlier operation failed.
        if cleanup_errors:
            raise Refuse("cleanup failure: " + "; ".join(cleanup_errors))


def proposed_real_boundary_inventory(*, known_entrypoints: set[str], covered_entrypoints: set[str],
                                     direct_sqlite_paths: set[str], covered_direct_paths: set[str]) -> bool:
    """Eligibility predicate; production coverage needs independent proof."""
    required = known_entrypoints | direct_sqlite_paths
    covered = covered_entrypoints | covered_direct_paths
    return bool(required) and required <= covered
