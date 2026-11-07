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

## Current source status (2026-11-08)

The screened path is implemented in `main` at `0ea4fe0`, including dispatch,
shortlisting, retries, dropped-title views and evaluate-only promotion. The
original motivation below is historical evidence, not a new measurement or a
claim that implementation is pending. Current ranking follows approved category
priority, then score and newest ID; scores are advisory, not hard admission
cutoffs. Promotion allowance counts actual assessment starts, not skipped work.

This change supplies admission to the candidate-digest/native-assessment slice;
`native-assessment-acceptance` owns its follow-up acceptance evidence. Package
consolidation is independent. Repository defaults do not establish the loaded
configuration or revision of any running service. Acceptance and release tasks
remain open until supported by current evidence and separate authorization.

## Implemented scope
- New execution mode `screened`: cheap deterministic steps first, the agent last and only for the few best postings.
  Order: title/metadata prescreen → liveness + full-ad fetch → one structured read (extract) → one structured score
  (evaluate) → canonical eligibility gate → agentic evaluation for the top N gate-passed postings only.
- Search queries use job titles only. Free-text focus items that are not title-shaped are not sent to boards.
- Eligible transport-class dead letters are re-queued automatically within the existing attempt, age and per-run bounds.
- A read-only "dropped by title" list (CLI and board) shows what the prescreen skipped in the last 7 days.

## Non-goals
- No change to collectors, dedupe, ad fetching, the agentic evaluator's internal checks, drafting or submission.
- No new service, timer, port, database or data copy.
- No candidate facts, target roles or locations in this repository.

## Rollback and containment

Follow current `INTENT.md`: source reconciliation does not authorize deployment,
paid assessment or timer activation. Keep assessment off where acceptance is
unverified. Any authorized release must preserve the effective runtime settings,
exact prior revision, approvals and new records, and verify its actual rollback
path. Switching to standalone `agentic` is not an accepted substitute for the
screened/native slice or proof of a safe runtime rollback.
