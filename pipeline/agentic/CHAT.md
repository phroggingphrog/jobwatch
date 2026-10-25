# Jobwatch native agent API (TASK-183)

The owner chose: **"native API is my plan"**. Jobwatch runs the agent itself.
A client uses authenticated HTTP endpoints; a website or external AI chat host is
not required. LangChain model/tool interfaces, Deep Agents planning and specialist
work, and LangGraph persistence/HITL run inside the backend.

## Install and start

From an isolated checkout, install the locked runtime with `uv sync --frozen`.
Run `uv run --no-sync jobwatch-agent --host 127.0.0.1 --port 8914`. Only a loopback
bind is accepted; `0.0.0.0`, `::` and any LAN or public address exit without serving.
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

## Profile intake and approval

The person comes only from the bearer token; ids belonging to another person return 404. Uploads and
proposals stay private and separate from the approved profile until confirmed. Nothing here prepares
documents or submits; confirmation only starts discovery within the scope shown. Submitting is a separate step: the owner's own click, or Jobwatch pressing Submit after the owner confirms that exact reviewed form (board button or chat `submit_application`).

| Method and path | Scope | Result |
|---|---|---|
| `POST /api/agent/profile/uploads` | run | Multipart `file` + form `kind` (`cv`, `letter`, `evidence`; `.pdf .docx .txt .md`, 10 MiB). 201 `{upload_id,sha256,kind,bytes}`. Only route exempt from the 64 KiB cap (all POST, PUT, PATCH and DELETE bodies are capped); needs run scope before the body is read; counted while streaming. |
| `POST /api/agent/profile/proposals` | run | `{upload_ids,base_version}` -> 202 pending proposal: `status` `parsing`, revision 1, the open questions (employment, availability, work rights, constraints, exclusions, career focus, location) already listed. The documents are read in the background (one parse per person, 180 s). |
| `POST /api/agent/profile/proposals/{id}/uploads` | run | `{upload_ids}` -> 202. Reads further documents into the same draft in the background; what the person already said is untouched. `proposal_parsing` while a parse is running. |
| `GET /api/agent/profile/proposals/{id}` | read | The proposal: `status` (`parsing`, `draft`, `confirmed`, `superseded`), `parse_error` (an error code if the background parse failed; the draft and its answers stay usable), facts with basis and sources, open questions. |
| `PATCH /api/agent/profile/proposals/{id}` | interact | `{expected_revision,edits}` (`add`, `set`, `remove`). |
| `POST /api/agent/profile/proposals/{id}/answers` | interact | `{expected_revision,question_id,text}`. |
| `GET /api/agent/profile/proposals/{id}/confirmation` | read | `proposal_digest`, `scope`, `scope_digest`, what it does and does not authorise. |
| `POST /api/agent/profile/proposals/{id}/confirm` | approve | `{proposal_digest,scope_digest}` exactly as shown -> 201 `{version}`. Model text is never approval. |
| `GET /api/agent/profile/`, `GET /api/agent/profile/versions` | read | Current approved version (`{"version":null}` if none); version list. |
| `GET /api/agent/profile/policy` | read | The decision policy built from the latest confirmed profile, read only (nothing is written, no model is called): `{policy, mode, enabled, open_questions}`. `policy` is the policy JSON (`profile_version`, `strategy`, `focus`, `exclusions`, `home`, `max_commute_km`, `remote_ok`, `work_rights`, `seniority`, `regions`, `open_questions`, `policy_hash`); `mode` is `profile` and `enabled` is true (historical `legacy` config spelling is read as a compatibility alias). `open_questions` is a list of `{code, question, why}`. With no confirmed profile: `policy` is `null`, `open_questions` is `[]` and `reason` is `no_confirmed_profile`. |

Errors are `{"error": code}`. 409: `proposal_changed`, `scope_changed`, `adopt_first`, `proposal_not_draft`,
`already_adopted`, `profile_edited_by_hand`, `profile_incomplete`. 413: `too_large`. 415: `unsupported_type`. 422:
`no_extractable_text`, `invalid_edit`, `parse_failed`, `unreadable_document`, `nothing_to_adopt`. 404:
`upload_not_found`, `proposal_not_found`, `fact_not_found`, `question_not_found`. 503: `extractor_unavailable`.
403: `person_required`, and `gateway_not_allowed` / `model_not_allowed` when the gateway or the person's reader model is not an approved paid route (every parse path checks it before any text is sent). 409 also `proposal_in_progress` (one paid parse per person at a time, shared by the API and the chat tools; 180 s deadline) and `proposal_parsing` (confirm or add uploads while the documents are still being read). Capabilities include a `profile` object with the upload limits.

### Decision policy from the confirmed profile

