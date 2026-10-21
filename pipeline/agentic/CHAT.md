# Jobwatch native agent API (TASK-183)

The owner chose: **"native API is my plan"**. Jobwatch runs the agent itself.
A client uses authenticated HTTP endpoints; a website or external AI chat host is
not required. LangChain model/tool interfaces, Deep Agents planning and specialist
work, and LangGraph persistence/HITL run inside the backend.

## Install and start

From an isolated checkout, install the locked runtime with `uv sync --frozen`.
Run `uv run --no-sync jobwatch-agent --host 127.0.0.1 --port 8914`.
The endpoint is a standalone FastAPI application using existing dependencies; it
does not start the board, browser auto-fill loop, DSH or collection timers.

Load credentials through the service's private environment/secret manager:

| Setting | Meaning |
|---|---|
| `JOBWATCH_AGENT_TOKEN` | Random bearer secret of at least 32 characters; read/run scope. |
| `JOBWATCH_AGENT_APPROVAL_TOKEN` | Different random bearer secret; read/interact/approve scopes. Keep it in the trusted user-interaction client, away from model tools. |
| `JOBWATCH_AGENT_PERSON` | Server-configured Jobwatch person; defaults to the existing default account. |
| `JOBWATCH_AGENT_CREDENTIALS_FILE` | Optional mode-0600 JSON array of `{token, person, scopes}` for multiple accounts; replaces the simple environment mapping. |

The existing Jobwatch settings supply the gateway, model choices and data paths.
The approved loopback gateway must be configured; generic external-provider
fallbacks and free/stealth/Opus/Astra helper selections fail closed. Conversation
and specialist calls use one shared gateway transport and the configured credential
index. No fallback to the first credential is added.

Bearer credentials select identity on the server. Cookies, a JSON `person` field,
`human_decision=true`, arbitrary filesystem paths, and client graph config are not
API inputs. No permissive CORS configuration is installed. Use HTTPS through the
existing reverse proxy before remote access. Bearer authentication is suitable for
a configured trusted client; interactive OAuth enrollment is not implemented.

## Native contract (schema version 1)

Every protected request uses `Authorization: Bearer <secret>`.

| Method and path | Result |
|---|---|
| `GET /health` | Liveness/worker health; no private state. |
| `GET /api/agent/capabilities` | Effective mode, skill version, credential scopes. |
| `GET /api/agent/openapi.json` | Authenticated API schema. |
| `POST /api/agent/threads` | Server-generated thread ID and pinned skill hash. |
| `GET /api/agent/threads/{id}` | Own thread and run identifiers. |
| `POST /api/agent/threads/{id}/runs` | Start work from `{"message":"..."}`; returns 202 with run ID. Requires `Idempotency-Key`. |
| `GET /api/agent/runs/{id}` | Status, final answer/outcomes, pending interactions, usage, protected artifact references. |
| `GET /api/agent/runs/{id}/events` | SSE activity with stable event IDs; reconnect with `Last-Event-ID` or `after`. |
| `POST /api/agent/interactions/{id}/responses` | `{"decision":"answer","answer":"..."}`, `decline`, `approve`, or `reject`. Requires interact scope; approvals also require approve scope. Returns resume run ID when all responses are supplied. |
| `POST /api/agent/runs/{id}/cancel` | Cooperative cancellation. A dispatched provider request may finish before cancellation takes effect. |
| `POST /api/agent/runs/{id}/retry` | Explicitly recover an interrupted/deferred run with the same identity and retained usage. |
| `GET /api/agent/artifacts/{id}` | Own verified CV, letter or form map; no server path is exposed. |

A completed run means a **conversation turn** completed. The `result.outcomes`
array supplies actual Jobwatch statuses/reasons. READY requires the existing
immutable-package, factual-review, PDF and current-posting checks. The assistant's
text cannot certify success.

Run states include queued, running, waiting_for_input, waiting_for_approval,
completed, resumed, deferred, interrupted, failed and cancelled. Poll the returned
run ID or read SSE. A response to an interaction can create a new resume run;
follow that returned run ID. Earlier runs and interactions remain inspectable.
An unsupported/stale/expired interaction never authorizes work.

POST bodies are bounded to 64 KiB; message text to 16,000 characters; answers to
4,000. Bodies reject extra fields. Validation and error responses omit submitted
content. Private responses use no-store. Idempotency keys are scoped to the thread;
reusing a key with different inputs returns 409. Only one active run per thread
is admitted, and a person's queued work is bounded.

