# Design

## Context

`pipeline/agentic/mcp_server.py` builds an authenticated FastMCP server with a token of at least 32 characters bound to one Jobwatch person. `_person_from_request()` reads the verified subject; model tool arguments never select an account. `chatgpt_connector.register` adds eleven tools, six of them `READ_ONLY`.

Two reads are absent. `job_detail` returns an ad link, not the stored text. No tool returns follow-up cadence.

The reads themselves already exist inside the code: `service._capture(conn, posting_id)` returns posting identity, local advertisement text and text kind; `followup.events.history` and `application_cadence` return the recorded events and the next due date.

## Goals / Non-Goals

**Goals:** give an authenticated client the stored advertisement and the follow-up cadence, per person, with no model call and no approval. Keep person isolation identical to the chat path.

**Non-Goals:** no write, no state change, no submit path, no chat turn, no new service or port, no migration, no second name for a read that already exists, no summarisation over advertisement text.

## Decisions

1. **A read never calls `dispatch`.** A chat turn can spend paid calls and can interrupt for a person. `_read()` instead resolves the person, enters `users.use(person)`, loads the config and opens `job_connection(config)` read-only.

2. **Reuse the canonical reader.** `career_reader` calls `service._capture`, the same function the internal `inspect_job` chat tool uses, so the text and its kind match what the native pipeline sees.

3. **Cadence is counted, never drafted.** `followup_history` returns dates, counts, state and `draft_allowed` from `jobwatch/followup/tracking.py`. It sends nothing and generates no text.

4. **Reuse the existing annotation constant.** Both tools carry `chatgpt_connector.READ_ONLY`, so the protocol advertises `readOnlyHint: true` and a client can refuse work without reading the description.

5. **Unknown identifiers return a status.** A missing posting returns `status: missing`; a missing application returns `status: missing`; an unverifiable history returns `status: unknown` with the reason code. The client reports a fact instead of retrying.

6. **No duplicate names.** `find_jobs`, `application_status` and a second status read were dropped after inspecting the registered tool set. `jobs_overview`, `job_detail`, `application_detail` and `assessment_detail` already serve them.

## Risks

- Advertisement text in an MCP response. The stored text is already bounded by the collector and by `adtext`, and the payload carries no host path.
- A future contributor adding a write tool under a read name. The spec states the rule and the test asserts the annotation of both tools.