The policy is derived from the person's latest confirmed profile and nothing else. Only an evidence-basis fact in the
`{"kind", "value"}` form becomes a rule; free text never becomes a rule and is listed as an open question instead
(`exclusion:<fact id>`: "Is '<value>' an employer, a kind of work, a place, a job family or a title word? Until you say, it
is not applied as a rule."). The standing questions (`employment_status`, `work_rights`, `location`, `career_focus`) use the
same wording as the intake questions. `agentic.decision_policy` defaults to `profile`; historical `legacy` spelling
also uses canonical confirmed policy and cannot reactivate personal defaults. Any other value is `invalid_configuration`. `GET /api/agent/profile/policy` and the
chat tool `profile_policy()` return the same dictionary for the server-bound person and only read: neither writes a fact, a
rule, a label or an approval, and `profile_policy` is not a gated tool.

### Field and job discovery

This screen requires a complete saved advert but uses bounded text: at most four
1,500-character embedding windows with 150-character overlap, and the first
12,000 characters for relevance extraction. Semantic dedupe shares these vectors.
It is separate from canonical full-ad assessment and does not establish complete
passage coverage for long adverts.

Field hypotheses compare approved profile evidence with public, versioned
occupation references. They are search hypotheses, never qualification proof.
The shared public references live under `<data>/reference/<dataset>/<version>/`;
person-specific hypotheses and plans live under `<person>/discovery/`. Embedding
calls use the configured Qwen embedding model through the approved paid
OmniRoute route and are charged to the confirmed scope's budget.

| Read-only route (read scope) | Result |
|---|---|
| `GET /api/agent/discovery/fields` | Cached hypotheses and status (`ready` or `not_computed`); this route does not call a model. |
| `GET /api/agent/discovery/plan` | Cached search plan, status and discovery flags. |
| `GET /api/agent/discovery/postings/{posting_id}/relevance` | Latest stored relevance judgment, mode and time; 404 `not_found` when none exists. |

Discovery flags are `pipeline.agentic.search_plan` (default `false`),
`pipeline.agentic.relevance` (`off | shadow | on`, default `shadow`),
`pipeline.agentic.dedupe` (`legacy | semantic`, default `legacy`) and
`pipeline.agentic.ordering` (`legacy | hypotheses`, default `legacy`). Shadow
judgments archive nothing; screening makes no model or embedding call until
fields and a plan have been refreshed. `relevance: on` archives a verified `no`
as `not_relevant`; `uncertain` proceeds. The exclusion pre-filter archives as
`excluded_by_rule` from the current confirmed policy in the normal default path. Semantic dedupe and hypothesis ordering use the approved embedding
route. The tuning defaults are `pipeline.discovery.similar_at: 0.60`,
`duplicate_cosine: 0.95`, `screen_per_run: 40`, `reconsider_per_run: 20`,
`embedding_token_ceiling: 2000000`, `screen_token_ceiling: 300000`, and
`relevance_model: null` (the configured evaluator model).

The explicit operator commands are `python -m pipeline.agentic.discovery
refresh --user NAME`, `python -m pipeline.agentic.discovery status --user
NAME`, and `python -m pipeline.agentic.discovery restore --user NAME`.
`status` is read-only; `refresh` computes and caches the current profile's
hypotheses and plan and may make paid embedding calls. Collection always derives unpaid search inputs from
the current confirmed scope. `search_plan: true` adds current cached occupational hypotheses; missing or stale
indexes fall back to approved directions without a paid refresh. Seek, Jora and JobSpy rotate every approved
location within existing request limits. Reddit uses confirmed geography. ATS/RSS/provider inventories remain
explicitly configured sources; there is no automatic acquisition of new providers. The similarity thresholds are
uncalibrated, there is no lexical hybrid, and these routes do not establish
matching accuracy or deployment.

### Guided onboarding in the chat agent

The chat agent guides a new person through the same draft instead of waiting for a finished parse. Answers given
while the documents are read are kept: when the parse ends it merges into the draft under the proposal lock, a fact the
person stated wins over a parsed fact in a one-answer section (employment status, availability, work rights, career
focus), questions already answered stay closed, and the revision increments (a client holding the old revision gets
`proposal_changed` and re-reads). A failed parse sets `parse_error` and the conversation continues with the answers.
Tools (identity is bound by the server, never an argument): `profile_start(upload_ids, use_existing_files)` (the
person's own `profile/` text files can be offered; symlinks are refused), `profile_status`, `profile_policy` (read only), `profile_answer`,
`profile_correct` (both record only the person's own words from their latest message; the prompt forbids inventing
or paraphrasing facts), `profile_confirmation` (scope, daily limits, what it does not authorise; `profile_incomplete`
when there is nothing to search for) and `profile_confirm`. Answers and corrections update only the unconfirmed
draft without a separate approval. `profile_confirm` remains gated: human approval is bound to the exact
`proposal_digest` and `scope_digest`. A changed draft or scope needs another review, and model text is never
approval. Confirmation starts discovery within the scope shown; it authorises no documents, employer
messages or submission. The legacy `/welcome` onboarding leaves unspecified level unknown; generated suggestions still require confirmation.

`profile_answer` and `profile_correct` are refused with `not_person_words` unless every recorded string is (after casefold,
whitespace collapse and edge-punctuation trim) a clause of the person's own message for the turn, or a span inside one of their
clauses that their own words affirm: a negation, pending or aspirational word governing the span refuses it, so "I am not a
citizen" never records "a citizen". The turn's words are the person's message (on a resumed turn: the last human message in the
thread or a human answer to `ask_human`; none means refused). The check runs when the draft tool executes.
`answer_question` applies the same test to the answer it records. `profile_start` reserves its background parse
against the turn's budget and may start one parse per turn. A draft left `parsing` by a dead worker (no live slot, file older
than 2 x 180 s) reads back as `draft` with `parse_error` `parse_interrupted`, answers kept. The parse slot frees just after
the draft turns `draft`, so an immediate new start can briefly see `proposal_in_progress`. A person-stated location does not
drop a parsed one (both are kept). The optional MCP adapter cannot present profile confirmation and refuses it
(`invalid_chat_interaction`); see the MCP section.

