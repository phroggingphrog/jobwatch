# Plan 6b: Evaluation and monitoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay the frozen baseline through the baseline and the revised pipeline, measure the brief's criteria on leakage-safe development and untouched holdout splits against explicit owner labels, and produce reproducible private reports, bounded automated comparisons, eligible local model fits and a full-suite CI job, without claiming improvement the evidence does not show.

**Architecture:** `pipeline/agentic/eval_data.py` owns owner labels, the leakage audit and the write-once grouped split. `pipeline/agentic/evaluate_runs.py` owns `replay` (baseline arm = frozen outputs; revised arm = Plans 2–4 deterministic stages on frozen inputs through one injectable `RevisedStages` seam; optional paid re-run of the model roles). `pipeline/agentic/eval_metrics.py` is pure metric code. `jobwatch/reports/` builds hashed private reports and runs the bounded monitor. `jobwatch evaluate ...` is the CLI. No schema change, no run-key change, no timer.

**Tech Stack:** Python 3.12, pydantic v2 `StrictFrozen` models, SQLite (read-only here), existing `PreferenceStore`/`fit_store` (R/JAGS), pytest, GitHub Actions.

**Spec:** [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md) section A.5 and the B directions; [roadmap](2026-10-21-backend-roadmap.md) row 6b; [contract](2026-10-21-cross-plan-contract.md) "Phase 7". Method: `pipeline/agentic/MATCHING.md` "Remaining experiment before policy promotion".

## Global Constraints

- Synthetic data only. Never use live candidate records, the owner's `baselines/` or `profile/` as fixtures (AGENTS.md).
- Per-person isolation: everything lives under `users.user_dir(person)` (`baselines/<id>/`, `reports/`), 0700 dirs and 0600 files through `apply.paths.ensure_dir/safe_write_bytes`; person is `users.current()`, never an argument from a client.
- Paid model calls only on approved routes: `service.configured_llm(config)` plus `execution.require_route(llm, model)` (`embedding=True` for the embedding model); tests use synthetic transports (`tests/test_agentic_service.py` `SyntheticGateway` pattern, `LLM(transport=..., keys=['synthetic'], base_url=model_choice.SERVER_URL)`). Paid replay is only ever reached from an explicit `--paid --budget-tokens N` on the CLI; the monitor and every default path make zero model calls.
- No service or timer activation; no new file under `systemd/`. No submission, no employer contact; this plan never imports `jobwatch/apply/submit_confirm.py` or `openrouter_extras`.
- Model output is never recorded as a person's choice or approval. Owner labels (`actor='owner'`) are written only by the interactive `jobwatch evaluate label` command (refuses without a terminal). Model self-grades and synthetic checks establish nothing about recommendation quality.
- Schema changes additive. This plan adds no table, migration, config key read by `service._config`, or change to `RunKey`, `IMPLEMENTATION_VERSION`, the policy, the gate or any stored model. Therefore no run key changes and no paid re-evaluation of stored jobs (contract rule 1).
- Do not edit the five files `jobwatch/preferences/features.py|store.py|model.py|fit_choice_model.R|choice_model.jags` (contract rule 5).
- Reports contain counts, ids, hashes and rates only: no candidate quotes, no ad text, no evidence text.
- The revised arm offline always uses `ordering='provisional'`. A personalised (fitted) ordering is never evaluated on cases that may have trained it; fit quality is reported only through the fit's own held-out gate (`evaluate_fit`).
- Python 3.12 venv outside the repo: `uv venv --python 3.12 <scratch>/venv && uv pip install --python <scratch>/venv/bin/python -e '.[dev]'`. Test command: `<venv>/bin/python -m pytest -q -p no:cacheprovider <paths>`.

## Review Focus

1. Duplicate adverts or related employers on both sides of the split (a 6a grouping bug): `record_split` refuses with `split_leakage` instead of producing an optimistic holdout. (Task 2)
2. Missing or too few owner labels: every label-based metric reads `owner_labels_required`, nothing is imputed, and a holdout with fewer than 10 labelled cases makes the report status `owner_holdout_labels_required`. (Tasks 5, 6)
3. The live profile changed after the baseline was frozen: the revised arm still evaluates under the frozen profile version and copy. (Task 3)
4. Paid replay with no budget, a non-approved gateway, or a budget that runs out midway: refuses before any call, or stops with the rest marked `not_replayed`, with no write to the production database or `agentic/` artifacts. (Task 4)
5. Peeking at the holdout: a second holdout report for different code is recorded and flagged, not hidden. (Task 6)

---

### Task 1: Record the design (ADR and glossary)

**Files:**
- Create: `docs/adr/NNNN-evaluation-and-monitoring.md` (next free number at execution time; `ls docs/adr`)
- Modify: `GLOSSARY.md` (add only terms not already present: Arm, Owner label, Development set, Holdout set, Evaluation report, Monitor run; if Plan 6a did not add it, also Frozen baseline)

- [ ] **Step 1:** Write the ADR (Context, Status Accepted owner direction, Decision, Consequences, references to brief A.5). Decisions it must record, each as its own bullet:
  - Arms: `baseline` = frozen outputs (shortlisted iff frozen gate route is `draft`, ordered by holistic score desc then posting id); `revised` = frozen inputs through Plan 2 policy, gate, Plan 4 coverage/label/ordering, never new model output unless `paid`.
  - Revised offline ordering is `provisional`; personalised ordering is not evaluated offline (training leakage).
  - Metric definitions exactly as in Task 5 (missed suitable, suitable held, unsupported claims, ordering via condensed list, exclusion violations, uncertainty handling, cost, latency) and `MIN_LABELS = 10`, `K_VALUES = (5, 10)`.
  - Split: grouped by `FrozenCase.group_id`, seeded, 30% holdout, written once per baseline; holdout reports are aggregate-only, logged, and flagged when read again for different code.
  - Relevance is not replayed (a placeholder `uncertain` with note `relevance_not_replayed`) because `judge_relevance` is Plan 3's own live paid step.
  - Reports hash code and data; cost is tokens (no price table, no currency); no improvement is claimed from descriptive counts.
  - CI: one full-suite job on push and pull request with R/JAGS installed; the synthetic-backend job stays as the fast gate.
- [ ] **Step 2:** Add the glossary rows (one sentence each; "Holdout set: baseline cases never used to tune anything; read at most once per code version").
- [ ] **Step 3: Commit** `docs: ADR NNNN evaluation and monitoring design`.

### Task 2: Owner labels, leakage audit and the write-once grouped split

