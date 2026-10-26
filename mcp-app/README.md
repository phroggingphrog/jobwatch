# Jobwatch MCP App (mcp-use, TypeScript)

A thin MCP Apps front for the Jobwatch ChatGPT connector. It holds no job data and no safety logic.
Every tool calls the Python JSON front `pipeline/agentic/connector_http.py` (loopback, bearer), which calls the same
`chatgpt_connector` functions the live Python MCP service uses. The digest check, single-use approvals,
per-person binding and "already queued" refusal all stay in Python.

## Tools
| Tool | Model sees it | View | Notes |
|---|---|---|---|
| `jobs_overview` | yes | jobs-overview | read-only |
| `job_detail` | yes | job-detail | read-only, never carries the digest |
| `task_status` | yes | task-status | read-only |
| `review_submission` | yes | review | read-only; shows every filled answer, attached files, employer and role; digest and shown_hash only in result `_meta` |
| `prepare_application`, `revise_application` | yes | task-prepare / task-revise | hand work to Jobwatch's agent; never submit; approval binding only in `_meta` |
| `career_ops_start_chat`, `career_ops_continue_chat` | yes | - | same Career Ops agent as the Python MCP server; a question for the person comes back as plain `needs_answer` content (question + options) and is answered only by the person's own words via continue_chat; approvals are declined, never answered here |
| `decide` | app only | - | Approve/Reject button |
| `submit_reviewed` | app only | - | destructiveHint + openWorldHint; needs the digest |

## Safety
- Submit needs the confirm digest of the reviewed form AND the `shown_hash` of exactly what the review showed (answers, documents, digest); Python refuses `review_changed` if either differs, and does not offer Submit when the owner edited the live form after the fill (`edited_in_browser`). Answers shown are read from the CURRENT live form (the native browser review, same source as the web app); an edit after the fill is re-reviewed and Submit needs the fresh hash. The web process still re-checks the live form before pressing.
- Submit needs the confirm digest of the reviewed form. The view gets it from `_meta` (view-only data) and passes it
  to `submit_reviewed`; Python re-checks it against the live reviewed form and queues once.
- Residual risk: `_meta` is not model-visible by MCP Apps convention, but a host may still forward it to the model.
  Even then the model could only replay `submit_reviewed` with a digest for a form the person has already reviewed;
  hosts hide app-only tools from the model, and Python still refuses a changed form or a second press.
- Authentication is handled by Cloudflare Access Managed OAuth with the configured Google identity provider.
  The tunnel's `originRequest.access.required` setting validates Access JWTs before forwarding to this loopback-only app.
  The app does not ask for a Jobwatch bearer token or passphrase. Keep port 18942 bound to `127.0.0.1` and publish it
  only through the Access-protected tunnel hostname.
- Never run write tools against real data in tests: use `test/mock-backend.mjs`.

## Run (local, mock backend)
    . test/env.sh                      # fake tokens
    node test/mock-backend.mjs &       # port 18941
    npx mcp-use dev --port 18942       # inspector at /mcp/inspector; add header Authorization: Bearer <token>
    npm test                           # needs `npx mcp-use build` first; spawns its own server on 18943

## Real backend
    JOBWATCH_CONNECTOR_TOKEN=... python -m pipeline.agentic.connector_http --port 18940   # JOBWATCH_MCP_PERSON picks the person
    JOBWATCH_MCP_TOKEN=... JOBWATCH_CONNECTOR_TOKEN=... JOBWATCH_BACKEND_URL=http://127.0.0.1:18940 npx mcp-use start --port <port>

## Real-application check (temp dir only)
    python -m tests.realapp serve --root /tmp/opencode/realapp --connector-port 18952 --native-port 18951   # real fill + browser; prints the token
    JOBWATCH_REAL_APP_TEST=1 JOBWATCH_PYTHON=<venv python> npx vitest run test/realapp.test.ts
