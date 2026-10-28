# BUI-143 / BUI-132 gate-holds fix

## Scope and revisions
- Worktree: `/home/phroggingphrog/workspace/jobwatch-bui-132`.
- Branch: `fix/bui-132-gate-holds`; base: `888f25e`.
- Tests-first commit: `7d2aa08`.
- Implementation candidate: `c9d17f00415216f9565a5b7612474bbda5f3c02e`.
- Only changed files: `pipeline/nodes/gate.py`, `tests/test_gate_holds.py`, this summary.
- Goal contract unchanged; SHA-256: `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`.

## Changes and safety argument
Present blocking claims now accept an overlapping deterministic rights rule as corroboration. Original quote presence remains mandatory. A private helper rejoins only a split first letter forming full, unrestricted, unlimited, permanent, citizen, citizens or citizenship (case-insensitive); the original quote, not the repaired quote, is checked against the ad.

Unverified claims and same-sentence rule disagreements defer their hold until the unchanged non-rights checks finish: not_target, too_senior, full_time_only, low_score. Verified blocking claims and rule-only findings retain their archive precedence. A hold never becomes draft: it becomes either archive or the same review hold. Existing archives and drafts take the same paths as before. Threshold 3.8, four-year boundary, schemas, reader rules, graph and draft caps are unchanged.

Decision: follow the issue's explicit worktree/branch and three-file scope rather than the generic phase layout. The supplied self-contained issue is the execution plan. No unrelated tracking files were edited.

## Verification (from the isolated worktree)
Python executable: `/home/phroggingphrog/apps/jobwatch/.venv/bin/python`.

- `python -m pytest -q tests/test_gate_holds.py` before implementation -> exit 1: **21 failed, 9 passed**. Failures were assertion mismatches for the requested corroboration, split-word verification and archive-before-hold behavior, not collection errors. Tests committed before implementation.
- `python -m pytest -q tests/test_gate_holds.py tests/test_pipeline.py tests/test_reader_rules.py` -> exit 0: **699 passed in 4.24s**.
- `python -m pytest -q` -> exit 0: **1565 passed, 1 skipped, 2 warnings in 76.82s**. Warnings: Starlette testclient and future WeasyPrint HarfBuzz-Subset requirement.
- `git diff --check` -> exit 0.
- Read-only replay -> exit 0: **2245 gate decisions, 0 diffs**; 202 ingest-only archived records had no extract/evaluate output and therefore no gate decision to replay.

### Replay method
Opened `file:/home/phroggingphrog/brain/data/jobwatch/jobwatch.db?mode=ro` with SQLite URI mode, enabled `PRAGMA query_only=ON`, and began a single read transaction. Loaded base gate via `git show 888f25e:pipeline/nodes/gate.py` into a separate Python namespace. For each archived/draft_queued/drafted/ready record with extract/evaluate outputs, validated JobFacts and MatchScore (filtering persisted evaluation metadata to schema fields), retrieved text through `ingest.ad_text` (`allow_fetch=False`) and title from the stored ingest output. Compared route plus the entire GateDecision model dump between base and candidate. Replayed the requested open gate DLQ entries identically. Only IDs and enum decisions were printed; no ad text, profile, answers, model calls or writes. Closed the read transaction with rollback.

### DLQ resolution table
| DLQ ID | Posting ID | Candidate route | Candidate reason |
|---:|---:|---|---|
| 3 | 6465 | archive | low_score |
| 4 | 2026 | archive | not_target |
| 140 | 8908 | archive | work_rights:citizen_only |
| 141 | 8987 | archive | work_rights:unrestricted_work_rights |
| 142 | 9284 | archive | work_rights:unrestricted_work_rights |
| 143 | 9375 | archive | not_target |
| 144 | 9480 | review | rights_rule_disagrees |
| 145 | 9859 | review | rights_rule_disagrees |
| 146 | 10312 | archive | work_rights:citizen_only |
| 147 | 3918 | archive | not_target |
| 148 | 8028 | archive | work_rights:unrestricted_work_rights |

## Review revision: preceding-article split keywords
- Resumed from candidate `20dc9bbb01aca06a06c334c6d9c531d83b032874`; preserved existing worktree and commits.
- Blocker confirmed: the generic regex consumed rejected `a P` / `a C` matches and missed overlapping `P ermanent` / `C itizen` repairs.
- Chosen fix: match only the seven allowlisted split keywords, case-insensitively, so rejected pairs consume no text. Original-quote presence and non-keyword rejection remain unchanged.
- Regression commit: `a8f2703`; fix commit: `042942c2b9a6dd8afc7e9795b4d400f09ffb8504`.
- Added both preceding-article reproductions and two absent-quote guards. First test run: exit 1, 2 failed/32 passed; one failure was a fixture typo (`pr_required` is not a schema enum). Corrected to `citizen_or_pr`, then reran before implementation: exit 1, **2 assertion failures/32 passed**, both review instead of archive. Committed tests before fix.
- `/home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q tests/test_gate_holds.py tests/test_pipeline.py tests/test_reader_rules.py` -> exit 0: **703 passed in 5.63s**.
- `/home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q` -> exit 0: **1569 passed, 1 skipped, 2 warnings in 72.19s** (same Starlette/WeasyPrint warnings).
- Read-only replay rerun with the method above -> exit 0: **2245 decisions, 0 diffs**, 202 ingest-only skips; all eleven DLQ results exactly match the table above. Scratch script printed only counts, IDs, routes and enum reasons.
- `git diff --check 888f25e..HEAD` -> exit 0; `git diff 888f25e..HEAD -- GOAL_CONTRACT.md` -> exit 0, empty; `sha256sum GOAL_CONTRACT.md` -> exit 0, unchanged hash above.
- Scope remains the three authorized files. No merge, DB writes, retries, model calls, service changes or other worktree changes. Review-fix evidence is recorded here instead of creating an out-of-scope REVIEW-FIX.md.
- Undo revision: revert `042942c`; next step: Staff Reviewer rechecks the overlap-safe repair, then Release owns integration/recovery.

## Handoff
What works: all requested gate behaviors, existing gate/reader tests, full suite, unchanged historical gate decisions.
Verified edge cases: preceding-single-letter articles before permanent/citizen, absent split-keyword quotes, all seven split-word keywords, non-keyword split, absent quote, unrelated sentence, both hold types yielding to all four non-rights checks, four-year boundary, full-time program exception, verified/rule-only archive precedence, not-real-job precedence and passing-job Graduate Visa disagreement.
What remains unbuilt / what still doesn't work: this is a local candidate only; no merge, deployment or DLQ recovery was performed. Actual held records remain held until the separately owned Release/recovery follow-up. No live DB writes, retries, service/timer changes, model calls or other worktree changes.
Undo: discard this isolated branch/worktree before release, or revert the implementation commit if subsequently integrated.
Next step: Staff Reviewer verifies the candidate; Release owns integration and recovery.
