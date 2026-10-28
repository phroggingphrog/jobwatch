# Offline legacy too-senior correction and recovery

## Scope and authorization
This is **offline preparation only**. No live correction is authorized, and the CLI deliberately refuses the canonical `~/brain/data/jobwatch/` tree. Do not bypass that refusal, point it at an alias of a live file, or treat `--offline-copy` as approval. Parent BUI-96 owns live acceptance; independent Staff Reviewer must review the exact candidate before any live-action approval is requested. A future authorized live execution needs its own reviewed execution procedure. This run used synthetic data only; no live DB was opened or copied.

Base: `68fb0b0042d46d6555eefeb157e0d83a4cf1b2ad` (compatibility repair).
Code candidate: `64309f5619ad1d5a372c2b4db5315a5d31d6b733`.
Branch: `phase/bui-211-too-senior`.
Worktree: `/home/phroggingphrog/workspace/jobwatch-bui-211`.
Contract SHA256: `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`.

## Why this reason is truthful
`jobwatch/reader.py:76-82` defines too_senior as a pursued/adjacent family at an unsuitable level, not an unrelated field. `jobwatch/reader.py:1114-1115` explicitly maps a not-wanted too_senior report to hide/too_senior. This proposal restores that existing reason convention from already-stored model classification, without inventing a named target kind or rerunning any evaluation. It is not new validation of ad content, seniority, rights or hours. The existing compatibility reader intentionally does not include too_senior in its named not-target allowlist.

## Selection and safety
Only hide/not_target reviews whose report JSON is an object with no valid named kind, model JSON is an object with exactly `not_target_kind=too_senior`, and effective reader remains generic with **no terminal pipeline override** qualify. Malformed/non-object report JSON is excluded (fail closed). Uses candidate reader functions directly for pipeline precedence.

Apply requires exactly four at preflight; `BEGIN IMMEDIATE` then compares the entire selected review/pipeline snapshot. Each update rechecks the complete predicates and snapshot while holding the writer lock; changes only hide_reason, guarded by verdict/reason. Unexpected review triggers abort. All four postimages are verified before commit. Missing schema, IO errors, changed rows/count/pipeline, existing backup or transactions abort. No silent retry. Preflight may report a different count, but apply must refuse it.

Backup is exclusively created mode 0600 and fsynced before writes, and stores only database path, four private row identifiers, original reasons and full review/pipeline pre/post SHA256 hashes (no ad text). Keep it in a mode 0700 directory on this VPS; never upload it or log its contents. Full-row hashes make rollback conservative: even unrelated review or pipeline changes to a selected row block rollback. Rollback verifies database identity/path, four unique records and exact postimages inside a writer transaction, restores only the reasons, then verifies exact preimages. Repeated rollback refuses. A backup left by an aborted transaction is not proof of commit; do not blindly rollback or reuse it.

## Reproduce on a synthetic or already-authorized private offline copy
From the candidate checkout, use an existing Python environment with project dependencies. No installs, models or services needed:

```bash
PY=/home/phroggingphrog/apps/jobwatch/.venv/bin/python
$PY -m pytest -q tests/test_legacy_too_senior.py tests/web/test_legacy_kinds.py tests/web/test_ai.py
git diff --check
sha256sum GOAL_CONTRACT.md
# Set COPY and RECOVERY to private offline paths; no default DB path exists.
# The copy must include normal web tables and pipeline_state from this candidate.
$PY -m scripts.legacy_too_senior --db "$COPY" --offline-copy
# Expected: count 4; unsorted all/matches 4 on the representative synthetic fixture.
$PY -m scripts.legacy_too_senior --db "$COPY" --offline-copy --action apply --backup "$RECOVERY"
# Expected: count 0; unsorted all/matches 0 on that fixture.
$PY -m scripts.legacy_too_senior --db "$COPY" --offline-copy --action rollback --backup "$RECOVERY"
# Expected: count 4; unsorted all/matches 4 on that fixture.
```

CLI outputs aggregates only; error output is deliberately generic. Exit 0 means the selected offline action completed, not live acceptance. Exit 1 means guard/IO failure; exit 2 means invalid CLI arguments. Do not relax the four-row guard to fit a changed dataset. Backup JSON is trusted private recovery evidence, not an externally supplied input. Library functions are for tests/offline operation and assume the caller supplies an offline connection; CLI path restrictions cannot prove copy provenance or protect against malicious live-file aliases.

## Evidence and remaining boundary
24 new tests plus compatibility/web AI regression suite: **169 passed**, one existing Starlette httpx deprecation warning. Tests use temporary synthetic SQLite files, including a real second writer changing model JSON between preflight and locking. Representative 21-row fixture has 17 named legacy rows plus four too_senior: compatibility dry-run unsorted all=4, matches=4; corrected copy all=0, matches=0; unrelated reviews unchanged. This is synthetic evidence, **not measured live aggregates**.

No threshold/cap/form-fill edits, schema changes, sorter/model calls, merges, deployment or service restarts. What still doesn't work: live zero-unsorted is not achieved or claimed. Parent must evaluate any future reviewed, approved live procedure and recheck actual all/matches plus live board rendering. Code undo: leave branch unapplied, or revert this candidate via normal approved integration. Offline data undo: the exact guarded rollback above; if drift blocks it, diagnose privately rather than weakening guards.
