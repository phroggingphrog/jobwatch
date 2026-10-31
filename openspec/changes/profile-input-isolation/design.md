# Design

## Context

See `proposal.md` for motivation. The current implementation uses person-specific profile directories, immutable version directories, evidence snapshots, projection helpers, and downstream candidate readers. The active worktree contains uncommitted changes. Commit `a8eef4c` records one verified retry milestone. Other profile regressions remain unverified. The same base commit is `152fc29224b9bd098ccf2731f991d2b29689c9a7`.

## Goals / Non-Goals

**Goals:** enforce one source boundary, publish version snapshots atomically, and make all gates and readers consume consistent approved state.

**Non-Goals:** changing product policy, editing live candidate data, activating services, or deploying this change.

## Decisions

1. Keep person input files in the live profile directory. Generated projections go to the immutable version root. Evidence annotations remain in the evidence snapshot. This avoids overwriting source data and keeps approvals auditable. Do not copy generated output back into live input.
2. Treat the atomic version-directory rename as the publication commit point. Store the exact amendment identity and all required projection data in the staged approval record before rename. Retry must inspect the published version and resume idempotently. Do not create a second version or repair by overwriting live input.
3. Preserve policy and evidence together. Snapshot validation must retain annotations and constraints such as `Policy: part-time only.` A missing or invalid snapshot must fail closed with a specific reason.
4. Resolve readers by the server-bound person and approved version. Do not use an ambient user's paths or mix live input with generated version data.
5. Verify focused tests against the same-base clean checkout. Classify each failure as a branch regression or baseline failure before changing behavior.

Alternatives considered: continue writing projections into `profile/` (rejected because it changes person input); rebuild a missing published version from live files (rejected because the source can change); silently fall back to the latest files (rejected because it hides integrity failures).

## Risks / Trade-offs

- Existing version data may not contain all new metadata → add backward-compatible reads and test adoption and legacy versions.
- A partial filesystem publication may leave a staging directory → ignore incomplete staging entries and make retry use only a complete approved record.
- Readers may have different path assumptions → migrate them in focused groups and test each group.
- Strict integrity checks may close discovery for damaged data → return a specific reason and preserve evidence for repair.

## Migration Plan

No live data migration or deployment is authorized. Keep the work in the current branch. Test existing directory layouts with synthetic fixtures. A later approved release must use the existing release and data path. Rollback by reverting the source commit; do not delete or rewrite profile data.

## Open Questions

None that change the stated contracts or architecture.