**Files:**
- Create: `pipeline/agentic/eval_data.py`
- Test: `tests/test_eval_data.py`; Create: `tests/evaluation_helpers.py` (synthetic baseline builder, see Step 1)

**Interfaces:**
- Consumes (Plan 6a, `pipeline/agentic/baseline.py`): `FrozenCase`, `OwnerLabel`, `Baseline`, `load_baseline(baseline_id) -> tuple[Baseline, list[FrozenCase]]`, `TAGS`. Baseline folder `users.user_dir(person)/baselines/<baseline_id>/`.
- Produces:
  - `MIN_LABELS = 10`, `DEFAULT_HOLDOUT_FRACTION = 0.3`
  - `class SplitRecord(StrictFrozen)`: `baseline_id: str`, `seed: int`, `holdout_fraction: float`, `development: tuple[str, ...]`, `holdout: tuple[str, ...]` (case ids, sorted), `created_at: str`
  - `read_labels(baseline_id: str) -> dict[str, OwnerLabel]` (last line per `case_id` wins; absent file -> `{}`; malformed line or `actor != 'owner'` -> `AgenticError('labels_invalid')`)
  - `write_label(baseline_id: str, label: OwnerLabel) -> None` (rewrites `labels.jsonl` atomically via `safe_write_bytes`; case id must exist in the baseline else `AgenticError('unknown_case')`)
  - `leakage_audit(cases: Sequence[FrozenCase]) -> list[str]` returning fixed codes `ad_hash_split_across_groups` and/or `employer_split_across_groups`
  - `split(cases: Sequence[FrozenCase], *, holdout_fraction: float = 0.3, seed: int) -> dict[str, list[str]]` with keys `development`, `holdout`
  - `record_split(baseline_id: str, *, holdout_fraction: float = 0.3, seed: int | None = None) -> SplitRecord` (seed default = first 8 hex digits of `sha256(baseline_id)` as int), `load_split(baseline_id) -> SplitRecord | None`, `tag_coverage(record: SplitRecord, cases) -> dict[str, dict[str, int]]`

- [ ] **Step 1: Write the failing tests.** First `tests/evaluation_helpers.py::make_baseline(tmp_path, monkeypatch, specs) -> str`: sets `JOBWATCH_DATA_DIR`, builds each case's evaluation with `build_case` + `evaluate_job` + `FakeModel` from `tests/test_agentic_evaluate.py` (match/score/ad variants), builds `FrozenCase` and `Baseline` models and writes them in the 6a layout (`baseline.json`, `profile/` with a synthetic `cv.md`, `cases/<case_id>.json`). If Plan 6a ships a test builder (`grep -rn "freeze_baseline\|def make_baseline" tests`), wrap it instead. `specs` rows: `case_id, group_id, tags, route, reason, score, match, company`. Then in `tests/test_eval_data.py`:

```python
def test_split_never_separates_a_group(): # 40 cases, 10 groups of sizes 1..7
    parts = split(cases, holdout_fraction=0.3, seed=7)
    assert set(parts['development']).isdisjoint(parts['holdout'])
    assert set(parts['development']) | set(parts['holdout']) == {c.case_id for c in cases}
    groups = {c.case_id: c.group_id for c in cases}
    assert {groups[i] for i in parts['development']}.isdisjoint({groups[i] for i in parts['holdout']})
    assert abs(len(parts['holdout']) - 12) <= 7            # the largest group

def test_split_is_deterministic_per_seed(): assert split(cases, seed=7) == split(cases, seed=7) and split(cases, seed=7) != split(cases, seed=8)
@pytest.mark.parametrize('f', [0, 1, -0.1, 1.5])
def test_split_rejects_bad_fraction(f): pytest.raises(ValueError, match='invalid_holdout_fraction')
def test_leakage_audit_flags_one_ad_hash_in_two_groups(): assert leakage_audit(cases) == ['ad_hash_split_across_groups']
def test_leakage_audit_flags_one_employer_in_two_groups(): assert leakage_audit(cases) == ['employer_split_across_groups']  # company normalised with jobwatch.dedupe._norm(company, _COMPANY_NOISE)
def test_record_split_is_write_once_and_idempotent():
    first = record_split(bid, seed=3)
    assert record_split(bid, seed=3) == first and load_split(bid) == first
    with pytest.raises(AgenticError, match='split_exists'): record_split(bid, seed=4)
    assert stat.S_IMODE((baseline_dir / 'split.json').stat().st_mode) == 0o600
def test_record_split_refuses_a_leaky_baseline(): pytest.raises(AgenticError, match='split_leakage')   # nothing written
def test_tag_coverage_lists_tags_missing_from_the_holdout(): assert cov['stretch'] == {'development': 4, 'holdout': 0}
def test_label_round_trip_last_label_wins_and_file_is_private()
def test_malformed_label_line_is_an_error_not_a_skip()    # 'labels_invalid'
def test_label_for_unknown_case_is_refused()               # 'unknown_case'
def test_another_person_cannot_read_labels_or_split():
    with users.use('mate'): pytest.raises(AgenticError)    # baseline not found for mate
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_eval_data.py` -> FAIL (module missing).
- [ ] **Step 3: Implement** `eval_data.py`. Split algorithm: unique `group_id`s ordered by `sha256(f'{seed}:{group_id}')`; take groups into the holdout in that order until holdout case count >= `round(holdout_fraction * n)`; never cut a group; both lists sorted. `record_split` runs `leakage_audit` first (non-empty -> `AgenticError('split_leakage')`), writes `split.json` with `O_EXCL` semantics (existing file with equal parameters returns the stored record; different parameters raise `split_exists`). Employer audit key: `_norm(company, _COMPANY_NOISE)` from `jobwatch/dedupe.py` applied to `snapshot['posting']['company']`; ad key: `snapshot['run_key']['ad_hash']`.
- [ ] **Step 4: Run** the test file -> PASS.
- [ ] **Step 5: Commit** `feat: owner labels, leakage audit and write-once grouped split for evaluation`.

### Task 3: Replay both arms offline

**Files:**
- Create: `pipeline/agentic/evaluate_runs.py`
- Modify: `jobwatch/candidate/evidence.py` (add `bundle_from_contents(contents: dict[str, bytes]) -> EvidenceBundle`, built exactly like the construction inside `snapshot_evidence`, which then calls it; only if `grep -rn "def bundle_from" jobwatch pipeline` finds nothing from Plan 6a)
- Test: `tests/test_evaluate_runs.py`, `tests/candidate/test_evidence_bundle_rebuild.py`

