# ADR 0007: Evidence-based ranking and explained shortlist

**Status:** Accepted and implemented on the Phase 5 branch; independently reviewed, with an intermittent browser-test validation gap recorded in the [source verification report](../audits/2026-10-22-shortlist-release.md) (2026-10-22).

## Context

Jobwatch must surface plausible opportunities while showing the evidence, unknowns and practical conditions behind each one. The inherited holistic score cannot serve as the sole suitability rule: it can reject supported employment-first opportunities and obscure missing evidence. Preference predictions are distinct from eligibility and require genuine owner choices. The approved design follows the matching direction in [INTENT.md](../../INTENT.md) and the owner's instruction to “Preserve it as a comparison baseline.” Phase 5 delivery is tracked in [GitHub issue #16](https://github.com/phroggingphrog/jobwatch/issues/16), with matching evaluation in [issue #6](https://github.com/phroggingphrog/jobwatch/issues/6).

The binding implementation contract is the [Phase 5 execution plan](../superpowers/plans/2026-10-22-phase-5-execution.md). The older [Plan 4](../superpowers/plans/2026-10-21-plan-4-ranking-shortlist.md) and [cross-plan contract](../superpowers/plans/2026-10-21-cross-plan-contract.md) remain historical background where they conflict with this accepted design.

## Decision

1. **Importance and credit.** Weights are critical 4, high 3, meaningful 2, preferred 1, and low-signal 0. Demonstrated, partial, unknown and contradicted earn 1, 0.5, 0 and 0 credit. Not-applicable requirements are omitted. Coverage reports a conservative weighted value, an upper bound that assumes unknowns are met, and the unknown share.
2. **Historical status.** Missing historical judgments map to unknown, never to an inferred gap or contradiction. Only exact, validated evidence can establish a contradiction.
3. **Mandatory requirements.** Blockers and critical requirements are mandatory. Unknown mandatory facts need clarification; partial mandatory facts make a stretch; contradicted mandatory facts exclude the job.
4. **Labels.** A held or insufficient-evidence job, empty weighted evidence, excessive unknown share, unknown mandatory fact, or relevant strategy-specific uncertainty needs clarification. Partial mandatory evidence, nonmandatory conflict, or coverage below two thirds yields stretch. Other candidates are stronger matches. The holistic score and north-star dimension do not affect labels.
5. **Exclusions.** Exclude only closed or stale jobs, current enforced relevance failures, mandatory contradictions, and outcomes excluded by canonical eligibility or confirmed personal policy. Relevance shadow/off never acts as an exclusion.
6. **Candidate pool.** Re-decide stored evaluations through the canonical gate under the current confirmed profile. Eligible drafts may be considered; insufficient-evidence holds may appear as clarification candidates. Ranking never changes a gate outcome.
7. **Order.** Provisional ordering is deterministic: label tier, requested career focus, weighted coverage, coverage upper bound, current relevance similarity, and posting ID. A valid preference fit may reorder within tiers only and must cover every candidate. Without that fit, the whole list is provisional. Callback rates and response time never affect order.
8. **Scores.** Holistic scores are advisory comparison data, with no legacy score-policy flag or former score exclusion gate in shortlist behavior.
9. **Explanations.** Use verified citations, distinguish missing documentation from gaps and conflicts, report practical conditions and unresolved facts, and explain rank and uncertainty. Transferability requires frozen evidence-matched facts; word overlap or profile inference alone is not proof.
10. **Preference model.** Keep neutral zero priors for every feature and family. Do not fabricate propensity. Feature values are populated only from their approved source; salary conversion requires explicit source hours. No fixed-hour weekly conversion is assumed.
11. **Migration and exposure.** Historical choices move only through an explicit owner-confirmed migration that preserves originals, chosen values including none, and train/holdout assignments; changed or unverifiable records are skipped. Impressions may record exposure but do not become choices or apply a selection-bias correction.

## Consequences

The first-day order is provisional and available without preference answers. Preference fits can reorder within label tiers only after their provenance and validity checks pass. Historical choices and fits do not silently become current under a changed feature schema; migration is explicit and preserves the original record and split. `status_held` has no learned effect until actual owner choices contain held alternatives. The R/JAGS toolchain was verified with synthetic fits under the unchanged acceptance gates. Ranking, shortlist read/build/refresh make no model calls.

The remaining evaluation is governed by Phase 5's plan and GitHub issues [#16](https://github.com/phroggingphrog/jobwatch/issues/16) and [#6](https://github.com/phroggingphrog/jobwatch/issues/6). Independent source review is complete. The [source verification report](../audits/2026-10-22-shortlist-release.md) records 3653 passing tests, 11 skips and one intermittent browser failure in the complete run, plus the passing browser-module rerun. Synthetic checks establish mechanics and invariants, not recommendation quality. Source verification does not establish merge or deployment.

## Non-goals

- No model call in ranking, explanation, shortlist build/read or refresh.
- Callback statistics or time-to-response estimates do not influence order.
- No selection-bias correction is applied to ranking or impressions.

## References

- [INTENT.md: Evidence matching overhaul](../../INTENT.md)
- [Phase 5 execution plan](../superpowers/plans/2026-10-22-phase-5-execution.md)
- [Original Plan 4 (historical background)](../superpowers/plans/2026-10-21-plan-4-ranking-shortlist.md)
- [GitHub issue #16: Phase 5 ranking and explained shortlist](https://github.com/phroggingphrog/jobwatch/issues/16)
- [GitHub issue #6: matching evaluation](https://github.com/phroggingphrog/jobwatch/issues/6)
