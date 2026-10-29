## Why

Product pivots left obsolete embedded UI paths and overlapping module/CLI names. Consolidate the source layout without changing current LibreChat/native Artifacts behavior or human approval and submit-confirmation semantics.

## What Changes

Implement five ordered steps. Run focused checks for each implementation scope and the full reconciled local suite once after all writers finish. Keep unrelated working-tree changes out of any commits. The owner's 2026-10-28 continuation authorizes completing this cleanup, not deployment or paid candidate experiments:

1. Trace imports and remove or archive superseded GenUI/MCP App cards only where disconnected from current LibreChat/native Artifacts paths; update obsolete tests.
2. Group interview, follow-up, Google integrations and utility modules into subpackages; update all callers.
3. Rename the collection orchestrator `jobwatch/pipeline.py` to `jobwatch/run.py`.
4. Consolidate the six business CLIs under `jobwatch/commands/` and the `jobwatch` entry point; retain documented thin wrappers only for deployment compatibility.
5. Split README topics into `docs/`, leaving a short linked overview.

Internal Python import paths change. CLI compatibility must be established from actual deployment callers before removing wrappers. No dependency additions, service activation, deployment, candidate-data migration or changes to approval/submission logic.

## Capabilities

### New Capabilities

- `package-organization`: Stable ownership boundaries for collection, shared utilities, domain packages and CLI dispatch while preserving runtime behavior.

### Modified Capabilities

None. Existing product behavior remains unchanged except removal of explicitly superseded UI surfaces proven unused by the current path.

## Impact

Affected: `jobwatch/`, `pipeline/agentic/`, `client/genui/`, tests, scripts, packaging entry points, README and topic documentation. Existing unrelated working-tree edits must not be staged. Work is isolated on `refactor/package-consolidation`; no deployment is authorized.
