# Ranking and explained shortlist rules

Rules version: ranking-rules-v1

**Status:** Implemented on the Phase 5 branch and independently reviewed. The [source verification report](audits/2026-10-22-shortlist-release.md) records the complete run and its intermittent browser-test failure. PR integration and deployment remain separate.

## D1. Importance weights and coverage

Each applicable requirement has a weight: critical 4, high 3, meaningful 2, preferred 1, and low-signal 0. Demonstrated evidence earns full credit, partial evidence earns one half, and unknown or contradicted evidence earns no credit. `not_applicable` requirements are omitted.

`weighted` is credited weight divided by total applicable weight. It is the conservative lower bound. `weighted_upper` adds all unknown weight before dividing. `unresolved_share` is unknown weight divided by total. When total weight is zero, all three values are zero. These are documented conventions, not fitted measures.

**Example:** one demonstrated high requirement (weight 3) and one unknown meaningful requirement (weight 2) gives `weighted = 3/5 = 0.60`, `weighted_upper = 1.00`, and `unresolved_share = 0.40`.

## D2. Requirement status and history

Use the stored judgment when present. For historical evaluations without judgments, map `strong` to demonstrated, `partial` to partial, and `missing` to unknown. A historical missing match is not proof of a skill gap or contradiction. Ignore `not_applicable`. Sort reported requirement IDs by descending weight and then ID.

Unknown requirements with positive weight are missing documentation. Partial requirements with positive weight are real gaps. Contradictions are conflicts and require the validated contradictory quote.

## D3. Mandatory requirements

A requirement is mandatory when it is a blocker or its importance is critical. A mandatory requirement is unmet unless it is demonstrated. Unknown mandatory requirements need clarification; partial mandatory requirements make the job a stretch; a contradicted mandatory requirement excludes the job from the shortlist.

**Example:** a critical unknown language requirement is mandatory and unresolved. A meaningful blocker with partial evidence is also mandatory and unmet.

## D4. Labels

Apply the first matching rule:

1. `needs_clarification` when the gate holds for insufficient evidence, there are no weighted requirements, unknown weight exceeds one third, a mandatory requirement is unknown, or relevance is uncertain for a non-employment-first strategy.
2. `stretch` when a mandatory requirement is partial, a non-mandatory requirement is contradicted, or weighted coverage is below two thirds.
3. `stronger_match` otherwise.

The two-thirds and one-third boundaries are versioned presentation conventions. The holistic score and `north_star` do not affect coverage or labels. Employment-first does not ask for clarification solely because relevance is uncertain; its purpose is to search broadly across related work.

**Stronger match example:** two demonstrated high requirements, no unknowns or mandatory gaps: coverage is 1.00 and the label is `stronger_match`.

**Stretch example:** one demonstrated meaningful requirement (weight 2) and one partial high requirement (weight 3) give coverage `(2 + 3×0.5)/5 = 0.70`; when the partial requirement is mandatory, the label is `stretch`.

**Needs clarification example:** one demonstrated high requirement and one unknown meaningful requirement: coverage is 0.60 and unresolved share is 0.40, so it is `needs_clarification` even without a demonstrated gap.

## D5. Exclusions

Exclude a posting when its mandatory requirement is contradicted, current relevance is `no`, it is closed, or its stored run is no longer current. Count exclusions by reason. Hard-gated and confirmed-policy-excluded jobs are not shortlist candidates. Relevance `no` excludes only when relevance enforcement is on and the judgment matches the current ad and search plan; relevance shadow or off does not exclude.

## D6. Candidate pool

Re-decide stored evaluations through the canonical gate using the current confirmed policy. A current `draft/eligible` decision enters as eligible. A current `hold/insufficient_evidence` decision enters as held and is labelled `needs_clarification`. Other routes are absent. A held job is never made eligible by ranking.

## D7. Ordering

Provisional ordering is always available. Sort by label tier (`stronger_match`, `stretch`, `needs_clarification`), then by confirmed career-focus relevance when career focus is requested, then by weighted coverage descending, upper-bound coverage descending, current relevance similarity descending, and posting ID ascending.

Personalised ordering is available only with a valid current preference fit and utilities for every candidate. It keeps the same label tiers and sorts within each tier by posterior-mean utility, then the provisional keys. Otherwise the entire list remains provisional. A preference model cannot lift a stretch above a stronger match. Callback history and response time never affect order. No callback or selection-bias correction is applied.

**Provisional example:** two stronger matches sort by coverage, then upper bound, then similarity, then posting ID; all stretch entries follow both, and clarification entries follow stretches.

**Personalised example:** if a stretch has higher estimated utility than a stronger match, it stays below the stronger match; its utility may reorder it only among other stretches.

## D8. Score policy and model boundary

Holistic and alignment scores are advisory comparison fields; no legacy score threshold or score-policy flag is used to decide shortlist membership or ranking. The shortlist reads current stored evaluations, evidence, policy and valid stored preference results. Ranking, explanations, read, build and refresh make no model calls. No paid work is triggered by a shortlist read or refresh.

## D9. Explanations and evidence

Explanations are deterministic and use verified stored citations:

- **Evidence:** “The ad asks for {requirement}; {exact candidate quote} supports it ({demonstrated/partial}).” Include at most six demonstrated or partial requirements, ordered by weight.
- **Transferable skills:** “{approved fact} ({basis}) may transfer to {matched duty}.” Use only frozen facts already matched to evidence; word overlap or profile inference alone is not proof.
- **Objective fit:** “This fits your {employment-first/career-focus/balanced} search because {confirmed focus or supported hypothesis}; weighted evidence coverage is {weighted} ({weighted}–{weighted_upper} with unknowns).”
- **Conditions:** “The ad states {verified hours, location, work-rights wording, level/years, programme, or legitimacy condition}.” Location wording comes from the verified ad quote and canonical location check, never a stored location label.
- **Mandatory requirements:** “{requirement text} [{status}].”
- **Unresolved facts:** “Still unknown: {open question or unstated material ad fact}.”
- **Rank reason:** “Ranked {rank} as {label} with coverage {weighted}–{weighted_upper}; {ordering basis}.”
- **Uncertainty:** “Order is provisional; {answered} of {minimum} owner comparisons are available.” When personalised, identify the valid preference fit and retain coverage uncertainty.

Citations must resolve to approved canonical evidence and the frozen ad. Missing facts remain questions and are never filled by model inference.

## What this does not claim

Labels and ordering are evidence-based conventions, not matching accuracy, hiring probability, eligibility or advice to apply. The thresholds require later review against owner labels. A stored fit is not a qualification verdict. No model call, response-time prediction, or selection-bias correction is part of ranking.
