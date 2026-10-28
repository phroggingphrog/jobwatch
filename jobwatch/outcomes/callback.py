"""Callback rate per arm (PLAN-apply D9): Beta-Binomial with prior Beta(1, 15).

successes = applications that reached assessment/interview/offer (now or ever, so a later
rejection still counts as a callback); trials = applications that were applied.
Posterior Beta(1 + s, 15 + n - s): mean and 95% highest-density interval. The HDI uses scipy when
installed, else 200k draws from numpy with a fixed seed (deterministic).
"""
from __future__ import annotations

PRIOR_A, PRIOR_B = 1.0, 15.0
SUCCESS = ("assessment", "interview", "offer")
APPLIED = ("applied", "assessment", "interview", "offer", "rejected")
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


def callback_stats(conn) -> dict:
    """{arm: posterior} plus '_all'. Only applications that were applied count."""
    rows = conn.execute(
        """SELECT a.id, COALESCE(a.arm, m.arm, '?') AS arm, a.status, a.applied_at
           FROM applications a LEFT JOIN matches m ON m.id=a.match_id""").fetchall()
    reached: dict[int, set] = {}
    for r in conn.execute("SELECT application_id, to_status FROM application_events WHERE to_status IS NOT NULL "
                          "AND kind IN ('status','outcome_decided')"):
        reached.setdefault(r[0], set()).add(r[1])
    per: dict[str, list[int]] = {}
    for r in rows:
        hist = reached.get(r["id"], set()) | {r["status"]}
        if not (r["applied_at"] or hist & set(APPLIED)):
            continue
        s = 1 if hist & set(SUCCESS) else 0
        for key in (r["arm"], "_all"):
            agg = per.setdefault(key, [0, 0])
            agg[0] += s
            agg[1] += 1
    out = {arm: posterior(s, n) for arm, (s, n) in sorted(per.items())}
    if "_all" not in out:
        out["_all"] = posterior(0, 0)
    return out


def render_lines(stats: dict) -> list[str]:
    lines = ["Callback rate (Beta-Binomial, prior Beta(1,15); callback = assessment/interview/offer):"]
    allp = stats.get("_all")
    if not allp or allp["n"] == 0:
        lines.append(f"  no applied applications yet (prior mean {PRIOR_A / (PRIOR_A + PRIOR_B):.3f})")
        return lines
    for arm, p in stats.items():
        name = "all arms" if arm == "_all" else arm
        lo, hi = p["hdi"]
        lines.append(f"  {name}: {p['successes']}/{p['n']} → mean {p['mean']:.3f}, "
                     f"95% HDI [{lo:.3f}, {hi:.3f}] (n={p['n']}{', small n' if p['n'] < 10 else ''})")
    return lines
