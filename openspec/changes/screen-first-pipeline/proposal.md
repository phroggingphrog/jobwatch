# Proposal: screen-first pipeline

## Why
The `agentic` execution mode sends every collected posting through a multi-turn agent with snapshot hashes, per-job
token/turn/time ceilings and exact-citation checks. Measured 2026-10-31 on the live data directory: 423 agentic runs,
0 ready, 404 held (`snapshot_changed` 183, `token_limit` 82, `turn_limit` 22, `deadline_exceeded` 19,
`daily_budget` 24). The retained deterministic `pipeline` mode reached READY on real jobs with a 6.4% dead-letter rate.
Ad-fetch failure is the same in both (14% vs 16%), so the regression is in evaluation, not reading.

Search queries are also built from free-text `career_focus` evidence (`jobwatch/candidate/policy.py:282`,
`jobwatch/occupations/plan.py:46`), so boards receive sentences instead of job titles and some return HTTP 403.

Owner direction (verbatim, 2026-10-31): "What i aim is to have a filter first fetch the ad first by title, like the
career ops? so basically old pipeline leaning into career ops?"

## What changes
- New execution mode `screened`: cheap deterministic steps first, the agent last and only for the few best postings.
  Order: title/metadata prescreen → liveness + full-ad fetch → one structured read (extract) → one structured score
  (evaluate) → canonical eligibility gate → agentic evaluation for the top N gate-passed postings only.
- Search queries use job titles only. Free-text focus items that are not title-shaped are not sent to boards.
- Transport-class dead letters are re-queued once automatically.
- A read-only "dropped by title" list (CLI and board) shows what the prescreen skipped in the last 7 days.

## Non-goals
- No change to collectors, dedupe, ad fetching, the agentic evaluator's internal checks, drafting or submission.
- No new service, timer, port, database or data copy.
- No candidate facts, target roles or locations in this repository.

## Rollback
Set `pipeline.execution_mode: agentic` in `config/jobwatch.yaml` (one line) and restart nothing: the next timer run
uses the old mode. Code for `screened` stays inert when not selected.
