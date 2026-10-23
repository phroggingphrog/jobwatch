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

## Embedded app

Set `JOBWATCH_MCP_APP_ENABLED=true` and
`JOBWATCH_APP_ORIGIN=https://<existing-librechat-host>` in the private environment.
Run the optional `jobwatch-mcp-app` entry point from the same checkout and data
root as the native API, using the same credential mapping. Its default native
URL is `http://127.0.0.1:18914`. The service template binds MCP to loopback port
18918; forward it only on the private container bridge when needed.

Merge this into LibreChat's configuration (replace the example bridge addresses):

```yaml
mcpAppSandbox:
  url: https://<dedicated-sandbox-host>/api/mcp/sandbox
mcpSettings:
  apps: true
  allowedAddresses: ["<private-bridge>:18918"]
mcpServers:
  jobwatch:
    type: streamable-http
    url: http://<private-bridge>:18918/mcp
    startup: false
    headers:
      Authorization: "Bearer {{JOBWATCH_DECISION_KEY}}"
    requestHeaders:
      Authorization: "Bearer {{JOBWATCH_CHAT_KEY}}"
    customUserVars:
      JOBWATCH_CHAT_KEY:
        title: Jobwatch chat key
        description: Read and run, bound to your Jobwatch person.
      JOBWATCH_DECISION_KEY:
        title: Jobwatch decision key
        description: Human app actions, bound to the same person.
modelSpecs:
  list:
    - name: jobwatch
      label: Jobwatch
      mcpServers: [jobwatch]
      preset:
        endpoint: Jobwatch
        model: jobwatch-agent
```

Set `MCP_SANDBOX_FRAME_ANCESTORS=https://<existing-librechat-host>` in LibreChat’s
private environment and serve only its `/api/mcp/sandbox` route on the dedicated
sandbox hostname. Other paths on that hostname must return 404; do not serve the
chat login or API there. The sandbox and LibreChat must have different origins.

Keep the existing custom endpoint's API key set to that person's chat key. Store
the two MCP variables through LibreChat's encrypted per-user credentials, never
as global shared owner keys or model arguments. Common headers authorize human
app callbacks; chat-only `requestHeaders` replace them with the read/run key.
App-only tool visibility is advisory: the server independently refuses every
mutation without human approval scope. Verify both credential paths in the
installed LibreChat release before deployment.

Route **only** `/api/agent/client/upload` and `/api/agent/client/download` on the
existing LibreChat HTTPS hostname to the native API. Keep the current Access
policy. These narrow endpoints require short-lived, single-use capabilities;
uploads additionally bind the exact person, filename, kind, byte count and SHA-256.
Only the upload endpoint accepts sandbox `Origin: null`, with its capability;
normal bearer API routes do not gain CORS access. The browser uses a simple POST
with a fixed capability envelope ahead of the raw file, avoiding unauthenticated
CORS preflights through Access without changing its policy. The native 10 MiB file limit
remains. File contents never enter model tool arguments. Generic LibreChat file
attachments remain disabled for Jobwatch.

## Use

Select the **Jobwatch preset** (or `/c/new?spec=jobwatch`) and start with
“Help me set up my profile.” LibreChat displays **Open app** on the Jobwatch
response; it opens the panel **inside the conversation**. The panel follows saved
native progress and resumed runs. It shows relevant profile intake, questions,
exact decisions, shortlist explanations and verified document previews.
Downloads use a separate short-lived capability. No external controls-page link
is needed for this flow; `/agent` remains a separately authenticated fallback.

Open **Agent models** inside the panel to set the paid model ID for each role.
The canonical per-person settings and existing route restrictions apply; new
choices affect new work. Qwen3 Embedding 8B remains the evidence embedding route.
The `jobwatch-agent` label in LibreChat selects the backend adapter, while these
role settings select the actual models used by Jobwatch.

Each app mutation opens LibreChat's own confirmation dialog with the exact tool
arguments. Review it before confirming. Profile confirmation also shows the
actual draft and search scope and refuses changed inputs. Model-facing tool
calls, prior assistant/tool text and typing “approve” never consume a decision.
The adapter emits one read-only view call and returns the native answer on the
tool continuation without starting another paid run. Disconnecting leaves work
durable. SSE keepalives preserve the connection while Jobwatch works.

Run completion describes a conversation turn; explicit outcomes describe READY
packages or held/deferred work. Synthetic tests and screenshots do not certify
live writing quality or an actual employer form fill. Final Submit retains its
separate exact-filled-form confirmation and existing browser review requirement.

## Undo

Stop/disable the newly installed agent and private forwarding units. Restore the
saved LibreChat configuration and restart its container. Remove only the added
path-specific proxy rule. Keep legacy services and timers stopped and masked when the owner requested
isolation. Restore only the fresh deployment’s previous revision/configuration;
do not reactivate legacy units as a rollback side effect. Keep both runtime folders, database backups,
documents and credentials private; reverting source does not erase state.
