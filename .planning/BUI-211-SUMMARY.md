# BUI-211 offline guarded correction

Base `68fb0b0042d46d6555eefeb157e0d83a4cf1b2ad`; code `64309f5619ad1d5a372c2b4db5315a5d31d6b733`; branch `phase/bui-211-too-senior`.

Delivered `scripts/legacy_too_senior.py`, `tests/test_legacy_too_senior.py`, and self-contained `.planning/BUI-211-RUNBOOK.md`. Script dry-runs by default, requires explicit offline attestation, refuses canonical live data tree, guards exactly four, rechecks full review/pipeline predicates under writer lock, fsyncs an exclusive 0600 reason/hash backup, and implements exact postimage-guarded transactional rollback. No ad text/IDs in stdout or issue logs.

Checks from isolated checkout with `/home/phroggingphrog/apps/jobwatch/.venv/bin/python`:
- `-m pytest -q tests/test_legacy_too_senior.py` before implementation -> exit 2, import failure for absent script (RED).
- Same command after initial implementation -> exit 0, 21 passed.
- `-m pytest -q tests/test_legacy_too_senior.py tests/web/test_legacy_kinds.py tests/web/test_ai.py` after extended guards -> exit 0, 169 passed, 1 warning in 41.71s (existing Starlette httpx deprecation).
- `git diff --check` -> exit 0, no output.
- `sha256sum GOAL_CONTRACT.md` -> exit 0, `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`.

Synthetic dry-run count=4, all/matches unsorted=4; corrected 21-row fixture unsorted=0 in both scopes. Rollback roundtrip restores originals exactly. CLI dry-run and offline argument gate exercised in subprocess tests. No private/live copy used.

What works: narrowly guarded offline apply, truthful existing too_senior reason mapping, private recovery and synthetic zero-unsorted with compatibility candidate.
What remains unbuilt: live execution procedure/authorization, release and parent live acceptance; this tool deliberately cannot be used in the canonical live data tree.
Verified edge cases: wrong count 0/3/5; separate-writer preflight drift; malformed/non-object model/report JSON; named report precedence; every terminal pipeline stage; nonterminal fallback; unrelated reviews unchanged; wrong rollback DB; modified postimage; repeated rollback; trigger refusal; existing backup protection; injected post-update failure rolls all changes back.
What still doesn't work: actual live service remains unchanged and zero live unsorted is not claimed.

Decisions/deviations: issue supplies its own bounded execution scope rather than a separate phase PLAN; no shared planning state touched. Fail closed on malformed reports. Synthetic-only verification chosen to avoid unnecessary access to personal live data. TDD red execution occurred but tests and implementation committed together (no separate RED commit). Staff Reviewer gate is the next step; no live approval requested.

## Self-check: PASSED
All four planned deliverables exist; code commit exists; contract unchanged; tests passed. No stubs or application behavior changes.
