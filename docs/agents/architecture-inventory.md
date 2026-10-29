# Architecture inventory

Static source inventory, 2026-10-28, against the working tree based on `9111a0d`.
This is not deployment evidence. The embedded-UI removals below were already
uncommitted when this reconciliation began; they are not a newly verified release.

## Keep: collection and canonical services

| Area | Responsibility and source evidence | Disposition |
|---|---|---|
| `jobwatch/pipeline.py` | Collection, publish/prune, then assessment dispatch in `run()`; invoked by `jobwatch/cli.py` and collection service commands | Keep; no rename in this pass |
| `jobwatch/execution_mode.py` | Selects assessment mode; `jobwatch/pipeline.py` dispatches `agentic` to `pipeline.agentic.service.after_collect`, `pipeline` to `pipeline.graph.after_collect`, and `reader` to `jobwatch.reader.after_collect` | Keep all currently wired modes; changing support needs its own evidence |
| `pipeline/graph.py`, `pipeline/nodes/`, `pipeline/cli.py` | Selectable deterministic orchestration and `jobwatch pipeline` commands, wrapping canonical services | Keep; not proven dead merely because agentic is the configured default |
| `pipeline/store.py`, `pipeline/schemas.py` | Shared stage/event/dead-letter substrate used by agentic persistence, the web board, prescreen and user provisioning | Keep; this is not a legacy-only package |
| `pipeline/agentic/` | Native orchestration, HTTP and adapters; `service.py` imports canonical candidate evidence, assessment, policy and other Jobwatch services | Keep; wraps rather than replaces canonical domain operations |
| `jobwatch/` domain services | Authoritative evidence, eligibility, review, package and application operations | Keep; no new parallel state or package reorganization here |

There is reverse coupling as well as orchestration-to-domain imports:
`jobwatch/users.py` imports `pipeline.store`, and candidate assessment imports
agentic contracts/runtime. This is a layering concern to evaluate separately,
not evidence that either package can be deleted. Top-level `pipeline/` contains
shared substrate, a selectable deterministic orchestrator and the current
agentic layer; calling the whole package “legacy” is incorrect.

## Remove: superseded embedded client implementation

The working tree already removes `client/genui/`, `client/jobwatch-app/`,
`mcp-app/`, `pipeline/agentic/mcp_app.py`, `cards.py`, `genui.py`, the embedded
`jobwatch-app.html` bundle, its standalone service and corresponding obsolete
renderer tests/packaging. General presentation guidance moves to
`pipeline/agentic/presentation.py`, imported by `chat.py`.

These removals must be reconciled and tested by their implementation owner before
release. This inventory neither stages them nor certifies their behavior.
Historical descriptions in HANDOVER are not evidence of current routing.

## Keep pending explicit migration: active adapters and controls

| Surface | Current source connection | Disposition |
|---|---|---|
| ChatGPT connector widget | `mcp_server.py` registers `chatgpt_connector`; connector serves `text/html;profile=mcp-app` resources | Retain optional adapter; do not claim all MCP widget HTML is removed |
| LibreChat model catalog | `librechat.py` imports `client_api.model_catalog` | Retain; removing the whole module would break a current caller |
| `/agent/controls.*` | Served by `librechat.py`; controls use run/profile endpoints | Retain; not the removed embedded panel |
| Compatibility client routes | `api.py` mounts `client_api` only when `JOBWATCH_MCP_APP_ENABLED=true`; includes ticketed files and browser controls | Retain pending consumer/runtime evidence; historical flag name does not prove a renderer remains |
| Native browser API | `api.py` mounts `browser_api`, whose routes are gated by `JOBWATCH_NATIVE_BROWSER_ENABLED` | Retain; separate from compatibility iframe routes |
| Website | `jobwatch/web` | Retain as a separate canonical frontend |

Vanilla LibreChat/native Artifacts is the current chat-client direction. Existing
optional connector widgets do not authorize rebuilding a Jobwatch-specific
LibreChat card system. Approval and confirmed-Submit authority remain canonical.

## Migration and verification still needed

- Determine actual deployed consumers of compatibility routes before deprecating
  them; static tests prove reachability, not live use. Do not inspect or expose
  secrets to resolve this question.
- Reconcile `deploy/LIBRECHAT.md`'s compatibility flag advice with those consumers.
- `deploy/jobwatch-agent.service` points at `~/apps/jobwatch`, not this checkout.
  Confirm the owner's actual service before any deployment claim; do not silently
  edit a template to authorize a different deployment.
- Regenerate ignored installed entry-point metadata during an authorized install;
  stale metadata is not a reason to restore the retired renderer.
- Verify retained uploads, model catalog, controls, browser/approval boundaries and
  packaging after reconciling code removals. No runtime, provider acceptance or
  full application test result is established by this documentation pass.

Broader domain moves, CLI consolidation and collection-module renaming remain
separate proposed work. They must not obscure the immediate canonical assessment
acceptance milestone or be reported complete through this inventory.
