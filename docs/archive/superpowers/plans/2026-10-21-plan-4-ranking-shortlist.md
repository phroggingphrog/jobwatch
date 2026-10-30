# Plan 4: Ranking and explained shortlist — Implementation Plan

> **Superseded for Phase 5.** The owner-approved [Phase 5 execution plan](2026-10-22-phase-5-execution.md)
> is the binding design. This file is retained as historical background only;
> its score-policy flags, nonzero preference priors, fixed-hour salary conversions,
> feature assumptions and word-overlap transfer rule are not current requirements.
> Phase 5 source implementation is available on the current branch; full-suite
> verification and review/PR remain pending. It is not merged or released.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn stored requirement judgments into a ranked, explained shortlist (stronger match / stretch / needs clarification) that works from the first day with documented provisional rules, demote the holistic 1–5 score from the sole exclusion to a comparison baseline behind a flag, and improve the existing R/JAGS preference model (wider families, filled factual features, held jobs in the pool) with an explicit re-featurisation migration.

**Architecture:** A pure module `pipeline/agentic/ranking.py` holds the documented weights, `coverage()`, `label_for()`, ordering and explanation builders (no I/O). `pipeline/agentic/shortlist.py` gathers current evaluations (re-deciding each stored evaluation through Plan 2's `service.gate_current`, the one live gate call), assembles `ShortlistEntry` rows, persists them in three additive tables (`db.py` migration) and logs impressions; `pipeline/agentic/shortlist_api.py` exposes them. The preference model keeps its structure; `features.py`/`model.py`/`fit_choice_model.R` change once (feature version v3) and `preference_service.refeaturise` copies the owner's answered sets into the new version on explicit request. Ordering is `personalised` only while `PreferenceStore.status() == 'valid'`, else `provisional`.

**Tech Stack:** Python 3.12, pydantic v2 (`StrictFrozen`), SQLite, FastAPI, numpy-free pure Python, R 4.3 + JAGS 4.3 + rjags/coda/jsonlite (installed by Task 2), pytest with synthetic data.

**Spec:** [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md) sections 1, 3 (preference ranking, employer outcomes, cold start, holistic score) and 4 (shortlist explanations); [roadmap](2026-10-21-backend-roadmap.md) Plan 4; [cross-plan contract](2026-10-21-cross-plan-contract.md) "Phase 5 — Plan 4" and "Reconciled decisions" (binding; applied here, see "Contract reconciliation" at the end); [code map](reference/2026-10-21-codemap.md) section 4 (line numbers as of `ce9e342`; Plans 6a, 2 and 3 are merged before this runs, so re-check every line and grep for their names).

## Global Constraints

- "Include plausible stretch opportunities in the shortlist, clearly distinguished from stronger matches."
- "Each shortlist entry should explain: Relevant candidate evidence and transferable skills. Why it fits the current search objective. Practical conditions, mandatory requirements and unresolved facts. Whether it is a stronger match, stretch opportunity or needs clarification. Why it ranks where it does, including uncertainty."
- "Ability assessment: retain requirement-level evidence judgments: demonstrated, partial, unknown and contradicted. Exact citations must remain verifiable. Separate missing documentation from an actual skills gap or explicit conflict."
- "Preference ranking: improve the existing hierarchical Bayesian conditional-logit model rather than duplicating it. Expand narrow family categories and incomplete factual features. Learn from genuine user choices and rejection reasons. Choice probabilities describe preference among alternatives—not eligibility or hiring probability."
- "Employer outcomes: preserve the existing descriptive statistics. Investigate time-to-response modelling only when sufficient reliable history exists. Pending applications are not negative outcomes. Account for application selection bias and uncertainty before allowing predictions to influence ranking."
- "Cold start: deliver useful evidence-based shortlists immediately. Insufficient feedback must not prevent discovery. Clearly distinguish provisional ordering from validated personalised predictions. Document the initial ordering rules rather than inventing unexplained numerical weights."
- "The inherited holistic 1–5 score must not remain the sole exclusion mechanism. In particular, low career alignment must not automatically reject a suitable employment-first opportunity. Preserve it as a comparison baseline while validating the replacement policy." (INTENT.md: "change automatic exclusion policy only after a reviewed comparison including jobs the old matcher archived" — so the new policy ships behind a flag that defaults to the old behaviour.)
- "Never record agent-generated answers as user choices or approval." Nothing here records a choice. The one tool that copies existing answered owner choices (`preferences migrate`) is a human CLI action that needs `--confirm-owner`, is not reachable from the API, chat tools or any model output, and never creates an unanswered or new pick.
- Synthetic data only: no live candidate record, CV text, posting or preference answer in any test, fixture, ADR or example. Do not run `preferences migrate`, `preferences fit` or any collection against the owner's real database.
- Per-person isolation: every read/write is under `users.use(person)` with the person taken from the bearer token; new files use `apply.paths.safe_write_*`/`ensure_dir` (0600/0700); the shortlist tables live in that person's `jobwatch.db`.
- Paid model calls only via approved routes (`PaidGatewayEmbeddings`, `jobwatch.llm.LLM` with `require_route`); tests use `SyntheticGateway` transports. This plan adds **no** model call: ranking, labels, explanations and shortlist building are deterministic and database-only.
- No service/timer activation, no deployment, no submission or employer contact; `jobwatch/apply/submit_confirm.py` is untouched. Installing R/JAGS happens only in the executor's own environment.
- Schema changes additive: new tables via the next `jobwatch/db.py` migration only (not also lazily); no stored-model field is renamed or retyped; `ShortlistEntry`/`Coverage` only add fields to the contract.
- Run-key rule (contract rule 1): this plan changes none of `_config()`, `TargetPolicy`/policy contents, `IMPLEMENTATION_VERSION`, `LOCATION_REFERENCE_HASH`, evaluator prompts or the skill files. The new flags live under `pipeline.agentic.ranking`, are read outside `_config()` by `ranking_settings`, and default to today's behaviour. **Expected paid re-run cost: 0 jobs × 3 model roles.** A test (Task 4) proves the flag does not move a run key.
- Preference-file rule (contract rule 5): editing the five hashed files (`features.py`, `store.py`, `model.py`, `fit_choice_model.R`, `choice_model.jags`) invalidates every answered set. This plan edits them **once**, in Tasks 5–6, as feature version `choice-features-v3`, and ships the re-featurisation migration (Task 7). No other plan touches them. Task 5 also adds `experience.py` to the hashed list.
- Python 3.12 virtualenv outside the repo (EXECUTING.md rule 3); test command `<venv>/bin/python -m pytest -q -p no:cacheprovider <paths>`, run from the repo root. Branch `claude/phase-5-ranking-shortlist` from `main`. Run one pytest process at a time.

## Review Focus

1. A job whose every requirement is `unknown` (the CV simply does not document it): label `needs_clarification`, never `stretch`, never dropped, `real_gaps` empty, `missing_documentation` lists all. (Task 3 `test_all_unknown_is_needs_clarification`, Task 8 builder test.)
2. Historical evaluations with no `judgment` (legacy `match='missing'`): read as `unknown`, never as a conflict or a real gap. (Task 3 `test_legacy_missing_is_unknown_never_a_gap`.)
3. A mandatory requirement the person's own evidence contradicts: not shortlisted, counted under `excluded.mandatory_conflict` in the build summary, never labelled `stretch`. (Task 3, Task 8.)
4. A profile change after evaluation (new run key) or a person with no confirmed scope: no stale entries; another person's token sees only their own shortlist. (Task 8 `test_stale_run_key_is_not_listed`, Task 10 isolation test.)
5. A `synthetic_valid`, `stale`, `rejected` or `insufficient_data` preference fit must not produce `personalised` ordering, and personalised ordering never lifts a `stretch` above a `stronger_match`. (Task 3, Task 8.)

## Owner decisions (the executor does not block on any of them; it uses the default and lists each in the PR)

| # | Decision | Default used meanwhile |
|---|---|---|
| 1 | Turn on `pipeline.agentic.ranking.score_policy: advisory` (jobs the old rule archived for score appear on the shortlist, labelled by coverage). Cost: 0 tokens, the gate is re-applied to stored evaluations. Needs the reviewed comparison from Plan 6b first. | `legacy` (old behaviour; shortlist omits score-archived jobs) |
| 2 | Cold-start thresholds: `STRONG_MIN = 2/3`, `UNRESOLVED_MAX = 1/3`, partial credit `0.5`, tier order stronger → stretch → needs clarification. | As documented in `docs/ranking-rules.md`; revisit with owner labels in Plan 6b |
| 3 | Whether a validated personalised model may reorder across label tiers. | No: only within a tier |
| 4 | Preference priors: neutral (0) for taste features instead of the owner's archived directions. | Neutral; `coverage` +2.0 and `must_have_gaps` −0.5 kept |
| 5 | Running `jobwatch preferences migrate --confirm-owner` on the live database (copies answered choices into feature version v3). | Not run; until then the old answers do not count and ordering stays provisional |
| 6 | Retiring the undefined feature `automation_angle` (no data source exists). | Retired |
| 7 | Pay conversion assumes a 38-hour week and AUD. | 38 h, AUD, documented |
| 8 | Installing R/JAGS on the production host for fitting. | Not done; only the executor's environment and CI |

## File structure

| File | Responsibility |
|---|---|
| `pipeline/agentic/ranking.py` (new) | Pure: weights, `Coverage`, `coverage`, `label_for`, `exclusion_reason`, `rank_candidates`, explanation builders, `ShortlistEntry`, `RankingSettings`, `RULES_VERSION`. No database, no model. |
| `pipeline/agentic/shortlist.py` (new) | Database: `build_shortlist`, `record_impressions`, `latest_entries`, `load_latest`, `load_entry`, persistence of the three tables, current-evaluation gathering. |
| `pipeline/agentic/shortlist_api.py` (new) | FastAPI router `mount(app, require, get_config)`: the read routes (plus the database-only `refresh`); Plan 5's routes live in `feedback_api.py`. |
| `jobwatch/preferences/{features,model,store}.py`, `fit_choice_model.R`, new `experience.py` | Feature version v3 (Tasks 5–6). `choice_model.jags` stays unchanged. |
| `jobwatch/preference_service.py` | `current_runs`, `pool(statuses=)`, `refeaturise`. `jobwatch/preference_cli.py`: `migrate`. |
| `pipeline/agentic/gate.py`, `service.py` | `score_policy` on `decide` and Plan 2's `gate_current`, `ranking_policy`, `after_collect` hook, the re-queue fix. |
| `jobwatch/outcomes/readiness.py` | `response_time_readiness` (investigation only). |
| `docs/adr/<next>-ranking-and-explained-shortlist.md`, `docs/ranking-rules.md`, `docs/examples/ranking-shortlist.md`, `GLOSSARY.md`, `CHAT.md`, `MATCHING.md`, `README.md`, `SETUP.md`, `.github/workflows/backend.yml`, `scripts/install-r-jags.sh` | Records, docs, toolchain. |
| tests: `tests/ranking_support.py`, `tests/test_ranking.py`, `tests/test_shortlist.py`, `tests/test_shortlist_api.py`, `tests/preferences/{test_features_v3,test_experience,test_toolchain}.py`, `tests/outcomes/test_response_time.py`, additions to `tests/test_agentic_gate.py`, `tests/test_agentic_service.py`, `tests/test_preference_service.py`, `tests/preferences/test_core.py`, `tests/preferences/test_local_r.py` | |

## Design decisions (binding; Task 1 copies D1–D9 into `docs/ranking-rules.md`)

- **D1 Weights and credit.** `IMPORTANCE_WEIGHTS = {'critical': 4, 'high': 3, 'meaningful': 2, 'preferred': 1, 'low_signal': 0}` (contract). Credit per requirement: `demonstrated` 1.0, `partial` 0.5, `unknown` 0, `contradicted` 0. `weight_total` = sum of weights of applicable requirements (`not_applicable` ignored). `weighted = Σ w·credit / weight_total` (the conservative lower bound; 0.0 when `weight_total == 0`). `weighted_upper = (Σ w·credit + Σ w[unknown]) / weight_total` (what coverage would be if every unknown were met). `unresolved_share = Σ w[unknown] / weight_total`. Why: weights are the documented importance enum, not fitted; 0.5 for partial is a stated convention that keeps order monotone and is replaced only by an owner-labelled study (Plan 6b).
- **D2 Status.** A requirement's status is `match.judgment.status`; without a judgment: `strong→demonstrated`, `partial→partial`, `missing→unknown` (historical `missing` cannot be told from missing documentation; repo practice in `evaluation.py`), `not_applicable→` ignored. Lists in `Coverage` hold requirement ids sorted by `(-weight, id)`: `missing_documentation` = `unknown` with weight > 0; `real_gaps` = `partial` with weight > 0 (evidence reviewed shows less than the ad asks); `conflicts` = `contradicted` (a quoted contradiction exists, already validated by `EvidenceJudgment`).
- **D3 Mandatory.** A requirement is mandatory when `blocker` is true or importance is `critical`. `mandatory_unmet` = mandatory ids whose status is not `demonstrated`.
- **D4 Labels** (first match wins; constants `STRONG_MIN = 2/3`, `UNRESOLVED_MAX = 1/3`):
  1. `needs_clarification` if `held` (the gate said `hold/insufficient_evidence`), or `weight_total == 0`, or `unresolved_share > UNRESOLVED_MAX`, or a mandatory requirement is `unknown`, or (`relevance == 'uncertain'` and `policy.strategy != 'employment_first'`).
  2. `stretch` if a mandatory requirement is `partial`, or any non-mandatory conflict exists, or `weighted < STRONG_MIN`.
  3. else `stronger_match`.
  The holistic score and `north_star` take no part. Employment-first never asks about uncertain relevance (broad search across related fields is its purpose); career-focus does.
- **D5 Not shortlisted** (`exclusion_reason`): `mandatory_conflict` (a mandatory requirement is `contradicted`), `relevance_no` (Plan 3 judged `no`), `closed` (`postings.closed_at` set), `not_current` (stored run key differs from today's). Counted in the build summary; hard-gated and policy-excluded jobs are never candidates.
- **D6 Candidate pool.** After `service.gate_current` (Plan 2's one live gate call, D8; `ranking.candidate_status(route, reason)` is the pure mapping): route `draft/eligible` → status `eligible`; `hold/insufficient_evidence` → `held`; everything else is absent. Under `score_policy: advisory` the gate no longer returns `score_below_threshold`, so those jobs arrive as `eligible` by re-deciding their stored evaluation.
- **D7 Order.** Provisional (cold start, always available): tier `stronger_match < stretch < needs_clarification`, then for `career_focus` entries whose relevance is `yes` and match the focus first, then `weighted` desc, `weighted_upper` desc, Plan 3 `similarity` desc, `posting_id` asc. `ordering='provisional'`. Personalised only when `PreferenceStore(conn).status(identity)['status'] == 'valid'` (not `synthetic_valid`) and utilities exist for every entry: same tiers, within a tier by posterior-mean utility desc then the provisional keys; `ordering='personalised'`, `fit_id` stored. Impression `probability` is the plug-in softmax of posterior-mean utilities over the entries in that response plus the outside option (utility 0), stored only for personalised, documented as an approximation. Callback statistics and time-to-response never influence order.
- **D8 Score policy.** `pipeline.agentic.ranking.score_policy` ∈ `legacy` (default; today's `global_score < 3.0 or north_star < 3 → archive score_below_threshold`) and `advisory` (that check is skipped; the score is display-only `holistic_score`). `decide(..., score_policy=...)` and the same keyword on Plan 2's `service.gate_current(...)` are the only gate changes. `gate_current` is the single place the live gate is called; `run_agentic_job`, `preference_service.pool` and the shortlist all use it so their decisions agree, and the shortlist always passes the same `decision_policy` as the live run (`service.decision_policy_for(config)`: the profile policy in `profile` mode, None in `legacy`).
- **D9 Explanations** (deterministic, templates in `docs/ranking-rules.md`, no model text): `evidence` = up to 6 demonstrated/partial requirements by weight with their exact stored citations; `transferable_skills` = approved-profile facts of section `transferable_skill` (with their basis in brackets when not `evidence`) that share a ≥4-letter word with a non-demonstrated requirement, the job's required skills or duties; `objective_fit` names the strategy (employment-first / career focus / balanced), the matched focus or hypotheses when Plan 3 supplies them, and the coverage fraction; `conditions` = hours, location, work-rights wording, level/years, programme, legitimacy, where the location condition is the verified `location_evidence` quote and, when the policy has regions, Plan 2's `location_verdict(quote, regions, ...)` against `policy.regions`; the stored label `location_fit == 'melbourne'` is never read as "home region" (contract decision 16); `mandatory_requirements` = `"<text> [<status>]"`; `unresolved` = judgments' `open_question`, ad uncertainties, unstated hours/location; `rank_reason` and `uncertainty` per D7 (they state the tier, the coverage interval `weighted`–`weighted_upper`, the ordering kind and, when provisional, how many answered comparisons exist of the 25 needed).
- **D10 Preference model v3.** `FEATURE_VERSION='choice-features-v3'`, `PRIOR_VERSION='neutral-taste-sd05-missing-sd05-v2'`. `FAMILIES` = the 21 `KNOWN_FAMILIES` plus `'unknown'` (22 levels; other strings → `other`); `FAMILY_PRIOR` = zeros (the hard-coded accounting +0.5 is removed from `fit_choice_model.R`, which reads `input$family_prior`). `NAMES` = the 17 v2 names minus `automation_angle` plus `status_held` (0 eligible, 1 held). Filled: `pay_low_c`/`pay_high_c` ($/hour from `postings.salary_*`; hour 1, day /7.6, week /38, month /164.67, year /1976; outside $5–$500/h → missing; one bound → both), `age_days` (days between provider `posted_at` and `first_seen_at`, 0–90; missing when `posted_at_source != 'provider'`), `hours_flexible_full_time` (1 full-time-only ad with flexible-hours wording, 0 full-time-only without, else missing), `exp_shortfall`/`exp_excess` (`max(0, min_years − years)` / `max(0, years − min_years)` with `years` from the approved CV's role date ranges via `experience.candidate_years`; missing if either side unknown), `rights_welcomes_visa` (1 when the ad's wording invites non-citizens, else missing). `PRIOR_MEANS` are 0 except `coverage` 2.0 and `must_have_gaps` −0.5. `status_held` is learned only once choice sets include held jobs (Plan 5 comparisons); until then its coefficient is its prior.
- **D11 Exposure.** `shortlist_impressions` records each API view (entry, rank, ordering, probability, surface, one row per entry/surface/UTC day) so later plans can correct for selection (Schnabel et al.). No correction is applied here.

---

### Task 1: Record the design (ADR, glossary, ranking rules)

**Files:**
- Create: `docs/adr/<next free number>-ranking-and-explained-shortlist.md` (check `ls docs/adr` at execution time; Plans 6a/2/3 take earlier numbers)
- Create: `docs/ranking-rules.md`
- Modify: `GLOSSARY.md`

- [ ] **Step 1: Write `docs/ranking-rules.md`.** Header `Rules version: ranking-rules-v1`. One section per D1–D9 above in plain language, with a worked example for each of the three labels using invented requirements, the explanation templates (one sentence pattern per field), and a closing "What this does not claim": order and labels are evidence-based conventions, not accuracy, hiring probability or eligibility; thresholds are conventions to be checked with owner labels in Plan 6b.
- [ ] **Step 2: Write the ADR** (Context: brief §3–4 and INTENT.md matching section; Status Accepted; Decision: D1–D11 in that order plus the three non-goals — no model call here, callback/time-to-response never influence order, no selection-bias correction; Consequences: score policy flag and its zero re-run cost, preference sets must be migrated by the owner, `status_held` untrained until Plan 5, R/JAGS needed to verify sampler changes; References: brief sections, owner words "Preserve it as a comparison baseline", GitHub #6).
- [ ] **Step 3: Add GLOSSARY rows** (one sentence each): Shortlist, Stretch, Label (stronger match / stretch / needs clarification), Coverage (importance-weighted), Provisional ordering, Personalised ordering, Score policy, Impression.
- [ ] **Step 4: Commit** `docs: ADR, glossary and rules for ranking and the explained shortlist`.

### Task 2: R/JAGS toolchain and a baseline sampler run

**Files:**
- Create: `scripts/install-r-jags.sh` (executable), `tests/preferences/test_toolchain.py`
- Modify: `.github/workflows/backend.yml`, `SETUP.md` (section "Local preference fitting (R and JAGS)")

**Interfaces:** Produces `Rscript`, `jags` and the R packages `rjags`, `coda`, `jsonlite` in the executor environment; a CI job `preference-sampler`.

Planning-container finding (not an install): Ubuntu 24.04, root, outbound HTTPS only through the egress proxy; apt mirrors are `http://` and the proxy README says plain-HTTP (non-CONNECT) requests are refused (not tried here), but `https://archive.ubuntu.com/ubuntu` works with `-o Acquire::https::Proxy="$HTTPS_PROXY"`. A simulated `apt-get -s install --no-install-recommends r-base-core jags r-cran-rjags r-cran-coda r-cran-jsonlite` resolved 11 packages (R 4.3.3, JAGS 4.3.2).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.skipif(os.environ.get('JOBWATCH_TEST_R') != '1', reason='set JOBWATCH_TEST_R=1 where R/JAGS is installed')
def test_r_jags_toolchain_is_installed():
    assert shutil.which('Rscript') and shutil.which('jags')
    done = subprocess.run(['Rscript', '--vanilla', '-e', 'for (p in c("rjags","coda","jsonlite")) library(p, character.only=TRUE)'],
                          capture_output=True, timeout=120, env={'PATH': os.environ['PATH'], 'LANG': 'C.UTF-8'})
    assert done.returncode == 0, done.stderr.decode()[:300]
```

- [ ] **Step 2: Run** `JOBWATCH_TEST_R=1 <venv>/bin/python -m pytest -q -p no:cacheprovider tests/preferences/test_toolchain.py` → FAIL (`Rscript` missing).
- [ ] **Step 3: Write and run `scripts/install-r-jags.sh`.** `set -euo pipefail`; exit 0 at once if the check in the test already passes; `SUDO=sudo` unless root; try `$SUDO apt-get update && $SUDO apt-get install -y --no-install-recommends r-base-core jags r-cran-rjags r-cran-coda r-cran-jsonlite`; if `apt-get update` fails and `HTTPS_PROXY` is set, retry both commands with `-o Dir::Etc::sourcelist=<temp file>` (a copy of the Ubuntu `noble`/`noble-updates` `main universe` lines using `https://archive.ubuntu.com/ubuntu` and the keyring `/usr/share/keyrings/ubuntu-archive-keyring.gpg`), `-o Dir::Etc::sourceparts=/dev/null` and `-o Acquire::https::Proxy="$HTTPS_PROXY"`; finish by printing `Rscript --version` and `jags` version. Packages must be system-wide: `fit_store` runs `Rscript --vanilla` with only `PATH` and `LANG` in the environment. Run `bash scripts/install-r-jags.sh`.
- [ ] **Step 4: Re-run the toolchain test → PASS. Then the baseline on UNMODIFIED sampler code:** `JOBWATCH_TEST_R=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -s tests/preferences/test_local_r.py` (up to 10 minutes) → PASS; record the printed `max_rhat`, `min_ess`, elapsed time in the ledger. If it fails on unmodified code, record the evidence, continue, and treat every later sampler change as unverified.
- [ ] **Step 5: Wire CI and docs.** In `backend.yml` add a job `preference-sampler` (ubuntu-latest, 25 min; checkout, setup-python 3.12, setup-uv, `scripts/install-r-jags.sh`, `uv sync --frozen --extra dev`, then `JOBWATCH_SETTINGS=/dev/null JOBWATCH_TEST_R=1 uv run --no-sync python -m pytest -q tests/preferences`). `SETUP.md`: the install command, the three checks, "needed only to fit the preference model; everything else runs without it".
- [ ] **Step 6: If installation is impossible** (no root, no network, apt refused): skip Steps 3–4, record `R/JAGS unavailable: <reason>` in the ledger, and proceed. Every later R/JAGS step then means: Python-side tests (which need no R) plus a read-through review of the R diff; the opt-in tests in `tests/preferences/test_local_r.py` stay in the repo and the PR states "sampler changes unverified here; run `JOBWATCH_TEST_R=1 pytest tests/preferences` where R/JAGS exists". Never claim the sampler works without a real run.
- [ ] **Step 7: Commit** `build: R/JAGS toolchain script, CI sampler job and setup notes`.

### Task 3: Coverage, labels, ordering and explanations (pure)

**Files:**
- Create: `pipeline/agentic/ranking.py`, `tests/ranking_support.py`, `tests/test_ranking.py`

**Interfaces:**
- Consumes: `AgenticEvaluation`, `Requirement`, `RequirementMatch`, `EvidenceJudgment`, `StrictFrozen` (`pipeline/agentic/contracts.py`); Plan 2 `DecisionPolicy` (fields `strategy`, `focus`, `regions`, `open_questions`, `policy_hash`) from `jobwatch/candidate/policy.py` and `pipeline.agentic.location.location_verdict(quote, regions, *, remote_fit, remote_ok)`; Plan 3 `RelevanceJudgment` (`relevant`, `similarity`, `matched_hypotheses`) from `pipeline/agentic/discovery.py`. Only attribute reads (plus the one `location_verdict` call); tests pass small stand-ins.
- Produces (names fixed by the contract unless noted):
  - `IMPORTANCE_WEIGHTS`, `STRONG_MIN`, `UNRESOLVED_MAX`, `PARTIAL_CREDIT = 0.5`, `RULES_VERSION = 'ranking-rules-v1'`
  - `class Coverage(StrictFrozen)`: contract fields `weighted: float`, `demonstrated: int`, `partial: int`, `unknown: int`, `contradicted: int`, `mandatory_unmet`, `missing_documentation`, `real_gaps`, `conflicts` (tuples of requirement ids) plus additive `weighted_upper: float`, `unresolved_share: float`, `weight_total: int`, `without_judgment: int`, `mandatory_unknown: tuple[str, ...]`, `mandatory_partial: tuple[str, ...]`, `mandatory_conflicts: tuple[str, ...]`
  - `coverage(evaluation: AgenticEvaluation) -> Coverage`
  - `candidate_status(route: str, reason: str) -> Literal['eligible', 'held'] | None` (D6 as a pure function: `draft/eligible` → `eligible`, `hold/insufficient_evidence` → `held`, anything else None; `shortlist.py`, `preference_service` and Plan 6b's revised arm use it)
  - `Label = Literal['stronger_match', 'stretch', 'needs_clarification']`; `label_for(coverage, relevance, policy, *, held: bool = False) -> Label` (`held` is an additive keyword); `exclusion_reason(coverage, relevance) -> str | None`
  - `@dataclass(frozen=True) Scored(case_id: str, coverage: Coverage, relevance: str | None, label: Label, similarity: float = 0.0, focus_match: bool = False, unresolved: tuple[str, ...] = ())`; `@dataclass(frozen=True) Ranked(case_id: str, rank: int, ordering: Literal['provisional', 'personalised'], rank_reason: str, uncertainty: str, unresolved: tuple[str, ...])`
  - `rank_candidates(scored: Sequence[Scored], *, strategy: str = 'employment_first', utilities: Mapping[str, float] | None = None, answered: int = 0, minimum: int = 25) -> list[Ranked]` — the pure ordering (Plan 6b's replay calls it); `utilities` keyed by `case_id`, used only if it covers every item.
  - `class ShortlistEntry(StrictFrozen)`: contract fields (`entry_id`, `posting_id`, `run_key`, `profile_version`, `label`, `rank`, `rank_reason`, `ordering`, `uncertainty`, `evidence`, `transferable_skills`, `objective_fit`, `conditions`, `mandatory_requirements`, `unresolved`, `holistic_score`, `created_at`) plus additive `shortlist_id: str`, `posting: dict` (title, company, location, url, work_type, salary_text), `utility: float | None = None`, `coverage: dict`, `requirements: tuple[dict, ...]`
  - `explain(evaluation, cov, label, *, policy, relevance, approved_facts) -> dict` returning `evidence`, `transferable_skills`, `objective_fit`, `conditions`, `mandatory_requirements`, `unresolved` per D9.
  - Test support in `tests/ranking_support.py`: `make_evaluation(spec, *, blockers=(), legacy=(), posting_id=1, score=4.0, north_star=4.0, hours='part_time_ok', open_questions=None) -> AgenticEvaluation`, where `spec` is a list of `(requirement_id, importance, status)` with status in `demonstrated|partial|unknown|contradicted|not_applicable`; it builds validator-correct objects (stated requirements cite the ad, strong/partial matches cite an evidence item, `partial|unknown|contradicted` judgments carry an `open_question`, a contradiction carries a quote, critical/high gaps carry risk and mitigation); ids in `legacy` get no `judgment` (a historical `missing`). Also `policy_stub(strategy='employment_first', focus=(), open_questions=())` and `relevance_stub(relevant='yes', similarity=0.5, matched=())`.

- [ ] **Step 1: Write the failing tests** in `tests/test_ranking.py` (names and assertions; `cov = coverage(make_evaluation(...))`):

```python
def test_importance_weights_are_the_documented_table():
    assert IMPORTANCE_WEIGHTS == {'critical': 4, 'high': 3, 'meaningful': 2, 'preferred': 1, 'low_signal': 0}

def test_partial_counts_half_unknown_counts_zero_with_an_upper_bound():
    cov = coverage(make_evaluation([('r1', 'high', 'partial'), ('r2', 'high', 'unknown')]))
    assert (cov.weight_total, cov.weighted, cov.weighted_upper, cov.unresolved_share) == (6, 0.25, 0.75, 0.5)
    assert cov.real_gaps == ('r1',) and cov.missing_documentation == ('r2',) and cov.conflicts == ()

def test_legacy_missing_is_unknown_never_a_gap():
    cov = coverage(make_evaluation([('r1', 'high', 'unknown')], legacy=('r1',)))
    assert (cov.unknown, cov.without_judgment, cov.real_gaps, cov.conflicts) == (1, 1, (), ())

def test_contradicted_is_a_conflict_with_no_credit(): ...        # conflicts == ('r1',), weighted == 0.0
def test_mandatory_unmet_covers_blockers_and_critical():          # [('r1','critical','demonstrated'),('r2','critical','unknown'),('r3','meaningful','partial')], blockers=('r3',) -> ('r2','r3')
def test_not_applicable_is_ignored_and_empty_set_has_zero_weight(): ...   # weight_total == 0, weighted == 0.0
def test_coverage_ignores_requirement_order(): ...               # reversed spec -> equal Coverage
def test_all_unknown_is_needs_clarification():                    # Review Focus 1
    cov = coverage(make_evaluation([('r1', 'critical', 'unknown'), ('r2', 'high', 'unknown')]))
    assert label_for(cov, None, policy_stub()) == 'needs_clarification' and cov.real_gaps == ()
def test_two_thirds_demonstrated_without_mandatory_gap_is_stronger_match(): ...
def test_partial_mandatory_or_low_coverage_or_conflict_is_stretch(): ...      # three parametrised cases
def test_held_gate_result_forces_needs_clarification(): ...                   # label_for(..., held=True)
def test_uncertain_relevance_asks_only_for_career_focus(): ...                # employment_first -> stronger_match; career_focus -> needs_clarification
def test_contradicted_mandatory_is_excluded_not_labelled(): ...               # exclusion_reason == 'mandatory_conflict'; relevance 'no' -> 'relevance_no'
def test_holistic_score_and_north_star_never_change_label_or_coverage():      # same spec, score 1.0/north_star 1.0 vs 5.0 -> equal coverage() and label_for()
def test_provisional_order_is_tier_then_coverage_then_posting_id(): ...       # rank_candidates over 5 Scored; ties broken by case_id order given as posting id strings; ordering == 'provisional'
def test_career_focus_prefers_focus_matches_within_a_tier_but_employment_first_does_not(): ...
def test_personalised_order_stays_within_label_tiers():                       # Review Focus 5: a stretch with the highest utility still ranks after a stronger_match; ordering == 'personalised'
def test_incomplete_utilities_fall_back_to_provisional(): ...                 # utilities missing one case_id
def test_uncertainty_states_answered_comparisons_when_provisional(): ...      # 'of 25' appears; interval 'weighted'-'weighted_upper' appears in rank_reason
def test_evidence_lists_demonstrated_and_partial_citations_in_weight_order_with_exact_quotes(): ...
def test_transferable_skills_come_only_from_approved_facts_with_their_basis():  # facts: transferable_skill 'Stakeholder reporting' (inference) shares 'stakeholder' with a partial requirement -> ['Stakeholder reporting (inference)']; unrelated fact and a 'skill'-section fact are omitted
def test_conditions_cover_hours_location_rights_and_level(): ...
def test_location_condition_comes_from_the_verified_quote_not_the_stored_label():    # contract decision 16
    # location_fit='melbourne' with quote 'Sydney NSW' and policy.regions ('NSW',): the condition names the quote and 'in your area', never 'Melbourne'; quote 'Level 3, 1 Example St' -> 'location not stated'
def test_candidate_status_maps_gate_results():
    assert candidate_status('draft', 'eligible') == 'eligible' and candidate_status('hold', 'insufficient_evidence') == 'held'
    assert candidate_status('hold', 'verification_required') is None and candidate_status('archive', 'hard_gate') is None and candidate_status('archive', 'policy_excluded') is None
def test_unresolved_collects_open_questions_and_unstated_facts(): ...
def test_objective_fit_names_the_strategy_and_focus(): ...                    # 'employment-first' / focus term appear
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_ranking.py` → FAIL (module missing).
- [ ] **Step 3: Implement `ranking.py`** per D1–D9 exactly; pure functions, no I/O, deterministic (sort with explicit keys, never rely on dict order); `rank_reason`/`uncertainty` follow the templates in `docs/ranking-rules.md`.
- [ ] **Step 4: Run** `tests/test_ranking.py` → PASS.
- [ ] **Step 5: Commit** `feat: importance-weighted coverage, labels and cold-start ordering`.

### Task 4: Demote the holistic score behind a flag (`score_policy` on the one gate call)

**Files:**
- Modify: `pipeline/agentic/gate.py` (the last block, `if evaluation.global_score < 3.0 or evaluation.dimensions["north_star"].score < 3:` near line 352 at `ce9e342`; Plan 2 may have moved it), `pipeline/agentic/service.py` (Plan 2's `gate_current` and its call in `run_agentic_job`), `jobwatch/preference_service.py` (`pool`, its `gate_current` call), `pipeline/agentic/ranking.py`, `config/jobwatch.yaml` (commented `ranking:` block under `pipeline.agentic`)
- Test: `tests/test_agentic_gate.py`, `tests/test_agentic_service.py`, `tests/test_preference_service.py`

**Interfaces:**
- Consumes (Plan 2, `pipeline/agentic/service.py`): `gate_current(evaluation: AgenticEvaluation, *, posting: Mapping[str, Any], ad_text: str, decision_policy: DecisionPolicy | None, policy: TargetPolicy, captured_complete: bool = True, expected_run_key: RunKey | None = None, evidence_bundle: EvidenceBundle | None = None, commute_km: int | None = None) -> AgenticGateDecision`, `decision_policy_for(config) -> DecisionPolicy | None`, and `gate.decide(..., decision_policy=None, company='')`. Before editing, `grep -n "def gate_current\|def decision_policy_for" pipeline/agentic/service.py`; if either is missing, stop and report the failed precondition.
- Produces:
  - `decide(..., score_policy: Literal['legacy', 'advisory'] = 'legacy')` — `legacy` keeps the existing block verbatim; `advisory` skips it (the evaluation's `global_score` stays on the decision).
  - `service.gate_current(..., score_policy: Literal['legacy', 'advisory'] = 'legacy')` — the Plan 2 function with one more keyword, passed through to `decide`. Callers pass `score_policy=ranking_policy(config).score_policy`: `run_agentic_job` and `preference_service.pool` here, `current_runs` (Task 7) and the shortlist (Task 8) later.
  - `ranking.RankingSettings(StrictFrozen)`: `score_policy: Literal['legacy','advisory'] = 'legacy'`, `shortlist_limit: int = 50` (1..200); `ranking.ranking_settings(raw: dict | None) -> RankingSettings`; anything invalid → `AgenticError('invalid_configuration')`.
  - `service.ranking_policy(config) -> RankingSettings` reading `agentic_settings(config).get('ranking')`. **Not added to `_config()`.**

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agentic_gate.py
def test_advisory_score_policy_never_archives_on_score(evaluation, policy):
    low = evaluation.model_copy(update={'global_score': 2.0,
        'dimensions': {**evaluation.dimensions, 'north_star': Dimension(score=1.0, reason='synthetic')}})
    assert decide(low, ad_text=AD, policy=policy, score_policy='advisory').reason == 'eligible'
    assert (decide(low, ad_text=AD, policy=policy).route, decide(low, ad_text=AD, policy=policy).reason) == ('archive', 'score_below_threshold')
def test_advisory_policy_still_applies_every_other_rule(evaluation, policy): ...   # work-rights blocker still archives under advisory
# tests/test_agentic_service.py
def test_ranking_flag_is_off_by_default_and_outside_the_run_key(world):
    assert service.ranking_policy(config).score_policy == 'legacy'
    assert service._config(with_ranking(config, 'advisory')) == service._config(config)   # same RunKey for the same posting
def test_invalid_ranking_settings_are_refused(): ...    # score_policy 'x', shortlist_limit 0 -> AgenticError('invalid_configuration')
def test_score_policy_reaches_the_gate_from_every_live_caller(world, monkeypatch):
    # spy on service.gate_current: during agentic_batch_run(operation='evaluate') and during pool() with ranking.score_policy='advisory' every call carries score_policy='advisory'
    # and otherwise the same keyword set as before; with the default it carries 'legacy'
# tests/test_preference_service.py
def test_advisory_policy_lets_a_low_score_job_into_the_pool(world):
    # add(4, low=True) is archived score_below_threshold under legacy (absent from pool); with ranking.score_policy='advisory' it is present with status 'eligible' (Task 5 adds the key; here assert posting id)
```

- [ ] **Step 2: Run** those tests → FAIL.
- [ ] **Step 3: Implement** the `decide` keyword, `ranking_settings`, `ranking_policy`, and the extra `gate_current` keyword; update the two existing call sites (`run_agentic_job`, `pool`) to pass `score_policy=ranking_policy(config).score_policy`. `pool` keeps its other behaviour. No caller may call `decide` directly (Plan 2 rule).
- [ ] **Step 4: Run** `tests/test_agentic_gate.py tests/test_gate_holds.py tests/test_agentic_service.py tests/test_preference_service.py tests/test_agentic_contracts.py` → PASS (the legacy tests prove no change when the flag is off).
- [ ] **Step 5: Commit** `feat: score policy flag (advisory by choice) on the one live gate call`.

### Task 5: Preference features v3 (factual features, families, status)

**Files:**
- Modify: `jobwatch/preferences/features.py`, `jobwatch/reader.py` (add public `welcomes_visa_holders(text: str) -> bool` using the existing `_VISA_WELCOME`), `tests/preferences/test_core.py`
- Create: `jobwatch/preferences/experience.py`, `tests/preferences/test_features_v3.py`, `tests/preferences/test_experience.py`

**Interfaces:**
- Produces in `features.py` (D10): `FEATURE_VERSION`, `PRIOR_VERSION`, `NAMES` (17), `PRIOR_MEANS` (17 aligned), `FAMILIES` (22), `FAMILY_PRIOR` (zeros), `family_index(family) -> int` (1-based; unknown strings → `other`), `hourly_pay(posting: Mapping) -> tuple[float | None, float | None]`, `posting_age_days(posting: Mapping) -> int | None`, `flexible_hours(ad_text: str) -> bool`, `validate_alternative(raw) -> dict`, `validate_alternatives(alternatives, *, size: int | None = 3)` (size `None` accepts 1–100), each alternative now requires `status in ('eligible', 'held')`, `alternative_from_evaluation(evaluation, *, title, company, profile_hash, gate, posting=None, ad_text=None, candidate_years=None)` (status derived from the gate decision: `draft/eligible` → `eligible`, `hold/insufficient_evidence` → `held`, anything else `PreferenceError('current_eligible_evaluation_required')`; all new inputs optional and absent means the feature stays missing). `versions()` hashes `experience.py` too.
- Produces `experience.candidate_years(role_quotes: Iterable[str], *, as_of: date | None) -> float | None` — parses `Mon YYYY – Mon YYYY|Present` and `YYYY – YYYY|Present` (hyphen, en/em dash, `to`), year-only dates read as mid-year (1 July), `Present|current|now|ongoing` ends at `as_of` (range skipped when `as_of` is `None`), overlaps merged, rounded to 0.1, `None` when nothing parses.

- [ ] **Step 1: Write the failing tests**

```python
# tests/preferences/test_features_v3.py
def test_automation_angle_is_retired_and_priors_align():
    assert 'automation_angle' not in NAMES and 'status_held' in NAMES and len(PRIOR_MEANS) == len(NAMES) == 17
    assert PRIOR_MEANS[NAMES.index('coverage')] == 2.0 and PRIOR_MEANS[NAMES.index('hours_part_time')] == 0
def test_family_vocabulary_covers_known_families_and_collapses_the_rest():
    assert set(KNOWN_FAMILIES) | {'unknown'} == set(FAMILIES) and len(FAMILIES) == 22 and FAMILY_PRIOR == (0.,) * 22
    assert family_index('data_analyst') != family_index('accounting') and family_index('zzz') == family_index('other')
def test_hourly_pay_converts_units_and_rejects_implausible_values():
    # hour 50 -> (50,50); year 98800 -> 50.0; month 8233.33 -> ~50; day 380 -> 50; week 1900 -> 50; min 0 -> (None, None); year 60 -> (None, None); only max -> both; swapped min/max -> ordered
def test_posting_age_uses_provider_dates_only():           # observed -> None; 10 days before first_seen -> 10; negative -> 0; 400 days -> 90
def test_flexible_hours_wording(): ...                     # 'flexible working hours', 'flexitime', 'hours are flexible' True; 'hybrid' False
def test_factual_features_are_filled_from_their_sources():
    alt = alternative_from_evaluation(ev_full_time_only, title='t', company='c', profile_hash='b'*64, gate=draft_gate,
                                      posting=posting_with_pay_and_dates, ad_text='... flexible hours ...', candidate_years=4.0)
    f = alt['features']   # min_years 2
    assert f['hours_flexible_full_time'] == 1 and f['exp_shortfall'] == 0 and f['exp_excess'] == 2.0
    assert f['pay_low_c'] == 30.0 and f['age_days'] == 5 and f['status_held'] == 0
def test_experience_features_stay_missing_when_either_side_is_unknown(): ...       # candidate_years None or min_years None
def test_visa_welcome_is_one_or_missing_never_zero(): ...
def test_held_gate_result_gives_status_held_one_and_other_holds_are_refused():     # hold/insufficient_evidence -> status 'held', status_held 1; hold/verification_required -> PreferenceError
def test_validate_alternatives_accepts_sets_of_any_size_when_asked(): ...         # size=None with 5; default still 3
def test_versions_hash_includes_the_experience_module(): ...
# tests/preferences/test_experience.py
def test_candidate_years_merges_overlapping_ranges(): ...   # 'Ledger Co, Accounts Assistant, 2021 - 2023' + 'Intern, Jan 2022 - Jun 2022' -> 2.0
def test_present_needs_as_of_and_is_skipped_without_it(): ...   # 'Mar 2020 - Present' with as_of 2023-03-01 -> 3.0; without -> None
def test_unparseable_quotes_give_none(): ...
```

  Update `tests/preferences/test_core.py` helpers so `alternative()` carries `'status': 'eligible'` and the prediction fixture uses `len(FAMILIES)` instead of 5.
- [ ] **Step 2: Run** `tests/preferences/test_features_v3.py tests/preferences/test_experience.py` → FAIL.
- [ ] **Step 3: Implement** per D10. `hourly_pay` implements the table in D10 and ignores non-positive values; every feature stays `None` when its input is absent; `feature_sources` gains entries for pay, age, experience and visa wording; `missing_features` is still derived from the feature dict.
- [ ] **Step 4: Run** `tests/preferences/test_features_v3.py tests/preferences/test_experience.py tests/preferences/test_core.py` → PASS (the `test_core.py` model tests that need `model.py` changes are fixed in Task 6; if any fail only because of `FAMILIES`/`NAMES` length, leave them for Task 6 and note it in the ledger).
- [ ] **Step 5: Commit** `feat: preference features v3 with filled factual features and wider families`.

### Task 6: Model, R script and store for feature version v3

**Files:**
- Modify: `jobwatch/preferences/model.py`, `jobwatch/preferences/fit_choice_model.R`, `jobwatch/preferences/store.py`, `tests/preferences/test_core.py`, `tests/preferences/test_local_r.py`
- Unchanged: `jobwatch/preferences/choice_model.jags`

**Interfaces:**
- Produces: `prepare_data(sets)` payload gains `'family_prior': list(FAMILY_PRIOR)`; `predict_utilities(store, alternatives, context_hash) -> dict` = `{'fit_id', 'context_hash', 'utilities': {posting_id: {'utility': interval, 'family_intercept': interval}}, 'meaning': 'Posterior utility against the outside option (fixed at 0): a preference among alternatives, not eligibility or hiring probability.'}` with the same fit checks as `predict_set` (`valid_current_fit_required`, `invalid_fit_provenance`, `invalid_posterior`) and any number of alternatives (`validate_alternatives(size=None)`); `PreferenceStore.create_set(alternatives, context_hash, *, holdout: bool | None = None, migrated_from: str | None = None)` — a pinned `holdout` replaces the `len(existing) % 5 == 4` rule but still raises `split_overlap` when a posting already has the other assignment; `migrated_from` goes into the hashed payload.

- [ ] **Step 1: Write the failing tests** (`tests/preferences/test_core.py`, `test_local_r.py`):

```python
def test_prepare_data_carries_wide_vocabulary_and_family_prior(store):
    payload = prepare_data(populate(store))
    assert len(payload['families']) == 22 and payload['family_prior'] == [0.0] * 22
    assert len(payload['prior_means']) == 2 * len(NAMES) and payload['names'][-1] == NAMES[-1] + '_missing'
def test_predict_utilities_handles_any_set_size_and_matches_predict_set(): ...    # Stub fit as in the arithmetic test; 5 alternatives; for the first three, utility means equal predict_set's
def test_predict_utilities_refuses_without_a_valid_owner_fit(): ...                # status 'stale' -> valid_current_fit_required; origin 'synthetic' -> invalid_fit_provenance
def test_create_set_can_pin_holdout_and_records_provenance(store): ...             # holdout=True honoured; payload 'migrated_from' present and changes payload_hash; conflicting pin -> split_overlap
def test_r_script_reads_family_prior_from_input():
    text = Path('jobwatch/preferences/fit_choice_model.R').read_text()
    assert 'input$family_prior' in text and 'c(.5,0,0,0,0)' not in text
@pytest.mark.skipif(os.environ.get('JOBWATCH_TEST_R') != '1', reason=...)
def test_real_fit_with_wide_vocabulary_and_filled_features(tmp_path):
    # 25 synthetic sets, families drawn from 6 of the 22 levels, coverage and pay_low_c set, picks follow coverage;
    # summary['gate']['accepted'], 'alpha[22]' in summary['parameters'], len(summary['draws']['alpha'][0]) == 22,
    # store.status(ctx)['status'] == 'synthetic_valid'
```

- [ ] **Step 2: Run** `tests/preferences/` (without `JOBWATCH_TEST_R`) → FAIL.
- [ ] **Step 3: Implement** the Python changes. In `fit_choice_model.R` replace the hard-coded `a0 <- c(.5,0,0,0,0)` with `a0 <- unlist(input$family_prior); stopifnot(length(a0) == F)` and change nothing else. Keep `RHAT_MAX`, `ESS_MIN`, `MCSE_RATIO_MAX`, `MIN_TRAIN`, `MIN_HOLDOUT` as they are.
- [ ] **Step 4: Run** `tests/preferences tests/web/test_preferences.py` → PASS. With R/JAGS installed (Task 2): `JOBWATCH_TEST_R=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -s tests/preferences/test_local_r.py` → PASS for both real-sampler tests. If the gate rejects only for ESS (22 intercepts make `tau` slower), raise the test's and `fit_store`'s default iterations to 60000 (cap 100000), record the time, and do not relax any threshold. If R/JAGS is unavailable, state "sampler unverified" in the ledger and PR.
- [ ] **Step 5: Commit** `feat: preference model v3 (family prior from input, any-size utility prediction, pinned split)`.

### Task 7: Pool of current evaluations and the re-featurisation migration

**Files:**
- Modify: `jobwatch/preference_service.py`, `jobwatch/preference_cli.py`, `tests/test_preference_service.py`
- Create: `tests/test_cli_preferences.py`

**Interfaces:**
- Consumes: Plan 2 `service.gate_current` and `service.decision_policy_for(config)` with Task 4's `score_policy` keyword, Task 4 `service.ranking_policy`; Task 3 `ranking.candidate_status`; Task 5 `alternative_from_evaluation`, `experience.candidate_years`; Task 6 `create_set(holdout=, migrated_from=)`.
- Produces:
  - `@dataclass class CurrentRun: posting_id: int; captured: tuple; posting: dict; key: RunKey; result: dict; evaluation: AgenticEvaluation; decision: AgenticGateDecision`
  - `current_runs(conn, config) -> tuple[str, EvidenceBundle, object, list[CurrentRun]]` — identity (the preference `context_hash`), bundle, policy and one `CurrentRun` per posting with a full ad, a stored evaluation whose run key equals today's key and a readable gate decision (obtained with `service.gate_current(..., decision_policy=service.decision_policy_for(config), score_policy=ranking_policy(config).score_policy)`). This is the first half of today's `pool`, extracted; the run-key comparison and `validate_model_payload` handling are unchanged.
  - `pool(conn, config, *, statuses: tuple[str, ...] = ('eligible',)) -> tuple[str, list[dict]]` — builds alternatives (passing `posting`, `ad_text`, `candidate_years`) for decisions whose `ranking.candidate_status(route, reason)` is in `statuses`; the default keeps today's behaviour.
  - `refeaturise(conn, config, *, actor: str) -> dict` — `actor` must be `'owner'` else `PreferenceError('explicit_owner_required')`. For each answered owner set whose `versions` differ from the current ones, in creation order: if all three postings are in `pool(statuses=('eligible', 'held'))` and each old alternative's `run_key` equals the current one, create the new set with `holdout` pinned to the old assignment and `migrated_from=<old set id>`, then `store.pick(new_id, selected, actor='owner', request_id='migrate:' + old_id)`; otherwise count it under `not_current` or `changed`. Idempotent. Returns `{'migrated', 'already', 'not_current', 'changed'}`. Never touches an unanswered set, never creates a pick for anything not already answered.
  - CLI `jobwatch preferences migrate --confirm-owner` (refuses with `{"error": "confirm_owner_required"}`, exit 2, without the flag); not exposed anywhere else.

- [ ] **Step 1: Write the failing tests** (`world` from `tests/test_agentic_service.py`, as `tests/test_preference_service.py` does):

```python
def test_pool_defaults_to_eligible_only_and_can_include_held(world, monkeypatch):
    # three evaluated postings; monkeypatch service.gate_current to return hold/insufficient_evidence for posting 3
    assert {a['posting_id'] for a in pool(conn, config)[1]} == {1, 2}
    held = {a['posting_id']: a for a in pool(conn, config, statuses=('eligible', 'held'))[1]}
    assert held[3]['status'] == 'held' and held[3]['features']['status_held'] == 1 and held[1]['features']['status_held'] == 0
def test_pool_alternatives_carry_filled_features_from_the_posting(world): ...    # pay/age from the postings row (add salary_min/salary_unit/posted_at via SQL), age_days None when posted_at_source observed
def test_current_runs_skips_stale_and_legacy_rows(world): ...                   # changed ad text -> absent; the legacy agentic_runs table test still passes
def _answered_old_set(conn, config, monkeypatch): ...                            # create + pick a set under patched store.versions (old version), then unpatch
def test_refeaturise_copies_owner_picks_into_the_new_version(world, monkeypatch):
    summary = refeaturise(conn, config, actor='owner')
    assert summary == {'migrated': 1, 'already': 0, 'not_current': 0, 'changed': 0}
    new = [s for s in PreferenceStore(conn).list_sets() if s['versions'] == versions()]
    assert len(new) == 1 and new[0]['answered'] and new[0]['selected'] == old_selected and new[0]['holdout'] == old_holdout
    assert conn.execute("SELECT request_id, actor FROM preference_picks WHERE set_id=?", (new[0]['id'],)).fetchone() == ('migrate:' + old_id, 'owner')
def test_refeaturise_is_idempotent_and_leaves_old_sets_untouched(world, monkeypatch): ...
def test_refeaturise_skips_sets_whose_evaluation_or_ad_changed(world, monkeypatch): ...      # 'changed' / 'not_current'
def test_refeaturise_never_picks_for_unanswered_sets(world, monkeypatch): ...                # unanswered old set -> no new pick row
def test_refeaturise_requires_the_owner_actor(world): ...                                    # actor='agent' -> explicit_owner_required, no rows
# tests/test_cli_preferences.py
def test_migrate_needs_the_confirm_flag(capsys): ...         # exit code 2 and 'confirm_owner_required'; the store is not touched
```

- [ ] **Step 2: Run** `tests/test_preference_service.py tests/test_cli_preferences.py` → FAIL.
- [ ] **Step 3: Implement.** `candidate_years` gets role quotes from `bundle.items` of kind `role` and `as_of` from `intake.current_version(users.current())['confirmed_at']` (date part; `None` if absent). `create_next`/`record_pick` keep using `pool(..., statuses=('eligible',))` so the owner-facing page is unchanged. `record_pick` still compares the full alternative dict, which is stable because every v3 feature depends only on stored data (no "now").
- [ ] **Step 4: Run** `tests/test_preference_service.py tests/test_cli_preferences.py tests/web/test_preferences.py tests/preferences/test_core.py` → PASS.
- [ ] **Step 5: Commit** `feat: current-run pool with held jobs, and an explicit owner re-featurisation migration`.

### Task 8: Shortlist tables, builder and impressions

**Files:**
- Modify: `jobwatch/db.py` (append the next migration: number = `len(MIGRATIONS) + 1` at execution time), `pipeline/agentic/service.py` (`after_collect`)
- Create: `pipeline/agentic/shortlist.py`, `tests/test_shortlist.py`

**Interfaces:**
- Consumes: Task 3 `ranking` (`coverage`, `label_for`, `exclusion_reason`, `rank_candidates`, `explain`, `candidate_status`, `Scored`), Task 4 `ranking_policy`, Task 7 `current_runs`/`pool`, Plan 1 `intake.current_version`/`discovery_scope`, Plan 2 `policy_for(person)` and `service.decision_policy_for(config)`, Plan 3 `pipeline.agentic.discovery.latest_judgment(conn, posting_id) -> RelevanceJudgment | None` (contract decision 7), `PreferenceStore`, Task 6 `predict_utilities`.
- Migration tables (never created lazily): `shortlists(shortlist_id TEXT PRIMARY KEY, built_at TEXT NOT NULL, profile_version INTEGER NOT NULL, ordering TEXT NOT NULL CHECK(ordering IN ('provisional','personalised')), rules_version TEXT NOT NULL, score_policy TEXT NOT NULL, fit_id TEXT, content_hash TEXT NOT NULL, summary_json TEXT NOT NULL)`; `shortlist_entries(entry_id TEXT PRIMARY KEY, shortlist_id TEXT NOT NULL REFERENCES shortlists, posting_id INTEGER NOT NULL, run_key TEXT NOT NULL, profile_version INTEGER NOT NULL, label TEXT NOT NULL CHECK(label IN ('stronger_match','stretch','needs_clarification')), rank INTEGER NOT NULL, rank_reason TEXT NOT NULL, ordering TEXT NOT NULL, uncertainty TEXT NOT NULL, objective_fit TEXT NOT NULL, holistic_score REAL, utility REAL, payload_json TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(shortlist_id, posting_id))` plus an index on `(shortlist_id, rank)`; `shortlist_impressions(id INTEGER PRIMARY KEY AUTOINCREMENT, shortlist_id TEXT NOT NULL, entry_id TEXT NOT NULL, posting_id INTEGER NOT NULL, rank INTEGER NOT NULL, ordering TEXT NOT NULL, probability REAL, shown_at TEXT NOT NULL, surface TEXT NOT NULL, shown_day TEXT NOT NULL, UNIQUE(entry_id, surface, shown_day))`. `payload_json` holds evidence, transferable_skills, conditions, mandatory_requirements, unresolved, posting; `detail_json` holds coverage and the requirement rows.
- Produces in `shortlist.py`:
  - `build_shortlist(conn, config) -> list[ShortlistEntry]` — database-only, no model call. Returns `[]` unless `intake.discovery_scope(person)` and `policy_for(person)` exist. It re-decides every stored evaluation through `service.gate_current` (inside `current_runs`) with the same `decision_policy` as the live run, so the stored route is never trusted; labels, strategy and explanations read `policy_for(person)`. Steps: `current_runs`; the relevance of each posting is `discovery.latest_judgment(conn, posting_id)` (None, or a judgment whose `ad_hash` differs from the run key's, means "no relevance information"); exclusions by D5 (counted); `coverage`, `label_for(..., held=decision is hold)`, `explain`; ordering by `rank_candidates` with utilities from `predict_utilities` only if the preference status is `valid`; at most `ranking_policy(config).shortlist_limit` entries; persists a new `shortlists` row only when the content hash differs from the latest one (`shortlist_id = sha256(content_hash + built_at)[:32]`, `entry_id = sha256(shortlist_id + ':' + posting_id)[:32]`), inside `BEGIN IMMEDIATE`; the summary records `candidates`, `excluded` per reason, `labels`, `profile_open_questions` (`policy.open_questions`), `answered`/`minimum`. Stale or other-profile entries are never returned.
  - `latest_entries(conn) -> list[ShortlistEntry]` (contract decision 10): every entry of the newest `shortlists` row in rank order, `[]` when none; Plan 5 reads it. `load_latest(conn, *, label=None, limit=20, offset=0) -> dict | None` (shortlist header + entries from the newest row), `load_entry(conn, posting_id) -> ShortlistEntry | None` (the entry in the newest shortlist only), `record_impressions(conn, entries, surface: str, *, now=None) -> int` (INSERT OR IGNORE on the unique key; `probability` per D7 only for personalised).
- `after_collect` calls a private `_refresh_shortlist(conn, config)` after `agentic_batch_run` and also on the `daily_budget` branch (not on `busy`/`disabled`/no profile), adds `{'shortlist': {'shortlist_id', 'entries', 'ordering'}}` to its result, and catches any exception, reporting `{'shortlist': {'error': 'shortlist_failed'}}` — a shortlist failure never fails collection.

- [ ] **Step 1: Write the failing tests** in `tests/test_shortlist.py`:

```python
def test_migration_adds_the_three_tables_additively(tmp_path):
    conn = db.connect(tmp_path / 'j.db')
    assert {'shortlists', 'shortlist_entries', 'shortlist_impressions'} <= tables(conn)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == len(db.MIGRATIONS) and db.migrate(conn) == len(db.MIGRATIONS)
def test_build_lists_current_evaluations_with_explanations(world):
    # add(1), add(2); agentic_batch_run(..., operation='evaluate') with SyntheticGateway
    entries = build_shortlist(conn, config)
    assert [e.posting_id for e in entries] == [1, 2] and all(e.label == 'stronger_match' and e.ordering == 'provisional' for e in entries)
    assert entries[0].evidence and entries[0].evidence[0]['citations'][0]['quote'] and entries[0].rank_reason and entries[0].uncertainty
    assert entries[0].run_key == latest_result(conn, 1)['run_key'] and entries[0].holistic_score == 4.3
def test_build_is_idempotent_for_unchanged_inputs(world): ...             # second call -> same shortlist_id, one shortlists row
def test_stale_run_key_is_not_listed(world): ...                           # change the ad text after evaluation -> posting absent, summary excluded.not_current == 1 (Review Focus 4)
def test_low_holistic_score_job_follows_the_score_policy(world):           # add(3, low=True)
    # legacy: absent; advisory (ranking.score_policy) : present with label 'stronger_match' and holistic_score 2.7 (employment-first strategy, low alignment never rejects)
def test_relevance_comes_from_the_stored_plan_3_judgment(world, monkeypatch):     # contract decision 7
    # insert a posting_relevance row (relevant='no', ad_hash = the run key's) via discovery's own writer for posting 2: it is counted under excluded.relevance_no and not listed;
    # a row with another ad_hash, or no row, or an uncertain row (employment_first) leaves the posting listed; career_focus + uncertain -> needs_clarification
def test_shortlist_gate_follows_the_live_decision_policy(world, monkeypatch):     # decision_policy_for patched to a policy excluding posting 3's family -> absent in profile mode, present in legacy mode; both agree with run_agentic_job
def test_latest_entries_returns_the_newest_shortlist_in_rank_order(world): ...    # [] before any build; after two builds with a changed input, only the second shortlist's entries
def test_no_confirmed_profile_builds_nothing(world, monkeypatch): ...      # intake.discovery_scope -> None -> []
def test_mandatory_conflict_and_closed_postings_are_counted_not_listed(): # assemble path with make_evaluation: contradicted critical requirement -> excluded.mandatory_conflict; postings.closed_at set -> excluded.closed
def test_held_job_is_needs_clarification_and_ranks_last(world, monkeypatch): ...      # gate_current -> hold/insufficient_evidence for posting 2
def test_valid_fit_personalises_within_tiers_and_other_statuses_do_not(world, monkeypatch):
    # patch PreferenceStore.status -> 'valid' + predict_utilities (fake) => ordering 'personalised', fit_id stored, tier order preserved;
    # statuses 'synthetic_valid', 'stale', 'rejected', 'insufficient_data', 'no_data' => 'provisional' (Review Focus 5)
def test_building_changes_no_application_or_draft_rows(world): ...         # row counts of applications, drafts, agentic_packages unchanged; no llm call (transport spy never invoked)
def test_impressions_are_logged_once_per_entry_surface_and_day(world): ... # same call twice -> rows once; another surface -> new rows; probability None when provisional
def test_after_collect_refreshes_the_shortlist_and_survives_a_failure(world, monkeypatch): ...  # normal and daily_budget branches call it; a raising builder -> 'shortlist_failed', collection result intact
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_shortlist.py` → FAIL.
- [ ] **Step 3: Implement** the migration and `shortlist.py` per the interface. Transferable skills and `approved_facts` come from `intake.current_version(person)['facts']`. Per-posting work is wrapped so one unreadable artifact (`AgenticError('artifact_invalid')`) skips that posting and is counted under `excluded.unreadable`.
- [ ] **Step 4: Run** `tests/test_shortlist.py tests/test_agentic_service.py tests/test_db_maintenance.py tests/test_dedupe.py tests/test_interview_subjects.py` → PASS.
- [ ] **Step 5: Commit** `feat: explained shortlist with labels, provisional/personalised ordering and impressions`.

### Task 9: Stop re-queueing held jobs whose evaluation is current

Contract decision 11. `after_collect` puts every job that is neither `ready` nor `archived` into `pending`, oldest `updated_at` first, so each `held / evaluation_complete` job is picked again on every run: it takes one of the 20 slots and one of the day's `daily_assessments`, is re-observed over HTTP and re-screened, only to be held again with no model call. With hundreds of them the oldest 200 crowd out new postings (`unseen` is capped at 25 per run). The shortlist now re-decides these jobs from stored data, so the re-queue buys nothing until something changed.

**Files:**
- Modify: `pipeline/agentic/service.py` (`after_collect`, where `pending` is built)
- Test: `tests/test_agentic_requeue.py` (new; reuse `from test_agentic_service import SyntheticGateway, world  # noqa: F401`)

**Interfaces:**
- Consumes: `service._capture`, `service._run_key(posting_id, captured, bundle, policy, cfg, inputs, structural)`, `service.load_inputs`, `analyse_candidate`, `persistence.latest_result(conn, posting_id)` (keys `run_key`, `reason`), `liveness.latest_observation` and `observation_current(observation, *, posting_id, url, ad_hash)` (24 h maximum age), Plan 2 `decision_log.latest(conn, run_key) -> dict | None` and `service.decision_policy_for(config)`.
- Produces: `service._evaluation_current(conn, posting_id, captured, key, decision_policy) -> bool` — True only when all of these hold: the newest stored result has reason `evaluation_complete`; its `run_key` equals `key.value` (so the ad text, evidence bundle, runtime configuration and code version are all unchanged); the newest liveness observation is current; and, when `decision_policy` is not None, `decision_log.latest(conn, key.value)` carries `decision_policy.policy_hash` (the current policy has already been applied to this evaluation). `after_collect` computes the bundle, inputs and structural analysis once per call, builds each pending job's key, and drops the jobs for which `_evaluation_current` is True from `pending`. Everything else is queued exactly as before: new and `unseen` postings, a changed snapshot or profile, liveness older than 24 hours, a changed policy (queued once; the re-decision is free), `MODEL_RETRY` reasons, backoffs. If the bundle or keys cannot be built, nothing is dropped.

- [ ] **Step 1: Write the failing tests** (`ids` = the list `after_collect` passes to `agentic_batch_run`, captured by patching `service.agentic_batch_run` with a spy that returns a summary dict):

```python
def test_current_evaluation_complete_jobs_are_not_requeued(world):
    # evaluate postings 1-3 (held / evaluation_complete); first after_collect with a spy: none of 1-3 in ids; agentic_activity row count unchanged by the call
def test_changed_ad_text_requeues_only_that_job(world): ...         # adtext.save_text on posting 2 -> ids == [2]
def test_changed_profile_requeues_every_job(world): ...             # a different evidence bundle -> run keys differ -> all three queued
def test_stale_liveness_requeues(world): ...                        # observation checked_at 25 h ago -> queued; 23 h ago -> not
def test_changed_decision_policy_requeues_once(world, monkeypatch): # profile mode: a decision_log row for the old policy_hash -> queued; after the run records the new hash -> not queued again
def test_model_failures_and_other_reasons_still_requeue(world): ... # latest reason model_unavailable / snapshot_changed / posting_check_required -> queued as before
def test_new_postings_are_not_starved_by_current_held_jobs(world): # 205 current held jobs plus one new posting: the new one is in ids and no more than the cap is queued
def test_unbuildable_keys_fall_back_to_the_old_queue(world, monkeypatch): ...   # _run_key raises -> nothing dropped, no exception from after_collect
def test_a_dropped_job_is_still_on_the_shortlist(world): ...        # the held job appears in build_shortlist (Task 8) although it was not re-queued
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_agentic_requeue.py` → FAIL.
- [ ] **Step 3: Implement** `_evaluation_current` and the filter in `after_collect`; add no table and no `_config()` key.
- [ ] **Step 4: Run** `tests/test_agentic_requeue.py tests/test_agentic_service.py tests/test_shortlist.py` → PASS (the service file is slow; run it alone).
- [ ] **Step 5: Commit** `fix: do not re-queue held jobs whose evaluation is still current`.

### Task 10: Shortlist API and response-time readiness

**Files:**
- Create: `pipeline/agentic/shortlist_api.py`, `tests/test_shortlist_api.py`, `tests/outcomes/test_response_time.py`
- Modify: `pipeline/agentic/api.py` (mount next to `profile_api.mount(...)`, near line 258; add a `shortlist` object to `capabilities`), `jobwatch/outcomes/readiness.py`, `pipeline/agentic/CHAT.md`

**Interfaces:**
- Produces `readiness.response_time_readiness(conn) -> dict` — investigation only, never a fit or a rate: counts applications with an `applied_at` and a first employer reply timestamp (`application_events.at` for `to_status` in `assessment|interview|offer|rejected`, `kind in ('status','outcome_decided')`, at or after `applied_at`); everything else applied is `censored` (pending, not negative). Returns `{'status': 'insufficient_history' | 'investigate', 'responses', 'censored', 'minimum_responses': 30, 'model': 'none', 'selection_bias': 'applications are chosen by the owner, so response times describe applied jobs only', 'reason'}`; `investigate` only permits an offline survival analysis later and nothing consumes it for ranking. Tolerates tables or the `at` column being absent (`insufficient_history`).
- Produces `shortlist_api.mount(app, require, get_config)` (the read routes of contract decision 10, plus the database-only `refresh`; Plan 5's feedback, selection and prompt routes live in `pipeline/agentic/feedback_api.py` on the other paths of the contract); all routes under `/api/agent/shortlist`, person from the bearer token, work inside `users.use(person)`:
  - `GET /api/agent/shortlist?label=&limit=20&offset=0` (scope `read`; `limit` 1..50; `label` one of the three labels else 422) → `{'status': 'ok' | 'no_confirmed_profile' | 'not_built', 'shortlist_id', 'built_at', 'profile_version', 'ordering', 'rules_version', 'score_policy', 'total', 'labels': {label: n}, 'excluded': {...}, 'open_questions': [...], 'ordering_basis': {'preference': {status, n_choices, n_train, n_holdout, minimum_train, minimum_holdout}, 'response_time': {...}}, 'meaning': 'Labels and order describe evidence fit and, when personalised, learned preference among alternatives; they are not eligibility, hiring probability or advice to apply.', 'entries': [...]}`; records impressions (`surface='api'`) for the returned page.
  - `GET /api/agent/shortlist/{posting_id}` (scope `read`) → the entry with full `coverage` and `requirements` rows; 404 `{'error': 'not_found'}` if not in the latest shortlist; impression `surface='api_detail'`.
  - `POST /api/agent/shortlist/refresh` (scope `run`) → rebuilds with `build_shortlist` (no model call) unless the latest shortlist for the same profile version is under 60 s old; returns `{'rebuilt': bool, ...header}`.
  A person without a database file gets `status: 'not_built'` (never a 503). Nothing here records a choice, prepares documents or contacts anyone.

- [ ] **Step 1: Write the failing tests** (`create_api(credentials=..., config={'agentic': {'enabled': False}}, llm_factory=...)` and `Principal` as in `tests/test_profile_api.py`; shortlist rows are written directly with `shortlist.save` of `ShortlistEntry` objects built from `make_evaluation`, so no pipeline run is needed; the refresh test uses `world`):

```python
def test_get_returns_explained_entries_for_the_token_person(api): ...         # fields: label, rank, rank_reason, uncertainty, evidence[0]['citations'], transferable_skills, objective_fit, conditions, mandatory_requirements, unresolved, holistic_score
def test_requires_read_scope_and_refresh_requires_run_scope(api): ...         # no token 401; read-only token on POST refresh 403
def test_another_person_sees_only_their_own_shortlist(api): ...               # token B: status 'not_built', entries []; GET /{posting_id} of A's posting -> 404
def test_no_confirmed_profile_returns_a_status_not_stale_entries(api): ...
def test_detail_returns_coverage_and_requirement_rows(api): ...
def test_label_filter_pagination_and_validation(api): ...                     # label=stretch; limit=0 -> 422; limit=51 -> 422
def test_views_are_logged_as_impressions_once_per_day(api): ...
def test_refresh_is_idempotent_and_rate_limited(world_api): ...               # second call within 60 s -> rebuilt False, same shortlist_id; api never calls the llm_factory
def test_capabilities_advertise_the_shortlist(api): ...                       # capabilities['shortlist']['labels'] == the three labels
# tests/outcomes/test_response_time.py (own in-memory schema with an `at` column; the existing readiness tests keep theirs)
def test_no_history_is_insufficient_and_gives_no_rate(): ...
def test_pending_applications_are_censored_not_negative(): ...
def test_thirty_timed_replies_allow_investigation_but_still_no_model(): ...   # status 'investigate', model 'none'
def test_events_before_the_application_date_are_ignored(): ...
def test_missing_tables_or_columns_are_insufficient_history(): ...
```

- [ ] **Step 2: Run** the new files → FAIL.
- [ ] **Step 3: Implement** the router (sync handlers, `job_connection(config, write=True)` only for impressions and refresh, read-only otherwise; check `job_database(config).exists()` first) and `response_time_readiness`; extend `capabilities` with `shortlist=dict(labels=[...], orderings=['provisional','personalised'], rules_version=RULES_VERSION)`; add a "Ranking and shortlist" table and error list to `CHAT.md` in the style of the profile section.
- [ ] **Step 4: Run** `tests/test_shortlist_api.py tests/outcomes tests/test_profile_api.py tests/test_auth.py tests/test_deepagents_runtime.py` → PASS.
- [ ] **Step 5: Commit** `feat: native API for the explained shortlist and response-time readiness`.

### Task 11: Release check, documentation and workflow example

**Files:**
- Create: `docs/examples/ranking-shortlist.md`
- Modify: `README.md`, `pipeline/agentic/MATCHING.md`, `.github/workflows/backend.yml`

- [ ] **Step 1: Run the full suite** `<venv>/bin/python -m pytest -q -p no:cacheprovider` (about 20 minutes; `--ignore` the ten Playwright files if the `browser` extra is absent and say so). Record the pass/skip counts. A failure counts as pre-existing only with evidence: run the same test on a clean `origin/main` worktree and show it fails there too. Also run the sampler tests if R/JAGS is installed (`JOBWATCH_TEST_R=1 ... tests/preferences`) and record elapsed time and diagnostics, or write "sampler unverified" with the reason.
- [ ] **Step 2: Write `docs/examples/ranking-shortlist.md`** in the style of `docs/examples/profile-intake.md`: capture real responses with a one-off script (kept outside the repo) that drives the real API with `TestClient` over the synthetic `world` and `SyntheticGateway`: refresh, `GET /api/agent/shortlist`, a detail view, and the same call with `score_policy: advisory` showing a low-score job appear. Shorten hex ids as that example does and say plainly that no hosted model and no real person's data were used. Include the first-day (provisional) wording and what changes when a fit becomes valid.
- [ ] **Step 3: Update docs.** `README.md`: a short "Shortlist" section (flow, flags, the migrate command, R/JAGS pointer). `MATCHING.md`: the Preferences section gains feature version v3, the neutral priors, the `status_held` note and the score-policy flag; keep its test-count line unchanged unless Step 1 gives a new verified number. `backend.yml`: add `tests/test_ranking.py tests/test_shortlist.py tests/test_shortlist_api.py tests/test_preference_service.py tests/test_cli_preferences.py tests/outcomes tests/preferences` to the `synthetic-backend` file list (the sampler job from Task 2 runs the R tests).
- [ ] **Step 4: Commit** `docs: ranking and shortlist workflow example, README and matching notes`; push the branch; open the PR with: summary, exact checks and results, the owner-decisions table, rulings, the contract issues below, what is unverified (sampler if R/JAGS was unavailable; ranking quality has no independent labels, so no accuracy claim), limitations (below) and undo.

## Rollback

Revert the merge commit. Then, per person database, optionally `DROP TABLE shortlist_impressions; DROP TABLE shortlist_entries; DROP TABLE shortlists;` (the migration number stays; the tables are inert once the code is gone, so leaving them is safe). If the owner ran `preferences migrate`, the copied sets in `preference_sets` (payload `migrated_from`) cannot be deleted (immutable triggers); they are ignored after the revert because the reverted code's `versions()` equals the old hash again, so the original answered sets count as before. The flag `pipeline.agentic.ranking` is read by nothing after the revert. `scripts/install-r-jags.sh` only installs OS packages in the environment it was run in (`apt-get remove jags r-base-core r-cran-rjags r-cran-coda r-cran-jsonlite` undoes it). No timer, service or deployment is touched.

## Limitations to state in the PR

Labels and order are documented conventions, not validated accuracy; Plan 6b measures them against owner labels. Coverage depends on stored model judgments and exact citations; historical evaluations without judgments read as `unknown`. `status_held` stays at its prior until choice sets include held jobs. Impressions are logged but no selection-bias correction is applied; callback statistics and response times never influence order. Distance features remain Victoria-only wherever Plan 2/3 left them. A held job whose evaluation is current is no longer re-queued by `after_collect` (Task 9), so a newly confirmed exclusion or gate change reaches its `pipeline_state` only at its next policy-hash or liveness re-queue (at most a day, free of model calls) while the shortlist re-decides it at once from stored data.

## Self-review notes (already applied)

Spec coverage: coverage/labels/cold start (Tasks 3, 8), explained entries (3, 8), shortlist API (10), holistic score demoted (4), re-queue starvation (9), preference model (5–7), employer outcomes descriptive plus time-to-response investigation (10), selection exposure (8), R/JAGS (2, 6). Type consistency: `Coverage`, `Scored`, `Ranked`, `ShortlistEntry`, `pool(statuses=)`, `current_runs`, `gate_current` and `predict_utilities` carry the same names in every task that uses them. Review Focus lines each map to named tests.

## Contract reconciliation

Reconciled decisions of the [cross-plan contract](2026-10-21-cross-plan-contract.md) that apply to this plan; all are applied above.

- **2 One live gate call:** Plan 2 creates `service.gate_current`; this plan adds its `score_policy` keyword (Task 4) and calls it from `run_agentic_job`, `preference_service.pool`, `current_runs` and the shortlist (Tasks 4, 7, 8).
- **7 Relevance is stored:** relevance is read with Plan 3's `discovery.latest_judgment(conn, posting_id) -> RelevanceJudgment | None` (Tasks 3, 8); the earlier `load_relevance` is gone.
- **10 Ranking modules:** `pipeline/agentic/ranking.py` is pure (`IMPORTANCE_WEIGHTS`, `Coverage`, `coverage`, `label_for(coverage, relevance, policy, *, held=False)`, `Scored`, `Ranked`, `rank_candidates(scored) -> list[Ranked]`, `explain`, plus `candidate_status`, `exclusion_reason`); `pipeline/agentic/shortlist.py` holds `build_shortlist(conn, config)`, `record_impressions`, `latest_entries(conn)`; `shortlist_api.py` holds the read routes (Tasks 3, 8, 10).
- **11 Re-queue starvation:** Task 9.
- **12 Preference features:** `automation_angle` has no defined source (it appears only in `jobwatch/preferences/features.py` `NAMES` and `PRIOR_MEANS`) and is retired; `status_held` is added; `preference_picks.actor` stays `'owner'` (Tasks 5-7).
- **15 Migrations:** the shortlist tables take the next free `MIGRATIONS` index at execution (Task 8).
- **16 `location_fit`:** the location condition uses the verified quote, never the stored `'melbourne'` label (Task 3).

Additive fields: `label_for(..., held: bool = False)`; `Coverage` and `ShortlistEntry` carry extra fields beyond the contract's; none is renamed or retyped. Hard-gated and policy-excluded archives never enter the pool; score-archived jobs enter through `score_policy: advisory` and held jobs through `status='held'`, so pool statuses are `eligible|held`.
