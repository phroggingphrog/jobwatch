# Tasks

## 1. Baseline and interface

- [x] 1.1 Characterize legacy ordering, vocabulary, triage, routing, promotion and gate decisions in sanitized tests, including unknown and in-flight jobs.
- [x] 1.2 Define and validate the per-user category snapshot and opaque-ID interface; test invalid IDs, priority, action and missing configuration; share the interface with TASK-447 owner.

## 2. Goal research and configuration

- [x] 2.1 Implement per-user goal-versioned research through existing website access, recording source URLs and retrieval dates; test source-specific queries and no new collector activation.
- [x] 2.2 Implement versioned suggestions, explicit constraints and corrections with refresh and rollback; test stale refresh, failure, isolation and override retention.
- [x] 2.3 Test that researched restrictions never add qualifications, work-rights, hours or negative personal filters, and that no implicit code vocabulary appears.

## 3. Screening and migration

- [x] 3.1 Replace fixed category ordering and phrases with snapshot data; test add, rename, reorder and remove without code changes, and same-title per-user differences.
- [x] 3.2 Generate title-triage schema and prompt from the snapshot; test configured IDs and neutral errors without model calls.
- [x] 3.3 Convert ingest routing, promotion and gate exception to explicit policy fields; test legacy protections and neutral absent configuration.
- [x] 3.4 Implement reversible migration to per-user data and ID mapping for in-flight records; run golden regression tests for existing owner behavior and rollback.

## 4. Integration

- [x] 4.1 Run focused integration tests for goals through research, config, source queries, triage and promotion, with mocked external calls and isolated users.
- [x] 4.2 Provide parent a rollout and undo plan, fixture results, interface contract and exact owner-entrypoint verification steps; do not deploy in this change.
