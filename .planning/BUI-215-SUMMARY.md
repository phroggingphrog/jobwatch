# BUI-215 preparation summary

Base: 9553a4e4dd916a355661a8d2f20c6109e5983b1c.
Code/runbook candidate: e34d99d541ae29f93cf384b89a5193ce96ab3187.
Branch: phase/bui-215-live-procedure; isolated worktree /home/phroggingphrog/workspace/jobwatch-bui-215.

Built separate approval-bound CLI, immutable private manifest, full crash-durable SQLite backup, whole-data change abort, exact identity/count/selection guards, narrow transaction and guarded rollback. Offline tool unchanged. Scope derived directly from issue because no new CONTEXT/PLAN was supplied; no shared planning state touched. Required work-memory tool unavailable in this runtime; no memory retention attempted.

Diagnosis/rehearsal is fully described in BUI-215-RUNBOOK.md. Current candidate generic=3/3, deployed reader=20/20. Three eligible, four stored too_senior excluded by archived precedence. Private copy 3/3 -> 0/0 -> 3/3 and exact logical preimage restored. Private identities never printed or committed.

Checks:
- RED: pytest tests/test_live_legacy_procedure.py -> exit 2, missing new module.
- First GREEN -> exit 1, 7 passed/1 failed due fixture missing pipeline content_hash; fixed using existing staged helper.
- Final `.venv/bin/python -m pytest -q tests/test_live_legacy_procedure.py tests/test_legacy_too_senior.py tests/web/test_legacy_kinds.py tests/web/test_ai.py` (existing main environment absolute Python path) -> exit 0, 178 passed, one existing Starlette warning.
- git diff --check -> exit 0.
- git diff --quiet 9553a4e -- GOAL_CONTRACT.md scripts/legacy_too_senior.py -> exit 0.
- RO private copy rehearsal -> exit 0, exact_snapshot_restored=true.
- HX all/matches without job, HX-Target results -> exit 0, HTTP 200 both (not zero acceptance).
- Contract sha256sum -> exit 0, 808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487.

What works: separately reviewable preparation and verified synthetic/private-copy transaction and rollback.
What remains unbuilt: live correction/release not executed or authorized; live zero not achieved. Exact candidate still requires independent Staff Reviewer gate; parent owns any later live approval.
Verified edge cases: three-only guard, unrelated/eligible/pipeline drift, directory fsync failure before writes, failure after updates atomic rollback, rollback drift/repeat refusal, CLI no approval refuses before writer open.

Threat surface: new CLI queries control-plane approval with run environment credentials (never logged); creates full personal backup retained privately on VPS. Direct library functions are test seams, not an authorization interface. Fresh final integration candidate/manifest needs review and approval anew. Full-data guard is intentionally strict and may routinely abort with active collectors.

## Self-check: PASSED
New code, tests, runbook and code commit exist. No known functional stubs. Main/form-fill worktrees untouched. No live mutation, merge, deployment, restart or model calls.
