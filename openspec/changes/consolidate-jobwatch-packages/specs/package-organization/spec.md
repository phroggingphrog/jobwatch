## ADDED Requirements

### Requirement: Source packages reflect domain ownership
The source tree SHALL group interview, follow-up, Google integration and shared utility modules into explicit subpackages, and SHALL distinguish the collection-run module from the top-level agentic `pipeline` package. All in-repository importers SHALL use the resulting paths.

#### Scenario: Existing callers after relocation
- **WHEN** tests, scripts, collection orchestration or agentic code import moved functionality
- **THEN** the imports resolve and the original behavior is preserved

### Requirement: Superseded UI removal preserves the current client
Cleanup SHALL trace imports and runtime wiring before removing GenUI, MCP App card surfaces or rendering helpers. Code still required by standard LibreChat/native Artifacts SHALL remain. Human approval, server-bound identity and confirmed-submit logic SHALL remain unchanged.

#### Scenario: Shared helper remains in use
- **WHEN** a helper in a legacy-named module is called by the current LibreChat/native Artifacts path
- **THEN** it is retained or relocated with its behavior and security boundaries preserved

### Requirement: Business CLIs use a common entry point
The business CLIs SHALL be organized under `jobwatch/commands/` behind the `jobwatch` entry point. Deployment-dependent legacy invocations MAY remain as thin documented wrappers with unchanged argument semantics.

#### Scenario: Existing deployed invocation
- **WHEN** a deployment caller requires a legacy business CLI module
- **THEN** a documented thin wrapper continues to dispatch that invocation without argument or behavior changes

### Requirement: Cleanup is staged and verifiable
The cleanup SHALL preserve reviewable scopes for superseded UI removal, package grouping, orchestrator rename, CLI unification, and README split. Focused checks SHALL cover each scope and the full required local suite SHALL run on the reconciled final state. Required failures SHALL be investigated and reported, not hidden by removing still-relevant tests. README topic content SHALL remain available through working relative links.

#### Scenario: Step completion
- **WHEN** the combined cleanup is ready for completion
- **THEN** its final full-suite result and focused evidence are recorded, and any commits exclude unrelated working-tree edits
