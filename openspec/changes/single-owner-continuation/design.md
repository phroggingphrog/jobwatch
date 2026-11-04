# Design

## Context

Baseline e5db902 is an isolated single-owner branch. TASK-451 commit a8e8f48 and notifier commit 212b56d are available locally and have historical tests, but must be verified against this branch. Preserve the distinct-posting daily promotion filter added here.

## Goals / Non-Goals

Deliver a valid evaluation without drafting, accountable started promotions, integrity-checked replay and explicit selected preparation. Preserve canonical gates and budgets. Do not deploy, enable automation, submit applications, send real notifications, upgrade frameworks or restore multi-person support.

## Decisions

Use the existing EVALUATED stage/status repair and canonical persisted candidate/evaluation validation. Invoke promotion accounting after the execution claim starts, deduplicating retry callbacks. Apply packaging readiness only to preparation; missing identity cannot invalidate a useful evaluation. Restore no personal facts from obsolete profile versions without current human confirmation. Use synthetic fixtures for tests and read only readiness booleans from runtime profile/configuration. Paid acceptance requires a proven approved paid route and a bounded approved spend; missing prerequisites produce a release hold, not fabricated acceptance.

## Risks / Trade-offs

TASK-451 predates single-owner changes: adapt fixtures without restoring identities. A passing synthetic flow does not prove provider quality. Existing runtime/off settings and notification disabling must remain unchanged. Existing task and spec completion flags are historical evidence, not acceptance of this revision.

## Migration / Rollback

Existing SQLite stage/status text accepts EVALUATED without destructive migrations. Preserve data/config and immutable approved profiles. Revert only this continuation's source commit to return to e5db902; do not restore databases over newer usage/history.

## Open Questions

Whether current approved profile provides name/contact and whether the configured route meets paid-only policy are verified before acceptance. Unknown prerequisites remain explicit release holds.
