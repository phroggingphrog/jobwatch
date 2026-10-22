# Profile preference audit — 2026-10-22

Owner direction:

> pre filter shouldn't be hardcoded

> yeah can you do an audit where preferences is hardcoded because it shouldn't profile preferences behavior shouldn't be hardcoded

This is a source and call-site audit of the current backend, collection, ranking,
writing and retained legacy modes. Two Sol 6.1 workers traced collection and
assessment/model paths; LUNA inventoried the remaining surfaces. The parent
checked the findings and implements the location correction in the current
discovery phase. No person's runtime records, live provider, fitting or deployed
service were inspected. A setting in shared YAML is not inherently personal: the
problem is applying it as a person's preference without their confirmation.

## Current-phase correction

`Rules.location_rule` now takes regional admission from the current person's
confirmed `DecisionPolicy` through `discovery_gate.profile_location_rule`, using
the canonical location classifier. Sydney, Melbourne and Perth receive the same
logic. Remote work uses the confirmed remote preference. Missing location
preferences and unresolvable posting locations proceed as unknown; they do not
default to Victoria or establish eligibility. This applies before collection
matching and before full-ad ingest, without needing `search_plan: true`.

The old regional configuration path remains only when no approved policy exists;
automatic discovery itself still requires a confirmed profile and search scope.
This correction does **not** replace the retained legacy final gate described
below. Synthetic regression tests cover different regions, remote restrictions,
unknowns and the ingest call site.

## Original findings at audit time (before remediation)

