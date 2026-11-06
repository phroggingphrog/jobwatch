# Tasks

## 1. Add the two reads

- [x] 1.1 Inspect the registered tool set before adding anything; record that `jobs_overview`, `job_detail`, `application_detail` and `assessment_detail` already serve search, advertisement link, status and history, and drop the three duplicate tools from the first draft.
- [x] 1.2 Add a `_read()` helper to `pipeline/agentic/mcp_server.py` that resolves the person from the verified token, enters `users.use(person)`, loads the config and yields a read-only `job_connection`.
- [x] 1.3 Register `career_reader` over `service._capture`, returning posting identity, stored text and text kind, with `status: missing` for an unknown id.
- [x] 1.4 Register `followup_history` over `followup.events.history` and `application_cadence`, returning dates, counts, state, due date and `draft_allowed`, with `status: missing` for an unknown application.
- [x] 1.5 Annotate both tools with the existing `chatgpt_connector.READ_ONLY` constant and extend the server instructions.

## 2. Prove the boundary

- [x] 2.1 Test both tools against a scratch database: a known posting, an unknown posting, an application with events, an unknown application. Assert no host path appears in a payload.
- [x] 2.2 Test that the database is opened read-only and that a call writes nothing: compare a file checksum before and after.
- [x] 2.3 Test the tool set: both names present, both annotated read-only, `submit_reviewed` still the only destructive tool, and no duplicate read name for an existing read.

## 3. Align and record

- [x] 3.1 Confirm `pipeline/agentic/skills/inspect-jobs/SKILL.md` and `.pi/skills/jobwatch/SKILL.md` name the same read operations; update a name only where they disagree.
- [x] 3.2 Run the focused MCP and chat checks, record the exact command and result on TASK-382, and report the undo.
