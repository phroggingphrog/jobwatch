import pytest
from bui263_window_prototype import FakeController, Refuse, UnitState, bounded_window, proposed_real_boundary_inventory


def controller(failures=(), *, active_oneshot=False, gate_covered=True):
    units = {
        "timer": UnitState("timer", True, "enabled"),
        "web": UnitState("web", True, "enabled"),
        "oneshot": UnitState("oneshot", active_oneshot, "static", True),
        "inactive": UnitState("inactive", False, "disabled", True),
    }
    return FakeController(units, [], set(failures), gate_covered)


def run(c, *, writers=set(), inflight=False, manifest=True, times=None):
    values = iter(times or [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    return bounded_window(c, writers=writers, inflight=inflight, manifest_ok=lambda: manifest,
                          now=lambda: next(values))


def test_success_tracks_only_stopped_units_and_preserves_enabled_state():
    c = controller()
    assert run(c) == "applied"
    assert c.events == ["gate_close", "stop:timer", "stop:web", "fresh_manifest",
                        "authorized_correction", "start:web", "start:timer", "gate_open"]
    assert c.changed == [] and not c.gate_closed


@pytest.mark.parametrize("kwargs", [dict(writers={"manual-sqlite"}), dict(inflight=True)])
def test_unknown_or_inflight_writer_refuses_before_gate(kwargs):
    c = controller()
    with pytest.raises(Refuse, match="writer"):
        run(c, **kwargs)
    assert c.events == []


def test_active_oneshot_refuses_before_stopping_anything():
    c = controller(active_oneshot=True)
    with pytest.raises(Refuse, match="one-shot"):
        run(c)
    assert c.events == []


def test_incomplete_boundary_refuses():
    c = controller(gate_covered=False)
    with pytest.raises(Refuse, match="coverage"):
        run(c)


def test_manifest_mismatch_runs_finally_restore():
    c = controller()
    with pytest.raises(Refuse, match="manifest"):
        run(c, manifest=False)
    assert c.events[-3:] == ["start:web", "start:timer", "gate_open"]
    assert not c.gate_closed


def test_stop_failure_restores_only_prior_successful_stops():
    c = controller(["stop:web"])
    with pytest.raises(Refuse, match="stop:web"):
        run(c)
    assert c.events[-3:] == ["start:timer", "gate_open"] or c.events[-2:] == ["start:timer", "gate_open"]
    assert not c.gate_closed


def test_failure_at_each_transition_attempts_cleanup():
    for step in ("gate_close", "stop:timer", "fresh_manifest", "authorized_correction"):
        c = controller([step])
        with pytest.raises(Refuse):
            run(c)
        if step == "gate_close":
            assert "gate_open" not in c.events
        else:
            assert "gate_open" in c.events
        assert not c.gate_closed


def test_cleanup_failure_reported_and_gate_open_attempted():
    c = controller(["authorized_correction", "start:web"])
    with pytest.raises(Refuse, match="cleanup failure"):
        run(c)
    assert "gate_open" in c.events


def test_deadline_reserves_cleanup_time():
    c = controller()
    with pytest.raises(Refuse, match="bounded time"):
        run(c, times=[0, 101, 102, 103])
    assert "gate_open" in c.events


def test_boundary_eligibility_includes_direct_sqlite_paths():
    assert proposed_real_boundary_inventory(known_entrypoints={"dbm"}, covered_entrypoints={"dbm"},
                                            direct_sqlite_paths={"web direct"}, covered_direct_paths=set()) is False
    assert proposed_real_boundary_inventory(known_entrypoints={"dbm"}, covered_entrypoints={"dbm"},
                                            direct_sqlite_paths={"web direct"}, covered_direct_paths={"web direct"})
