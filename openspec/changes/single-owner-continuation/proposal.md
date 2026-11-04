# Proposal

## Why

The owner approved continuing the isolated jobwatch-new copy through a release decision. Its single-owner branch still conflates evaluation with preparation and lacks the verified TASK-451 repairs.

## What Changes

- Reconcile the single-owner contract with existing code, retaining exact-input human approval and confirmed submission.
- Integrate assessment completion, artifact integrity, started-promotion accounting and notification regressions from TASK-451.
- Keep document identity readiness separate from evaluation readiness.
- Verify synthetic flows and existing runtime readiness without activating services or inventing profile approval.

## Capabilities

### New Capabilities

- `assessment-completion`: assessment-only scheduling, durable evaluated results and artifact-validated reuse.
- `notification-delivery`: enabled-channel dispatch and idempotent delivery results.

### Modified Capabilities

None; this copy has no main capability specifications.

## Impact

Existing pipeline, persistence and notification services, their tests and product documentation. No new dependencies, clients, services or framework upgrades. TASK-424 owns continuation status; TASK-451 and issue 61 supply prior repair evidence. Deployment remains a separate owner decision.
