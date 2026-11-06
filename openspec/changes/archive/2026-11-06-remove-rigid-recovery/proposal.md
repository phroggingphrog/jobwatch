# Proposal

## Why

The owner requested "remove the rigidity" after offline investigation reproduced lexical rejection of faithful paraphrases and premature exhaustion of distinct improving corrections. These are Jobwatch contracts, so a framework migration is unnecessary for this repair.

## What Changes

- Bind draft profile updates to server-owned human conversation sources and preserve original wording without requiring a model to reproduce it exactly.
- Keep legacy verbatim calls compatible and return actionable source references when an update lacks provenance.
- Replace the total per-tool correction allowance with persisted progress-aware recovery; repeated failures/churn remain bounded by existing budgets and no-progress limits.

## Capabilities

### New Capabilities

- `human-draft-provenance`: source-bound draft updates independent of model paraphrase.
- `assessment-recovery`: progress-aware, persisted correction boundaries.

### Modified Capabilities

None; neither capability has a main spec in this checkout.

## Impact

Chat profile tools, canonical intake provenance notes, native assessment correction accounting and focused synthetic regressions. No framework change, dependency, service activation, approved-profile edit or paid inference. Existing 32 release failures are separate recorded work.
