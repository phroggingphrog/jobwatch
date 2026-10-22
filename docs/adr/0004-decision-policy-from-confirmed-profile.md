# ADR 0004: Decision policy from the confirmed profile

Date: 2026-10-21

Status: Accepted owner direction (backend brief of 2026-10-21); delivery has its own acceptance criteria.

## Context

The agreed backend brief asks for the search strategy to follow the person's
confirmed profile: employment-first discovery for someone who is unemployed and
gave no contrary instruction, an explicit career or degree focus prioritised,
explicit exclusions always respected, a question when missing information
materially affects a decision, and a strategy that is updated when the confirmed
profile changes. It also asks the owner's words to be kept: "Remove person-specific
assumptions from application code. Preserve genuine eligibility constraints."

Today the gate and the prompts carry assumptions about one person: a commute-distance
constant, regional place regexes, a stored location-fit label that stands for the
home region, an entry-level preference applied to everyone, student wording in
prompts, and occupation family lists. They are reachable for every person and do
not come from any confirmed fact. Genuine eligibility is different: work rights and
hours limits the person states are real constraints and stay.

Two limits shape the change. The first model pass never sees the candidate, so a
stored label written by it cannot say whether a location is the person's home
region. And two built-in occupation codes are hashed into every run key through
`TargetPolicy`, so changing that object re-keys every stored job.

## Decision

- The decision policy is built only from approved facts whose basis is `evidence`.
  Inferred and unknown facts never become rules; they stay open questions.
- It is a separate object from `TargetPolicy`, so run keys do not move.
- A flag `pipeline.agentic.decision_policy` takes `legacy` or `profile`. The default
  is `legacy` and the flag lives outside `_config()`. With `profile` and no confirmed
  scope-bearing profile version, the legacy path runs. Exclusion rules take effect
  immediately only with `profile`.
- Five search rules are implemented, and the derivation table is in the Plan 2
  implementation (Task 3). In plain terms: an unemployed person with no contrary
  instruction gets employment-first discovery across permitted fields using
  relatable skills; an explicit career or degree focus is prioritised; explicit
  exclusions are always respected and unemployment never overrides them; missing
  information that materially affects a decision becomes a question and is not
  silently treated as failure; a change to the confirmed profile changes the
  strategy.
- An `exclusion` fact whose value is `{"kind", "value"}` becomes an `ExclusionRule`
  that carries its `source_fact_id`. A free-text exclusion stays prompt text and the
  gate does not enforce it. It adds the open question `exclusion:<fact_id>`, which
  asks the person which kind it is. The answer goes through the digest-bound rule
  confirmation of Plan 5.
- Location is recomputed from the verified ad quote. The stored home-region label
  of `location_fit` is not trusted as "home region", because the first model pass
  never sees the candidate. Renaming the label would change evaluator prompts and
  need a paid re-evaluation.
- The person-specific branches remain only in `_legacy_person_checks`, as the
  `legacy` comparison baseline. They are deleted in a follow-up once the owner has
  re-confirmed the profile and switched to `profile`.
- `gate_current` is the one live gate call, and every gate caller uses it.
- `MINIMUM_EXCLUDED_CODES`, the two built-in occupation codes hashed into every run
  key through `TargetPolicy`, is parametrised and not removed. Removing it would
  re-key every stored job (Task 7).
- Deferred to other plans: the collection pre-filter and `_target_first` to Plan 3;
  the holistic-score gate and the preference families to Plan 4.

The policy only reads confirmed facts. Nothing here writes a fact, a rule or an
approval, and an agent-generated answer is never recorded as a person's choice.

## Consequences

- Every wrong rule is visible in `GET /api/agent/profile/policy`, so the person can
  correct the fact it came from.
- With the default `legacy` flag nothing changes for anyone until the owner has
  re-confirmed the profile and switched to `profile`; until then the
  person-specific branches still run.
- Stored run keys and stored evaluations stay valid, because `TargetPolicy` and the
  stored labels are untouched.
- A free-text exclusion is not enforced until the person says which kind it is.
- Accepted design is not deployed behaviour; a merge or passing checks does not
  establish a running backend.

## Alternatives rejected

- Removing `MINIMUM_EXCLUDED_CODES` outright: it would re-key every stored job.
- Renaming the stored location-fit label: it would change evaluator prompts and
  require a paid re-evaluation.
- Folding the policy into `TargetPolicy`: run keys would move.
- Treating inferred facts as rules: a CV gap or a guess would silently exclude jobs.
- Enforcing free-text exclusions by model interpretation: the person has not said
  what they mean, and model text is not approval.

## References

- Backend brief 2 (search strategy from the confirmed profile; remove
  person-specific assumptions, keep genuine eligibility) and brief 4 (explicit
  exclusions are rules; agent answers are never recorded as user choices).
- Owner's words: "Remove person-specific assumptions from application code.
  Preserve genuine eligibility constraints."
- [INTENT.md](../../INTENT.md), "Evidence matching overhaul".
- The code map, section 2, in
  [the codemap](../superpowers/plans/reference/2026-10-21-codemap.md).
- [ADR 0002](0002-profile-intake-and-approval.md), [ADR 0003](0003-frozen-baseline.md)
  and [the backend contract](../../pipeline/agentic/CHAT.md).
