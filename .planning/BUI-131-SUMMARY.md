# BUI-131: sorting deadline fix

Base: `50ed8bb08` (full base recorded in issue evidence); branch `fix/bui-131-sort-deadline`.
Source finding: BUI-129, parent BUI-128. Fix scope: `pipeline/nodes/sort.py`, `pipeline/structured.py`, `jobwatch/llm.py`, deterministic regression tests.

## Decision and implementation

Use one absolute monotonic deadline across sort batches, structured retries, and permission-key fallback, rather than a fresh timeout per attempt. Each transport timeout is the smaller of the usual timeout and remaining budget. `DeadlineExceeded` is non-retryable and sorting records `time_limit`, leaving unlabelled jobs pending. Only `max_seconds=None` is unlimited; zero and negative budgets stop immediately. Reader-label processing checks the same deadline. Replies arriving at/after expiry are not applied.

No routes, moves, events or DLQ writes were added. Existing callers without a deadline retain their normal three-attempt behavior. An isolated worktree based on the requested candidate/docs branch avoids touching the main checkout; no merge or deployment.

## Tests-first evidence

`/home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q tests/test_sort_deadline.py` before implementation: exit 1, six failures. Reproduced clock 779 → 1319 (three 180s attempts with a 1s budget); permission-key fallback was worse (779 → 1859).

After implementation:
- `.../python -m pytest -q tests/test_sort_deadline.py tests/test_pipeline.py` → exit 0, `30 passed in 1.30s`.
- `.../python -m pytest -q` → exit 0, `1546 passed, 1 skipped, 2 warnings in 68.55s`. Warnings: Starlette httpx deprecation and future WeasyPrint HarfBuzz requirement.
- `git diff --check` → exit 0.

Verified edges: nearly expired timeout ends at 780; zero/negative budgets make no calls; retry plus key fallback receives 1, 0.75, 0.5 second timeouts; refusal exactly at expiry makes no fallback call; success at expiry is discarded. Tests use fake transport and in-memory SQLite only.

What works: shared remaining-budget accounting and labels-only semantics.
What remains unbuilt / what still doesn't work: independent review and release remain; no real model, board, PDF or form walkthrough was performed for this isolated fix. The synchronous transport must honor the supplied timeout; this does not forcibly cancel a transport that ignores it, and requests' timeout is an I/O timeout rather than an OS-level hard wall-clock cancellation.

GOAL_CONTRACT.md unchanged: SHA256 `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`.
Undo: revert the fix commit on this branch; no live DB/config/service changes to undo.
