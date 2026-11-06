# Proposal

## Why

Profile confirmation and downstream readers still mix person-owned files with generated projections. This creates data-loss risk, inconsistent policy and evidence, and retries that can mint duplicate versions. The current branch has known focused and full-suite failures, so the contracts must guide the remaining fixes.

## What Changes

- Keep live person files read-only for generated writes.
- Store generated projections and approval metadata in immutable per-person versions.
- Preserve the evidence snapshot and policy, including `Policy: part-time only.`
- Make confirmation and rule-amendment recovery reuse a published version.
- Make adoption, readers, and discovery gates use the correct approved version and report specific failure reasons.
- Add focused regression coverage and compare known failures with the same base commit.

## Capabilities

### New Capabilities
- `profile-input-isolation`: contracts for source isolation, snapshots, recovery, readers, adoption, policy, and gates.

### Modified Capabilities
- None. The repository has no existing capability specs.

## Impact

Affected areas include `jobwatch/candidate/intake.py`, `projection.py`, `rules.py`, candidate readers, `pipeline/agentic/`, and focused tests. No new dependency, live-data change, deployment, or service is in scope. Commit `a8eef4c` records the verified rule-amendment recovery milestone. Its focused recovery test passed, and `tests/candidate/test_rules.py` passed 8 tests. Other work remains unverified.