## Runtime and recovery

One worker per data root owns a process file lock. It serializes paid runs and
fairly checks configured people. Run creation persists before execution; requests
return promptly. The existing per-person dispatcher lock also prevents overlapping
MCP/direct callers; contention is reported as a deferral rather than waiting while
holding an API request open.

Graph checkpoints, pending writes, API threads/runs/interactions/activity, artifact
references and advisory memory live in `<person>/career-chat/state.sqlite`.
The directory is 0700 and database is 0600. SQLite WAL and transactions protect
state; databases are separate per person. The dispatcher uses the configured jobs
DB, creates worker-owned connections with row factories, and closes them explicitly.

After an unclean stop, running operations become `interrupted`. A trusted client
can retry explicitly. Graph-complete work is recovered without another model call;
unfinished graph work resumes from persisted state. A model request dispatched
just before a crash can still have uncertain provider spend. Its conservative
reservation remains charged, and retry does not reset usage or role budgets.

Approval is bound to the person/thread checkpoint, operation, relevant evidence,
posting/config identity and skill version. Changed inputs require another decision.
Consumed decisions cannot be changed or reused for another action. Interactions
expire after 24 hours; durable thread state has a separate lifetime.

Skills are pinned by hash. Old thread history remains readable after a skill
change, but execution reports `thread_skill_version_changed`. Resume with the
matching release or start a new thread; no silent instruction migration occurs.
Automatic evidence summarization remains disabled.

## Agent capabilities

Deep Agents provides planning, scoped virtual files, named reader/company-research/model-insights/reviewer
specialists, per-person advisory memory, skills and human interrupts. Existing
bounded evaluator/writer/reviewer role graphs own canonical assessment and package
work. Their model transport, route checks and invocation budgets are shared with
the supervisor. No shell, arbitrary host filesystem or final Submit tool is exposed.

`find_jobs`, `application_status` and `source_health` support read-only discovery.
The reader can retrieve canonical evidence by source name, hash and explicit line
pages. The researcher uses saved public employer identity; candidate details cannot
be supplied as search queries. Approved writing references are retrieved locally.

`assess_job` evaluates without drafting. `prepare_application` prepares the existing
CV/letter/form package; `run_career_ops` is its compatibility entry point.
`prepare_interview` and `draft_followup` reuse existing evidence/history-bound
services. All paid/persisted career operations pause for human approval. Missing
personal facts pause for a user answer, without editing the canonical profile.
Style feedback allows one rewrite; factual/company/placeholder/PDF failures block.
A form map does not mean a browser form has been filled, and no tool sends mail.

Workflow guidance is packaged in `skills/*/SKILL.md` and selectively loaded by the
native Skills middleware. Personal facts are loaded from the current person's
runtime evidence, never packaged into a skill. Memory is advisory, not a profile.

## Execution modes and diagnostics

`pipeline.execution_mode` is the single effective AI selection: `off`, `reader`,
`pipeline`, or `agentic`. It supersedes legacy booleans. Installations without it
retain the old precedence: agentic, then pipeline, then reader. Collection is
independent. Roll back by selecting the desired effective mode, not toggling a
legacy flag underneath it.

Collector IDs, batch IDs, API invocation IDs, job run keys and posting IDs are
linked in `agentic_activity`. Batch summaries distinguish clock deferrals, lease
conflicts and missing jobs, with an eligible time where known. Conservative token
charges and reported actual usage are separate. No dollar amount is invented for
unknown usage/pricing.

SSE/diagnostic rows contain activity, safe codes, IDs and usage, not prompts,
answers or candidate documents. Those remain in authenticated private state.
Candidate-bearing LangSmith tracing is disabled, inherited callbacks are removed,
and global debugging/tracing handlers are refused. Raw local failure capture is
opt-in via `JOBWATCH_CAPTURE_PRIVATE_FAILURES=true`; those private files must never
be uploaded or committed. Existing raw files are preserved, not automatically deleted.

For local deterministic AgentEvals checks, install the dev extra and run:
`uv run --no-sync jobwatch-agent --person <person> --evaluate-run <run-id> --expected-tools <tool> ...`.
This compares tool trajectories without a model judge, candidate text or hosted
tracing. It does not measure writing quality.

## Backup, release and undo

