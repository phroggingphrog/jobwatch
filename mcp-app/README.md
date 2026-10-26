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
| `decide` | app only | - | Approve/Reject button |
| `submit_reviewed` | app only | - | destructiveHint + openWorldHint; needs the digest |

## Safety
- Submit needs the confirm digest of the reviewed form AND the `shown_hash` of exactly what the review showed (answers, documents, digest); Python refuses `review_changed` if either differs, and does not offer Submit when the owner edited the live form after the fill (`edited_in_browser`). Answers shown are the fill-time ones from the same preparation the digest binds; the web process still re-checks the live form before pressing.
- Submit needs the confirm digest of the reviewed form. The view gets it from `_meta` (view-only data) and passes it
  to `submit_reviewed`; Python re-checks it against the live reviewed form and queues once.
- Residual risk: `_meta` is not model-visible by MCP Apps convention, but a host may still forward it to the model.
  Even then the model could only replay `submit_reviewed` with a digest for a form the person has already reviewed;
  hosts hide app-only tools from the model, and Python still refuses a changed form or a second press.
- Auth: a bearer token is required (`JOBWATCH_MCP_TOKEN`, 32+ chars; the server will not start without it).
  The OAuth consent flow stays in the Python service; this server only verifies the static bearer.
- Never run write tools against real data in tests: use `test/mock-backend.mjs`.

## Run (local, mock backend)
    . test/env.sh                      # fake tokens
    node test/mock-backend.mjs &       # port 18941
    npx mcp-use dev --port 18942       # inspector at /mcp/inspector; add header Authorization: Bearer <token>
    npm test                           # needs `npx mcp-use build` first; spawns its own server on 18943

## Real backend
    JOBWATCH_CONNECTOR_TOKEN=... python -m pipeline.agentic.connector_http --port 18940   # JOBWATCH_MCP_PERSON picks the person
    JOBWATCH_MCP_TOKEN=... JOBWATCH_CONNECTOR_TOKEN=... JOBWATCH_BACKEND_URL=http://127.0.0.1:18940 npx mcp-use start --port <port>
