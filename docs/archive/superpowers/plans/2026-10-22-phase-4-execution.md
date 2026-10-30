# Phase 4 execution and model routing

Goal: execute the existing approved [Plan 3](2026-10-21-plan-3-discovery.md), using the local checkout and the owner's current model choices.

Architecture and interfaces remain those of Plan 3 and the cross-plan contract. The native backend owns discovery; occupation similarity is a search hypothesis, never qualification proof.

| Plan tasks | Worker | Reason |
|---|---|---|
| 1 ADR/glossary, 10 bounded documentation | LUNA, parent verified | Narrow source-backed writing |
| 2–3 reference investigation, fetch and loaders | Sol 6.1 | External schemas, licensing, hashes and parsing |
| 4–5 counted embeddings, caches and fields | Sol 6.1 | Durable budgets, private state and semantic retrieval |
| 6–9 collector overlay, relevance, dedupe, ordering and API | Parent | Shared pipeline changes and authorization boundaries |
| Integration and release checks | Parent | One authority for shared files and evidence |
| Final independent review | Sol 6.1 | Fresh review of regression and contract risks |

Execution rulings:

- The owner's current request supersedes EXECUTING.md's cloud/Sonnet environment and model choices. Use a local isolated `codex/` branch and a Python 3.12 environment outside the repository. No deployment or services.
- Start from current `origin/main`, including PR #12's projection fix, after confirming the prerequisites were merged.
- Preserve all existing run-key inputs and the legacy defaults. Default shadow relevance performs no paid work before a refresh. No paid refresh is run during development.
- Run focused synthetic checks during implementation, then the phase's full regression once the integrated source is ready.
- The parent integrates shared files and commits; workers have disjoint ownership. All new candidate-bearing fixtures are invented.

Acceptance: reference tooling and field hypotheses, private cached plans, collector overlays, quoted relevance with shadow/on modes, conservative cross-source duplicates, bounded ordering, read-only account-bound API, documented rollback and actual synthetic verification. No accuracy or deployment claim.

The complete implementation rulings, including verified dataset schema adjustments,
ingest compatibility and unavailable-route behavior, are recorded in
[ADR 0005](../../adr/0005-field-and-job-discovery.md#implementation-rulings).

Owner follow-up: the location prefilter now uses the current confirmed profile
without feature flags. The wider hardcoded-preference audit is recorded in
[the audit report](../../audits/2026-10-22-profile-preferences.md) and GitHub #14;
its remaining eligibility, ranking and legacy-mode repairs are not claimed as
completed by this discovery phase. The new discovery and location checks join
the normal focused synthetic CI job.

## Verification recorded 2026-10-22

- Environment: Python 3.12, external `/tmp/jobwatch-phase4-venv`, synchronised
  from `uv.lock` with `uv sync --frozen --extra dev --extra browser`.
- Final full command: `/tmp/jobwatch-phase4-venv/bin/python -m pytest -q -p no:cacheprovider`.
  Result: **3344 passed, 10 skipped, 6 warnings in 1406.39s**. Warnings were
  dependency deprecations for future HarfBuzz-Subset use and TestClient cookies.
- Focused discovery, API and profile-location checks: **115 passed in 12.41s**.
- `jobwatch check --code` passed with an isolated invented profile and settings;
  no live candidate records were used. The CI YAML parsed and includes the new
  synthetic checks. `git diff --check` passed.
- Earlier development runs were interrupted when integration and owner-directed
  location changes were still being made; they are not counted as final release
  verification. The final run above used the final source and locked environment.
- Independent Sol 6.1 review findings were resolved with synthetic regressions.
  Full-suite correctness does not establish live model quality, recommendation
  accuracy, completeness of skipped coverage or deployment.
