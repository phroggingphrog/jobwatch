# Tasks: screen-first pipeline

Executor rules: work only in `~/projects/.worktrees/jobwatch-screen-first` (branch `spec/screen-first-pipeline`).
Run each step's check before the next step. If a check fails twice, stop and write the failure on Backlog TASK-424.
Never run against `~/.local/share/jobwatch-native` until step 7. Never POST or click on the live board.

## 1. Execution mode
- [x] 1.1 `jobwatch/execution_mode.py`: add `'screened'` to the allowed tuple in `effective_mode`.
- [x] 1.2 `jobwatch/run.py`: after the `elif mode == 'pipeline':` branch add
      `elif mode == 'screened':` → `from pipeline import screened` and
      `ai = {"screened": screened.after_collect(conn, config, max_seconds=ai_budget(started, config, tier), deadline=deadline)}`.
- [x] 1.3 Check: `uv run pytest -q tests -k execution_mode` passes; add test `tests/test_execution_mode_screened.py`
      asserting `effective_mode({'pipeline': {'execution_mode': 'screened'}}) == 'screened'`.

## 2. SHORTLISTED stage and graph override
- [x] 2.1 `pipeline/schemas.py`: add `SHORTLISTED = "shortlisted"` to `Stage`.
- [x] 2.2 New `pipeline/screened.py`:
      - `SCREENED_EDGES = {**graph.EDGES, Stage.SCORED: graph.Edge("gate", frozenset({Stage.SHORTLISTED, Stage.ARCHIVED}))}`
        with `Stage.DRAFT_QUEUED` and `Stage.DRAFTED` keys removed.
      - `GATE_ROUTE = {"draft": Stage.SHORTLISTED, "archive": Stage.ARCHIVED, "review": Stage.DLQ}`.
      - `TERMINAL` adds `Stage.SHORTLISTED`.
      - Implement by subclassing `graph.Graph` and overriding only the attributes/method that read `EDGES`,
        `GATE_ROUTE`, `TERMINAL` (read `pipeline/graph.py` lines 72-226 to find them; do not edit `graph.py` logic).
- [x] 2.3 Check: new `tests/test_screened_graph.py` with a fake LLM (copy the fake used in existing pipeline graph tests:
      `grep -rln "Graph(" tests`) proving gate 'draft' → SHORTLISTED and nothing reaches DRAFT_QUEUED.

## 3. Closed ads
- [x] 3.1 `pipeline/nodes/ingest.py`: where `adtext.ensure_text` returns, if `adtext.last_status(conn, r)` (the function at
      `jobwatch/util/adtext.py:95`) is `"gone"`, move the posting to ARCHIVED with reason `posting_closed` and `continue`.
- [x] 3.2 Check: test with a fetcher stub returning 404 → stage ARCHIVED, reason `posting_closed`, zero LLM calls.

## 4. Promotion
- [x] 4.1 `pipeline/screened.py`: `promote(conn, config, *, max_seconds, deadline)`:
      read `config.settings['pipeline']['screened']` with defaults `promote_per_run=3`, `promote_per_day=10`, `min_score=3.0`;
      count today's promotions from `pipeline_events` rows with `node='promote'` in the last 24 h;
      select SHORTLISTED rows with score >= min_score ordered by score DESC, posting_id DESC; limit to remaining allowance;
      call `pipeline.agentic.service.agentic_batch_run(ids, config, conn, max_seconds=max_seconds, deadline=deadline)`;
      write one `pipeline_events` row per id with `node='promote'`.
- [x] 4.2 `after_collect(conn, config, max_seconds, deadline)`: run auto-retry (step 6), run the screened graph with
      half of `max_seconds`, then `promote` with what remains; return a dict of counts.
- [x] 4.3 `config/jobwatch.yaml`: add under `pipeline:` a `screened:` block with the three defaults. Do not change `execution_mode`.
- [x] 4.4 Check: test with 5 SHORTLISTED rows (4.5, 4.2, 4.0, 3.5, 2.9) and a stub `agentic_batch_run` → called once with the top 3 ids.

## 5. Title-shaped queries
- [x] 5.1 `jobwatch/occupations/plan.py`: add `TITLE_RE = re.compile(r'^[a-z0-9][a-z0-9 &/+\-]*$')` and
      `def title_shaped(q): q=q.casefold().strip(); return 1 <= len(q.split()) <= 6 and bool(TITLE_RE.match(q))`.
      In `search_plan` line 46, filter `policy.focus` through `title_shaped`; store the count of dropped items as
      `dropped_focus` in the returned plan data (add field `dropped_focus: int = 0` to `SearchPlan`; it is part of `plan_hash`).
- [x] 5.2 Check: test that `"Looking for a supervised entry role, about three days a week."` is dropped and `"graduate analyst"` kept;
      run `uv run pytest -q tests -k "plan or occupation"`.

## 6. Auto-retry transport failures
- [x] 6.1 `pipeline/screened.py`: `retry_transport(conn, limit=50)` selects unresolved `pipeline_dlq` rows with
      `attempts < 4`, `created_at <= now-6h`, and `error` containing any of `Connection`, `Timeout`, `timed out`,
      `502`, `503`, `504`; for each call the same function `pipeline/cli.py` uses for `dlq --retry ID`.
- [x] 6.2 Check: test with three DLQ rows (transport 7 h old, transport 1 h old, validation 7 h old) → only the first re-queued.

## 7. Dropped-by-title view
- [ ] 7.1 `pipeline/cli.py`: add action `dropped` with `--days` (default 7) printing JSON lines
      `{posting_id,title,company,reason,decided_at}` from `prescreen_decisions` (stage `metadata`, outcome `skip`) joined to `postings`.
- [ ] 7.2 `jobwatch/web/queries.py`: add `dropped_by_title(conn, days=7)` returning the same rows; render a read-only
      table on the page that already uses prescreen data in that file (follow its existing template pattern). No buttons.
- [ ] 7.3 Check: CLI on a DB copy: `cp ~/.local/share/jobwatch-native/jobwatch.db /tmp/jw-copy.db` then
      `JOBWATCH_DATA_DIR=<dir of copy> uv run jobwatch pipeline dropped --days 7 | head`. Web: serve the copy on port 8971
      and take a server-side screenshot of the page.

## 8. Dry run on a copy, then release
- [ ] 8.1 Full tests: `uv run pytest -q` all pass.
- [ ] 8.2 On the DB copy with `execution_mode: screened` in a copied config: `uv run jobwatch run --tier fast --limit 50`.
      Record counts: prescreened, fetched, closed, extracted, scored, shortlisted, promoted, dlq, agentic ready/held.
      Acceptance: no posting left without a stage; promoted <= 3; zero model calls on prescreened/closed postings.
- [ ] 8.3 Write the counts and the commit SHA on TASK-424. Move it to Waiting for owner with "Ready to go live".
- [ ] 8.4 Go-live (owner approval only): merge branch to `main`, update `~/apps/jobwatch-release` through the existing
      release step, set `pipeline.execution_mode: screened`. Undo: set it back to `agentic`.
