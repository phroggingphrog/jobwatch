# Separate approval-bound legacy correction procedure

## Authorization and exact scope
Preparation only. Do not execute live apply/rollback until independent Staff Reviewer accepts the exact commit and the parent obtains board approval for that exact commit, action and private manifest hash. This document is not approval. The existing OFFLINE ONLY script and its four-row guard are unchanged. No models, sorter, thresholds, draft caps, schema, form-fill worktree or goal-contract edits.

Use `scripts.live_legacy_procedure`, not an alias or bypass of the offline CLI. Its write CLI verifies a real approved `request_board_approval` in the current Paperclip company before opening SQLite mode=rw. The approval payload must contain `legacy_correction` exactly `{candidate: <full HEAD SHA>, action: apply|rollback, manifest_hash: <SHA256 from inspect>}`. A local attestation is insufficient. Library functions exist for synthetic/copy tests; direct library calls are not the authorized live execution interface. Operators must not bypass the CLI.

## Changed preflight diagnosis (2026-10-09, this preparation run)
Canonical DB opened mode=ro, query_only=ON, explicit read transaction. Current deployed reader: generic all=20, matches=20. Exact base candidate reader: all=3, matches=3. Stored hide/not_target reviews=1049, disjoint exclusions/selection: named report=992; named model=50; model too_senior with terminal pipeline override=4; model too_senior with no pipeline row and eligible=3. No invalid-object/other-model remainder in this partition. All four overridden too_senior rows are archived; candidate precedence excludes them. This establishes why stored too_senior is NOT the eligible subset, and why reducing a count without checking pipeline state would be unsafe.

The prior four was synthetic evidence, not a persisted live snapshot (see base runbook). No historical identity snapshot proving a particular row transitioned exists in that artifact. Therefore no claimed historical row transition: current three is independently diagnosed, not a predicate broadening. Selection uses unchanged `legacy_too_senior.eligible`: stored hide/not_target; object report/model; no named report; model exactly too_senior; effective generic reader; no terminal override. Existing reader maps this level classification to too_senior: reason-only correction is truthful, not re-evaluation or cosmetic creation of a named kind.

Eligible digest: `ab6829dda7a722a09ad114678cd6ff5fc5a947e4fb28325dc49d58c8899e7967`.
Whole logical DB snapshot: `24c33d9ac0225b4e14381c34171f56b7015e776c44a8dcc66c77988aaeee95bb`.
Private manifest hash: `50a82762f33c9c84eeb54096a39e2077406dbd856e35d8fde20f7ba0cb09667e`.
Private evidence directory: `~/brain/data/jobwatch/private-bui-215/`, mode 0700; manifest and SQLite copies mode 0600. Do not upload any contents or identifiers. The preparation manifest will likely be stale by execution; stale means abort and independently diagnose/review a new manifest, never silently refresh under old approval.

## Safety mechanics
Manifest binds canonical path/device/inode, whole logical schema+data hash, full selected review/pipeline hash, private exact three IDs and exact all/matches counts. Inspection uses one read transaction. Apply holds BEGIN IMMEDIATE, refuses review triggers, recomputes exact manifest under lock, and refuses any logical DB drift, even unrelated data. No retry. Full SQLite online backup from a second read-only connection occurs while the writer lock is held, before updates. Backup must not exist; created 0600, integrity_checked, logical snapshot verified, closed, file fsynced and parent directory fsynced before any UPDATE. Any failure aborts.

Only three hide_reason cells change. A whole-database expected postimage is computed and verified before commit, proving all other logical data unchanged. SQLite journal transactions supply atomicity; crashes before commit leave original DB, after commit leave verified postimage. A backup alone does not prove commit. Inspect privately to determine exact preimage or postimage before recovery; neither means STOP. Do not replace the live DB file with the full backup: that could lose concurrent writes and invalidate WAL users.

Rollback is also approval-bound, verifies original backup hash, same path/inode and exact whole DB postimage under lock, reverses only the three reasons, then verifies exact preimage before commit. Any intervening data change blocks rollback. Repeated apply or rollback refuses. Backup/manifest remain private recovery evidence even after abort; never overwrite/reuse backup. If rollback refuses, diagnose and obtain a newly reviewed recovery procedure, not weaker guards.

