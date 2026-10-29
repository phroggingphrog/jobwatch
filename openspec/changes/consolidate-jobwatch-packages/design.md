## Context

See proposal.md for scope. `INTENT.md` records multiple historical directions; its later standard LibreChat/native Artifacts direction controls the cleanup. `pipeline/agentic/CHAT.md` documents native API authentication and exact-input approval boundaries. The checkout contains unrelated modified guidance and untracked configuration; these must remain outside cleanup commits.

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

No deployment occurs. Implement in the five user-requested stages, reconcile each writer before testing, and commit each stage separately after a full test run. Parent owns full-suite execution and commit scope; specialists own focused checks only. For module moves, smoke-test public imports and CLI help using synthetic inputs, never live candidate records. For documentation, check relative links and run the explicitly requested full suite despite normal documentation-only exemptions.

Rollback is `git revert` of individual cleanup commits in reverse order; no runtime data rollback is needed. Planning artifacts do not authorize deployment.
