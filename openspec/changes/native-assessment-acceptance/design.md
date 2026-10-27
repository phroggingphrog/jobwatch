# Design

## Context

See proposal.md and the current assessment-failure report. Source `dd24c7a` has native candidate understanding, deterministic screening, a single native Evaluation graph, private response journaling, DeepSeek reasoning preservation and evidence-payload deduplication. Its final skill-path guidance repair is tested offline only. The last provider run used a warm digest, six native model calls, one embedding operation and one unknown-usage classifier: 67,327 charged tokens, 75.01 seconds, no canonical evaluation.

This is a follow-up to `candidate-digest-native-assessment`, not a replacement architecture. Its unchecked acceptance/release tasks remain open. The last observed live source was `9111a0d`, with assessment paused and collect-only timers active; verify that state again during apply.

The canonical reader `service.after_collect` can dispatch up to 20 selected postings and currently has no invocation assessment-count argument. The authenticated discovery start request and queued payload likewise lack that control. Running the timer unchanged cannot promise a one-posting production observation.

## Goals / Non-Goals

**Goals:** establish correct recovery and deliberate completion, measure one real warm-digest evaluation honestly, and release only with exact runtime proof. Make the production observation explicitly bounded by posting count.

**Non-goals:** new stages or supervisors, replacement frameworks, arbitrary filesystem access, guessed candidate facts or thresholds, statistical refits, candidate-bearing Jev expansion, hidden spending caps, document preparation or employer contact. Models remain canonical services accessed by the existing agents; their readiness and unavailable states remain explicit.

## Decisions

1. **Prove the observed sequence before paying again.** Use synthetic evidence to exercise requirements, batch search, further reads, refined search, an erroneous candidate filename through the skill reader, corrected evidence access and canonical completion. Include reasoning-bearing responses and recovery both before and after successful tool dispatch. Reuse existing passing cases and change code only when a focused assertion exposes a gap. Never turn production candidate material into a fixture. A new broad architecture audit or an immediate provider retry would add cost without distinguishing the known failure.

2. **Keep source permissions and improve the producing tool boundary.** Skill reads remain limited to packaged stage skills. Candidate facts remain available only through bound evidence operations. Check the existing `dd24c7a` descriptions and persisted one-correction feedback; verify repeated mistakes do not reset on resume. Retrieval returns full primary records once per actual transcript, then references; canonical access history cannot substitute for restored text. If ambiguity remains in the synthetic sequence, expose compact source/requirement identifiers or field-specific feedback at that boundary. Do not add another model, forced successful judgments or a six-turn runtime cap.

3. **Separate acceptance dimensions and all costs.** Report native model calls, classifier calls, any orchestration/child calls, embeddings, digest delta, known tokens, unknown conservative charges, wall time and outcome. Target 3–6 total per-job model calls, including classifiers; fewer than three valid calls are acceptable. Embeddings count in total paid operations, not model-generation turns. Preserve cold digest costs separately and never compare the cold 29-operation total directly with a warm evaluation. A canonical gate may hold or archive a job correctly; that is distinct from application readiness.

4. **Use one prepared acceptance attempt.** Resolve actual server person/configuration, verify the current digest without writes or model calls, verify ad liveness and native DeepSeek protocol, and refuse accidental cold digestion. Preserve paused incidents; if the chosen posting is paused, the apply run must explicitly identify and record the exact controlled retry before releasing only that incident. Use the approved gateway and existing private journals/ledgers. Run evaluate-only, validate the canonical output and gate, then repeat unchanged inputs for zero paid operations. If the ad is unavailable, report that non-paid preflight blocker rather than quietly selecting another job. A provider failure or more than six model calls blocks activation and ends paid experimentation for this apply pass.

5. **Bound the real reader observation explicitly.** Add optional `max_assessments` (strict integer 1–20) to authenticated discovery start, its queued payload and `after_collect`. Omission preserves current behavior. Include the field in existing idempotency/context checks; same request ID with different controls must conflict. Apply the limit to the final assessment selection without altering approved daily scope or saved Unlimited settings; mark remaining postings deferred rather than consuming or archiving them. This limits assessed jobs, not deterministic collection or all possible discovery-preparation costs, which must still be recorded. Do not temporarily rewrite the person's approved profile to obtain a one-job run.

## Risks / Trade-offs

- Synthetic success does not predict DeepSeek choices: require the single measured provider result, not a scripted call-count claim.
- Corrected tool feedback may add a call and still miss the target: record quality and efficiency separately and leave activation paused.
- Evaluation code changes invalidate job results: keep digest binding independent, never transplant old paid responses across changed input/protocol identities.
- A current digest may become stale before acceptance: fail preflight without buying another cold digest; identify the changed binding.
- Reader preparation can have its own paid operations: report them separately and in invocation totals; `max_assessments=1` is not a promise of one total paid call.
- Existing full-suite shard fixture errors could recur: collect tests in their normal directory context before partitioning, investigate real failures and never suppress required cases to obtain a green result.

## Migration Plan

During apply, keep reader scheduling paused and deterministic collection available. Verify the current native configuration, ledger and process state first; preserve unrelated work. Run focused tests and review the changed boundaries before the one provider acceptance. Record its quality/efficiency results against original task 4.5.

Only after acceptance, run the full reconciled release suite once and `jobwatch check --code`; address concrete failures and record exact results for original task 5.1. Back up native config/databases, reconcile reviewed source into the live branch, deploy the exact revision through the existing native services and confirm effective DeepSeek assessment-only native routing. This supplies original task 5.2, without treating a worktree commit as delivery.

Keep the reader timer paused while invoking the deployed authenticated discovery endpoint once with `max_assessments=1`. Observe one canonical outcome and verify unchanged-input reuse. Record imported source, person identity, measured charges and current collector/health status for original task 5.3, then restore automatic assessment. If the live check fails, retain its checkpoints/accounting and return assessment to the paused state. Roll back code/config only as needed; never restore whole databases over new activity. Reconcile the original change's checkboxes only from evidence, not because this proposal exists. TASK-279 remains the work-status record.