| Priority | Surface and evidence | Current effect | Required repair |
|---|---|---|---|
| High | `pipeline/agentic/service.py:decision_policy_mode`, `gate.py:_legacy_person_checks`, commented `decision_policy` in `config/jobwatch.yaml` | Agentic execution still defaults to the legacy final gate: Victoria, 50 km commute and entry/junior assumptions. A profile-driven prefilter does not stop this later gate rejecting another person's suitable work. | Complete profile-gate parity and compare stored decisions against the frozen baseline, including rejected work; make the canonical confirmed profile the normal policy through explicit source/release changes. No live flag was changed here. |
| High | `pipeline/agentic/gate.py:decide` score checks; `service.py:evaluate_job` call | Both legacy and profile paths archive `global_score < 3` or `north_star < 3`. Confirmed `strategy`/`focus` do not control this rule. Employment-first users can lose supported jobs over career direction. | Plan 4: evidence-based coverage and explained ordering; preserve the holistic scores as comparison data, and validate before promoting new exclusions. |
| High | `jobwatch/candidate/contracts.py:MINIMUM_EXCLUDED_CODES`, `TargetPolicy`; `analysis.py:analyse_candidate`; `service.py:run_agentic_job`; `model_insights.py`; `preference_service.py` | Permanent occupation codes `431111` and `541211`, plus reference `excluded` annotations, hide occupations for everyone in structural/advisory paths. `profile_target_policy()` exists but is not used there. | Remove personal desirability annotations from reference meaning, apply only confirmed exclusions, and version affected structural/preference inputs. The new field-hypothesis loader already ignores the bundled `excluded` flag. |
| High | `jobwatch/collectors/ats_workday.py:collect` and `row_to_posting`; `Rules.title_relevant`; `discovery.recall_filter` | Legacy title filtering or lexical plan matches can decide whether ambiguous-location Workday listings receive a detail fetch. Some listings disappear before full-ad semantic assessment. | Keep bounded acquisition, but make title terms a prioritization aid rather than an irreversible personal-fit decision; retain unknown listings for later detail retrieval. |
| High | `pipeline/agentic/gate.py:_profile_person_checks`, `_hours_signals`, `ENTRY_MAX_YEARS` | Junior preference still becomes a fixed two-year experience cutoff. Any numeric hours limit can cause full-time work to be rejected, even where explicit weekly hours could fit the confirmed fortnightly limit. | Compare actual advertised requirements to approved experience and applicable hours, retaining unknowns. Requested job level is not a maximum amount of experience the person may have. |
| High | `pipeline/agentic/gate.py:_rights_checks` and combined `citizen_or_pr` input | Different citizenship, residence, clearance and sponsorship situations are compressed into fixed blocking rules. PR can suppress a citizen-only restriction; a supported clearance/sponsorship condition is not independently matched. | Dedicated eligibility repair: separate approved statuses and employer requirements. Preserve hard eligibility controls; missing facts must remain unresolved rather than being guessed in either direction. |
| Medium | `jobwatch/preferences/features.py:PRIORS`, `FAMILIES`; `fit_choice_model.R` accounting intercept; `model.py:fit` | Every person's learned preference model starts with directional priors favoring part-time, entry work and nearby commutes, and an accounting intercept. Coarse families collapse unrelated careers. Readiness tests keep these advisory, but do not make the priors personal evidence. | Plan 4: neutral cold-start taste priors, broader family vocabulary, versioned re-featurisation; no automatic live retraining or invented owner choices. |
| Medium | `config/searches.yaml`, `config/feeds.yaml`; `jobwatch/collectors/reddit.py`; `occupations/plan.py` | Default searches remain static until a derived plan is enabled. Reddit geography is not overlaid from the confirmed scope. Only the first planned location reaches aggregator queries. | Derive all supported collector scopes from confirmed locations/directions, rotate multiple locations within limits and make unsupported collectors explicit. First-location-only behavior is a documented current Plan 3 limit, not fulfillment of all confirmed locations. |
| Medium | `occupations/plan.py:searches_overlay`, `collectors/jobspy_src.py:collect`, `collectors/ats_oracle.py:_locations` | A copied remote-search block can survive a profile that refuses remote work. JobSpy has a literal Melbourne fallback. Oracle sorts Victorian locations first before truncating saved location text. | Clear incompatible remote configuration, preserve unknown home instead of injecting a city, and preserve all relevant locations without Victoria-first preference. |
| Medium | `jobwatch/onboarding.py:write_profile`, `fieldgen.py:generate_config`; `web/queries.py:fit_score` | Older onboarding can turn missing level into `entry`; generated rules assume senior-title/experience exclusions. The board's fallback score adds 15 for entry-level work. | Unknown intake facts stay unknown; generated preferences need confirmation; replace taste bonuses with approved preferences or clearly provisional neutral ordering. These paths are separate from native profile intake. |
| Medium | `pipeline/agentic/draft.py` and `review.py` writing prompts | Shared graduate-template, praise/eagerness and content-selection instructions apply to every writer. Some preserve earlier owner writing directions; they are not invented candidate facts. | Separate factual/verification requirements from each person's approved style and template options. Do not silently reverse existing owner instructions while changing their scope. |
| Legacy | `jobwatch/reader.py`, `recall.py`, `pipeline/nodes/gate.py`, `nodes/evaluate.py` | Reader and deterministic pipeline modes retain restricted-rights, junior/graduate, full-time and regional assumptions. They are not the checked-in agentic dispatch path but remain selectable/manual paths. | Route their person-dependent checks through canonical profile policy or retire the paths explicitly; an agentic-only repair is not pipeline-wide parity. |

## Important distinctions

- Collection regex rejection controls matches and alerts, but agentic ingest scans
  all recently stored postings. Do not report every title regex as a final
  exclusion. Workday can drop a listing before storage, which is materially worse.
- SmartRecruiters can defer full text without dropping the listing. JSON-LD title
  checks prioritize links; finite detail caps can crowd out other links.
- AU-only acquisition is a stated product boundary, distinct from assuming a
  person's home is Melbourne. Factual geographic names/coordinates and occupation
  classifications should not be deleted as though they were preferences.
