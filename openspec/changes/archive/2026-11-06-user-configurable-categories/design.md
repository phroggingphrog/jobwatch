# Design

## Context

`tracks.py` injects `PROGRAM_WORDS` and has a fixed `ORDER`. `title_triage.py` fixes both the model schema and prompt taxonomy. `nodes/ingest.py` selects ordering and actions by category ID; `screened.py` selects promotion order and eligibility by ID; `nodes/gate.py` grants the undergraduate hours exception by ID. See the proposal and regression issue #58.

## Goals / Non-Goals

Goals: per-user goal-to-research-to-config-to-query workflow; replaceable taxonomy; explicit policy; preserve existing decisions; isolate users.

Non-goals: add or enable collectors, alter TASK-447, infer personal restrictions, run research against live candidate data during planning, deploy, or change live configuration.

## Decisions

1. Version a per-user configuration containing goals, category IDs and labels, ordered priority, phrases, routing action, promotion eligibility and explicit hours treatment. Validate unique IDs and references before activation. Classification returns an ID or unassigned. Runtime code reads behavior fields, never specific IDs. Unassigned is neutral unless an explicit user policy says otherwise. A configuration-driven output schema contains valid IDs and a neutral unsure result; generated prompt descriptions use only that user's data.
2. Research uses relevant existing website access capabilities to derive discovery suggestions and source-specific query vocabulary. Each suggestion retains source URL, retrieval date, goal/input version, and suggestion provenance. Persist explicit user constraints and corrections separately; merge them deterministically above suggestions. A goal change queues a refresh and retains prior active configuration until a validated replacement is available. Failure preserves the previous version and exposes an actionable error. This is vocabulary research, not permission to enable a collector. Do not transmit candidate or sensitive data beyond the minimum goals authorized for research.
3. Publish a stable category interface to TASK-447: a validated per-user snapshot supplies IDs, labels, priority and actions; consumers treat IDs as opaque. Coordinate integration with the parent and do not modify the other worktree.
4. Model title fallback uses only configured IDs and returns unsure on errors. No model output may invent eligibility or exclusions. Current approved gate protections stay intact, including a migrated explicit hours exception; no new hours policy is invented. Preserve all unrelated gates.

Alternatives rejected: category-name switches cannot support renaming; built-in generic words are hidden user-specific defaults; inferred exclusions can silently reject suitable jobs; changing collectors conflates research and collection authorization.

## Advisory decision rewrite

The owner approved a broader rewrite and removal of blocking product audit safeguards. Candidate intent separates goals/preferences, explicit constraints and factual work rights. A shared assessment record separates fit, conflicts, unknowns and technical errors. Low fit and goal relevance do not authorize archival. Category archival requires explicit confirmed exclusion authority.

Short nonempty ads can enter evaluation with a completeness warning. Citation and advertisement provenance gaps become advisory findings. Expected runtime identity, evidence-bundle identity, injection protection, authentication, per-user isolation, spending and submission approval remain security boundaries. Invalid model output produces a separate safe partial record without invented facts or scores.

Bounded reconsideration restores open goal-only archives and stale category-only decisions. It preserves history and explicit conflicts. Research expansion preserves approved location templates. Stable-revision regression and full-suite evidence precede release claims.

## Risks / Trade-offs

- Research can be stale or fail: version sources, retain the last active snapshot, and surface failures.
- Renames can strand stored IDs: plan explicit ID mappings and retain old snapshots for queued jobs; test in-flight migration.
- A broad research term can change discovery volume: separate discovery terms from negative filters and log provenance without exposing personal data.
- Legacy hours behavior may be subtle: characterize every current branch before migration; do not substitute guessed limits.

## Migration Plan

Before changes, capture sanitized golden fixtures for current explicit owner configuration and current code-derived words, category order, routing, promotion and exact hours behavior. Build a deterministic migration that writes those legacy decisions into a versioned per-user snapshot, including injected legacy vocabulary as data and the precise legacy exception, not new defaults. Validate and compare fixture outcomes, including existing in-flight jobs and stored track IDs, before activation. Back up configuration in the designated backup location, record the source revision and provide a reversible mapping and version restore procedure. Migration and activation require parent-controlled rollout; do not edit live config in this phase. Rollback restores the prior configuration version and compatible application revision and verifies queues and decisions. Never remove eligibility protections as a migration shortcut.