**Interfaces:**
- Consumes: Task 2; 6a `load_baseline`, `pinned_profile(baseline_id)`; Plan 2 `policy.policy_for`, `gate.decide(..., policy=DecisionPolicy)`; Plan 4 `ranking.coverage`, `ranking.label_for`, a pure ordering function (contract issue 2: `ranking.rank_candidates`); `candidate.assessment.verify_candidate_citations`; `runtime.validate_model_payload`.
- Produces:
  - `class ArmCase(StrictFrozen)`: `case_id, posting_id: int, group_id, tags: tuple[str, ...]`, `route: Literal['draft','archive','hold']`, `reason: str`, `shortlisted: bool`, `claims_qualified: bool`, `rank: int | None`, `label: str | None`, `ordering: Literal['holistic','provisional'] | None`, `relevance: Literal['yes','no','uncertain'] | None`, `coverage: dict[str, float | int]` (keys `weighted, demonstrated, partial, unknown, contradicted, mandatory_unmet, missing_documentation, real_gaps, conflicts`), `citation_failures: int`, `unresolved: int`, `uncertainty_disclosed: bool`, `charged_tokens: int`, `actual_tokens: int | None`, `latency_seconds: float`, `not_replayed: str | None`
  - `class ArmResult(StrictFrozen)`: `arm: Literal['baseline','revised']`, `baseline_id: str`, `paid: bool`, `cases: tuple[ArmCase, ...]` (sorted by `case_id`), `reused_frozen_outputs: bool`, `new_model_calls: int`, `notes: tuple[str, ...]`
  - `@dataclass(frozen=True) class RevisedStages` with callables `policy(baseline) -> object`, `gate(case, policy, bundle) -> AgenticGateDecision`, `relevance(case, policy) -> RelevanceJudgment`, `coverage(evaluation) -> Coverage`, `label(coverage, relevance, policy) -> str`, `shortlisted(decision, relevance) -> bool` (default: `decision.route == 'draft' and relevance.relevant != 'no'`), `rank(scored: list[Scored]) -> list[Ranked]`; `Scored(case_id, coverage, relevance, label)`; `Ranked(case_id, rank: int, ordering: Literal['provisional'], rank_reason: str, uncertainty: str, unresolved: tuple[str, ...])`
  - `default_stages(baseline: Baseline) -> RevisedStages` (the only place that names Plans 2–4 functions)
  - `bundle_of(case: FrozenCase) -> EvidenceBundle` (rebuild from `case.snapshot['contents']`; `bundle_hash != run_key.evidence_hash` -> `AgenticError('baseline_case_invalid')`)
  - `replay(baseline_id: str, arm: Literal['baseline','revised'], *, paid: bool = False, budget_tokens: int = 0, llm=None, config=None, stages: RevisedStages | None = None) -> ArmResult`
  - re-export `split` from `eval_data` (contract name)

- [ ] **Step 1: Write the failing tests** (fake stages built in the test; no Plan 2–4 import except the integration test):