- The structural 60/40 similarity heuristic, callback Beta prior, convergence and
  held-out requirements, budgets, citations, isolation and exact approvals are
  model/operational controls. Their validity needs its own evidence, but they are
  not all personal preferences. The reference occupation `excluded` flags are a
  personal-policy exception.
- A 48-hour web timestamp cutoff only chooses hours versus days for display.
  It is unrelated to work rights. Interview/follow-up/browser prompts inspected
  here did not embed a fixed candidate home or career preference.
- Native chat prompts call canonical operations and approved facts; replacing the
  chat client would not repair the shared gate or collector issues.

## Original acceptance criteria

Finish this discovery phase with the location correction, audited limitations,
synthetic verification and no deployment. Track the remaining repairs separately:
canonical eligibility first, then Plan 4 ranking/model migration, collector scope
parity and person-approved writing/legacy-path parity. Do not silently relabel
those future changes as completed by this audit.

Each repair must prove at least two people with different preferences receive
different appropriate behavior, a missing fact is not converted to a preference,
confirmed exclusions are respected, and an agent cannot write human choices.
Exclusion-policy promotion must include the existing frozen-input comparison;
synthetic checks alone do not establish recommendation quality.

Undo this audit document by reverting its source commit. The audit itself changed
no private state. Undo the location correction by reverting its source change;
no profile migration or service change is involved.


## Remediation of every finding in #14

Owner's subsequent instruction:

> fix all of the issues then merged into main

The original table above preserves what the audit found. The following records
the completed source repairs; release verification and merge results are recorded
below separately. None of these changes activates a service or changes private records.

| Finding | Source repair | Synthetic evidence |
|---|---|---|
| Legacy final gate/default | `service.decision_policy_mode` defaults to canonical profile; historical legacy config aliases the same path. `candidate.eligibility` is shared by native gate, retained reader and deterministic pipeline. No live fixed-policy branch remains. | `test_agentic_gate_policy`, `candidate/test_eligibility`, `test_personal_legacy_gate` |
| Career/holistic thresholds | Gate scores stay advisory; evaluator receives confirmed strategy/focus. Interview preparation after an owner's transition no longer has a career-score cutoff. | `test_profile_gate_comparison`, `test_preference_service`, `test_interview_service` |
| Structural donor exclusions | No mandatory occupation codes or reference/person-file exclusions in current analysis; default targets project only confirmed family rules. Historical payloads remain readable. | `candidate/test_policy`, `candidate/test_contracts`, `candidate/test_analysis` |
| Workday title loss | Titles prioritize bounded rotating detail retrieval. Unknown listing locations remain unknown and listings remain stored for assessment. | `test_profile_collectors`, `test_collectors` |
| Junior years/hours | Desired seniority never imposes a two-year experience cap. Primary-evidence matching checks qualifications. Actual advertised hours meet confirmed numeric limits; unknown material hours hold. A program flag cannot waive a numeric restriction. | `candidate/test_eligibility`, `test_agentic_gate_policy`, `test_profile_gate_comparison` |
| Rights/clearance/sponsorship | Independent approved statuses; quotes must corroborate requirements. Citizenship is not inferred from PR or a combined disjunction. Clearances, sponsorship and contradictions remain distinct; unknown material facts hold. | `candidate/test_eligibility`, `test_gate_holds`, `test_agentic_gate_policy` |
| Taste priors/families | Neutral zero-mean priors, canonical family vocabulary, new model/feature/structural identities. Confirmed-profile context changes mark immutable old choices/fits stale. No automatic refit. | `preferences/test_profile_neutral`, `test_preference_service`, R syntax parse |
| Search/feed scope | Every confirmed scope overlays inherited searches and Reddit geography, including dry runs, with unpaid approved directions when no current semantic index exists. All supported locations rotate within request caps. | `test_profile_collectors`, `occupations/test_plan`, `test_collect_pipeline` |
| Remote/home/provider defaults | Refused remote searches cleared; no JobSpy Melbourne fallback, no invented Jora place, no Oracle VIC-first truncation. | `test_profile_collectors`, `test_collectors` |
| Older onboarding/generation/board | Missing level unknown; generated rules omit unstated personal constraints; no entry bonus. Known mid/senior work is not labeled unstated; labels name confirmed scope. | `test_onboarding_wrangle`, `test_fieldgen`, `web/test_neutral_board_score` |
| Writing style/template | Neutral factual defaults, explicit approved style/template choices, selected renderer order honored. Examples are opt-in, per-person and protected against ancestor symlinks; legacy drafting/review share the controls. Factual/PDF checks remain mandatory. | `test_personal_writing_preferences`, `test_careerops_cv`, apply tests |
| Retained paths | Reader/recall prompts use approved policy, no APS-title citizenship inference or inherited score caps; full-ad eligibility delegates canonical policy. Deterministic gate follows the same policy. | `test_reader`, `test_pipeline`, `test_personal_legacy_gate`, `test_gate_holds` |

