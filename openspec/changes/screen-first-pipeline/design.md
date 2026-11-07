# Design: screen-first pipeline

## Source reconciliation (2026-11-08)

The flow is implemented in `main` at `0ea4fe0`. The diagram describes source
behavior, not an unimplemented plan or verified runtime deployment. Current
`INTENT.md` controls the single-owner, evaluation-only boundary. Candidate
understanding and native assessment are specified by
`candidate-digest-native-assessment`; its acceptance follow-up is
`native-assessment-acceptance`. Package cleanup is not a prerequisite.

## Flow
```
collect (unchanged)
  -> ingest      pipeline/nodes/ingest.py   prescreen 'metadata' skip -> no fetch, no model (existing)
                                            fetch full ad; adtext 'gone' -> ARCHIVED reason posting_closed
  -> extract     pipeline/nodes/extract.py  one structured call (existing)
  -> evaluate    pipeline/nodes/evaluate.py one structured call, score 1.0-5.0 (existing)
  -> gate        pipeline/nodes/gate.py     canonical eligibility: eligible|held|excluded (existing)
  -> shortlist       pipeline/screened.py   gate routes 'draft'/'review' -> SHORTLISTED (not DRAFT_QUEUED)
  -> promote         pipeline/screened.py   category priority, then score/newest ID -> bounded evaluation
```
The canonical `pipeline/agentic/service.py` batch entry point receives an explicit ID list.
Promotion explicitly requests `operation='evaluate'`; it does not prepare
packages. The callback records actual starts, so skipped work consumes no
promotion allowance. Held evaluations remain distinct from completed evaluations
and application readiness. Existing shortlisted jobs may be promoted before the
next graph pass to preserve their assessment time budget.

## Decisions
1. **Separate mode, not a rewrite.** `screened` exists beside
   `off|reader|pipeline|agentic` in `jobwatch/execution_mode.py`. Runtime rollback
   must preserve the actual prior revision/settings; a source config edit alone
   does not prove containment or service reload.
2. **Reuse the graph, stop before drafting.** `ScreenedGraph` overrides graph
   edges and routes gate `draft` and `review` to SHORTLISTED, and `archive` to
   ARCHIVED. Canonical holds still block invalid assessment/preparation; the route
   does not turn review into eligibility. Drafting/form mapping require separate
   selected preparation and are not part of automatic promotion.
3. **Promotion limits and ranking.** Defaults under `pipeline.screened` are
   `promote_per_run: 3` and `promote_per_day: 10`. Eligible categories with promotion
   enabled rank by category priority, then descending score and newest posting ID.
   `min_score: 3.0` remains readable for compatibility but is not a hard cutoff.
   Count actual started postings, exclude recent promotions, and do not charge
   skipped dispatches against the allowance.
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
- Historical `min_score` configuration can suggest a hard threshold where none
  applies. Explain category priority and advisory scores instead of treating a
  low score as an authorized exclusion.
- Source wiring and repository defaults do not prove the effective runtime mode,
  provider acceptance or loaded service revision. Current release evidence and
  separate authorization are required; keep unverified assessment off.
