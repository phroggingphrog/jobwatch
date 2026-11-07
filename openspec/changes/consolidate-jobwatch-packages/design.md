## Context

See proposal.md for scope. Current `INTENT.md` is the normative single-owner,
native-API-first contract; historical directions live in the linked owner history.
LibreChat/native Artifacts are compatibility clients, not a dependency of the
backend. `pipeline/agentic/CHAT.md` defines authentication and exact-input approvals.

At `main:0ea4fe0`, the domain packages, collection rename, command dispatch and
README topic split are already present. Reconcile remaining verification rather
than repeating source moves. Earlier references to a dirty checkout or a specific
refactor branch are historical, not observations of the current workspace.
Preserve unrelated changes if any are present.

## Goals / Non-Goals

Preserve behavior and test coverage of retained code. Make module ownership explicit without introducing dependencies or parallel implementations. Do not alter approval or submit-confirmation logic, migrate data, re-enable hosted CI, activate services, or claim deployment.

## Decisions

- Trace both static imports and indirect runtime references (routes, resource URIs, static assets, entry points, packaging and service scripts) before deleting legacy UI code. Names alone do not prove obsolescence. Retain current-client helpers even if housed in a legacy module.
- Use `jobwatch/interview/`, `jobwatch/followup/`, `jobwatch/google/` and `jobwatch/util/`. Prefer concise module names inside each domain (`ad`, `browser`, `inputs`, `prep`, `subjects`; `drafts`, `events`, and a clearly named follow-up orchestration module; `gmail`, `oauth`). Keep changes mechanical and update relative imports, test monkeypatch strings and scripts alongside moves.
- Rename the collection orchestrator to `jobwatch/run.py`; preserve the top-level agentic `pipeline/` package.
- Use `jobwatch/commands/` for business CLI implementation and one dispatching entry point. Preserve original run/collect invocation semantics. Thin legacy wrappers are permitted only where traced deployment callers require compatibility; document them instead of silently breaking service commands. Agent API/MCP/TUI/ACP service entry points are distinct transports, not the six business CLIs being consolidated.
- Split README by existing topics, maintaining content and relative links rather than rewriting behavior documentation.

## Risks / Trade-offs

- Dynamic references and relative resource paths can survive import-only checks → inspect string references, packaging and static routes; run focused CLI/import/resource tests plus the full suite.
- Broad automated replacement can change unrelated text or security-sensitive code → review rename-aware diffs and compare approval/submit-confirmation files against baseline.
- Existing tests may have environment or baseline failures → establish baseline at implementation start; preserve complete logs, distinguish introduced failures, and do not weaken assertions for retained functionality.
- Legacy embedded surfaces may still be wired despite being superseded → resolve each dependency before removal; keep shared native-client operations intact.

## Migration Plan

No deployment occurs. The five source scopes are already represented in main;
recover applicable review/check evidence and verify remaining compatibility gaps
rather than recreating moves or requiring five historical commits. Use focused
synthetic import, CLI and resource checks for source changes, and the full
reconciled suite only for release. Documentation-only reconciliation requires
artifact/link checks, not application tests. Current repository check policy
supersedes the older per-step full-suite instructions.

Rollback is `git revert` of individual cleanup commits in reverse order; no runtime data rollback is needed. Planning artifacts do not authorize deployment.
