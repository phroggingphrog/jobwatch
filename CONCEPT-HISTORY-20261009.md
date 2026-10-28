# jobwatch / job tracker: the full concept history (2026-10-09)

Sources: Hindsight work memory (bank "work", supervisor logs 2026-09-29..10-01), ~/brain/WHAT-HAPPENED.md,
GOAL_CONTRACT.md, TRACK.md, ~/brain/wiki/threads/jobwatch.md. Newest owner statement wins (GOAL_CONTRACT rule).

## 1. The original concept: "automated-career-ops" (29 Sep – 1 Oct) — AGENTIC

An agent fleet, not a script:
- **Agents (ZeroClaw "career fleet")**, each with its own OmniRoute role combo chosen by the owner (primary + 2 fallbacks):
  `career-router`, `career-eligibility`, `career-evaluator`, `career-writer`, `career-prefill`, `career-tracker`
  (+ runner roles: eligibility, feature extraction, browser prefill, triage). Map: `AGENT-MAP.md` / `ROUTES.md`.
- **Wiring:** agents → `career-mcp` (Rust MCP, tool `careerops_op`, per-role tool lists) → runner `/worker/careerops/<op>` (job-tools).
- **Plan steps 0–13** (owner-specified), incl.:
  - candidate analysis FIRST (career-potential plan v2): derive archetypes from the candidate, don't hand-set targets; map evidence to O*NET DWAs; O*NET/SOC→ANZSCO crosswalk, transferable skills, GWA ratings;
  - behavioural profiling (step 7), causal analysis (8), transferable-skills analysis (11);
  - **choice sets** sent to the owner by iMessage twice a day to learn preferences (choice model after 30 answers);
  - outcome model + application_outcomes table, knapsack portfolio, ranking v2, weekly job-market digest;
  - golden set (122 cases), shadow evaluations before cutover, career-judge (Opus → Sol) as independent judge.
- **Job tracker:** forked from Muatasim-Aswad/job-tracker; tracker.db (schema V11), `career-dashboard` (:8766).
  Crawler over 606 employers from Workopia (career sites, ATS, graduate pages); exclusions shown as **flags, not filters**;
  switchable professional/casual profiles; company research later.
- **Applying:** writer drafts CV/letter; prefill agent fills forms in an isolated **stealth browser** (CloakBrowser primary,
  invisible_playwright_mcp fallback, own persistent profile, cloak shim in `~/workspace/self-hosted-web-mcp/egress-proxy/cloak/`).
  **Agents never submit; the owner clicks Submit.**
- **Control:** "everything now in Paperclip" (30 Sep): supervised jobs ran as Paperclip issues (PHR-16..19). Later
  (1 Oct): tracker to be published on GitHub, Paperclip only an optional, swappable control panel.
- State 1 Oct: deployed at 60–70% with owner go; readiness 4 green / 6 red; missed the 1 Oct 08:00 deadline after Claude limits.

## 2. 4 Oct: fresh start — all of it archived
Old code/data: Drive `hermes-gdrive:phrogvps-archive-20261008/job-system-20261004.tar`, `job-data-20261004.tar`. Nothing runs.

## 3. 5–6 Oct: jobwatch rebuilt as a small watcher (the first drift)
Claude Code wrote PLAN.md with defaults D1/D11: **no LLM, no candidate profile**, keyword titles. Owner corrected it
(6 Oct, escalating): "basically automated career-ops" → AI reads the whole ad against `career_ops_profile.md` + CV.

## 4. 7 Oct: AI reader v5 on every run; κ 0.38 vs career-ops; owner labels to decide tuning.

## 5. 8 Oct: "Refactor automated-career-ops into a Deterministic State Pipeline" (the second drift)
Logged as an owner spec (WHAT-HAPPENED 2026-10-08 ~04:30; Hindsight: "LLMs used exclusively as schema-validated
transformation nodes ... without conversational loops"). Built as `pipeline/` (BUI-97/98): hardcoded edges, one fixed
prompt per node, strict schemas, drafts capped 10/day. ON since 8 Oct 10:14. **This is why drafts look like templates:**
no agent reads, researches, plans or revises; each node is a single fixed call.

## 6. 9 Oct (now): owner — "the original concept meant to use an agentic system"
Newest statement → wins. BUI-196 (Builder, high, started) rebuilds evaluation, research, drafting and apply-prep as agents;
collectors stay deterministic. Things from §1 that are NOT in jobwatch today and should be considered in BUI-196:
1. Role agents (evaluator, writer, prefill, tracker) with their own model chains and tools.
2. Candidate analysis first (derived archetypes, O*NET/ANZSCO, transferable skills) instead of hand-set targets.
3. Learning from the owner: iMessage choice sets → preference model; outcome model.
4. Independent judge + golden set + shadow runs before cutover.
5. Stealth-browser prefill (CloakBrowser) with an isolated profile.
6. Company research.
7. Note the 5 Oct owner decision that overrides §1: customer service and hospitality are NOT targets.
