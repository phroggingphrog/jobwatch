# Cross-plan contract for phases 2–7

Each roadmap plan is written and executed separately, so the names one plan produces and the next consumes
are fixed here. A plan may add internals freely; it may not rename, retype or drop anything below without a
ruling recorded in its own ledger and an edit to this file in the same pull request.

Spec: [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md). Order and scope:
[roadmap](2026-10-21-backend-roadmap.md). Code references: [code map](reference/2026-10-21-codemap.md)
(line numbers as of commit `ce9e342`; verify before editing).

## Rules every plan follows

1. **No silent re-evaluation.** `RunKey` (`pipeline/agentic/service.py` `_run_key`) hashes `_config()`, the
   policy, `IMPLEMENTATION_VERSION` and the location reference. A plan that changes any of these must say so in a
   task, state the expected paid re-run cost (jobs × three model roles), and gate the change behind a
   `pipeline.agentic.*` config flag that defaults to the old behaviour until the owner turns it on.
2. **Gate source is versioned.** Plan 6a introduces `GATE_VERSION` (sha256 over the gate's source files). Every
   later plan that changes gate behaviour bumps nothing by hand; the hash changes on its own and is stored with
   every recorded route.
3. **Profile reads come from the approved version.** New policy, labels and rules read
   `intake.current_version(person)` (approved.json facts with basis and sources), never `profile.yaml` or
   `interests_and_criteria.yaml` directly. Existing readers keep working until each plan migrates them.
4. **Schema changes are additive.** Stored models are strict and hashed. New fields get defaults and
   historical-omitting serialisers. New tables are added as the next `jobwatch/db.py` migration (13, 14, …) or
   with the lazy `ensure()` pattern, never both for the same table.
5. **Preference files are frozen.** Editing any of the five files that `jobwatch/preferences/features.versions()`
   hashes invalidates every answered set. Plan 4 does it once, behind an explicit re-featurisation migration.
   No other plan touches those files.
6. **Paid calls only on approved routes**, through `PaidGatewayEmbeddings` / `jobwatch.llm.LLM` with
   `require_route`; tests use synthetic transports (`tests/test_agentic_service.py` `SyntheticGateway`).
7. **Person-first.** Everything new is per person (`users.current()`), under `users.user_dir(person)` with
   0600/0700, written through `apply.paths.safe_write_bytes/ensure_dir`.
8. **Human-only decisions.** Any write that records a choice, rule, selection or approval takes
   `actor: Literal['person']` set server-side and is reachable only from an `approve`/`interact` scope, a human
   web action, or a gated chat interrupt. Model output never fills these.

## Reconciled decisions (2026-10-21, after the six plans were drafted)

These override the interface list below where they differ. Each plan has been edited to match.

1. **Pinned profile version.** `policy_for(person, *, approved: dict | None = None) -> DecisionPolicy | None`;
   `approved` is an `approved.json` payload (a baseline's frozen copy), defaulting to the current version.
   Plan 6a freezes `approved.json` and, when the policy path is active, the `DecisionPolicy` JSON.
2. **One live gate call.** Plan 2 creates `pipeline.agentic.service.gate_current(evaluation, *, posting, ad_text,
   decision_policy, ...) -> AgenticGateDecision`; every gate caller (live run, shortlist, preference pool, rules,
   replay) goes through it. `decide()` takes the new policy as keyword `decision_policy` (the existing `policy`
   parameter is the run-key `TargetPolicy`) and a `company` keyword.
3. **Flag for the profile policy.** `pipeline.agentic.decision_policy: legacy | profile`, default `legacy`. The
   owner-specific checks move into `_legacy_person_checks` and are deleted in a follow-up after the owner switches
   to `profile`. Exclusion rules take effect immediately only with `profile`.
4. **Run key stays stable.** `DecisionPolicy` fields (`exclusions`, `profile_version`, `policy_hash`,
   `open_questions`) never enter `RunKey.config_hash`. Plan 2 tests it; Plan 5 keeps a regression test.
5. **Gate version.** `GATE_VERSION` hashes `gate.py`, `location.py`, `jobwatch/candidate/person.py`, the work-rights
   regex module, `jobwatch/candidate/contracts.py`, `jobwatch/candidate/policy.py` (when present) and the location
   data JSON files; each file's hash is also listed in `Baseline.gate_dependencies`. Routes are not stored live
   today, so the version is recorded once per baseline, where all routes are recomputed together.
6. **Exclusion facts to rules.** Plan 2 turns an `exclusion` fact whose value is `{"kind": <ExclusionRule kind>,
   "value": <text>}` into an `ExclusionRule` with `source_fact_id`; a free-text exclusion stays prompt text and adds
   the open question `exclusion:<fact_id>` asking the person which kind it is. Plan 2 also removes or parametrises
   `MINIMUM_EXCLUDED_CODES`.
7. **Relevance is stored.** Plan 3 writes every `RelevanceJudgment` to table `posting_relevance` and exposes
   `discovery.latest_judgment(conn, posting_id) -> RelevanceJudgment | None`; Plans 4 and 6b read it.
   `RelevanceJudgment` gains `method`, `ad_hash`, `plan_hash`. Plan 3 also exposes
   `discovery.enforce_exclusions(conn, config, *, person=None)` for Plan 5.
8. **Plan 3 flags.** `pipeline.agentic.relevance: off | shadow | on` (default `shadow`: judged and stored, nothing
   archived), `dedupe: legacy | semantic` and `ordering: legacy | hypotheses` (defaults `legacy`).
9. **Reference data location.** `users.base_dir()/reference/<dataset>/<version>/` (shared, public, outside Git),
   with the bundled test fixtures in the repository.
10. **Ranking modules.** `pipeline/agentic/ranking.py` is pure: `IMPORTANCE_WEIGHTS`, `Coverage`, `coverage`,
    `label_for(coverage, relevance, policy, *, held: bool = False)`, `Scored`, `Ranked`,
    `rank_candidates(scored) -> list[Ranked]`, `explain`. `pipeline/agentic/shortlist.py` holds
    `build_shortlist(conn, config)` (database only; re-decides stored evaluations through `gate_current` under
    `policy_for(person)`), `record_impressions` and `latest_entries(conn)`. `shortlist_api.py` holds the read
    routes; Plan 5's routes live in `pipeline/agentic/feedback_api.py` on the paths below.
11. **Re-queue starvation.** Plan 4 stops `after_collect` from re-queueing `held / evaluation_complete` jobs unless
    their snapshot changed or liveness is stale, because the shortlist re-decides them from stored data.
12. **Preference features.** `automation_angle` has no defined source and is retired; `status_held` is added.
    `preference_picks.actor` stays `'owner'` (immutable schema); the feedback event log records `person`.
13. **Labels and usage (Plan 6a owns them).** `read_labels(baseline_id) -> list[OwnerLabel]`,
    `write_label(baseline_id, label)` (human CLI only), `FrozenCase.usage` keys `charged_tokens`, `actual_tokens`,
    `latency_seconds`, and `evidence.bundle_from_contents(contents) -> EvidenceBundle`.
14. **Signature additions.** `next_comparison(conn, person, config=None)`; `replay(..., llm=None, config=None,
    stages=None)`; `SearchPlan.queries` keyed by `searches.yaml` section (`seek`, `jora`, `jobspy`).
15. **Migrations.** Each plan takes the next free `jobwatch/db.py` `MIGRATIONS` index at execution time.
16. **`location_fit`.** Stored evaluations say `'melbourne'` because the first model pass never sees the
    candidate. No plan relies on it meaning "home region"; Plan 2 recomputes the region from the verified quote.

## Interfaces by plan

### Phase 2 — Plan 6a: frozen baseline (`pipeline/agentic/baseline.py`)

- `GATE_VERSION: str` — sha256 over `pipeline/agentic/gate.py`, `pipeline/agentic/location.py`,
  `jobwatch/candidate/person.py` and the work-rights regexes' module.
- `class FrozenCase(StrictFrozen)`: `case_id: str`, `posting_id: int`, `group_id: str`, `tags: tuple[str, ...]`,
  `snapshot: dict` (the `snapshot` artifact), `structural_inputs: dict`, `evaluation: dict` (AE JSON),
  `candidate: dict | None`, `model_insights: dict | None`, `decision: dict` (`AgenticGateDecision` JSON recomputed
  under the pinned profile), `commute_km: float | None`, `usage: dict` (charged/actual tokens, latency seconds).
- `class Baseline(StrictFrozen)`: `baseline_id: str`, `created_at: str`, `git_commit: str`, `gate_version: str`,
  `implementation_version: str`, `matching_version: str`, `profile_version: int`, `profile_files_sha256: dict[str, str]`,
  `case_ids: tuple[str, ...]`.
- `freeze_baseline(conn, config, *, posting_ids: list[int] | None = None, limit: int = 500) -> Baseline` — reads
  stored artifacts only (no model calls), copies the profile files into the baseline folder, writes
  `users.user_dir(person)/baselines/<baseline_id>/{baseline.json, profile/, cases/<case_id>.json}`.
- `load_baseline(baseline_id) -> tuple[Baseline, list[FrozenCase]]`; `pinned_profile(baseline_id)` context manager
  that points the profile readers at the frozen copy.
- `TAGS = ('previously_rejected', 'transferable_skills', 'unknown_facts', 'misleading_title', 'stretch', 'explicit_exclusion')`
  — deterministic tagger `tag_case(case) -> tuple[str, ...]`; owner tags are added through labels.
- `group_id` = `content:<ad hash>` merged with `employer:<normalised company>` clusters (union-find), so duplicate
  adverts and related employers share a group.
- `class OwnerLabel(StrictFrozen)`: `case_id`, `actor: Literal['owner']`, `suitable: bool | None`,
  `relevance: int | None` (0–3), `exclusion_violation: bool | None`, `note: str = ''`, `labelled_at`. Stored as
  `baselines/<id>/labels.jsonl`; written only by a human CLI/web action.
- CLI: `jobwatch baseline freeze [--limit N]`, `jobwatch baseline list`, `jobwatch baseline show <id>`.

### Phase 3 — Plan 2: decision policy (`jobwatch/candidate/policy.py`)

- `class ExclusionRule(StrictFrozen)`: `rule_id`, `kind: Literal['family', 'employer', 'title_term', 'location', 'work_type']`,
  `value: str`, `source_fact_id: str | None`, `actor: Literal['person']`.
- `class DecisionPolicy(StrictFrozen)`: `profile_version: int`, `strategy: Literal['employment_first', 'career_focus', 'balanced']`,
  `focus: tuple[str, ...]`, `exclusions: tuple[ExclusionRule, ...]`, `home: dict | None` (place, state, country),
  `max_commute_km: float | None`, `remote_ok: bool | None`, `work_rights: dict` (hours_limit_per_fortnight,
  full_time_programs_ok, visa terms), `seniority: tuple[str, ...]`, `open_questions: tuple[str, ...]`,
  `policy_hash: str`.
- `policy_for(person) -> DecisionPolicy | None` (None when there is no confirmed scope-bearing version);
  `strategy_for(facts) -> str` implements the brief's search rules (unemployed and no contrary instruction →
  employment_first; explicit career/degree focus → career_focus; exclusions always apply; missing material
  information → an open question, never a silent failure).
- Gate change: `decide(..., policy: DecisionPolicy)` replaces the hard-coded constants and live profile reads;
  person-specific code listed in code map §2.1 is removed. Genuine eligibility (work rights, hours limits) stays.
- Profile API addition: `GET /api/agent/profile/policy` (read) returns the policy and its open questions.

### Phase 4 — Plan 3: field and job discovery (`jobwatch/occupations/`, `pipeline/agentic/discovery.py`)

- Reference data under `data/reference/<dataset>/<version>/` with `manifest.json`
  (`dataset`, `version`, `source_url`, `licence`, `retrieved_at`, `sha256` per file). Datasets: O*NET, ESCO,
  ANZSCO 2022 / OSCA (and any correspondence found; investigation recorded in an ADR).
- `class FieldHypothesis(StrictFrozen)`: `scheme`, `code`, `title`, `similarity: float`,
  `supporting_facts: tuple[str, ...]` (approved fact ids), `rationale: str`, `is_qualification_proof: Literal[False]`.
- `field_hypotheses(person, *, limit: int = 15) -> tuple[FieldHypothesis, ...]`, cached per profile version and
  dataset version.
- `class SearchPlan(StrictFrozen)`: `profile_version`, `policy_hash`, `queries: dict[str, tuple[str, ...]]`
  (collector → queries), `locations: tuple[str, ...]`, `hypotheses: tuple[str, ...]`, `plan_hash`.
  `search_plan(policy, hypotheses) -> SearchPlan`; collectors read it in agentic mode instead of owner-specific
  `searches.yaml`, which stays as the legacy fallback.
- `class RelevanceJudgment(StrictFrozen)`: `posting_id`, `relevant: Literal['yes', 'no', 'uncertain']`,
  `quotes: tuple[str, ...]` (verbatim from title or full ad), `similarity: float`, `matched_hypotheses`,
  `reason: str`. `judge_relevance(posting, ad_text, policy, hypotheses) -> RelevanceJudgment`. Title keywords
  become a recall-only pre-screen; `relevant='no'` archives with reason `not_relevant`; `uncertain` proceeds.
- Semantic dedupe and `_target_first` move to `PaidGatewayEmbeddings`; `openrouter_extras.embed` leaves the timer path.

### Phase 5 — Plan 4: ranking and explained shortlist (`pipeline/agentic/ranking.py`, `pipeline/agentic/shortlist_api.py`)

- `IMPORTANCE_WEIGHTS = {'critical': 4, 'high': 3, 'meaningful': 2, 'preferred': 1, 'low_signal': 0}` (documented,
  not fitted). `class Coverage(StrictFrozen)`: `weighted: float`, `demonstrated`, `partial`, `unknown`,
  `contradicted` (counts), `mandatory_unmet: tuple[str, ...]`, `missing_documentation: tuple[str, ...]`,
  `real_gaps: tuple[str, ...]`, `conflicts: tuple[str, ...]`. `coverage(evaluation) -> Coverage`.
- `Label = Literal['stronger_match', 'stretch', 'needs_clarification']`; `label_for(coverage, relevance, policy) -> Label`
  using the cold-start rules written in `docs/ranking-rules.md`.
- `class ShortlistEntry(StrictFrozen)`: `entry_id`, `posting_id`, `run_key`, `profile_version`, `label`, `rank: int`,
  `rank_reason: str`, `ordering: Literal['provisional', 'personalised']`, `uncertainty: str`, `evidence: tuple[dict, ...]`
  (citations), `transferable_skills`, `objective_fit: str`, `conditions: tuple[str, ...]`,
  `mandatory_requirements: tuple[str, ...]`, `unresolved: tuple[str, ...]`, `holistic_score: float | None` (baseline,
  display only), `created_at`.
- Tables (migration): `shortlist_entries` (entry fields + `shortlist_id`), `shortlist_impressions(shortlist_id,
  entry_id, posting_id, rank, ordering, probability, shown_at, surface)`.
- `build_shortlist(conn, config) -> list[ShortlistEntry]` runs after `after_collect`; `record_impressions(conn, entries, surface)`.
- API: `GET /api/agent/shortlist` and `GET /api/agent/shortlist/{posting_id}` (scope `read`).
- Holistic score never excludes on its own; `north_star < 3` no longer archives an employment-first job.
- Preference model: re-featurisation migration, wider family vocabulary, the eight never-filled features filled
  from their sources, held/archived jobs eligible for the pool with a status feature; personalised ordering only when
  `PreferenceStore.status() == 'valid'`, otherwise `ordering='provisional'`.

### Phase 6 — Plan 5: feedback and selection (`pipeline/agentic/feedback.py`, extends `shortlist_api.py`)

- Table `feedback_events(id, posting_id, entry_id, kind, reason_code, reason_text, actor, source, created_at)` with
  `kind: Literal['reject', 'select', 'exclude', 'comparison', 'answer']`, `actor: Literal['person']`,
  `reason_code` from `REJECTION_REASONS` (defined in this plan; `other` keeps the person's words verbatim).
- Explicit exclusions become `ExclusionRule`s through a digest-bound confirmation (`POST
  /api/agent/profile/rules` → confirmation → `approve`), recorded as a profile amendment version; the gate and
  the discovery pre-filter enforce them at once after confirmation.
- `next_comparison(conn, person) -> Comparison | None` by expected information gain over posterior draws when the
  fit is valid; the documented cold-start rule otherwise; rate-limited.
- API: `POST /api/agent/shortlist/{posting_id}/feedback` (scope `interact`), `POST
  /api/agent/shortlist/selection` with `{'posting_ids': [...], 'expected_run_keys': {...}}` (scope `approve`) →
  enqueues `operation='prepare'` for each with a server-built approval binding; never a model's choice.

### Phase 7 — Plan 6b: evaluation and monitoring (`pipeline/agentic/evaluate_runs.py`, `jobwatch/reports/`)

- `replay(baseline_id, arm: Literal['baseline', 'revised'], *, paid: bool = False, budget_tokens: int = 0) -> ArmResult`
  — `baseline` reads frozen outputs; `revised` re-runs gate, relevance, coverage and ranking on frozen inputs
  offline, and re-runs model roles only when `paid=True` within `budget_tokens`.
- `split(cases, *, holdout_fraction=0.3, seed) -> dict[str, list[str]]` grouped by `group_id`; development vs
  untouched holdout recorded once per baseline and never reassigned.
- Metrics: missed suitable jobs, unsupported qualification claims, precision@k and nDCG on owner labels,
  exclusion violations, uncertainty handling, tokens/cost, latency. Missing labels reported as
  `owner_labels_required`, never imputed.
- Reports under `users.user_dir(person)/reports/<report_id>.{json,md}` with code and data hashes; no candidate quotes
  in aggregates.
- CI: full suite on push/PR in `.github/workflows/backend.yml`, R/JAGS installed for the sampler test.
