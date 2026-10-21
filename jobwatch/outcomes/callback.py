"""Callback rate per arm (PLAN-apply D9): Beta-Binomial with prior Beta(1, 15).

successes = applications that reached assessment/interview/offer (now or ever, so a later
rejection still counts as a callback); trials = explicitly resolved applications.
Pending submissions are censored. A rejected unsubmitted draft is not a trial.
This describes the resolved subset, not an unbiased forecast of eventual callbacks.
Posterior Beta(1 + s, 15 + n - s): mean and 95% highest-density interval. The HDI uses scipy when
installed, else 200k draws from numpy with a fixed seed (deterministic).
"""
from __future__ import annotations

PRIOR_A, PRIOR_B = 1.0, 15.0
SUCCESS = ("assessment", "interview", "offer")
SEED, DRAWS = 20261006, 200_000


def hdi_beta(a: float, b: float, mass: float = 0.95) -> tuple[float, float]:
    try:
        from scipy import optimize, stats  # type: ignore
    except ImportError:
        return _hdi_sampled(a, b, mass)
    dist = stats.beta(a, b)
    tail = 1.0 - mass

    def width(low_tail):
        return dist.ppf(low_tail + mass) - dist.ppf(low_tail)
    res = optimize.minimize_scalar(width, bounds=(0.0, tail), method="bounded",
                                   options={"xatol": 1e-10})
    lo = float(res.x)
    return float(dist.ppf(lo)), float(dist.ppf(lo + mass))


def _hdi_sampled(a: float, b: float, mass: float) -> tuple[float, float]:
    import numpy as np
    x = np.sort(np.random.default_rng(SEED).beta(a, b, DRAWS))
    k = int(np.floor(mass * DRAWS))
    widths = x[k:] - x[:DRAWS - k]
    i = int(np.argmin(widths))
    return float(x[i]), float(x[i + k])


def posterior(successes: int, trials: int) -> dict:
    a, b = PRIOR_A + successes, PRIOR_B + trials - successes
    lo, hi = hdi_beta(a, b)
    return {"successes": successes, "n": trials, "mean": a / (a + b), "hdi": (lo, hi), "a": a, "b": b}


def observed_outcome(status, applied_at, history):
    """One shared classification for the outcome inventory and callback model."""
    reached = set(history) | {status}
    if not (applied_at or 'applied' in reached or reached & set(SUCCESS)):
        return None
    if reached & set(SUCCESS):
        return 'callback'
    return 'no_callback' if status == 'rejected' else 'pending'


def callback_stats(conn) -> dict:
    """{arm: resolved-subset posterior and censored counts} plus '_all'."""
    rows = conn.execute(
        """SELECT a.id, COALESCE(a.arm, m.arm, '?') AS arm, a.status, a.applied_at
           FROM applications a LEFT JOIN matches m ON m.id=a.match_id""").fetchall()
    reached: dict[int, set] = {}
    for r in conn.execute("SELECT application_id, to_status FROM application_events WHERE to_status IS NOT NULL "
                          "AND kind IN ('status','outcome_decided')"):
        reached.setdefault(r[0], set()).add(r[1])
    per: dict[str, list[int]] = {}
    for r in rows:
        outcome = observed_outcome(r['status'], r['applied_at'], reached.get(r['id'], set()))
        if outcome is None:
            continue
        for key in {r['arm'], '_all'}:
            agg = per.setdefault(key, [0, 0, 0])
            agg[0] += outcome == 'callback'
            agg[1] += outcome == 'no_callback'
            agg[2] += outcome == 'pending'
    per.setdefault('_all', [0, 0, 0])
    out = {}
    for arm, (successes, failures, pending) in sorted(per.items()):
        out[arm] = {**posterior(successes, successes + failures), 'pending': pending,
            'applied': successes + failures + pending, 'resolved_without_callback': failures,
            'observation_rule': 'explicit_callback_or_rejection', 'prediction_available': False}
    return out


def render_lines(stats: dict) -> list[str]:
    lines = ["Callbacks among resolved applications (Beta(1,15) prior; pending excluded; not a forecast):"]
    allp = stats.get("_all")
    if not allp or allp["n"] == 0:
        lines.append(f"  no resolved outcomes yet; pending={allp.get('pending', 0) if allp else 0} "
                     f"(prior mean {PRIOR_A / (PRIOR_A + PRIOR_B):.3f})")
        return lines
    for arm, p in stats.items():
        name = "all arms" if arm == "_all" else arm
        lo, hi = p["hdi"]
        lines.append(f"  {name}: {p['successes']}/{p['n']} → mean {p['mean']:.3f}, "
                     f"95% HDI [{lo:.3f}, {hi:.3f}] (resolved={p['n']}, pending={p.get('pending', 0)}"
                     f"{', small n' if p['n'] < 10 else ''})")
    return lines
