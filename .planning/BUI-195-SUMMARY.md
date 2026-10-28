# Legacy reader not-target compatibility repair

## Candidate
- Base: `0fbb8487b28ae6a097568cc1ab81b6adf507c574`
- Code candidate: `e2e391a65af36669d3037b246fbbdd8a5d0f0f18`
- Branch: `phase/bui-195-reader-kinds`
- Worktree: `/home/phroggingphrog/workspace/jobwatch-bui-195`
- GOAL_CONTRACT.md SHA256: `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487` (unchanged).

## Diagnosis and decision
Read-only SQLite inspection confirmed 21 generic reader hide/not_target rows. All have parseable report_json without not_target_kind; model_json contains sales 1, other_field 6, reception 5, engineering_it 1, trades_manual 1, health_care_teaching 3, too_senior 4. The query did not select model_json, so ai_from_row could only see the absent report field. reader.sort_not_target writes the model field; rederive is intended to refresh the report/verdict afterward. Existing non-null model kinds also exclude these rows from sorter candidates. We did not establish why the historical report/verdict refresh was absent, and did not run the sorter or rederive.

Smallest safe repair: select model_json in the existing single query and use a string/allowlist-validated kind only as fallback for generic not_target. A valid report wins; other hide reasons and terminal pipeline precedence remain unchanged. Missing/malformed JSON and unsupported kinds stay explicitly unsorted. too_senior is not a NOT_TARGET_KEYS member: deliberately not relabelled by compatibility code. Also fixed _report's kind validation to reject list/dict values without an unhashable-type exception.

## Verification
Commands executed from candidate worktree with `/home/phroggingphrog/apps/jobwatch/.venv/bin/python`:
- `-m pytest -q tests/web/test_legacy_kinds.py` before implementation -> exit 1; 16 failed, 13 passed. Initial fixture attempt failed with missing pipeline_state; corrected scratch schema setup, then reproduced missing fallback and malformed report handling.
- `-m pytest -q tests/web/test_legacy_kinds.py tests/web/test_ai.py` -> exit 0; final **145 passed, 1 warning in 40.34s** (existing Starlette httpx deprecation).
- `git diff --check` -> exit 0, no output.
- Candidate q.load_rows against live DB opened with SQLite `mode=ro` -> exit 0; generic not_target **4 in all and 4 in matches**, all model kinds too_senior. No row IDs or personal data emitted.
- Live curl `GET http://127.0.0.1:8960/?ai=hide&why=not_target&scope=all`, `HX-Request:true`, `HX-Target:results`, no job parameter -> exit 0; HTTP 200, 21 cards and unsorted label still present. This is the unchanged running service, not candidate acceptance.

Verified edge cases: every named kind reaches scratch board filtering/rendering; malformed/non-object model JSON; unknown and too_senior model kinds; list/dict kind values; valid report precedence; non-generic hide reason preservation; scored/ingested pipeline fallback and archived pipeline override; raw joined columns removed.

What works: validated legacy named kinds render/filter in the candidate without data edits; 17 of the current 21 generic rows resolve under candidate read-only queries.
What remains unbuilt: release and historical verdict correction are not performed. Full suite/live zero acceptance is for parent verification after authorized release, not claimed here.
What still doesn't work: live service still shows 21 unsorted rows; candidate alone leaves four too_senior legacy rows truthfully unsorted.

## Exact remaining path (parent BUI-96 owns acceptance)
1. Independent Staff Reviewer checks this exact candidate in another checkout. No contract, threshold, draft cap or form-fill changes.
2. Parent/release agent requests board approval for integration and release of reviewed commit; execute only on approval. This issue performed no merge, deployment or service start/restart.
3. Four stale too_senior verdicts require separately reviewed and board-approved data correction, not a broad sorter/model invocation. Proposed bounded operation: within one transaction, select ad_reviews rows whose current verdict=hide, hide_reason=not_target, report_json is a valid object with no valid named not_target_kind, model_json is a valid object with not_target_kind=too_senior, and effective reader result remains generic not_target (no terminal pipeline override). Require exactly four at preflight; record a private local backup of affected hide_reason values; change only hide_reason to too_senior using predicates rechecked in UPDATE. Abort on changed count or any preflight mismatch. Do not overwrite reports, run model calls, or refresh unrelated rules. Rollback restores the backed-up reasons for exactly the approved rows. This is a proposal only, not executed or approved.
4. Parent rechecks read-only aggregate all/matches and live HX GET with no job parameter after authorized release/correction, and only then assesses zero live unsorted. New unsorted arrivals or changed preflight require fresh diagnosis, not blind mutation.

Undo candidate: revert code commit on the release branch through normal approved integration; local isolated branch can simply be left unapplied. Form-fill worktree untouched.