Discovery (collection and automatic assessment) runs for a person only while their CURRENT version carries a
confirmed scope (`approved.json` has `scope` and `scope_digest`) and the live `profile/` files still match the hashes
that version recorded (assessment reads them live, so a hand edit after confirming pauses discovery until the files match
again; `confirm` refuses to overwrite such an edit with `profile_edited_by_hand`). A version made by `jobwatch profile adopt` has no scope, so
it authorises nothing: an adopted owner onboards through a proposal with `base_version` set to the current version (guided in chat,
optionally from their existing files via `profile_start` with `use_existing_files`, or over the API), then confirms the scope shown. `jobwatch run` and `read` skip a person
without one (`--user all` still runs everyone else) and `after_collect` returns `{"skipped":"no_confirmed_profile"}`.
Confirming writes a new version, so an open draft proposal built on the previous version answers `proposal_changed`. A scope with an empty basis (an adopted version has no facts) is refused with `profile_incomplete` by `confirm`, and never authorises discovery; the manual `review`, `pipeline run|sort` and `python -m pipeline.agentic.cli` commands skip with the same reason. `--user all` splits a unit's time over the people who run.
Each person-local day it evaluates at most `scope.daily_assessments` jobs and stops once the day's charged tokens reach
`scope.daily_token_ceiling`; the rest stay queued for the next day (`{"deferred":"daily_budget"}`).

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
the supervisor. No shell or arbitrary host filesystem is exposed. `submit_application` is
and the in-chat application card both use the same confirmed-Submit operation: each is
approval-gated (approve scope), bound to the reviewed browser fill's confirmation digest,
and only queues a `submit_requests` row; the shared browser owner presses
within 15 minutes if the live form still matches, and `submit_status` reports the outcome
(pending, pressed, submitted, unsure, refused, expired). The shared browser owner trusts rows in the
person's jobs DB: code running as the agent API can write that DB, so the approval scope
protects the chat path, not a compromised agent process. The approval shows the posting id,
while the application card reads actual live values and attachments before its separate final Submit confirmation.

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

