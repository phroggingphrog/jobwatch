# Phase 7 source verification

Status: required local checks and independent review passed; delivered in PR #25.
The stable runtime/test source is `f94f8c1c2b3cb0bbac6cca27a110381236f7ae49`.
PR #25 delivers source and evaluation tools, not deployment or a real blind study.

## Delivered behavior

`jobwatch evaluate` provides frozen cases, genuine terminal-human labels, a
write-once grouped split, provisional canonical replay, private reports and bounded
development monitoring. New freezes pin complete approved profile/evidence, ads,
configuration, policy and per-case relevance. Old baselines without that context
remain historical records and return an explicit unavailable state for new replay.
A seeded split assigns whole related-ad/employer groups, with ceil(30% of groups)
in holdout and at least one development group; fewer than two groups is unavailable.

Default replay makes zero model calls and writes only private evaluation artifacts.
Monitoring is capped at 500 cases/300 seconds, reads development cases only and
never reads the human-label log. Explicit holdout access is audited before loading
cases or reports; legacy full-baseline inspection also requires explicit approval.
Paid replay requires both opt-in and a token budget. Optional local fitting retains
genuine-choice provenance and original preference train/holdout assignments, skips
choices crossing the evaluation holdout and uses unchanged canonical sampler gates.
It never activates a fit, and replay ordering remains provisional.

Metrics require ten applicable human labels per quality measure. Sparse labels,
unmeasured latency and partial replay remain explicit. Citation checks and mandatory
conflict counts are deterministic indicators, not independent qualification judgments.
Reports allow only safe IDs, enums, counts, metrics and hashes; holdout exports are
aggregate-only. Candidate/ad text, notes, raw labels and arbitrary model reasons are
excluded. Private content-addressed JSON/Markdown files are deterministic and immutable.
Pending outcomes do not influence ranking; exposure/selection bias and absent
propensities remain limitations.

See [ADR 0009](../adr/0009-frozen-evaluation-and-monitoring.md),
[the command example](../examples/evaluation-monitoring.md) and
[the backend contract](../../pipeline/agentic/CHAT.md#frozen-evaluation-and-bounded-monitoring-phase-7).

## Checks actually run

- Existing baseline and initial replay/data/CLI checks: **103 passed in 113.00s**.
- Pure metrics and private reports: **26 passed** in the component worker's focused run.
- Initial CLI and optional synthetic paid-runtime/fit-adapter checks: **5 passed in 15.01s**.
- Final initial Phase 7 suite: **43 passed in 35.02s**; additional frozen-choice and
  explicit leakage checks: **2 passed in 6.00s**.
- Parent-authored isolated installed-console exercise: **10 checks**, zero model calls,
  unchanged synthetic database and byte-identical repeated report exports. This
  exercised list/split/replay/report/monitor and paid-budget, holdout and nonterminal
  human-label refusal. It was parent-authored runtime QA, not independent review.
- Independent review reproduced two defects. New regressions failed **2/2 in 5.75s**
  before repair; affected CLI/data/legacy-baseline checks passed **18/18 in 24.89s** afterward.
- Isolated invented-profile `jobwatch check --code` and whitespace checks passed.
- Complete stable-source local release suite: **3804 passed, 11 skipped, 6 warnings
  in 2014.82s (33m34s)**. Runtime/test source was unchanged from the reviewed
  commit above; later completion commits change documentation only.
- Explicit real synthetic R/JAGS checks: **2 passed in 286.42s** on the stable
  source, using four local chains in each neutral and wide factual-feature case.
  Both fits passed unchanged diagnostics and beat their prior held-out log score.
  Maximum R-hat was below 1.0002, minimum ESS exceeded 25,800 and maximum MCSE
  ratio was below 0.0063. These synthetic fits do not establish live model quality
  or authorize activation. The tests retain their explicitly synthetic origin.

Hosted CI remains disabled and optional; it was not a completion or merge gate.
Invented fixtures and synthetic transports supplied the acceptance checks. No real
blind-quality labels or recommendation-quality measurements are claimed.

## Independent review and repair

One independent Sol 6.1 reader reviewed `3882d76..9bf5db9` against standards, the
approved Phase 7 spec and adversarial callers. Three bounded synthetic probes
returned **3 passed in 13.76s**, confirming observed defects/behavior rather than
certifying correctness. Final aggregate findings were both blocking acceptance gaps:

- R1: legacy `baseline show`, with or without `--cases`, bypassed holdout approval
  and audit for newly split baselines. The actual caller now audits explicit access
  before loading any case; unsplit historical baselines retain their prior behavior.
- R2: configuration drift during freezing could publish a manifest that immediately
  failed replay validation. Staging now compares the actual captured runtime digest
  with the original frozen digest and refuses publication on mismatch, cleaning the
  staging directory and read transaction.

The parent recorded shared repair round **1/5 before edits**. The final R2 blocking
classification superseded its preliminary nonblocking disposition before the repair.
Scoped independent follow-up over `9bf5db9..f94f8c1` passed, resolving both findings
with no new blocking issue. Two independent checks passed in **14.24s**, covering
unsplit inspection compatibility, audit failure before reads, drift cleanup, an
unchanged synthetic database and a valid subsequent freeze.

Normal labelled development replay parses the existing shared append-only human-label
log and filters development IDs before computing metrics/hashes. The reviewer
explicitly recorded this as nonblocking: monitoring never reads the log, and holdout
labels do not enter development metrics or training. The shared storage format was
preserved instead of introducing another human-label source.

## Verification incident

An additional parent-authored temporary console smoke harness initially invoked a
fixture without its normal pytest environment isolation. It inherited an installed
jobs-database setting and opened that database through canonical `db.connect`, which
can apply additive migrations. It then failed on an existing posting ID before a
synthetic posting was inserted. Read-only metadata afterward showed schema **16** and
empty feedback, prompt and selection tables. The prior schema was not recorded,
so the schema delta caused by this attempt cannot be established. No candidate
records were used in replay or model calls. No rollback or deletion was attempted;
the installed database was preserved.

The corrected harness sets isolated settings, database, data/profile and synthetic
gateway paths before importing Jobwatch, and asserts its temporary database path.
It completed the ten console checks recorded above. Automated pytest checks use the
repository's existing isolated environment fixtures. This incident means the entire
session cannot be described as having avoided installed-database access or possible
live additive migration. It was not deployment or service activation. Historical
Phase 6 verification records retain their earlier results and timing.

## Limits and rollback

All required local checks and review are complete; source merge is tracked in
PR #25. A real blind
study remains tracked separately in #6. Live paid replay/fitting, deployment, timers,
services and employer contact/Submit remain outside these source releases. Existing
real package-retrieval evidence is in the [Phase 6 audit](2026-10-23-feedback-selection.md).

Rollback is a reviewed source revert preserving approved profile versions, feedback,
genuine choices, fits, selections/results, packages, baselines, human labels, splits,
audit logs and evaluation reports. Do not delete histories or manually downgrade
schema metadata. There is no automatic data rollback.
