# Jobwatch MCP App (mcp-use, TypeScript)

A thin MCP Apps front for the Jobwatch ChatGPT connector. It holds no job data and no safety logic.
Every tool calls the Python JSON front `pipeline/agentic/connector_http.py` (loopback, bearer), which calls the same
`chatgpt_connector` functions the live Python MCP service uses. The digest check, single-use approvals,
per-person binding and "already queued" refusal all stay in Python.

## Tools
| Tool | Model sees it | View | Notes |
|---|---|---|---|
| `jobs_overview` | yes | jobs-overview | current canonical shortlist only, in canonical rank order; includes labelled evidence holds |
| `job_detail` | yes | job-detail | current shortlist entry, evidence/citations, conditions, questions and permitted actions; never carries the Submit digest |
| `refresh_shortlist` | yes | - | database-only canonical rebuild from stored assessments; no collection or paid model work |
| `applications_overview` | yes | applications | application, preparation and submission history; not recommendations |
| `application_detail` | yes | application-detail | history/document state, including jobs no longer on the shortlist |
| `assessment_detail` | yes | - | explicitly requested diagnostics, including exclusions; never a recommendation |
| `task_status` | yes | task-status | read-only |
| `review_submission` | yes | review | read-only; shows every filled answer, attached files, employer and role; digest and shown_hash only in result `_meta` |
| `prepare_application` | yes | task-prepare | after explicit consent, queues canonical selection for one exact current eligible entry; never submits |
| `revise_application` | yes | task-revise | requests revision through the existing job-work agent; pending approval binding only in `_meta` |
| `onboarding_status` | yes | - | saved facts, all open questions and current confirmed version |
| `discovery_status` | yes | discovery | collection/assessment progress, paused incidents and independent notification states; not matches |
| `start_discovery` | yes | - | one bounded assessment request through the durable native worker; never retries paused jobs |
| `get_discovery_settings` | yes | settings | focused saved allowance controls; also reachable through widget navigation |
| `set_discovery_settings` | yes | - | saves Unlimited or a positive daily token allowance for the authenticated person |
| `retry_assessment` | yes | - | explicit user-requested retry for one current incident/context, within unchanged daily limits |
| `start_onboarding` | yes | - | starts canonical document parsing from uploaded document IDs |
| `update_onboarding`, `answer_onboarding_question` | yes | - | saves the person's supplied answers in an unconfirmed draft, with revision checks |
| `review_onboarding` | yes | - | exact profile, search scope, limits and review digests |
| `confirm_onboarding` | yes | - | coordinating assistant passes the person's explicit confirmation and reviewed digests; refuses changed draft/scope |
| `decide` | app only | - | Approve/Reject button |
| `submit_reviewed` | app only | - | destructiveHint + openWorldHint; needs the digest |

## Results and interaction contract

Jobs is a projection of the existing account-bound shortlist, not a list of collected
postings, assessment attempts or application activity. It preserves canonical membership,
order and the `stronger_match`, `stretch` and `needs_clarification` labels. Evidence holds
remain visible with unresolved questions, but cannot prepare. Scores are advisory; this
adapter adds no score cutoff, title blacklist or personal preference.

`jobs_overview` returns the canonical `ok`, `not_built`, `no_confirmed_profile` or `stale`
status. A valid empty shortlist stays empty; missing or stale snapshots never fall back
to historical scores or activity rows. Each current entry carries its shortlist, entry
and run identities, explanations, conditions, requirements, citations and backend-derived
`can_prepare`. `job_detail` refuses to present an absent or stale entry as a recommendation.
Use `assessment_detail` only for an explicitly requested diagnostic lookup. Application
history remains accessible separately even when the job is no longer shortlisted.

`prepare_application` requires `posting_id`, `expected_entry_id`, `expected_run_key`,
`request_id` and `confirmed: true`, only after the person explicitly agrees to prepare
that reviewed entry. It calls canonical selection directly, not a second conversation.
Changed identities and evidence holds are refused. Reuse the same request ID after a
lost response; a changed payload under that ID conflicts. The response includes the
selection ID and `authorises: preparation_only`; it never grants Submit authority.
Old calls that supply only a posting ID or free-form instructions must obtain a current
entry and the person's explicit consent rather than being silently converted.

The contextual widgets share navigation between Jobs, Applications, Discovery and
Settings. Their compact rows, typography hierarchy and host-selected dark/light themes
follow the redesigned web dashboard (`jobwatch/web/static/v3/web.css`). Long evidence,
rank explanations and incidents expand on request. The host assistant keeps the
conversation; controls call typed operations without a chatbot relay. Widget resources
use `_meta.ui.resourceUri` and self-contained HTML/JS/CSS. A published resource, build or
protocol check does not prove it rendered in ChatGPT: verify the intended host journey
and report any client-side rendering limitation separately.

## Safety
- The coordinating assistant owns onboarding conversation and collects the person's answers and consent. Onboarding tools call canonical intake operations directly; they do not start a second chat agent or require widget approval. Only call `confirm_onboarding` after the person explicitly approves the reviewed profile and scope. The backend requires `confirmed: true`, validates both digests under the canonical locks, saves the confirmed version and enables its discovery scope. This does not authorise document preparation, employer messages or application submission. Canonical selection and its durable worker remain responsible for heavy application preparation.
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
    npm run build                      # embeds JS/CSS in the MCP View resource for protected deployments
    npm test                           # spawns its own server on 18943

## Real backend
    JOBWATCH_CONNECTOR_TOKEN=... python -m pipeline.agentic.connector_http --port 18940   # JOBWATCH_MCP_PERSON picks the person
    JOBWATCH_MCP_TOKEN=... JOBWATCH_CONNECTOR_TOKEN=... JOBWATCH_BACKEND_URL=http://127.0.0.1:18940 npx mcp-use start --port <port>

## Discovery configuration

Daily token allowance is per person: `get_discovery_settings` reads it and
`set_discovery_settings` saves a positive limit or `daily_token_ceiling: null` for
Unlimited. The separate Discovery panel reads collection and assessment progress,
paused reasons and Hermes handoff state; it can refresh or start discovery when a
confirmed scope is enabled. Status polling does not replace unsaved allowance edits. Individual job/run limits, failure pauses and historical
spending remain.

## Real-application check (temp dir only)
    python -m tests.realapp serve --root /tmp/opencode/realapp --connector-port 18952 --native-port 18951   # real fill + browser; prints the token
    JOBWATCH_REAL_APP_TEST=1 JOBWATCH_PYTHON=<venv python> npx vitest run test/realapp.test.ts
