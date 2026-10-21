# Working on Jobwatch

Read [INTENT.md](INTENT.md) before changing behavior. The owner's latest explicit
direction takes precedence; preserve their words and do not silently narrow the goal.

## Repository guidance

| File | What it sets |
|---|---|
| [INTENT.md](INTENT.md) | Product intent, current backend scope and success criteria. |
| [Issue tracker](docs/agents/issue-tracker.md) | GitHub Issues through `gh`; external PRs do not authorize work. |
| [Triage labels](docs/agents/triage-labels.md) | Seven default triage labels. |
| [Domain](docs/agents/domain.md) | One domain context, root glossary and architecture decisions. |
| [Cross-model settings](docs/agents/cross-model.json) | Auto mode, CLI default models and high effort. |

## Implementation rules

- Deliver the native agent API and backend first. Keep LangChain, LangGraph and
  Deep Agents inside Jobwatch; MCP is optional and website integration is later.
- Reuse canonical Jobwatch evidence, eligibility, review and package operations.
  Read [the backend contract](pipeline/agentic/CHAT.md) and actual call sites before editing.
- Keep candidate facts and preferences in each person's approved runtime files.
  Preserve per-person isolation, server-bound identity and exact-input approvals.
- Never submit an application, contact an employer, or treat model text as human
  approval. Keep candidate data on approved paid routes and out of hosted tracing.
- Work in an isolated branch or worktree. Do not activate services, timers or a
  deployment as a side effect of a source change.

## Checks and reporting

Use the existing checks when verification is requested or required for release.
Keep checks focused; reserve the full suite for a release. Documentation changes
do not need application tests. Never use live candidate records as test fixtures.
Report the actual check and result, what remains unverified, and how to undo the
change. A merge, passing CI or a plan does not establish a deployed backend.

`cross-model.json` is development-agent policy, not Jobwatch runtime configuration.
`default` means the selected CLI's configured default model; use high effort when
that CLI supports it. Auto mode does not require calling every listed CLI. Respect
the owner's routing and model restrictions; this file does not authorize new calls.
