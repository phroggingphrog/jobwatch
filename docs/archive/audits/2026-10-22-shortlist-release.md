# Phase 5 source verification

The [approved Phase 5 plan](../superpowers/plans/2026-10-22-phase-5-execution.md)
was implemented locally on `codex/phase-5-explained-shortlist`, based on main
`cd8d8fc73ac7de762836e33dc90d50ac0f8266d2`. Delivery is tracked in
[issue #16](https://github.com/phroggingphrog/jobwatch/issues/16). This report
records source checks; it does not establish merge, deployment or measured
recommendation quality.

## Checks

All application fixtures were invented. The project interpreter was
`/tmp/jobwatch-phase4-venv/bin/python` (Python 3.12).

| Check | Actual result |
|---|---|
| Complete stable-source release run: `python -m pytest -q --tb=short` | **1 failed, 3653 passed, 11 skipped, 6 warnings in 1136.20s** |
| Final focused integration before the last review fixes | 172 passed, 2 optional sampler skips |
| Final utility-batching and readiness-freshness covering checks | 29 passed in 98.37s |
| Independent final fix verification | 10 passed in 35.49s |
| Policy-wiring module after immutable-value assertion repair | 19 passed in 99.72s |
| Browser module rerun after the complete release run | 47 passed in 50.75s |
| Two real synthetic R/JAGS fits | 2 passed in 345.15s |
| Isolated `jobwatch check --code`, CI YAML parsing, `git diff --check` | Passed |

The complete run's sole failure was
`tests/test_browser_session.py::test_owner_login_anchor_popup_stays_scoped_and_restores_protected_application`.
It failed while waiting for the login popup at line 336 with
`BrowserSessionError: browser_action_failed`. A direct branch rerun initially
failed too; the entire unchanged browser module subsequently passed on the
branch. An isolated archive of base main passed the individual test, 31 further
individual repetitions, and all 47 browser-module tests. Browser implementation,
tests and shared fixtures have no source changes in this phase. These results
show an intermittent validation failure, without proving its cause or proving a
pre-existing baseline failure. The complete release run is **not fully green**. The unresolved failure is tracked
in [issue #17](https://github.com/phroggingphrog/jobwatch/issues/17); delivery is
a draft PR while this validation gap remains.

The default run skips optional integrations/samplers. Both synthetic R/JAGS cases
were run separately with the existing convergence, effective sample size,
Monte Carlo error and held-out improvement requirements unchanged. The neutral
case had maximum R-hat 1.000152, minimum ESS 39834.51 and held-out log score
-3.145 versus prior -7.077; the wider factual-family case had maximum R-hat
1.000112, minimum ESS 25888.06 and held-out log score -2.805 versus prior -8.119.
Later factual-extraction repairs deliberately invalidate those earlier fit
artifacts by source hash; sampler mathematics and acceptance thresholds did not
change. The historical directional-effect assertion now checks a positive mean
and positive lower HDI instead of an arbitrary coefficient above two. These
synthetic checks do not measure recommendation usefulness.

## Review

LUNA reconciled documentation; Sol 6.1 implemented the isolated ranking and
preference components; the parent integrated current evaluations, persistence,
scheduling and the native API. Independent Sol 6.1 component and integration
reviews found and verified repairs for citation normalization, missing-location
questions, factual negation/hours/experience provenance, liveness expiry,
candidate-artifact verification, completed-prefix queue starvation, profile
capture races, utility prediction above 100 candidates and stale descriptive
response-readiness summaries. The final scoped re-review found no remaining
concrete Phase 5 blocker before the full release run.

The full-run browser failure remains a validation gap. It was not hidden by
skipping the test, changing browser protections or reporting a green full suite.

## Limits and undo

Shortlists display at most 100 entries. Valid utilities are calculated for the
complete candidate pool in bounded batches; any missing or inconsistent batch
makes the whole shortlist provisional. Labels and thresholds are presentation
conventions, not qualification probabilities. Historical choices with missing or
changed provenance are skipped by migration. Real provider behavior and ranking
usefulness remain unverified; feedback/selection is Phase 6 and blind evaluation
is Phase 7.

No live migration, live fitting, paid provider call, service/timer activation,
deployment or application submission was performed. Hosted CI status belongs in
the PR and is separate from local verification.

Undo by reverting the phase's source merge. Preserve historical choices, fits
and snapshots. The additive tables `shortlists`, `shortlist_entries` and
`shortlist_impressions` can remain; older source ignores them. No destructive
private-data rollback is required.
