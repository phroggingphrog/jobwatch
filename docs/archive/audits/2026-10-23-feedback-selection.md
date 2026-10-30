# Phase 6 source verification

Status: required local checks passed and independent review is resolved.
This report uses invented fixtures and synthetic transports. It establishes no
deployment, live recommendation quality or real blind-study result.

## Delivered behavior

Native API and chat share append-only posting feedback, reversible restoration,
digest-confirmed exclusion amendments, bounded human prompts and durable selected
preparation. Confirmed rules remain canonical; amendments preserve historical
profile versions and invalidate dependent assessments without paid reassessment.
Personal identity comes from authentication. Only genuine comparison answers enter
preference training; displays, rejection, restoration and selection remain distinct.

Selections bind 1–10 eligible current entries and their complete preparation inputs.
The jobs outbox precedes API enqueue. A stable person-scoped identity prevents
duplicate queue runs, and an immutable completed result permits recovery through
API publication without preparing again or initializing a model client. Terminal
queue states and cancellation reconcile into selection status. Final Submit keeps
its separately confirmed canonical path.

See [the contract](../../pipeline/agentic/CHAT.md#feedback-and-selected-preparation-phase-6),
[ADR 0008](../adr/0008-feedback-and-selected-preparation.md) and
[the worked example](../examples/feedback-selection.md).

## Checks actually run

The stable runtime/test source is commit
`b6d676fae30a679a48b836fe7c1e425d44f052a0`. Documentation-only completion notes
may follow it; no runtime change is implied by those notes.

- Initial focused Phase 6 checks: **96 passed in 30.44 seconds**.
- Existing Deep Agents regression: **66 passed, 1 skipped in 9.89 seconds**.
- Native chat/selection/worker/package flow, unset and Qwen embeddings, with
  adjacent selection checks: **7 passed, 1 warning in 97.16 seconds**. The flow
  retrieved real CV and letter PDF bytes plus the verified form map through
  authenticated artifact endpoints. It did not submit an application.
- Prompt/preference focused run: **169 passed, 2 skipped, 1 warning in 67.50
  seconds**; final prompt-only additions: **33 passed in 6.44 seconds**. The two
  skipped local sampler cases were subsequently run explicitly below.
- Repair and adjacent Deep Agents checks: **84 passed, 1 skipped in 47.07
  seconds**, before the final lazy-client guard. Final directly affected checks:
  **18 passed in 33.29 seconds**, after that guard.
- Isolated `jobwatch check --code` and whitespace checks passed. The profile and
  settings check used an invented private profile, not an installed candidate.
- Complete stable-source local release suite: **3758 passed, 11 skipped, 6 warnings
  in 971.35 seconds**. Hosted CI remains disabled and is not a completion or merge gate.

The first full attempt reported browser/subprocess failures after its external
test environment disappeared during execution. The Python executable and package
directory under `/tmp/jobwatch-phase4-venv` were confirmed absent while the test
process was still running. That attempt was interrupted and is not release-pass
evidence. The cause of the directory removal is not established. Restoring the
unchanged `uv.lock` dependencies offline into a persistent cache environment,
without changing source or assertions, produced **67 passed in 73.90 seconds**
for the browser module, real CV printing, CLI isolation and affected Phase 6
API/selection checks. The complete suite was then restarted on the same source and passed as recorded above.

Tests exercised person isolation, exact human approvals, omitted optional chat
arguments, model-generated answer refusal, stale inputs, rule-confirmation races,
rejection/restoration history, idempotency conflicts, prompt caps and cooldown,
invalid posterior fallback, queue crash recovery, cancellation and unpaid paths.
Operational preparation checkpoints do not invalidate their own approved inputs;
changed evidence, ads, profile, policy or ranking context still invalidate them.

## Independent review

One independent Sol 6.1 reader reviewed standards, the approved Phase 6 spec and
adversarial lifecycle behavior over `04b11e3..e4228e0`. Five bounded invented-fixture
probes reproduced four concrete defects: legal omitted chat defaults, completed
selection/API-publication crash recovery, stale prompt display and cancellation
status disagreement. Those five passing probes demonstrated defects; they were
not repaired acceptance checks.

The parent recorded repair round **1 of 5** before editing. The follow-up reviewed
`e4228e0..b6d676f`, cleared all four findings and found no additional material issue
reachable from the fixes. Its independent bounded checks returned **7 passed in
17.08 seconds**, including actual API worker publication and three protected
artifact downloads after a simulated crash, with the same run identity and prior
usage retained. No model client was initialized during cached recovery. That
publication probe used invented artifact bytes; the separate pipeline check above
generated real PDFs. No unresolved independent-review finding remains.

## Real synthetic sampler checks

`JOBWATCH_TEST_R=1 python -m pytest -q -s -p no:cacheprovider
tests/preferences/test_local_r.py` returned **2 passed in 294.27 seconds** using the
existing external test environment. Both neutral and wide factual-feature cases
used four real local R/JAGS chains and the unchanged diagnostic, training/holdout
and predictive acceptance gates. Both fits were accepted and beat their prior
holdout log scores. Maximum R-hat was below 1.0002; minimum ESS exceeded 25,000;
maximum MCSE ratio was below 0.0063.

These were explicitly synthetic fits. They do not authorize a live fit, personalize
a real person's shortlist, or establish measured recommendation quality.

## Limits and rollback

Merge is tracked in PR #24. Real-world suitability labels,
blind quality comparison, deployment, live migration/fitting, timers and service
activation remain separate. The remaining evaluation tooling belongs to Phase 7.
Historical verification reports are preserved with their original results.

Rollback reverts this release's source. Retain approved profile versions, feedback,
prompts, genuine choices, fits, selections and completed results, packages and any
evaluation records. The additive schema and immutable history are not deleted or
rewritten as part of a source rollback; do not downgrade schema metadata manually.
