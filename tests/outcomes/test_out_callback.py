import math
from datetime import datetime, timezone

import pytest

from outkit import add_match, make_env
from jobwatch import db as dbm
from jobwatch.commands.state import set_status
from jobwatch.digest import gather, render
from jobwatch.outcomes.callback import _hdi_sampled, callback_stats, posterior, render_lines


def grid_hdi(a, b, mass=0.95, n=200_000):
    """Independent reference: HDI from a fine grid of the Beta density."""
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    xs = [(i + 0.5) / n for i in range(n)]
    dens = [math.exp(lb + (a - 1) * math.log(x) + (b - 1) * math.log1p(-x)) for x in xs]
    order = sorted(range(n), key=lambda i: -dens[i])
    acc, keep = 0.0, []
    for i in order:
        acc += dens[i] / n
        keep.append(i)
        if acc >= mass:
            break
    return xs[min(keep)], xs[max(keep)]


def test_prior_only():
    p = posterior(0, 0)
    assert p["mean"] == pytest.approx(1 / 16)
    lo, hi = p["hdi"]
    assert lo == pytest.approx(0.0, abs=1e-3)
    assert hi == pytest.approx(1 - 0.05 ** (1 / 15), abs=3e-3)        # 0.18104 analytically


def test_posterior_2_of_10():
    p = posterior(2, 10)                                              # Beta(3, 23)
    assert (p["a"], p["b"]) == (3, 23) and p["mean"] == pytest.approx(3 / 26)
    ref = grid_hdi(3, 23)
    assert p["hdi"][0] == pytest.approx(ref[0], abs=3e-3) and p["hdi"][1] == pytest.approx(ref[1], abs=3e-3)


def test_sampled_hdi_is_deterministic():
    assert _hdi_sampled(3, 23, 0.95) == _hdi_sampled(3, 23, 0.95)


def test_callback_stats_per_arm_and_digest(tmp_path, monkeypatch):
    config = make_env(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    t = datetime(2026, 10, 1, tzinfo=timezone.utc)
    m = [add_match(conn, i, arm="payroll_clerk" if i <= 4 else "call_centre") for i in range(1, 7)]
    set_status(conn, m[0], "applied", actor="owner", source="t", now=t)
    set_status(conn, m[0], "interview", actor="owner", source="t", now=t)
    set_status(conn, m[0], "rejected", actor="owner", source="t", now=t)   # a callback, then rejected
    set_status(conn, m[1], "applied", actor="owner", source="t", now=t)
    set_status(conn, m[2], "skipped", actor="owner", source="t", now=t)    # never applied: not a trial
    set_status(conn, m[3], "applied", actor="owner", source="t", now=t)
    set_status(conn, m[4], "applied", actor="owner", source="t", now=t)
    set_status(conn, m[4], "assessment", actor="owner", source="t", now=t)
    st = callback_stats(conn)
    assert (st["payroll_clerk"]["successes"], st["payroll_clerk"]["n"]) == (1, 1)
    assert st['payroll_clerk']['pending'] == 2
    assert (st["call_centre"]["successes"], st["call_centre"]["n"]) == (1, 1)
    assert (st["_all"]["successes"], st["_all"]["n"]) == (2, 2)
    assert st["_all"]["mean"] == pytest.approx(3 / 18)
    plain, _ = render(gather(conn))
    assert "Callbacks among resolved applications" in plain
    assert "payroll_clerk: 1/1 → mean 0.118, 95% HDI [" in plain and "resolved=1, pending=2" in plain
    assert "all arms: 2/2 → mean 0.167" in plain


def test_render_without_applications():
    lines = render_lines({"_all": posterior(0, 0)})
    assert "no resolved outcomes yet; pending=0 (prior mean 0.062)" in lines[-1]