Additional review repairs bind run and taste-model identity to the complete immutable
approved profile. New confirmation during a job or cached READY public recheck invalidates
the snapshot. Remote labels cannot bypass constraints without verified ad evidence;
recorded unknown seniority cannot turn into a schema placeholder. Fingerprints for frozen
baseline replay include canonical eligibility and projection sources. Historical baseline
manifests keep their original source inventory on load.
Final adversarial review also removed foreign-jurisdiction status inference: presence
in Australia is not Australian citizenship, negative foreign citizenship is not negative
Australian status, and mixed-country alternatives remain unresolved. Repeated Boolean
keywords and repeated identical clearance quotes retain the reader stress-test time limits.

### Interpretation and remaining verification limits

The frozen test fixture preserves the old **gate logic** with synthetic inputs, including
jobs the former gate rejected in Sydney/Perth or for low career scores. It imports current
ad scanners and contracts, so it is not a bit-for-bit reproduction of an earlier deployment.
These comparisons establish the intended policy change, not recommendation quality over
live archived jobs. No candidate records or live provider/model calls were used as fixtures.

AU product scope, geographic reference data, operational request/token caps, evidence
citations, factual/PDF review, human choices and exact Submit approvals remain controls.
Commute distance coverage remains limited to available reference data; missing distance
with a material confirmed limit holds. Unstated or ambiguous legal conditions require
clarification rather than an inferred legal answer. Configured ATS/RSS/subreddit source
inventories remain explicit acquisition coverage; this does not discover new providers.
No real taste model was refitted and no historical choices or posteriors were rewritten.

Undo the remediation by reverting its merge/source commits. No destructive schema or
private-data migration is required; historical artifacts remain immutable. Such a revert
restores the earlier policy behavior. Source merge does not establish deployed behavior.

### Release verification, 2026-10-22

The complete stable-source command `/tmp/jobwatch-phase4-venv/bin/python -m pytest -q --tb=short`
finished with **3,492 passed, 10 skipped, 6 warnings in 974.15 seconds**. The skips
remain optional/known test gaps; in particular this does not verify a real statistical
fit, live provider/model behavior or deployment. Warnings concern dependency configuration
and the test client's deprecated per-request cookie API.

The final independent read-only eligibility review cleared its eight exact jurisdiction
probes and **308 focused regressions**. The reader module separately passed all **655**
cases with its original stress-test time limits. `jobwatch check --code` passed with an
isolated invented profile; the R model source parses, and `git diff --check` passes.
Development runs interrupted for fixes are not counted as completed release evidence.

PR #15 carries these source repairs and Phase 4 discovery into main, closing #13 and #14
when merged. GitHub Actions could not start steps because account billing/spending limits
blocked execution; this is separate from the completed local release checks. No billing,
services, timers, model fitting, candidate records or application submission were changed.
Undo by reverting PR #15's squash merge; historical runtime artifacts need no destructive
migration. Merge does not establish deployment or live recommendation quality.