Create a consistent private state backup with
`jobwatch-agent --person <person> --backup <new-private-file>`.
The command refuses to overwrite a destination. Include the person's existing jobs
DB, evidence and immutable artifact directory in normal backups as well. Restore
state while the agent service is stopped, keep the pre-restore file, and restore
matching code/skills alongside it. There is no automatic deletion of checkpoints,
interactions or artifacts; archive backups before adopting a retention policy.

`deploy/jobwatch-agent.service` is an optional user-service installation template.
Install/restart only as a release action after configuring private credentials.
It is not installed or activated by importing the API. Run from a clean locked
installation, use the authenticated schema, and check one actual API interaction.

The focused native tests use synthetic data and deterministic gateway transports,
including an enabled pipeline and real generated PDF bytes. They cover question /
approval / rejection, idempotency, stale decisions, account isolation, downloads,
restart recovery and uncertain-operation handling. They do not establish live-model
writing quality or actual browser form behavior. The existing full test suite and
`jobwatch check --code` remain release checks.

Undo a source release by reverting its commit(s) and restarting only the agent
service. Additive SQLite tables can remain; preserve all user state and documents.
An effective execution-mode change should be restored from its config backup.
No UI/DSH changes or live-service activation are part of source verification.

MCP is optional (`uv sync --extra mcp`, `jobwatch-mcp`). Its experimental adapter
calls the same dispatcher and bound approval contract. It is not required to
install or use the native API.

## GitHub source workflow

The private source repository is `phroggingphrog/jobwatch`. It starts from a
filtered source baseline; older Git history, operator notes and profile snapshots
stay local. Use a fresh clone of that repository for future branches. The legacy
PhrogVPS checkout has a different root and must not push its historical branches.

Branch from GitHub `main`, commit one meaningful change, and open a draft pull
request. Inspect the synthetic CI result and review before merging. Keep profiles,
answers, credentials, databases, generated documents and backups outside Git.
Deployment is a separate action; publishing source does not activate the API.

## Company research and model insights

`company_researcher` replaces the earlier generic `career-researcher` specialist.
Its `research_company(posting_id)` reads the whole saved ad and gathers bounded,
cited public company/skills context using the saved employer and title only.
Explicit ad requirements, preferred skills, public company facts and inferences
remain distinct. Public pages do not create new eligibility requirements.
The shared core job service runs a dedicated bounded `company_researcher` role
before the writer, using the existing researcher budget and approved worker model.
Its structured desired-skills/duties/company-facts brief is checked against exact ad
and public-source quotes, saved as an immutable `company_research` artifact, and
passed to the writer and factual reviewer. It runs for automatic collected-job
preparation and API-requested preparation alike. The writer also receives the
approved career profile as interest framing, never as qualification evidence.
If research fails or is disabled, the writer uses actual ad duties and reports
ad-only context; it must not invent company details or personal motivation.

The core pipeline saves a `model_insights` snapshot before job evaluation and
passes it to the evaluator and writer. Structural fit, preference readiness and
historical callbacks stay separate advisory measures. Saved snapshots are reused
on recovery rather than rewritten when later history changes.

The optional conversation supervisor exposes the same existing calculations through
its `market_evaluator` specialist and `candidate_paths`,
`preference_insights` and `callback_insights`, alongside saved application status:

- Occupational fits use 60% activity coverage + 40% cosine similarity; structural
  proximity is not qualification or hiring probability.
- The local R/JAGS conditional-logit preference model predicts owner choice among
  three eligible jobs plus none. At least 20 training and 5 held-out choices,
  convergence/precision checks and held-out improvement are required. Only already
  answered, current comparisons can be predicted. Readiness states remain explicit.
- Historical callbacks use a Beta(1,15) prior with uncertainty. Prior-only and
  observed rates are distinguished; no individual-job hiring forecast is implied.
- The older pipeline's 40/30/30 skills/experience/domain rubric is confined to
  `pipeline` mode. The agentic holistic assessment is a separate measure.

The model tools are read-only; fitting and owner-choice collection keep their
existing CLI/web entry points. No live labour-market or salary research is added.
Load `company-research` or `model-insights` as appropriate. Changed skill hashes
require a new thread (or the matching old release); the implementation version also
changes to prevent reusing an old cached letter as evidence of the new writer.
Old artifacts and owner-choice history are preserved. Since preference contexts
include implementation provenance, old fits may no longer be current; historical
choice counts remain visible. No retraining or owner-choice migration occurs.

Chat, the existing web interface and future clients are interchangeable front ends.
This change belongs to the shared backend pipeline; it adds no chat or website UI.
