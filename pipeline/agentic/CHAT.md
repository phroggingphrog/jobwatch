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

## Profile intake and approval

The person comes only from the bearer token; ids belonging to another person return 404. Uploads and
proposals stay private and separate from the approved profile until confirmed. Nothing here prepares
documents, contacts an employer or submits; confirmation only starts discovery within the scope shown.

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
| `GET /api/agent/profile/policy` | read | The decision policy built from the latest confirmed profile, read only (nothing is written, no model is called): `{policy, mode, enabled, open_questions}`. `policy` is the policy JSON (`profile_version`, `strategy`, `focus`, `exclusions`, `home`, `max_commute_km`, `remote_ok`, `work_rights`, `seniority`, `regions`, `open_questions`, `policy_hash`); `mode` is `legacy` or `profile` and `enabled` is `mode == "profile"`. `open_questions` is a list of `{code, question, why}`. With no confirmed profile: `policy` is `null`, `open_questions` is `[]` and `reason` is `no_confirmed_profile`. |

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
same wording as the intake questions. The flag `agentic.decision_policy` is `legacy` (the default: the fixed rules decide) or
`profile` (the confirmed profile decides); any other value is `invalid_configuration`. `GET /api/agent/profile/policy` and the
chat tool `profile_policy()` return the same dictionary for the server-bound person and only read: neither writes a fact, a
rule, a label or an approval, and `profile_policy` is not a gated tool.

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
when there is nothing to search for) and `profile_confirm`. `profile_confirm` is a gated tool: the human approval is
bound to the exact `proposal_digest` and `scope_digest` (a changed draft or scope fails `approval_inputs_changed`),
and model text is never approval. It starts discovery within the scope shown; it authorises no documents, employer
messages or submission. The legacy `/welcome` onboarding is unchanged.

`profile_answer` and `profile_correct` are refused with `not_person_words` unless every recorded string is (after casefold,
whitespace collapse and edge-punctuation trim) inside the person's own message for the turn (on a resumed turn: the last human
message in the thread or a human answer to `ask_human`; none means refused). `profile_start` reserves its background parse
against the turn's budget and may start one parse per turn. A draft left `parsing` by a dead worker (no live slot, file older
than 2 x 180 s) reads back as `draft` with `parse_error` `parse_interrupted`, answers kept. The parse slot frees just after
the draft turns `draft`, so an immediate new start can briefly see `proposal_in_progress`. A person-stated location does not
drop a parsed one (both are kept). The optional MCP adapter does not know `profile_confirm` and refuses it (`invalid_chat_interaction`).

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
the only Submit path: it is approval-gated (approve scope), bound to the reviewed browser
fill's confirmation digest, and only queues a `submit_requests` row; the web process presses
within 15 minutes if the live form still matches, and `submit_status` reports the outcome
(pending, pressed, submitted, unsure, refused, expired). The web process trusts rows in the
person's jobs DB: code running as the agent API can write that DB, so the approval scope
protects the chat path, not a compromised agent process. The approval shows the posting id,
not the filled answers; review the fill on the board first.

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
row. Undo with `rm -rf <user_dir>/baselines/<baseline_id>` (or the whole `baselines`
folder); nothing else reads these folders. See
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
