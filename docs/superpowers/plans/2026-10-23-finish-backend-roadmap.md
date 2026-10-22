# Finish Jobwatch backend roadmap

**Status: backend source roadmap delivered through reviewed PRs #23, #24 and #25.** Phases 1–5 are merged. This
plan covers the three remaining sequential, reviewed and merged releases. The
owner-approved direction recorded for 2026-10-23 is binding where it differs
from the historical Phase 6/7 plans and cross-plan contract.

## Delivery rules

- Work on local `codex/` branches, one release at a time. Do not start a dependent
  release before its predecessor is reviewed and merged. Pure calculation work
  and documentation may proceed in parallel after their contracts are fixed.
- Each release gets a reviewed PR. Auto-merge that PR only after its required
  local checks pass and independent review findings are resolved. Hosted CI is
  disabled and does not gate completion or merge.
- Do not activate services or timers, deploy, migrate live data, run live fitting,
  contact employers, or submit applications. Preserve per-person identity,
  isolation, exact-input human approvals, canonical eligibility and preparation
  operations. Submission remains exclusively on the owner's confirmed-Submit path.
- Use synthetic records for tests. Never place candidate or advertisement text in
  hosted traces or evaluation reports.
- LUNA owns documentation; the parent verifies the documents. Sol 6.1 owns disjoint
  implementation pieces and independent review. The parent owns integration,
  migrations, the release full suite, and release coordination. Respect the
  repository's configured CLI routing and high-effort policy; it does not require
  calling every listed model or CLI.

## Release 1 — resolve issue #17

Diagnose issue #17 from a reproducible browser failure, identify its cause, and
implement a browser fix only when the failure and fix are demonstrated in the
running application. Add regression coverage for the reproduced failure and the
affected browser flow. The parent runs the full local suite on the stable release
source. The PR records the reproduction, browser evidence, local checks, review
and rollback. Do not claim a browser fix from source inspection alone.

**Complete when:** the original failure is reproduced, the fix is demonstrated in
the browser, regressions are covered, required local checks pass, independent
review is resolved, and the reviewed PR is merged.

## Release 2 — Phase 6 feedback and selection

Implement feedback and selection through shared backend operations exposed to
both the authenticated native API and interchangeable chat client. Chat is a
client for the same operations; it does not define separate policy or state.

- Record rejection as reversible feedback. Support the canonical rule kinds:
  family, employer, title term, location and work type. Store them as immutable,
  digest-confirmed profile amendments. Keep the person's answer verbatim; an
  answer never becomes a profile fact automatically.
- Bind every feedback choice and approval to its authenticated person and exact
  pending inputs. Derive identity from authentication. Preserve historical
  evaluation records and their run keys. A new approved profile changes current
  run keys and invalidates old current views, including evaluations, shortlists
  and fits. This supersedes historical Phase 6/7 no-rekey and inactive-legacy
  assumptions; it does not rewrite historical records.
- Offer comparisons among three eligible jobs plus “none.” Use expected
  information gain only with a current valid genuine-choice fit and canonical
  posterior validation. Otherwise use deterministic cold start over at most nine
  unseen jobs. Prompt defaults are one outstanding prompt of either type, at most
  three prompts in a rolling seven days, and a 30-day cooldown for repeated
  questions. Setting `prompts_per_week=0` disables all prompts.
- Selection accepts 1–10 currently eligible jobs. Bind approval to the full
  reviewed selection payload and recheck it before any paid work. Use a durable
  outbox and per-person idempotency so cross-database recovery cannot duplicate
  runs, feedback events or packages. A pending selection may have a null run ID.
  Reuse existing preparation budgets and cancellation behavior. Selection only
  prepares; it never submits.

**Complete when:** API and chat exercise the same operations; reversibility,
profile invalidation, exact approvals, idempotent recovery, eligibility rechecks,
budgets and cancellation are covered by local checks; independent review is
resolved; and the reviewed PR is merged.

## Release 3 — Phase 7 offline evaluation and monitoring

Build evaluation around frozen baselines and human labels. Preserve the boundary
between offline evidence and live model work.

- Freeze baselines once and split by related-ad/employer group using a seeded,
  write-once 30% holdout. Pin relevance labels and configuration in the manifest.
  Refuse advertisement or employer leakage across splits.
- Make provisional replay read-only, offline and zero-LLM. Defaults are 500 cases
  and a 300-second time limit. Monitoring is development-only and never reads the
  holdout. Paid replay requires explicit `--paid --budget-tokens`; fit eligibility
  is implemented but no live fit is run.
- Report missed suitable jobs, unsupported indicators, precision and nDCG at 5
  and 10, exclusions, unknowns, tokens and latency. Require at least 10 applicable
  human labels or report that labels are missing. Censor pending outcomes; do not
  apply bias correction without recorded propensities.
- Write private, hashed JSON and Markdown reports. Audit holdout access and keep
  advertisement and candidate text out of reports. Provide CLI operations to
  evaluate cases, label, split, run, report and monitor.

**Complete when:** split integrity and write-once behavior, zero-LLM provisional
replay, paid opt-in and budget enforcement, label minimums, report privacy,
holdout access audit and censored-outcome handling pass local checks; independent
review is resolved; and the reviewed PR is merged.

## Order, integration and finish line

The release order is issue #17, then Phase 6, then Phase 7. Phase 6 establishes
the feedback, profile-version and fit validity contracts that Phase 7 records in
its manifest. Fix shared contracts before parallel pure calculation or document
work. The parent integrates migrations and API/chat surfaces, resolves conflicts,
and runs the required local checks, including the full suite at the stable release
point. Address local failures and review findings; disabled hosted CI is not a
completion requirement.

The roadmap is complete when all three reviewed PRs are merged, required local
checks pass, independent review findings are resolved, and examples, backend
contracts and roadmap status describe the delivered source accurately. This is a
source-completion claim only; it does not claim deployment, live migration or
live fitting.

Rollback reverts source changes through reviewed PRs while preserving all
historical choices, confirmed profile versions, feedback, fits, packages and
reports. Do not delete or rewrite those records as part of rollback.


## Source completion record

Browser PR #23: 3655 passed, 11 skipped. Phase 6 PR #24: 3758 passed, 11 skipped;
confirmed-profile API/chat selection through verified package retrieval is covered.
Phase 7 PR #25: 3804 passed, 11 skipped, with independent review findings resolved
and real synthetic R/JAGS 2 passed under unchanged gates. Hosted CI stayed disabled.
The [Phase 7 verification report](../../audits/2026-10-23-evaluation-monitoring.md)
records exact timing, limitations, rollback and an extra smoke harness opening the
installed database before isolation; its prior schema was not recorded and the
schema delta is unknown. Source completion does not establish deployment, live
quality, or a real blind study (#6). Preserve historical records on rollback.
