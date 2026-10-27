# Design

## Context

See proposal.md and docs/architecture/assessment-failures.md. Live9111a0d wraps the legacy evaluator; pending7a37865 plus edits replaces it but removed separate candidate understanding. Four DeepSeek experiments failed. A saved live summary passes its terminal schema yet fails the canonical4000-character section limit.

## Goals / Non-Goals

Goals: reusable evidence/model-aware understanding before filtering; cheap clear exclusions; direct native canonical assessment; recovery without duplicated paid work; measured live delivery.

Non-goals: all career stages at once, automatic statistical refitting, new provider routes/dependencies, new spending caps, document/submission authority for assessment, restoring archived hardcoded personal preferences.

## Decisions

1. Use a dedicated native-tool Candidate Understanding agent with existing evidence, structural, preference and outcome services. Persist cited findings, approved constraints, gaps, model status/provenance and screening-policy references. Reject a prose-only digest or the previous uncached per-job candidate loop: neither supplies reusable accountable understanding. Applicable Jev capabilities are represented with route status; candidate-bearing Jev stays unavailable without approval. Job-specific predictions run only with posting inputs.

2. Cache per person and relevant profile/evidence/policy/reference/model/history/skill/schema versions. Distinguish stable evidence understanding from refreshable model observations, so new history need not re-read every evidence source. Reuse existing private persistence/checkpoint mechanisms; journal successful paid replies before tool execution. A cache hit cannot bypass freshness or current policy checks.

3. Keep prescreen deterministic and consistent across collector, reader and direct API paths. Use clause-aware keyword patterns, explicit years parsing and existing distance calculations where available. Replace implicit level-to-years heuristics with explainable parameters supported by approved actual experience and strategy; actual experience alone is not an invented absolute job threshold. Preserve negation, optional years, program exceptions, remote restrictions and unknown locations. Existing approved policy can be projected automatically; new personal exclusion choices require confirmation.

4. Keep the pending single native Evaluation graph and DeepSeek assessment-only routing. Remove irrelevant filesystem tools, redundant supplied-ad reads and repeated inventory payloads. Focus extraction tools on coherent outputs, bind hashes/identity in code where possible, freeze requirements and batch retrieval. Share canonical validators with completion tools. Schema/citation faults get compact field-specific feedback with at most one correction per affected boundary before a useful held checkpoint; do not rerun the full job or weaken citations. No hard six-call cap and no legacy fallback.

5. Preserve models as calculations accessed by agents, not extra general supervisors. Persist digest counts separately; show cold cost, reused per-job cost and amortized cost. Include public classifiers and embeddings as distinct paid-operation purposes and orchestration/child calls in totals. Unknown usage remains conservatively charged, clearly distinguished from actual measured tokens.

## Risks / Trade-offs

- Digest staleness or opaque exclusions → input manifests, citations, deterministic policy projection and explicit advisory suggestions.
- Smaller schemas add tool boundaries → batch operations and measure complete-job calls; do not promise reduction from source shape alone.
- Strict validation still rejects faulty outputs → feedback at the producing boundary, saved progress and informative held result.
- Provider reliability remains unresolved → offline saved-response replay first, then one controlled posting; failed acceptance blocks activation rather than starting repeated experiments.
- Place data and statistical history incomplete → explicit unavailable/readiness states, no guessed distance or prediction.

## Migration Plan

Keep reader/assessment paused and collect-only timers active during repair. Preserve existing WIP, historical records, paused incidents and owner Unlimited settings. Reuse the isolated checkout, reconcile pending fixes and complete focused checks/review. Run one controlled evaluate-only provider acceptance with count-only reporting and no employer action; reuse its canonical result for recovery checks. A specific fix can justify another bounded experiment, but recurring failure is a blocker, not permission for an experiment loop.

Finish full release suite once on the reconciled candidate (recover prior shard results where source remains applicable), jobwatch check --code and independent review. Commit/reconcile source, back up runtime/config, deploy the exact revision through jobwatch-native and verify imported revision, effective assessment model/protocol, health and one real reader outcome. Re-enable automatic assessment only after acceptance. Rollback the code/config or keep assessment off; do not restore whole databases or discard new usage/history. Record all evidence on TASK-279.