## Integration/release preflight (parent/Release, not performed here)
1. Review exact branch `phase/bui-215-live-procedure` in a separate detached checkout. Run checks below; compare contract to base `9553a4e4dd916a355661a8d2f20c6109e5983b1c`.
2. Record current main, live service command/checkout/revision, current dependency environment and protected form-fill branch/worktree. Do not reset or switch existing worktrees, stash, or overwrite their files. Integration can change HEAD, invalidating approval binding.
3. Assemble final release candidate in a separate checkout with current main; review its diff and rerun compatibility tests and copy rehearsal. No blind merge of stale base. Keep reader compatibility changes required to reduce 20 to 3; procedure alone will not repair deployed reader output.
4. Record existing code/service rollback revision and release procedure. Parent requests board approval covering exact final candidate integration/deploy/restart and separately exact data action/manifest. This preparation does not authorize any of them. Stop writers only if specifically covered by that approval; otherwise changed snapshot abort is expected.
5. Fresh read-only inspect on exact final candidate, privately diagnose changes, and bind the reviewed manifest hash in approval. Keep private evidence directory on this VPS. Do not run non-HX GET with job selection (can mark viewed).

## Commands after review and approval, run by authorized parent
Use existing dependency environment; no installs. Run from clean exact approved checkout; fail if git status is not clean. `DB` is canonical live file; `MANIFEST` and `BACKUP` are absolute private paths. Never print their contents.

```bash
PY=/home/phroggingphrog/apps/jobwatch/.venv/bin/python
$PY -m scripts.live_legacy_procedure --db "$DB" --manifest "$MANIFEST" --action inspect
# Inspect is RO and creates a NEW exclusive private manifest; count must be 3.
# Review manifest/hash and obtain bound real approval BEFORE next command.
$PY -m scripts.live_legacy_procedure --db "$DB" --manifest "$MANIFEST" --backup "$BACKUP" --action apply --board-approval-id "$APPLY_APPROVAL"
# Rollback requires a separate real approval binding action=rollback, same manifest hash.
$PY -m scripts.live_legacy_procedure --db "$DB" --manifest "$MANIFEST" --backup "$BACKUP" --action rollback --board-approval-id "$ROLLBACK_APPROVAL"
```

Exit 1 means guarded failure: no silent retry, diagnose privately. Do not expose Python tracebacks containing private DB data. Backup contains full personal database; keep on VPS only.

## Read-only acceptance after approved deployment/data action
- Exact deployed reader via SQLite mode=ro/query_only read transaction: generic hide/not_target in both q.load_rows scopes must be zero; selected reasons too_senior; no unrelated logical changes at commit. If deployed reader still gives 20, release compatibility is missing: do not claim success.
- Local live board GET `http://127.0.0.1:8960/?scope=all` and `?scope=matches`, headers `HX-Request: true`, `HX-Target: results`, WITHOUT job parameter: HTTP 200; parsed Not target (unsorted) sidebar count zero in both. Preserve only aggregates/hash, not response HTML. HX prevents board_visit touch and results partial avoids job_ctx/mark_viewed. Do not use a full page GET for this check.
- Current preparation HX checks were HTTP 200 both scopes, not a claim of zero or post-deploy success. No live mutation/deploy/restart happened.

## Reproduction evidence
`$PY -m pytest -q tests/test_live_legacy_procedure.py tests/test_legacy_too_senior.py tests/web/test_legacy_kinds.py tests/web/test_ai.py`: 178 passed, one existing Starlette warning. Code candidate `e34d99d541ae29f93cf384b89a5193ce96ab3187`; subsequent documentation commit does not change executable code.
Private RO online copy rehearsal: generic 3/3 -> 0/0 after reason correction -> 3/3 after rollback; exact full logical preimage restored. This is COPY evidence, NOT live zero. Original offline tool remains four-only and unchanged.
`git diff --check`: clean. Contract SHA256 unchanged: `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`.
What still doesn't work: live acceptance remains 20/20; independent review and parent live approvals/integration still required. No historic live-four identity provenance is claimed.
