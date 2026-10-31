# Design: screen-first pipeline

## Flow
```
collect (unchanged)
  -> ingest      pipeline/nodes/ingest.py   prescreen 'metadata' skip -> no fetch, no model (existing)
                                            fetch full ad; adtext 'gone' -> ARCHIVED reason posting_closed
  -> extract     pipeline/nodes/extract.py  one structured call (existing)
  -> evaluate    pipeline/nodes/evaluate.py one structured call, score 1.0-5.0 (existing)
  -> gate        pipeline/nodes/gate.py     canonical eligibility: eligible|held|excluded (existing)
  -> NEW: shortlist  pipeline/screened.py   gate route 'draft' -> stage SHORTLISTED (not DRAFT_QUEUED)
  -> NEW: promote    pipeline/screened.py   top N SHORTLISTED by score -> agentic_batch_run(ids, ...)
```
The agentic path (`pipeline/agentic/service.py:808 agentic_batch_run`) is called unchanged, with an explicit id list.
Its holds still happen but only for N postings per run, not every posting.

## Decisions
1. **New mode, not a rewrite.** `screened` is added beside `off|reader|pipeline|agentic` in
   `jobwatch/execution_mode.py`. Rollback is a config line.
2. **Reuse the graph, stop before drafting.** `screened` runs `pipeline.graph.Graph` with an edge override:
   `Stage.SCORED -> gate -> {SHORTLISTED, ARCHIVED, DLQ}`. Drafting/form_map belong to the agentic package path.
3. **Promotion limits** (in `config/jobwatch.yaml` under `pipeline.screened`): `promote_per_run: 3`,
   `promote_per_day: 10`, `min_score: 3.0`. Ties broken by newest `postings.id`.
4. **Title-shaped queries.** A focus item is a query only if it has 1-6 words, matches
   `^[a-z0-9][a-z0-9 &/+\-]*$` after casefold, and does not end in punctuation. Others are dropped from
   `search_plan` and counted in the plan as `dropped_focus`. Hypothesis titles (`query_for`) are unchanged.
5. **Auto-retry.** At the start of each `screened` run, unresolved `pipeline_dlq` rows whose `error` contains
   `Connection`, `Timeout`, `timed out`, `502`, `503` or `504`, with `attempts < 4` and `created_at` older than 6 h,
   are put back with the existing retry function, at most 50 per run.
6. **Dropped-by-title view.** Read-only query over `prescreen_decisions` where stage = 'metadata' and outcome = 'skip'
   for the last 7 days; CLI `jobwatch pipeline dropped [--days 7]`; board: one section on the page that
   `jobwatch/web/queries.py` already serves prescreen data to.

## Risks
- Prescreen rules that are too broad hide good jobs: mitigated by the dropped view and existing overrides.
- Score threshold 3.0 is a technical default, not an owner number; it is shown in `jobwatch pipeline status`.
