# Fresh Jobwatch deployment with LibreChat

LibreChat is an interchangeable chat client. The optional `/v1/chat/completions`
adapter enqueues the native API's durable runs; Jobwatch owns orchestration,
identity, checkpoints, budgets, tools and artifacts. No extra supervisor model is
required in LibreChat. Each read/run bearer selects its person on the server.
Client `user`/`person` fields never select an identity.

## Release

1. Use an isolated checkout of the intended revision. Install with
   `uv sync --frozen --extra dev --extra browser --extra mcp` for release checks.
   Run `uv run --no-sync python -m pytest -q` and `jobwatch check --code` against
   the intended runtime; report absent onboarding facts separately from source
   findings. Hosted CI stays disabled.
2. Create new mode-0700 data/config directories outside Git. Do not delete,
   import or overwrite another deployment's state. Set **both**
   `JOBWATCH_DATA_DIR` and `JOBWATCH_DB`; also isolate `JOBWATCH_PROFILE_DIR`,
   `JOBWATCH_CAREER_DIR` and `JOBWATCH_CONFIG_DIR`. A fresh profile remains
   unconfirmed and discovery must report `no_confirmed_profile`.
3. Supply approved existing paid loopback gateway credentials, `openai/sol`
   (or another already approved route), the configured credential index and the
   Qwen embedding route. Disable hosted tracing. Do not inherit personal model
   picks, profiles, mail credentials or notifications from old runtime folders.
4. Generate separate random `JOBWATCH_AGENT_TOKEN` (read/run) and
   `JOBWATCH_AGENT_APPROVAL_TOKEN` (read/interact/approve), at least 32 characters
   each, in a mode-0600 environment file. Set `JOBWATCH_LIBRECHAT_ENABLED=true`
   and `JOBWATCH_AGENT_PUBLIC_URL=https://<existing-jobwatch-host>`.
5. Install a user service based on `jobwatch-agent.service`, pointing at the
   new checkout and private environment. Bind the native API to loopback.
   Explicit deployment is required; source changes never activate a service.
6. Route `/agent`, `/agent/*`, `/api/agent/*` and `/v1/*` through the existing
   HTTPS/access proxy to the native API. Retain the board on its own route for
   browser fills and final form review, using the same new data root. If a
   container cannot reach loopback, use an authenticated API listener forwarded
   only on its private bridge. Do not publish a bearer endpoint on every host
   interface.
7. Merge `librechat.yaml`'s custom endpoint into LibreChat's existing config,
   set its reachable base URL and restart LibreChat. Each person supplies their
   own **chat key**, never the decision key. Existing LibreChat accounts and
   conversations need no reset. Verify startup config, authenticated chat,
   reconnection and cross-account denial before claiming deployment.

## Use

Select **Jobwatch → jobwatch-agent** in LibreChat and enter the chat key. Start
with “Help me set up my profile.” The agent guides intake. Native upload IDs
from `/agent` can be pasted into the conversation. Generic file attachments are
disabled for this endpoint so candidate documents use the canonical native upload
and approved parsing route rather than LibreChat's separate file/RAG pipeline.

Open the **Jobwatch controls, uploads and documents** link in a response. Enter
the chat key and the separate decision key there. They stay in page memory,
are sent only as bearer headers to the same origin, and disappear on reload.
Use **Connect / refresh** to see recent work. Review the exact operation and
binding before approving. Profile confirmation displays the actual draft and
scope and refuses a changed preview. Questions, rejection, cancellation,
retained-run retry and verified document download use the existing native API.
Refresh for resumed outcomes; the next LibreChat turn uses the same thread.

Typing “approve” in LibreChat does not approve an operation. A run awaiting a
decision is returned without starting another paid turn. Disconnecting leaves
durable work inspectable; it does not imply cancellation. The adapter sends SSE
keepalives while waiting, then the native result. Unsupported binary/image
messages require the native upload page. Requests retain the native 64-KiB body
cap and 16,000-character latest-message cap; very long client histories may
require a new conversation. Only the latest user message is dispatched, since
Jobwatch already persists its own history. Client system instructions and
assistant tool calls are never replayed as authority.

Run completion describes a conversation turn. Inspect explicit outcomes for
READY packages and their verified artifacts. The controls page cannot certify
live writing quality or a browser fill. Final Submit retains its separate,
exact-filled-form confirmation and requires the board's browser process.

## Undo

Stop/disable the newly installed agent and private forwarding units. Restore the
saved LibreChat configuration and restart its container. Remove only the added
path-specific proxy rule. Restore the saved board/collector unit configuration
and its previous timer states. Keep both runtime folders, database backups,
documents and credentials private; reverting source does not erase state.
