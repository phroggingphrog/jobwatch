# Career Ops backend conversation (TASK-183)

Owner request (verbatim): "need to utilise full deep agents capabilities and the langchain ecosystem framework integrated in and do not focus on front end as current goal is to be dispatched as a chat agent first before integration into website ui ux so need the back end working"

Owner correction (2026-10-21): build and understand the backend agent first. Do not wire it into DSH or the website in this phase.

## Trusted local backend entry point

```python
from pipeline.agentic.chat import dispatch

result = dispatch(person="authenticated-user", thread_id="conversation-id",
                  message="Inspect job 7 and prepare an application if eligible")
# Return result['interrupts'] to the human caller. Only after their explicit decision:
result = dispatch(person="authenticated-user", thread_id="conversation-id",
                  decisions=[{"type": "approve"}], human_decision=True)
```

This is a Python backend dispatch API, not an HTTP service, DSH plugin or website route.
A trusted host caller must map authenticated identity to Jobwatch's person name;
it must not let the model select the person or set `human_decision=True` itself.
Existing website chat remains read-only and unchanged. No host transport or UI
integration is included in this branch.

The response has `status` (`complete` or `interrupted`), `answer`, `interrupts`,
`todos`, and tool names. `complete` means the conversation turn ended, NOT that
an application was prepared. Consult Jobwatch tool results for work outcomes.
Reconstructing the graph on every dispatch intentionally verifies reopen/resume;
conversation and pending approval are stored locally, not just in RAM.

## Capability mapping and safety

Based on the official Python documentation read for this implementation:

| Capability | Implementation / boundary |
|---|---|
| [Planning](https://docs.langchain.com/oss/python/deepagents/overview#task-planning) | Explicit `TodoListMiddleware`; todos checkpoint with thread. Planning is opt-in in 0.7, not enabled by the old role runner. |
| [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) | Native `task` dispatch to `career-reader`, with only `inspect_job` and read-only virtual file tools. Existing evaluator/writer/reviewer remain bounded role graphs, reached through `run_agentic_job`; no duplicate drafting logic. Generic subagent disabled via the adapter's harness profile. |
| [Skills](https://docs.langchain.com/oss/python/deepagents/skills) | Career Ops skill seeded into thread StateBackend; SkillsMiddleware discovers it and `read_file` loads instructions. No skill scripts or shell execution. Canonical skill content is code-owned/read-only through filesystem permissions. |
| [Filesystem](https://docs.langchain.com/oss/python/deepagents/backends) | CompositeBackend: thread-scoped StateBackend, `/memories/` routed to StoreBackend with a closed-over person namespace. No FilesystemBackend, LocalShellBackend, shell, browser, arbitrary network tool or host path arguments. |
| [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Local synchronous `BaseCheckpointSaver` implementation stores full typed checkpoints and pending writes in SQLite. Per-person JSON `BaseStore` supports virtual files across threads; no embeddings or hosted memory. Official SqliteSaver package was unavailable and its installation was sandbox-blocked, so no dependency/environment change was made. |
| Memory | `/memories/AGENTS.md` is loaded by native memory middleware, with advisory notes only. Memory cannot write profile facts or bypass policy. All virtual files/checkpoints live in `<person>/career-chat/state.sqlite`; directory 0700, file 0600. |
| Middleware | Text-only gateway adapter, shared 24-model-call/180-second dispatch bound, native filesystem permissions, planning, skills, memory, and HITL. Custom tool middleware restores person identity in worker contexts. |
| [Human approval](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop) | `run_career_ops` pauses for approve/reject before paid/persistent career work. `ask_human` pauses for a human response without writing profiles. Only trusted caller-supplied explicit decisions resume. There is no Submit/contact tool, even after approval. |

Route checks reject non-server or non-loopback gateways and non-paid model prefixes
before candidate context is dispatched. The conversation and every pipeline role
model must use `openai/`, `claude/` or `google/`. Free/stealth/Opus/Astra selections
are refused, not silently replaced. Existing model selection code no longer enforced
these restrictions, so this entry point adds its own fail-closed boundary.
Legacy Jev/embedding extras are disabled in an invocation-only config copy because
some legacy paths send derived candidate facts outside the approved paid routes.
Eligibility, review, quota, fenced claims, immutable artifacts and run/defer reasons
remain owned by the existing Jobwatch service/store. No timer or saved config changes.

LangSmith tracing is explicitly disabled inside an empty context, callbacks are not
accepted, global debug/verbose and legacy tracing handlers are refused. No payload
capture is added. Exceptions exposed by this dispatcher use fixed safe codes.
The existing role runner's empty Context now preserves the current person explicitly,
preventing fallback to the default person's profile on nested role execution.

Not included: hosted LangSmith deployment/tracing/Hub, arbitrary MCP tools, shell,
code interpreter, generic/forked/async subagents, autonomous profile editing, browser
form filling or Submit. These expand privileges or parallel paid work without helping
this smallest chat slice. Automatic summarization is disabled so full job evidence is
not silently compressed; long conversations currently stop at the dispatch budget.
No frontend, service restart, timer/config edit, deployment or production DB access.

## Focused synthetic verification

Exact command (from this worktree):

```sh
PYTHONPATH=/home/phroggingphrog/.local/lib/python3.12/site-packages:/usr/lib/python3/dist-packages /home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q -s tests/test_deepagents_runtime.py::test_backend_chat_dispatch_synthetic
```

Observed: `1 passed in 2.59s`. Actual conversation output:

```text
FIRST: interrupted; tools = write_todos, read_file, write_file, task
pending action = run_career_ops(posting_id=7); allowed decisions = approve, reject
RESUMED: complete; Deferred: agentic_disabled. No application submitted.
MEMORY: Your synthetic preference is concise answers.
ISOLATION: Separate person; no previous messages. tools = []
RESULT: planning, skill read, specialist, SQLite reopen/resume, approval, defer, cross-thread memory and person isolation exercised; synthetic transport only.
```

The test uses only temporary synthetic per-person DBs and a deterministic gateway
transport through the real Deep Agents/LangGraph execution. It asserts tool names,
pending action, rejection of non-human approval, stored memory in the next thread,
and absence of the first person's memory/history in the other person's prompt.
The specialist inspects a missing synthetic posting and returns missing, not a
fabricated ad. Enabled evaluation/drafting, real paid model behavior, human question
response/rejection, crash recovery during side effects and any host chat transport
are **not verified** by this run. The owner's CV/letter golden example is not applicable:
this run generates no CV/letter and cannot establish writing quality.

## Undo and remaining gaps

Changed files: `pipeline/agentic/chat.py`, `pipeline/agentic/chat_storage.py`,
`pipeline/agentic/deepagents_runtime.py`, `tests/test_deepagents_runtime.py`, this document.
No dependency changes. Source was built in the isolated `feat/jobwatch-deepagents-chat`
worktree and fast-forwarded into local `main` as commit `129e0df`.
Undo: revert the backend feature commit in the local repository.
Do not delete person chat databases; archive them if retiring this feature.

Remaining: an enabled real-model/pipeline run, paid end-to-end draft/form proof,
retention/backup policy and production-grade checkpoint adapter hardening. Whole-tool replays around a crash use
the existing pipeline's claims/run-key artifacts, not a promise of exactly-once model
spend. Only synchronous dispatch is supported. Host transport and website integration
are intentionally out of scope. No production activation requested.

TASK-183 remains In Progress. Its current acceptance criteria and owner correction
are recorded on the task card.
