# Phase 5: ranking and explained shortlists — implementation plan

Owner approved the full plan in chat on 2026-10-22. This supersedes conflicting
legacy score-policy, personal-prior and unsupported factual-feature assumptions in
2026-10-21-plan-4-ranking-shortlist.md and the cross-plan contract.

Goal: explain supported evidence, uncertainty and rank through the native API.
Architecture: pure ranking, current stored evaluations, per-person additive
shortlist persistence and read/list/detail + unpaid refresh. Existing canonical
eligibility, approved profile, evidence, budgets and human approvals remain authoritative.
Tech stack: existing Python/FastAPI/SQLite and R/JAGS; synthetic tests only.

## Tasks and ownership

1. LUNA: ADR 0007, ranking rules, glossary, reconcile plan/cross-contract/README/MATCHING docs.
2. Sol 6.1: pure ranking.py + tests/ranking_support.py and test_ranking.py.
3. Sol 6.1: preference feature v4, observed sources/missingness, neutral model utility API and tests.
4. Sol 6.1: explicit historical-choice migration CLI/store integration, preserving originals/splits.
5. Parent: current-run pool, shortlist persistence, scheduler integration/freshness.
6. Parent: native API, response-time readiness, integration tests.
7. Independent Sol 6.1 review; parent integrates fixes, full stable-source release test, reviewed PR.

Worker writes are disjoint. Parent owns shared integration and commits. No worker
runs full suite: focused RED/GREEN checks each; parent runs release suite once stable.
Local codex/ branch from main cd8d8fc; no service/timer/deployment/live-data action.

## Binding behavior

Weights critical/high/meaningful/preferred/low_signal=4/3/2/1/0; credits
1/.5/0/0 for demonstrated/partial/unknown/contradicted; NA omitted. Upper bound adds
unknown weights only. Mandatory=blocker or critical. Existing thresholds2/3 strong,
1/3 unknown are versioned evidence presentation conventions, never exclusion gates.
Held, no weighted facts, mandatory unknown, >1/3 unknown, or uncertain relevance with
non-employment-first => needs_clarification; mandatory partial, nonmandatory conflict,
coverage<2/3 => stretch; else stronger_match. Sort tier, career-focus match when
requested, coverage desc, upper desc, current similarity desc, posting_id asc.
Valid genuine current preference fit can reorder within tiers only; otherwise whole
list provisional. Preserve all zero priors and canonical families. No callback ordering.
Verified citations only. Transferable proof comes from frozen evidence-matched facts;
word overlap and profile inference are not proof. Missing facts stay questions.

Use service.gate_current; eligible draft or hold/insufficient_evidence only. Mandatory
contradictions cannot be actionable. Exclude closed/stale/verification failures and
confirmed exclusions. Relevance:no excludes only under relevance:on with current ad
and plan, never shadow/off. Store and validate complete approved-profile hash,
evidence/ad/run/policy/rules/config/model context; revalidate before saving/returning.
No model calls in shortlist build/read/refresh. No run-key/implementation bump for
presentation-only changes; preference feature version changes invalidate fits only.

Feature v4: remove automation_angle, add status_held; preserve neutral priors.
Verified flexible-hours evidence, positive visa-welcome1 or missing; salary only AUD
hourly or when explicit source hours establish conversion (no38h/week assumption),
provider age at first_seen frozen0..90 days. Tenure only exact approved role dates,
union overlaps with Present pinned to approved confirmation date; specialist years
require matching occupational scope, otherwise exp_shortfall/excess stay missing.
Sources/missingness retained. Genuine fit thresholds20train/5holdout and existing
sampler diagnostics unchanged. Synthetic sampler checks never fit live records.

Migration command preferences migrate --confirm-owner only: genuine answered picks,
unchanged verifiable complete profile/ad/evidence/evaluation provenance; preserve
selected including none, holdout split, migrated_from, originals; skip changed or
unverifiable records; idempotent. No live invocation or automatic refit.

## Integration interfaces

ranking.py exports Coverage, coverage, Label, label_for(coverage,relevance,policy,*,held=False),
Scored, Ranked, rank_candidates(scored,*,strategy,utilities=None,answered=0,minimum=25),
exclusion_reason, candidate_status, explain, ShortlistEntry and RULES_VERSION.
Use the original Plan4 typed fields, with additive identity fields if needed.

preference_service.current_runs(conn,config) returns(identity,bundle,policy,CurrentRun[]);
CurrentRun fields posting_id,captured,posting,key,result,evaluation,decision.
pool(conn,config,*,statuses=('eligible',)) keeps existing default callers, optional held.
Parent owns preference_service.py; migration worker puts implementation in a separate
jobwatch/preferences/migration.py consuming current_runs/pool and extends preference_cli.py.
Features alternative_from_evaluation keeps old kwargs and adds optional posting/ad_text/
approved context; returns explicit status, provenance and missing features. Never mark
held jobs eligible. Model predict_utilities(store,alternatives,context_hash) arbitrary
bounded list, genuine valid fit only, per-posting posterior utility intervals.

Add migration-only tables shortlists/shortlist_entries/shortlist_impressions (not lazy
ensure). Snapshot content hash covers all eligibility/freshness inputs and whole catalog
including closures and newly evaluated jobs; unchanged builds idempotent. No stale
entries returned after input changes. Refresher normal and daily-budget collection
branches; errors isolated. Skip unchanged completed assessments only while run/policy
matches and liveness current; no starving retries/new/stale jobs.

GET /api/agent/shortlist read: label filter, limit20 default1..50, offset>=0;
GET /api/agent/shortlist/{posting_id} read: full detail or404;
POST /api/agent/shortlist/refresh run: database-only rebuild;60s reuse only when whole
snapshot unchanged. Missing DB=>not_built; missing profile=>no_confirmed_profile;
changed inputs=>stale empty. Bearer selects person, no client filesystem paths.
Actual impression rank/surface/day dedup, probability NULL for deterministic display.
Response-time readiness descriptive:30 timed responses permits investigation, pending
censored, no predictive ranking. No GET creates choices/fit/package or triggers paid work.

## Verification and delivery

Focused tests: labels/boundaries/historical missing, exact citations/contradictions,
ties, missing factual inputs, invalid fits, immutable migration/provenance/splits,
identity, changed profile/ad/closure, zeroLLM, API pagination/scope/throttle, scheduler
retry/liveness/budget paths, impressions not choices, pending outcomes censored.
Then complete release regression, code/settings validation, independent review and
one PR with actual evidence, limitations and rollback. No automatic merge/deployment.
Undo source changes; preserve historical choice/fit/shortlist records. Phase6 feedback/
selection and Phase7 blind quality evaluation remain separate. Tests are not quality
or deployment evidence.

## Source delivery evidence

Implementation and independent review are complete on the phase branch. The
[source verification report](../../audits/2026-10-22-shortlist-release.md) records
the actual full-run result, focused checks, synthetic sampler checks, remaining
browser validation gap and rollback. Merge, live migration/fitting and deployment
remain separate operations.