`<user_dir>/baselines/` holds frozen evaluation baselines made by
`jobwatch --user <name> baseline freeze`. It is candidate-bearing (copied profile files,
evidence, adverts and the owner's labels), so keep it private, never commit or upload it,
and note that it is included when the person's folder is backed up. It is not exposed
through the API, the chat tools or MCP, and a freeze calls no model and writes no database
row. Preserve these histories during source rollback; Phase 7 evaluation reads
them without changing their original cases or labels. See
[docs/examples/frozen-baseline.md](../../docs/examples/frozen-baseline.md).

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
install or use the native API. External MCP **client** tools for the chat
agent are separate and off by default (`mcp_client` below).

### External MCP client tools (off by default)

The chat agent can load tools from external MCP servers. Nothing is imported
and no server process starts unless both switches are on: `mcp_client.enabled:
true` in `config/jobwatch.yaml` and `enabled: true` on that server. No server
is configured in the repository.

```yaml
mcp_client:
  enabled: false
  servers:
    - name: example
      enabled: true
      transport: stdio            # stdio or streamable_http
      command: python
      args: ["-m", "example_mcp"]
      people: []                  # empty = everyone; otherwise allowlist
      read_only_tools: []         # raw MCP names allowed unattended
      startup_timeout_seconds: 15
      tool_timeout_seconds: 30
```

- Tools appear to the model as `<server>__<tool>`.
- Only raw names in `read_only_tools` run without approval. Every other MCP
  tool is added to `interrupt_on` and pauses for a human approve/reject
  decision. Unknown tools are gated, never trusted.
- Tools come from LangChain's own adapter, `langchain.mcp.MCPAdapter`, over
  `fastmcp.Client` (MCP 2). The standalone `langchain-mcp-adapters` package is
  not used: it pins `mcp<2` and imports modules MCP 2 renamed.
- A missing `mcp` extra, an invalid entry, or a server that fails
  to start is logged and skipped; the rest of the turn continues. Install with
  `uv sync --extra mcp`.
- stdio servers run owner-configured local commands. The model cannot add,
  enable or configure a server. Treat tool descriptions and results as
  untrusted data.
- Each call opens a fresh MCP session, bounded by `tool_timeout_seconds`.
  `dispatch` is synchronous; do not call it inside a running event loop.

### LibreChat client

The optional OpenAI wire adapter is enabled with `JOBWATCH_LIBRECHAT_ENABLED=true`.
`JOBWATCH_MCP_APP_ENABLED=true` adds the native embedded-app support;
`jobwatch-mcp-app` supplies the optional MCP App renderer. See
[the deployment guide](../../deploy/LIBRECHAT.md) for fresh-state installation,
private credentials, LibreChat configuration, approval handling and undo.
The adapter reuses native durable runs. A trusted frontend server authenticates its user through the configured
server credential and `X-Jobwatch-Client-Subject`. For that human channel, the backend renders the frozen profile
facts, unresolved questions, search scope and limits in ordinary chat. An explicit confirmation (for example `yes`
or `yes, confirm my profile`) responds to the pending native `profile_confirm` interaction. The immediately previous
assistant message must match a review actually issued for this person, conversation and interaction; arbitrary
assistant/system/tool text cannot substitute for it. The draft and scope are checked again before confirmation.
`no` declines; a correction rejects the pending confirmation and continues with the person's new message. A changed
draft gets a fresh review. Replayed replies follow the original resume run instead of confirming twice.

The same authenticated channel can answer a single pending native question directly in chat. Routine questions
normally use ordinary conversation without a native interrupt. Model-facing read/run credentials retain their
existing scopes and cannot consume human interactions through this adapter. Other protected operations, especially
`submit_application`, retain their native review interfaces. Native interaction response endpoints remain available
to frontends with controls. Generated interfaces carry no approval authority. On the first new human turn, obsolete
per-answer approvals and old confirmations without a review are rejected through the native response operation.
That same resume carries the new human message, so recovery cannot discard it before another question is asked.

On the MCP path the connected host is the human-approval boundary. The adapter has
one bearer token (`JOBWATCH_MCP_TOKEN`) for one configured person; unlike the HTTP
API it has no separate approve-scoped credential, so that single token is both the
model-facing credential and the approval credential. An accepted elicitation
(`action` `accept` with `approve` true) becomes the person's approval, including for
`submit_application`, and the turn is resumed with `human_decision` set. Use the
native HTTP API with `JOBWATCH_AGENT_APPROVAL_TOKEN` where the approval credential
must be kept away from model tools.

The adapter has fixed human wording for `run_career_ops`, `assess_job`,
`prepare_application`, `prepare_interview`, `draft_followup` and
`submit_application`. It cannot present the other gated operations (`profile_confirm`,
`reject_posting`, `restore_posting`,
`propose_exclusion`, `confirm_exclusion`, `pick_comparison`, `answer_question`,
`dismiss_prompt`, `select_jobs`, `cancel_selection`): their identity is a draft,
prompt, rule or selection rather than a posting, and the words a human would need
are in the binding subject the adapter does not read. Such a round is rejected on
the person's behalf (a rejection authorizes nothing) and the reply lists
`refused_operations`, so the thread stays usable; previously the interrupt stayed
checkpointed and every later message on that thread hit it again. The native HTTP
API presents all of them.

## GitHub source workflow

The private source repository is `phroggingphrog/jobwatch`. It starts from a
filtered source baseline; older Git history, operator notes and profile snapshots
stay local. Use a fresh clone of that repository for future branches. The legacy
PhrogVPS checkout has a different root and must not push its historical branches.

Branch locally from GitHub `main`, commit meaningful slices, and open a pull
request. Required local checks and independent review gate completion. Hosted CI
is disabled and optional; do not re-enable it. The owner's approved remaining-roadmap
plan authorizes merging each reviewed release before its successor. Keep profiles,
answers, credentials, databases, generated documents and backups outside Git.
Deployment is a separate action; publishing source does not activate the API.

## Company research and model insights

The shared evaluator now separates requirement-evidence judgments from its holistic
summary. Retrieval, status meanings, compatibility and remaining validation work
are documented in [MATCHING.md](MATCHING.md). This source change does not establish
matching accuracy or a deployed service.

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


### Preference policy and historical data

`candidate.eligibility.evaluate_eligibility` is shared by native assessment, the retained reader and
deterministic pipeline. Numeric advertised hours are compared with confirmed limits; program titles grant no
blanket exemption. A requested junior level does not create a two-year experience cutoff. Separate citizen,
permanent-resident, clearance and sponsorship facts are checked against quoted ad requirements; unknowns
and contradictions stay held. Holistic/career scores are advisory, not exclusion thresholds.

New run identities include the full immutable confirmed-profile digest. Confirmation during work invalidates
that input snapshot. Taste model feature/prior/structural versions changed; old immutable choices and fits
remain available but are stale under a changed profile/context, and are excluded from current training data.
New choice collection and fitting remain explicit. No live fit or private artifact was rewritten by source merge.

Writing defaults are factual and neutral. A confirmed preference can specify e.g.
`{"kind":"writing","value":{"tone":"warm","cv_template":"...","letter_template":"...",
"omit_grades":true,"responsibilities_per_role":3,"use_style_examples":true}}`.
Only supported installed templates are accepted; missing choices impose no graduate template, praise,
eagerness, grade suppression or bullet quota. Preferences frame writing but never become qualification proof.
See ADR 0006 and the source audit for release verification and undo.

## Ranking and explained shortlists (Phase 5)

Shortlists project current stored assessments without fetching ads or calling a model.
They use the same confirmed-profile gate as assessment. Eligible work and evidence-related
holds can appear; verification failures, confirmed exclusions, expired posting checks,
closed jobs and mandatory contradictions cannot appear as actionable matches. Holistic
scores stay advisory. The three evidence labels are `stronger_match`, `stretch` and
`needs_clarification`; documented weights and thresholds are provisional presentation
conventions, not measured hiring probabilities or personal preferences.

| Method and path | Scope | Result |
|---|---|---|
| `GET /api/agent/shortlist?label=&limit=20&offset=0` | read | Latest current snapshot with explained entries, rank reasons, coverage and unresolved facts; limit 1–50. |
| `GET /api/agent/shortlist/{posting_id}` | read | Full entry, frozen requirement rows and exact citations; 404 if absent or stale. |
| `POST /api/agent/shortlist/refresh` | run | Database-only rebuild. A snapshot under 60 seconds is reused only while its complete input identity remains unchanged. |

Bearer identity selects the person. Missing database returns `not_built`; no confirmed
profile returns `no_confirmed_profile`; changed inputs return `stale` with no entries.
Profile, evidence, ad, posting liveness, reference/configuration, gate/implementation,
ranking rules and preference-model context fence both persistence and reads. A change
inside the refresh window bypasses reuse. Shortlist snapshots display at most 100 entries;
list pages are bounded separately. Corrupt artifacts and unverifiable stored evaluations
must be assessed again rather than reused. Ordinary and spent-budget collection paths
refresh the shortlist without additional paid assessment; refresh failures stay isolated.

Ordering is provisional until a genuine current human-choice fit passes existing
20-training/5-holdout, convergence and held-out checks and supplies utilities for every
candidate. Personalisation operates within evidence tiers. Current semantic links to
confirmed career-focus facts can prioritize focus; unrelated evidence hypotheses cannot
silently become that preference. Callback statistics and response-time readiness never
change rank. Impression rows record actual displayed positions once per entry/surface/UTC
day; deterministic displays have NULL exposure probabilities and never create choices.

Preference features v4 retain zero priors and canonical families, replace the undefined
`automation_angle` with `status_held`, and preserve source provenance and missingness.
Only explicit observed salary units/hours permit conversion; no fixed 38-hour week is
assumed. Exact approved tenure can populate experience features only for a complete,
verified general-work-experience condition. Specialist scope, truncated source clauses,
unknown dates and unsupported inputs remain missing. Comparisons remain eligible-only;
evidence holds stay visible on the shortlist without becoming actionable selections.

`jobwatch preferences migrate --confirm-owner` is a separate explicit CLI operation.
It copies genuine answered choices only when complete old profile/policy/evaluation/ad
provenance remains verifiable and unchanged, retaining the original selection including
none, train/holdout split and migration lineage. Old records without that provenance are
skipped. Repeated migration is idempotent; original choices and fits remain immutable.
Neither application startup nor shortlist refresh migrates choices or fits a model.
Real synthetic sampler checks demonstrate statistical mechanics only; they do not validate
live ranking usefulness. No live migration, fitting or deployment is part of this release.

## Feedback and selected preparation (Phase 6)

Feedback events are immutable and person-bound. Rejection hides exactly one posting;
restore appends the original rejection ID and uses a new current snapshot. Both
transitions invalidate saved shortlist inputs. Reasons distinguish preference,
eligibility, data quality and neutral feedback. Impressions, rejections, restores,
selections and genuine comparison choices remain separate records.

| Method and path | Scope | Meaning |
|---|---|---|
| `GET /api/agent/feedback?limit=100` | read | Immutable history (maximum 200) and versioned reasons. |
| `POST /api/agent/shortlist/{posting_id}/feedback` | interact | Reject exact current `expected_entry_id`, `reason_code`, optional verbatim `reason_text`. |
| `POST /api/agent/shortlist/{posting_id}/restore` | interact | Restore exact `expected_rejection_id`; current eligibility still applies. |
| `GET /api/agent/profile/rules` | read | Active rules and proposals for the current approved version. |
| `POST /api/agent/profile/rules` | interact | Propose add (`kind`, `value`) or withdraw (`rule_id`) against the complete approved profile hash. |
| `POST /api/agent/profile/rules/{proposal_id}/confirm` | approve | Confirm exact `rule_digest`, publishing an immutable profile version. |
| `POST /api/agent/prompts/next` | read | Issue/reuse one bounded system comparison or question; no model call. |
| `GET /api/agent/prompts/next` | read | Read outstanding prompt without issuing one. |
| `GET /api/agent/prompts` | read | Person-bound prompt history. |
| `POST /api/agent/prompts/{prompt_id}/pick` | interact | Genuine displayed posting ID or `null` for none. |
| `POST /api/agent/prompts/{prompt_id}/answer` | interact | Verbatim answer, retained as feedback until separately confirmed as a profile fact. |
| `POST /api/agent/prompts/{prompt_id}/dismiss` | interact | Dismiss without creating a preference choice. |
| `POST /api/agent/selections` | approve | Approve preparation for 1–10 distinct current eligible jobs and exact entry/run IDs. |
| `GET /api/agent/selections/{selection_id}` | read | Durable selection, nullable run ID and eventual run/artifacts. |
| `POST /api/agent/selections/{selection_id}/cancel` | approve | Cancel pending dispatch or the existing queued/running preparation. |

Feedback writes, proposals, prompt replies/dismissal and selections require an
`Idempotency-Key`. Identical retries preserve the original result; different input
under that key conflicts. Rule confirmation binds its immutable proposal digest.
Authentication supplies identity and human scopes supply authority; actor/person
cannot be supplied in request bodies.

Canonical family, employer, title-term, location and work-type amendments take
effect on confirmation. Active rules survive later profile confirmation; old-base
drafts fail. Current full-profile hashing remains authoritative: amendments stale
evaluations, fits and shortlists and return work to normal budgeted processing.
Confirmation neither reassesses nor refits. The old `legacy` policy spelling is
a compatibility alias for canonical confirmed-policy enforcement.

Prompts default to one outstanding, three in rolling seven days and a thirty-day
repeated-question cooldown. Raw agentic settings `prompts_enabled`,
`prompts_per_week` (zero disables) and `question_cooldown_days` may reduce issuance
or lengthen cooldown. Valid current genuine-choice posteriors use canonical
diagnostics and held-out checks; otherwise at most nine unseen alternatives feed
deterministic factual disagreement. Every comparison displays three eligible jobs
and none. Display propensities remain NULL. Questions prioritize confirmed-policy
gaps, then facts unresolved across multiple current shortlisted jobs. Answers up
to 4000 characters remain verbatim in private event detail.

Selection commits its immutable manifest and events before API dispatch. A stable
person-scoped selection identity recovers the same API run across the two stores;
`pending_dispatch` exposes a selection ID and null run ID. Inputs and eligibility
are checked at acceptance, dispatch and execution; approval expires after 24 hours.
The completed result is retained with the selection so interrupted API publication
recovers it without another preparation pass or model-client initialization. Bounded
reconciliation reflects terminal queue states and cancellation into selection status.
Cancellation, budgets, package checkpoints and artifact verification reuse the
canonical preparation service. Preparation progress can resume without treating its
own operational checkpoints as changed evidence. Changed profile/ad/policy/model
inputs fail before paid work. A completed conversation may only have selected the
jobs: follow the selection's run to its actual READY/held/deferred outcome and files.

Chat exposes `ranked_shortlist`, `feedback_history`, `exclusion_rules`,
`next_feedback_prompt` and `selection_status` directly. Human writes use the same
domain services through exact-payload interrupts naming literal jobs, choices,
answers, reasons and amendments. `prepare_application` and `run_career_ops` select
one current entry; `select_jobs` selects 1–10. Question text must come verbatim from
the person's words. Model text never supplies approval. Skills changed with this
release; use a matching source/skills release for persisted conversations.

Selection authorizes preparation only. Final Submit remains the existing separately
confirmed operation. Source rollback retains profile history, feedback, choices,
fits, selections, packages and reports. See [ADR 0008](../../docs/adr/0008-feedback-and-selected-preparation.md)
and the [synthetic example](../../docs/examples/feedback-selection.md).


## Frozen evaluation and bounded monitoring (Phase 7)

`jobwatch --user <person> evaluate` provides `cases`, terminal-human `label`,
write-once `split`, `replay` (alias `run`), `report` and `monitor`. The tools operate
in the selected person's private baseline area; they are not agent tools or API
label writers. Existing `baseline label` also requires explicit audited access
when labelling a split's holdout case. Both `baseline show` variants require
`--allow-holdout` before inspecting a split baseline and audit that inspection.

New freezes pin complete approved profile/evidence, ads, target and decision
policy, runtime/discovery configuration, search plan, field hypotheses and matching
relevance judgments. Per-case relevance stays with that case, so monitoring does
not open holdout ad evidence through a shared context file. Older baselines without
this context report `frozen_context_unavailable`; replay never substitutes live
configuration. Freeze uses a read-only database snapshot and the profile-version
lock; configuration drift is rejected before publication. Replay does not read
production databases or the live approved profile.

Splitting unions duplicate-ad, normalized employer and historical grouping keys
transitively. A seeded order allocates `ceil(30% of groups)` to holdout, leaving at
least one development group; fewer than two groups is explicitly unavailable.
The same seed reuses the split and a different seed conflicts. Cross-partition
keys or groups are refused. Holdout replay, label and report operations require
`--allow-holdout` and append private source/data/split provenance to an audit log.
Reports contain aggregate holdout results, without individual holdout entries.

Default replay is zero-model and provisional, using the canonical gate, coverage,
labels and ordering with frozen inputs. It compares original baseline routes and
advisory-score ordering against that current calculation. A baseline frozen after
a gate revision remains labelled as such. Default limits are 500 cases and 300
seconds. Monitoring enforces those maxima in `evaluate_runs.replay` itself, not only in
the CLI, is development-only and never reads the human-label log or holdout cases.
Precision at k divides by k and reports `short_prefix` with the arm's actual depth when it
ranked fewer than k cases, so arms of different depth stay comparable. It creates no timer or service.

A paid evaluation requires both `--paid` and a positive `--budget-tokens`; the
canonical runtime, approved paid routes and remaining deadline enforce the budget.
It re-evaluates in memory and writes only private evaluation results. No research
fetch, production run, package or submission is performed. Optional `--fit` uses
only frozen genuine choices whose alternatives all belong to the processed
development cases, retaining original train/holdout assignments and canonical
sampler diagnostics. Its result is evaluation-only; ordering stays provisional.
Neither paid replay nor live fitting is part of source implementation verification.

Versioned metrics require ten applicable genuine human labels for each quality
metric. Missing suitability, relevance or exclusion labels remain missing; they do
not become negatives. Precision/nDCG at 5 and 10 explicitly use condensed labelled
ordering and report coverage. Partial replay suppresses comparative quality values.
Citation integrity and mandatory-conflict indicators are deterministic diagnostics,
not independent qualification judgments. Missing latency remains unmeasured;
original historical usage and new replay usage remain separate. Pending outcomes
are censored and never rank jobs; exposure/selection bias and absent propensities
remain limitations.

Private content-addressed JSON/Markdown exports allow only safe identifiers,
closed enums, numeric metrics and provenance hashes; they omit candidate/ad text,
notes, raw labels and arbitrary reasons/errors. Repeated exports have identical
bytes, and conflicts or symlink paths are refused. Directories are `0700`, files
`0600`. Retain baselines, human labels, splits, access logs, results, fits and reports
during rollback. See [ADR 0009](../../docs/adr/0009-frozen-evaluation-and-monitoring.md)
and [the command example](../../docs/examples/evaluation-monitoring.md). This tooling
supports a later real blind study; synthetic checks do not establish measured
recommendation quality or deployment.


Phase 7 [source verification](../../docs/audits/2026-10-23-evaluation-monitoring.md)
records the full local suite (3804 passed, 11 skipped), independent review and real
synthetic sampler checks. It discloses a temporary smoke-harness installed-database
access and unknown schema delta; source completion is not a no-live-access certificate
or a claim of deployment or measured recommendation quality.

## Complete LibreChat frontend

LibreChat and the website are separate frontends. The fixed MCP App uses
`jobwatch_view(run_id, card_kind, subject_id)` and `jobwatch://cards/...` to show
profile, models, jobs, progress, documents or application review. An automatic view
resolves canonical pending work first. Subjects are validated against the authenticated
person's native state. Historical `jobwatch://runs/...` resources retain their legacy
shape. Reopening cards only reads existing runs and never starts paid work.

A trusted server-to-server connection enrolls `POST /api/agent/librechat/enroll`
using `JOBWATCH_LIBRECHAT_IDENTITY_KEY`. The deployment pins
`JOBWATCH_LIBRECHAT_OWNER_SUBJECT` to the existing owner's signed-in LibreChat ID.
Other IDs provision isolated people atomically. Only LibreChat's authenticated server
supplies that subject; users, models and app tools cannot choose it. Distinct encrypted
chat and human credentials remain server-side. The deployment-level LibreChat `jobwatch`
configuration enables this connection; `mcpAppSandbox.autoOpenServers` allows automatic
cards only for the configured server. Defaults preserve other MCP apps.

`JOBWATCH_NATIVE_BROWSER_ENABLED=true` enables the shared native browser service.
The website uses it through loopback `JOBWATCH_NATIVE_BROWSER_URL`; without that
setting it remains independently usable with its existing local browser owner.
`/api/agent/applications` exposes only the person's application state; per-application
`open`, `answers`, `frame`, `review` and `submit` operations require human scope for
browser access/mutations. An in-chat five-minute control capability binds one person,
application and browser target, permits bounded browser input, including the final Submit click, which only goes through when it
carries the `confirmed_digest` of the exact form the owner reviewed (a refused attempt voids that review). No browser debugging port is exposed. The exact reviewed form includes
employer, URL, actual values and attached documents. Unsupported/custom unreadable
controls block review. Human corrections use a separate private review overlay;
original preparation records stay immutable. Final Submit still uses
`jobwatch/apply/submit_confirm.py`, one-use confirmation, expiry and press-time checks.
Uncertain outcomes block automatic retries.

Document revision requests are separately human-approved, scoped to one posting and
included in its exact pipeline run key. They remain writing instructions, never profile
facts. Canonical route, budget, claim verification, review and packaging gates apply.
The client retains unsaved form/model choices through API reconnects and provides a
text fallback inside chat; it never directs a user to the website as the fallback.

## Configured OmniRoute combo names

The owner removed the provider-prefix restriction on 2026-10-24 so existing
OmniRoute combos such as `deepseek-flash`, `distiller` and `openai/luna` can be
selected directly. Chat/reader routes accept valid model or combo IDs on the exact
configured loopback gateway. The existing free/stealth/Opus/Astra exclusions and
separate embedding allowlist remain. Gateway routing remains authoritative for
whether an ID exists and which subscription serves it; the native catalog lists
available routes. Per-person role choices remain runtime settings.

## Standard chat clients (2026-10-24)

The owner selected vanilla LibreChat with native Artifacts and no Jobwatch cards.
Chat answers are Markdown by default: GFM tables for comparisons and fenced mermaid
diagrams for flows. `JOBWATCH_UI_FORMAT=artifacts` adds native Artifact authoring when
the person explicitly asks for a visual. Chat renders no Jobwatch cards, so canonical
views, settings and application review stay on the board; old MCP resources remain
readable. Artifacts never grant human approval; a gated action stays paused when its
client cannot supply protected human review.

`POST /v1/chat/completions` accepts standard text/file content parts containing
`file.filename` and base64 `file.file_data` data URIs. Inline image/audio/video data
is retained too; remote URLs and unresolved file IDs are not fetched. The aggregate
original-byte limit is 10 MiB per turn, at most 20 files. The full request envelope,
including retained message/file history, is separately bounded at 64 MiB. Standard clients should
route attachments to the provider, preserving original bytes rather than extracting
text before transmission. Unknown or corrupt formats are retained with an explicit
unreadable receipt, not rejected as a failed conversation. Supported documents and
bounded ZIPs enter canonical intake as unconfirmed evidence. ZIP extraction reads
members in memory, with at most 100 entries and 20 MiB expanded content; it never
extracts paths onto disk or executes content.

A trusted chat host can use its configured server bearer credential and
`X-Jobwatch-Client-Subject` on `/v1/models` and `/v1/chat/completions`. LibreChat can
supply `{{LIBRECHAT_USER_ID}}` from its authenticated user through ordinary YAML
configuration. The existing private identity registry preserves the owner's mapping
and provisions isolated friends. This server credential never enters browser/model
text and this adapter grants only read/run scope. It cannot approve operations or
authenticate other native API routes. Existing per-person bearer clients continue
to work. Never use an unauthenticated browser/model field as a trusted subject.