```python
def test_baseline_arm_reads_frozen_outputs_and_orders_by_holistic_score():
    r = replay(bid, 'baseline')
    shown = [c for c in r.cases if c.shortlisted]
    assert {c.case_id for c in shown} == {c.case_id for c in frozen if c.decision['route'] == 'draft'}
    assert [c.rank for c in sorted(shown, key=lambda c: c.rank)] == list(range(1, len(shown) + 1))
    assert all(c.ordering == 'holistic' and c.label is None for c in shown)
    assert r.reused_frozen_outputs and r.new_model_calls == 0 and r.paid is False

def test_baseline_arm_makes_no_model_or_database_call(monkeypatch): # patch service.configured_llm / LLM to raise; no sqlite connection opened
def test_revised_arm_uses_stages_in_order_and_marks_ordering_provisional():
    r = replay(bid, 'revised', stages=fake_stages())
    assert all(c.ordering == 'provisional' for c in r.cases if c.shortlisted)
    assert r.notes == ('relevance_not_replayed',) and r.reused_frozen_outputs and r.new_model_calls == 0
def test_revised_arm_can_shortlist_a_case_the_baseline_archived():     # score 2.7 archived by baseline; fake gate returns draft
def test_revised_arm_ignores_a_profile_change_after_freezing(monkeypatch):
    # fake gate returns route by reading profile.yaml via apaths.profile_dir(); rewrite the LIVE profile after make_baseline
    assert replay(bid, 'revised', stages=reading_stages).cases[0].route == frozen_route   # frozen copy was read
def test_unverifiable_citation_is_counted_not_hidden():                 # tamper one citation quote in a frozen case
    assert case.citation_failures == 1
def test_tampered_snapshot_is_refused():                                 # contents edited so bundle hash differs
    with pytest.raises(AgenticError, match='baseline_case_invalid'): replay(bid, 'baseline')
def test_bundle_rebuild_round_trips(tmp_path):                           # tests/candidate/test_evidence_bundle_rebuild.py
    assert bundle_from_contents(bundle.contents).bundle_hash == bundle.bundle_hash
def test_default_stages_run_end_to_end_on_merged_plans():                # integration: no fakes; asserts the real names bind
    r = replay(bid, 'revised'); assert len(r.cases) == n_cases and all(c.ordering in (None, 'provisional') for c in r.cases)
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_evaluate_runs.py tests/candidate/test_evidence_bundle_rebuild.py` -> FAIL.
- [ ] **Step 3: Implement.** Baseline arm: `ArmCase` from `FrozenCase.decision`/`evaluation`/`usage` (`usage['charged_tokens'|'actual_tokens'|'latency_seconds']`; adapt in one private `_usage_of(case)` if 6a names differ), `shortlisted = route == 'draft'`, `claims_qualified = shortlisted`, rank by `(-decision.global_score, posting_id)`, coverage computed with `stages.coverage` of the default stages so both arms use one definition (the baseline arm also calls `default_stages(baseline).coverage` only; no other stage). Revised arm: load baseline, `with pinned_profile(baseline_id):` call `stages.policy(baseline)` once, then per case (sorted by `case_id`): `bundle_of`, validate the evaluation with `validate_model_payload(AgenticEvaluation, case.evaluation)`, gate, relevance placeholder `uncertain` (note `relevance_not_replayed`), coverage, label, `shortlisted`, then one `stages.rank` call over the included cases; `claims_qualified = label == 'stronger_match'`; `uncertainty_disclosed = bool(ranked.uncertainty.strip())`; `unresolved = coverage.unknown + coverage.partial`. `citation_failures` = number of citations in `match.evidence` and `judgment.contradiction_evidence` for which `verify_candidate_citations` raises. Latency of a reused revised case = measured `perf_counter` stage time; `charged_tokens = 0`. `default_stages`: `policy_for(users.current(), version=baseline.profile_version)` (contract issue 1; add the keyword-only `version` parameter to Plan 2's function if absent and record a ruling), `decide(evaluation, ad_text=snapshot['full_ad'], title=snapshot['posting']['title'], policy=policy, captured_complete=snapshot['text_kind'] == 'full', expected_run_key=evaluation.run_key, evidence_bundle=bundle, commute_km=case.commute_km)` using the merged signature; `AgenticError('policy_unavailable')` when no policy.
- [ ] **Step 4: Run** the two test files plus `tests/candidate` -> PASS.
- [ ] **Step 5: Commit** `feat: replay frozen baseline through baseline and revised arms offline`.

### Task 4: Optional paid replay of the model roles

**Files:**
- Modify: `pipeline/agentic/evaluate_runs.py`
- Test: `tests/test_evaluate_paid.py`

**Interfaces:**
- Consumes: Task 3; `service.configured_llm`, `service._config(config)` (keys `evaluator_model`, `embedding_model`, `job_token_ceiling`, `job_seconds`), `execution.Execution/use/require_route`, `runtime.BatchBudget/JobBudget`, `evaluator.evaluate_job`, `CandidateAssessment`.
- Produces: `replay(..., paid=True, budget_tokens=N, llm=..., config=...)` re-runs `evaluate_job` per case on frozen inputs and feeds the new evaluation to the same revised stages; `PAID_ROLES_PER_CASE = 3`; `estimate_paid(baseline_id: str, case_ids: Sequence[str] | None = None) -> dict` returning `{'cases': n, 'model_roles_per_case': 3, 'note': 'jobs x three model roles; spend is capped by budget_tokens'}`.

- [ ] **Step 1: Write the failing tests** (transport = scripted fake like `FakeModel` in `tests/test_agentic_evaluate.py` wrapped in `LLM(transport=..., keys=['synthetic'], base_url=model_choice.SERVER_URL)` with `model_choice.SERVER_URL` patched to loopback http as `confirm_discovery` does):

```python
def test_paid_without_budget_is_refused_before_any_call():     # AgenticError 'budget_required'; transport calls == 0
def test_paid_refuses_a_non_approved_gateway():                  # base_url elsewhere -> RuntimeErrorSafe 'gateway_not_allowed'; calls == 0
def test_paid_replay_reruns_roles_on_frozen_inputs_within_budget():
    r = replay(bid, 'revised', paid=True, budget_tokens=2_000_000, llm=llm, config=cfg, stages=fake_stages())
    assert r.paid and not r.reused_frozen_outputs and r.new_model_calls >= 3 * len(done)
    assert sum(c.charged_tokens for c in r.cases) <= 2_000_000 and all(c.not_replayed is None for c in r.cases)
def test_budget_exhaustion_marks_the_rest_not_replayed():        # budget fits one case
    assert [c.not_replayed for c in r.cases].count('budget') == len(r.cases) - 1 and 'budget_exhausted' in r.notes
def test_paid_replay_writes_nothing_to_production_state():       # no agentic_runs rows, no files under user_dir/'agentic', no new table
def test_estimate_states_jobs_times_three_roles(): assert estimate_paid(bid) == {..., 'cases': n, 'model_roles_per_case': 3, ...}
def test_baseline_arm_never_pays_even_if_asked():                # replay(bid,'baseline',paid=True) -> AgenticError 'paid_applies_to_revised_only'
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_evaluate_paid.py` -> FAIL.
- [ ] **Step 3: Implement.** Order of checks: arm, `budget_tokens > 0`, `llm = llm or configured_llm(config)`, `require_route` for the evaluator model and (when set) the embedding model, then one `BatchBudget(f'eval-{baseline_id}', token_ceiling=budget_tokens)`; per case a `JobBudget(run_key.value, batch, token_ceiling=min(cfg['job_token_ceiling'], budget_tokens - batch.charged_tokens))` and `Execution(run_id=..., seconds=cfg['job_seconds'], token_ceiling=same)` under `execution.use`; `evaluate_job(run_key, snapshot['full_ad'], job, llm, evidence_bundle=bundle_of(case), candidate_analysis=validate_model_payload(CandidateAssessment, case.candidate), model=cfg['evaluator_model'], research=None, commute_km=case.commute_km, model_insights=case.model_insights, embedding_model=cfg['embedding_model'])` (research off: it needs the live web). A case with `candidate is None` is `not_replayed='no_candidate'`; when `batch.charged_tokens >= budget_tokens` stop and mark the remainder `not_replayed='budget'`. Relevance stays the Task 3 placeholder (ADR decision; Owner decision 2). Usage per case comes from the execution's `usage()`.
- [ ] **Step 4: Run** the file and `tests/test_evaluate_runs.py` -> PASS.
- [ ] **Step 5: Commit** `feat: optional budgeted paid replay of the evaluation roles on frozen inputs`.

### Task 5: Metrics

**Files:**
- Create: `pipeline/agentic/eval_metrics.py`
- Test: `tests/test_eval_metrics.py`

**Interfaces:**
- Consumes: `ArmResult/ArmCase` (Task 3), `OwnerLabel`, `MIN_LABELS`.
- Produces: `K_VALUES = (5, 10)`; `wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]`; `ndcg_at(ranked_gains: Sequence[int], ideal_gains: Sequence[int], k: int) -> float` (gain `2**rel - 1`, discount `log2(position + 1)`); `compute_metrics(arm: ArmResult, labels: Mapping[str, OwnerLabel], case_ids: Collection[str]) -> dict`; `compare_arms(baseline: dict, revised: dict, baseline_arm: ArmResult, revised_arm: ArmResult, labels, case_ids) -> dict`.

Metric definitions (the ADR text; `case_ids` is one split, cases `not_replayed` are excluded from both arms):
- `labelled` = cases in the split with an owner label whose `suitable` or `relevance` is set. If fewer than `MIN_LABELS`, every label-based entry is `{'status': 'owner_labels_required', 'labelled': n, 'needed': 10}`; nothing is imputed.
- `missed_suitable`: labelled `suitable is True` and not shortlisted -> `{'count','of','rate','ci95'}`; `suitable_held`: the subset with route `hold`.
- `unsupported_claims` (no labels needed): among `claims_qualified` cases, those with `citation_failures > 0`, `coverage.mandatory_unmet > 0` or `coverage.conflicts > 0` -> `{'claims','unsupported','citation_failures','mandatory_unmet','conflicts'}`.
- `ordering`: relevant means `relevance >= 2`, else `suitable is True`; gain is `relevance`, else 3 if suitable else 0. The arm's ranking is taken over shortlisted labelled cases only (condensed list; unlabelled cases removed); the ideal list is all labelled cases, so a missed suitable job lowers nDCG. Reports `precision_at[k]`, `ndcg_at[k]`, `labelled_ranked`.
- `exclusion_violations`: `deterministic` = shortlisted cases tagged `explicit_exclusion`; `owner_labelled` = shortlisted, untagged cases whose label has `exclusion_violation is True`.
- `uncertainty`: `unknown_treated_as_failure` = route `archive`, reason `score_below_threshold`, `coverage.contradicted == 0`, `coverage.unknown > 0`; `unresolved_shortlisted` = shortlisted with `unresolved > 0`; `disclosed` = of those, `uncertainty_disclosed`.
- `cost`: sums of `charged_tokens`, `actual_tokens`, `unknown_usage_cases`, `new_model_calls`, `reused_frozen_outputs`, and `currency: 'not_estimated'`; `latency`: mean, median, p95 seconds.
- `by_tag`: per `TAGS` entry `cases, shortlisted, missed_suitable` (the last only when labels suffice).
- `compare_arms`: per metric the two values, the delta, and for `missed_suitable` and `exclusion_violations` the paired `fixed` (baseline wrong, revised right) and `broke` counts; `cost_comparison: 'not_comparable_reused_outputs'` when the revised arm reused frozen outputs; `significance: 'not_assessed'`.

- [ ] **Step 1: Write the failing tests** (build `ArmCase`s with a small factory; 12 cases, labels on all, baseline shortlists 1-6, revised 1-8, suitable = {1,2,3,7,8}):

```python
def test_wilson_matches_known_values():
    assert wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-3) and wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-3)
def test_ndcg_worked_example():       # ranked gains A=3,B=0,C=2 ; ideal 3,3,2,0 ; k=3
    assert ndcg_at([3, 0, 2], [3, 3, 2, 0], 3) == pytest.approx(8.5 / 12.9165, abs=1e-3)
def test_missed_suitable_counts_labelled_suitable_not_shortlisted():
    assert (m_base['missed_suitable']['count'], m_base['missed_suitable']['of']) == (2, 5) and m_rev['missed_suitable']['count'] == 0
def test_fewer_than_ten_labels_gives_owner_labels_required_and_no_numbers():
    assert m['missed_suitable'] == {'status': 'owner_labels_required', 'labelled': 9, 'needed': 10} and 'rate' not in json.dumps(m['ordering'])
def test_unsupported_claims_need_no_labels():          # baseline case 3 drafted with citation_failures=1
    assert m_base['unsupported_claims']['unsupported'] == 1 and m_rev['unsupported_claims']['unsupported'] == 0
def test_exclusion_violations_split_deterministic_and_owner_labelled(): # case 5 tagged, case 6 labelled
    assert m_base['exclusion_violations'] == {'deterministic': 1, 'owner_labelled': 1}
def test_unknown_treated_as_failure_and_disclosure():   # case 10 archived score_below_threshold with unknown=2, contradicted=0
    assert m_base['uncertainty']['unknown_treated_as_failure'] == 1 and m_base['uncertainty']['disclosed'] == 0 and m_rev['uncertainty']['disclosed'] >= 1
def test_ordering_uses_condensed_list_and_penalises_missed_suitable()
def test_not_replayed_cases_are_excluded_from_both_arms()
def test_compare_arms_reports_paired_fixed_and_broke_and_never_says_improved():
    c = compare_arms(...); assert c['missed_suitable']['fixed'] == 2 and c['missed_suitable']['broke'] == 0 and 'improv' not in json.dumps(c).lower()
def test_offline_cost_is_marked_not_comparable(): assert c['cost_comparison'] == 'not_comparable_reused_outputs'
def test_by_tag_covers_every_tag_even_when_empty()
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_eval_metrics.py` -> FAIL.
- [ ] **Step 3: Implement** the pure functions above; no I/O, no model, no clock.
- [ ] **Step 4: Run** -> PASS.
- [ ] **Step 5: Commit** `feat: evaluation metrics with explicit missing-label handling`.

### Task 6: Reproducible private reports and holdout discipline

**Files:**
- Create: `jobwatch/reports/__init__.py`, `jobwatch/reports/build.py`
- Test: `tests/test_reports.py`

**Interfaces:**
- Consumes: Tasks 2–5; `users.user_dir`, `apply.paths.safe_write_bytes/ensure_dir`; `GATE_VERSION` (6a); `MATCHING_VERSION` (`matching.py`), `IMPLEMENTATION_VERSION` (`service.py`), `jobwatch.preferences.features.versions()`.
- Produces:
  - `class Report(StrictFrozen)`: `schema_version: Literal[1]`, `report_id: str` (`'rep-' + sha256(...)[:16]` over baseline id, kind, split hash, labels hash, arm settings, code hashes), `kind: Literal['development','holdout','monitor']`, `baseline_id`, `created_at`, `status: Literal['descriptive_comparison','owner_labels_required','owner_holdout_labels_required']`, `split: dict`, `arms: dict`, `comparison: dict`, `tags: dict`, `cases: tuple[dict, ...]` (development only; ids, tags, route, shortlisted, rank, label per arm), `code_hashes: dict[str, str]`, `data_hashes: dict[str, str]`, `holdout_access: dict | None`, `monitoring: dict | None`, `limits: str`
  - `code_hashes() -> dict[str, str]`: `gate_version`, `implementation_version`, `matching_version`, `evaluation` (sha256 of `eval_data.py`, `evaluate_runs.py`, `eval_metrics.py`, `reports/build.py`), `ranking_rules` (sha256 of `docs/ranking-rules.md`), `preferences` (`versions()['source_hashes']` joined), `git_commit` (`git rev-parse HEAD` with a 10 s timeout, `'unknown'` on failure)
  - `data_hashes(baseline_id) -> dict[str, str]`: `baseline`, `cases`, `labels` (or `'none'`), `split`, `profile_files` (from `Baseline.profile_files_sha256`)
  - `build_report(baseline_id: str, *, kind: str, results: Mapping[str, ArmResult], monitoring: dict | None = None, now: str | None = None) -> Report`; `write_report(report: Report) -> Path` (writes `reports/<report_id>.json` and `.md`; an existing id is returned untouched); `render_markdown(report) -> str`; `list_reports() -> list[dict]`; `load_report(report_id: str) -> Report`
  - `record_holdout_access(baseline_id: str, report_id: str, code_hash: str) -> dict` appending to `baselines/<id>/holdout-log.jsonl` and returning `{'reads': n, 'prior_reads_with_other_code': m}`

- [ ] **Step 1: Write the failing tests**:

```python
def test_same_inputs_give_same_report_id_and_metrics_and_second_write_is_untouched():
    a, b = build(), build(); assert a.report_id == b.report_id and a.arms == b.arms
    p = write_report(a); before = p.read_bytes(); write_report(b); assert p.read_bytes() == before
def test_report_id_changes_when_a_label_or_the_code_hash_changes(monkeypatch)
def test_report_files_are_private():            # reports/ 0700, .json/.md 0600
def test_report_contains_no_candidate_text():   # marker string planted in the frozen ad, evidence quote and rationale
    assert MARKER not in report_json and MARKER not in report_md
def test_development_report_lists_cases_and_holdout_report_does_not():
    assert dev.cases and holdout.cases == ()
def test_status_without_enough_holdout_labels_is_owner_holdout_labels_required():
    assert holdout.status == 'owner_holdout_labels_required' and 'rate' not in json.dumps(holdout.arms['revised']['metrics']['missed_suitable'])
def test_no_improvement_claim_in_limits_or_markdown(): assert 'improv' not in render_markdown(r).lower() and 'not established' in r.limits
def test_second_holdout_report_for_different_code_is_flagged(monkeypatch):
    first = holdout_report(); monkeypatch.setattr(build, 'code_hashes', lambda: {**real, 'evaluation': 'x' * 64})
    second = holdout_report(); assert second.holdout_access == {'reads': 2, 'prior_reads_with_other_code': 1}
    assert 'holdout has been read before for different code' in render_markdown(second)
def test_reports_are_per_person(): with users.use('mate'): assert list_reports() == [] and pytest.raises(AgenticError, load_report, rid)
def test_code_hashes_name_every_version_the_contract_requires(): assert {'gate_version', 'implementation_version', 'matching_version', 'preferences'} <= set(code_hashes())
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_reports.py` -> FAIL.
- [ ] **Step 3: Implement.** Status: `descriptive_comparison` only when the report's split has >= `MIN_LABELS` labelled cases; `holdout` kind uses `owner_holdout_labels_required` for the same shortage, `development` uses `owner_labels_required`. Markdown is tables of counts and rates plus the `limits` text: "Descriptive counts on frozen inputs and owner labels. No improvement in matching accuracy, calibration or hiring probability is established. Model self-grades and synthetic checks are not labels. Preference ordering is evaluated only through the fit's own held-out gate." A holdout report rejects `results` containing `not_replayed` cases beyond those in `notes`.
- [ ] **Step 4: Run** -> PASS.
- [ ] **Step 5: Commit** `feat: reproducible private evaluation reports with holdout access log`.

### Task 7: Bounded monitor and eligible model fit

**Files:**
- Create: `jobwatch/reports/monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes: Tasks 2–6; `outcomes.readiness.outcome_readiness(conn)`; `preferences.PreferenceStore/fit_store`; `preference_service.pool(conn, config) -> (identity, alternatives)`; `shutil.which`.
- Produces:
  - `monitor_snapshot(conn, store_status: dict) -> dict`: candidate-free aggregates only: `outcomes` (the `outcome_readiness` counts; pending is not a failure), `preference` (`status, n_choices, n_train, n_holdout`, never the fit payload), `runs` (`SELECT status, COUNT(*) FROM agentic_runs GROUP BY status` when the table exists)
  - `eligible_fit(store: PreferenceStore, identity: str, out_dir: Path, *, fitter=fit_store, which=shutil.which) -> dict`: attempts only when `store.status(identity)['status'] in ('untrained', 'stale')` and `Rscript` and `jags` are on `PATH`; returns `{'attempted': False, 'reason': <status or 'toolchain_missing'>}` or `{'attempted': True, 'accepted': bool, 'reasons': [...]}` (or `{'attempted': True, 'error': <PreferenceError code>}`); CPU only, no model call
  - `run_monitor(config, *, max_cases: int = 500, max_seconds: float = 300, fit: bool = False, clock=time.monotonic) -> dict`: for the current person: newest baseline (`{'skipped': 'no_baseline'}` if none), `record_split` (idempotent), offline `replay` of both arms (never `paid`), development `build_report` with `monitoring`, `write_report`; returns `{'report_id', 'unchanged': bool, 'fit': dict | None, 'deferred': None | 'deadline' | 'case_limit'}`

- [ ] **Step 1: Write the failing tests**:

```python
def test_monitor_without_a_baseline_is_a_skip_not_an_error(): assert run_monitor(cfg) == {'skipped': 'no_baseline'}
def test_monitor_writes_one_development_report_and_never_a_holdout_report():
def test_monitor_twice_on_unchanged_inputs_is_unchanged(): assert second['unchanged'] and second['report_id'] == first['report_id'] and len(list_reports()) == 1
def test_monitor_makes_zero_model_calls(monkeypatch):   # configured_llm and LLM.chat_once patched to raise
def test_monitor_stops_at_the_deadline_without_a_partial_report(): # clock jumps past max_seconds after the baseline arm
    assert out['deferred'] == 'deadline' and list_reports() == []
def test_monitor_respects_the_case_limit():             # baseline with 6 cases, max_cases=3 -> 'case_limit', no report
def test_fit_is_attempted_only_when_eligible(): # 25 synthetic answered sets (as tests/preferences/test_local_r.py) with fake fitter and which -> /bin/x
    assert eligible_fit(store, ctx, tmp, fitter=fake, which=lambda n: '/bin/' + n) == {'attempted': True, 'accepted': True, 'reasons': []}
def test_fit_not_attempted_for_insufficient_data_or_missing_toolchain():
    assert eligible_fit(small_store, ctx, tmp)['reason'] == 'insufficient_data' and eligible_fit(store, ctx, tmp, which=lambda n: None)['reason'] == 'toolchain_missing'
def test_rejected_fit_is_reported_with_its_reasons_not_hidden()
def test_snapshot_has_no_candidate_text_and_counts_pending_separately()
def test_fit_flag_off_never_calls_the_fitter()
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_monitor.py` -> FAIL.
- [ ] **Step 3: Implement.** The DB is opened read-only (`sqlite3.connect(f'file:{path}?mode=ro', uri=True)`) except for the fit (`mode=rw`, as `preference_cli` does) and only when `fit=True`. Check the clock before the baseline arm, between arms and before writing; exceeding `max_seconds` returns `deferred='deadline'` and writes nothing. `report_id` is computed before writing; an existing id returns `unchanged=True`.
- [ ] **Step 4: Run** -> PASS.
- [ ] **Step 5: Commit** `feat: bounded evaluation monitor with eligible local model fit`.

### Task 8: `jobwatch evaluate` command

**Files:**
- Create: `jobwatch/evaluation_cli.py`
- Modify: `jobwatch/cli.py` (add `"jobwatch.evaluation_cli"` to the module list in `_extensions()`)
- Test: `tests/test_cli_evaluate.py`

**Interfaces:**
- Consumes: Tasks 2–7. Produces `register(sub)` / `handle(args) -> int | None` with `evaluate {cases,label,split,run,report,monitor} [BASELINE_ID]` and options `--case`, `--suitable {yes,no,unsure}`, `--relevance {0,1,2,3}`, `--exclusion-violation {yes,no}`, `--note`, `--seed`, `--fraction`, `--holdout`, `--paid`, `--budget-tokens`, `--max-cases`, `--max-seconds`, `--fit`. Output is one JSON line per command; errors are fixed codes on stderr with exit 1.
- Behaviour: `cases` prints `case_id, posting_id, title, company, tags, labelled` and never route, score, rank or arm (blind); `label` requires `sys.stdin.isatty()` else `human_required`, writes `OwnerLabel(actor='owner', labelled_at=now)`; `split` calls `record_split`; `run` replays both arms offline (revised paid only with `--paid --budget-tokens N`, after printing `estimate_paid`), writes a development report, or with `--holdout` a holdout report plus `record_holdout_access`; `report` lists or shows a report; `monitor` calls `run_monitor` (with `--user all` it runs per person, skipping those without a baseline).

- [ ] **Step 1: Write the failing tests** (`cli.main([...])` pattern from `tests/test_cli_profile.py`, `capsys`):

```python
def test_cases_listing_is_blind_to_arms(): assert not ({'route', 'score', 'rank', 'decision'} & set(json.loads(out)['cases'][0]))
def test_label_refuses_without_a_terminal(monkeypatch): rc == 1 and 'human_required' in err and not labels_file.exists()
def test_label_records_owner_actor_with_a_terminal(monkeypatch): monkeypatch.setattr(sys.stdin, 'isatty', lambda: True); assert read_labels(bid)['c1'].actor == 'owner'
def test_run_writes_a_development_report_and_prints_its_id(): assert out['kind'] == 'development' and (reports / f"{out['report_id']}.md").exists()
def test_holdout_run_is_aggregate_only_and_logged(): assert load_report(id).cases == () and (baseline_dir / 'holdout-log.jsonl').exists()
def test_paid_needs_budget_and_prints_the_estimate_first(): rc == 1 and 'budget_required' in err  # and with a budget the estimate line precedes the report line (synthetic transport)
def test_monitor_all_people_skips_those_without_baseline(capsys): both people listed, one 'no_baseline'
def test_evaluate_does_not_require_a_confirmed_profile_but_never_collects(): monkeypatch pipeline.run to raise; rc == 0
def test_help_lists_evaluate(): 'evaluate' in cli help
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_cli_evaluate.py tests/test_cli_profile.py` -> FAIL.
- [ ] **Step 3: Implement.** `handle` returns `None` unless `args.cmd == 'evaluate'`. Take the person from `users.current()` only. Config via `load_config(args.config_dir)`.
- [ ] **Step 4: Run** the two files -> PASS.
- [ ] **Step 5: Commit** `feat: jobwatch evaluate command for labels, splits, reports and the monitor`.

### Task 9: CI runs the full suite

**Files:**
- Modify: `.github/workflows/backend.yml`
- Test: `tests/test_ci_workflow.py`

**Interfaces:** Produces job `full-suite` (replaces the manual-only `release-regression`).

- [ ] **Step 1: Write the failing test** (parse with `yaml.safe_load`; PyYAML reads the key `on` as `True`, so read `wf.get('on') or wf.get(True)`):

```python
def test_full_suite_runs_on_push_and_pull_request_without_a_file_list():
    job = wf['jobs']['full-suite']; run = next(s['run'] for s in job['steps'] if 'pytest' in s.get('run', ''))
    assert {'push', 'pull_request'} <= set(trigger) and 'if' not in job and '.py' not in run and 'release-regression' not in wf['jobs']
def test_full_suite_installs_the_r_toolchain_and_enables_the_sampler_test():
    assert 'r-cran-rjags' in apt_line and 'jags' in apt_line and job_env['JOBWATCH_TEST_R'] == '1' and job['timeout-minutes'] >= 45
def test_fast_gate_stays_and_lists_the_new_evaluation_tests(): assert 'tests/test_eval_metrics.py' in fast_run and 'tests/test_reports.py' in fast_run
def test_workflow_has_no_deploy_or_schedule_step(): assert 'schedule' not in trigger and 'deploy' not in text.lower()
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_ci_workflow.py` -> FAIL.
- [ ] **Step 3: Implement.** Job `full-suite`: `needs: synthetic-backend`, `timeout-minutes: 60`, `uv sync --frozen --extra dev --extra browser`, `python -m playwright install --with-deps chromium` (as the existing release job does), `sudo apt-get update && sudo apt-get install -y r-base-core jags r-cran-rjags r-cran-coda r-cran-jsonlite poppler-utils`, env `JOBWATCH_SETTINGS: /dev/null` and `JOBWATCH_TEST_R: '1'`, command `uv run --no-sync python -m pytest -q -o faulthandler_timeout=300 --maxfail=5`. Add `tests/test_eval_data.py tests/test_evaluate_runs.py tests/test_evaluate_paid.py tests/test_eval_metrics.py tests/test_reports.py tests/test_monitor.py` to the `synthetic-backend` list. Keep `concurrency` and `permissions: contents: read`.
- [ ] **Step 4: Run** the test -> PASS. State in the commit body that Actions have not been starting in this repository and the package names and runtime are unverified until a runner executes them.
- [ ] **Step 5: Commit** `ci: run the full suite on push and pull request with R and JAGS`.

### Task 10: Release check, docs and workflow example

**Files:**
- Create: `docs/examples/evaluation-workflow.md`
- Modify: `README.md` (section "Evaluation and monitoring": commands, labels are the owner's, holdout rules), `pipeline/agentic/MATCHING.md` (point "Remaining experiment" and "Offline comparison tools" at `jobwatch evaluate`; update the CI paragraph; touch the test-count line only with an actual run), `pipeline/agentic/CHAT.md` (one paragraph: evaluation is CLI-only, no native endpoint, and why), `docs/superpowers/plans/EXECUTING.md` only if its phase table is wrong

- [ ] **Step 1:** Run the full suite once, alone: `<venv>/bin/python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=90` (install `.[dev,browser]` so the 10 browser-dependent files collect). Record the pass/skip counts. For each failure, run the same test on `origin/main`; only a failure that also fails there is "pre-existing" (report it with that evidence). `tests/preferences/test_local_r.py` skips here without R; say so.
- [ ] **Step 2: Prove the guard rails with diffs.** `git diff --name-only origin/main...HEAD` must not list `pipeline/agentic/service.py`, `gate.py`, `contracts.py`, `jobwatch/db.py`, anything under `systemd/`, or the five preference files; `grep -rn "submit_confirm\|openrouter_extras" pipeline/agentic/eval_*.py pipeline/agentic/evaluate_runs.py jobwatch/reports jobwatch/evaluation_cli.py` finds nothing.
- [ ] **Step 3:** Write `docs/examples/evaluation-workflow.md` from the Task 8 test transcript with synthetic data: `baseline freeze` (6a) -> `evaluate cases` -> `evaluate label` (owner, at a terminal) -> `evaluate split` -> `evaluate run` -> `evaluate run --holdout` -> `evaluate report` -> `evaluate monitor --fit`. Include real captured outputs, the `owner_labels_required` outcome before labelling, and an optional user-timer snippet marked "not installed by this change".
- [ ] **Step 4:** Update the docs listed above; keep wording to what ran (no accuracy claim, no deployment claim).
- [ ] **Step 5: Commit** `docs: evaluation workflow example and release notes`; push; open the PR with: summary, exact checks and results, rulings, limitations (below), unverified items (Actions runner, R/JAGS install, paid replay on the live route), and the Rollback section.

## Owner decisions (the executor does not block on these)

1. **Labels:** the owner must label at least 10 cases per split before any label-based number appears. Default: reports say `owner_labels_required`; the executor writes no labels.
2. **Paid revised replay:** whether to ever spend tokens re-running the three model roles per case, and the `--budget-tokens` ceiling (jobs x three roles; `estimate_paid` prints it). Default: never run; offline only. Relevance (Plan 3's live paid step) is not replayed even when paid.
3. **Monitor timer:** whether to install a user timer running `jobwatch --user all evaluate monitor`. Default: not installed; a snippet is documented only.
4. **GitHub Actions:** enabling Actions for the repository and accepting the 60-minute full-suite job. Default: workflow changed, unverified.
5. **Thresholds:** holdout fraction 0.3, `MIN_LABELS = 10`, `K_VALUES = (5, 10)`. Default: as written in the ADR.
6. **Report endpoint:** a read-only native API route for reports. Default: none (CLI only).

## Rollback

Revert the merge commit. No table, migration, config key or run-key input changes, so stored evaluations and packages are untouched. Folders and files this change creates, per person under `users.user_dir(person)`: `reports/` (reports and `reports/fits/`), and inside each baseline folder `split.json`, `holdout-log.jsonl` and `labels.jsonl`. Reports, `split.json` and `holdout-log.jsonl` can be deleted. **Keep `labels.jsonl`**: it is the owner's own work, only deleted at the owner's word. Any `monitor --fit` adds an append-only row to `preference_fits` (immutable triggers); it is superseded by later fits and harmless. `jobwatch/candidate/evidence.py` gains one function; reverting removes it.

## Limitations to state in the PR

- Offline, the revised arm reuses the baseline's model outputs, so cost and model latency are not comparable between arms; only a paid replay measures new spend.
- Relevance is not replayed; the revised arm treats it as `uncertain`.
- Personalised ordering is not evaluated; only the fit's held-out gate reports on it.
- Unsupported-claim counts are deterministic checks (citations, mandatory requirements, contradictions), not owner review of every requirement; requirement-level review stays with `--matching-comparison`.
- Time-to-response modelling is not attempted; the monitor reports `outcome_readiness` only.

## Self-review notes

Spec coverage: frozen identical inputs and tags (Tasks 2, 3, 5 `by_tag`); missed suitable, unsupported claims, ordering, exclusion violations, uncertainty, cost, latency (Task 5); duplicates and related employers not leaking, dev vs untouched holdout (Tasks 2, 6); automated bounded comparisons, eligible fits, monitoring, reproducible reports (Tasks 6, 7, 8); missing labels explicit (Tasks 5, 6, Owner decisions 1); CI full suite (Task 9); examples, limitations, rollback (Task 10, this file). Names match the contract: `replay`, `split`, `ArmResult`, `owner_labels_required`, report paths and CI job.

## Contract issues

- `policy_for(person)` takes no version; replay needs the policy as of `Baseline.profile_version`. Proposed: keyword-only `version: int | None = None` (additive), used in Task 3.
- Plan 4 names only `build_shortlist(conn, config)`; replay needs a pure ordering function over (coverage, label, relevance) returning rank, reason, uncertainty and unresolved facts. Proposed: `ranking.rank_candidates(...)`, called by `build_shortlist`.
- Plan 3 `judge_relevance` is a live paid step with no stored result; offline replay cannot reproduce it. Proposed: Plan 3 persists the `RelevanceJudgment` next to the evaluation so 6b can read it; until then 6b uses a placeholder `uncertain`.
- Plan 6a defines `OwnerLabel` but no label reader or writer (CLI lists only freeze/list/show), leaves `FrozenCase.usage` keys unnamed, and offers no evidence-bundle rebuild from `snapshot.contents`. 6b supplies `read_labels`/`write_label`, `_usage_of` and `evidence.bundle_from_contents`; 6a should adopt these names or tell 6b.
- Contract `replay(baseline_id, arm, *, paid, budget_tokens)` has no way to inject a gateway, config or stages; 6b adds keyword-only `llm`, `config`, `stages` with defaults (non-breaking).
