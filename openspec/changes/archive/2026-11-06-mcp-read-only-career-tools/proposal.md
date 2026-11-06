# Proposal

## Why

The MCP server already has a read surface. `pipeline/agentic/chatgpt_connector.py` registers `jobs_overview`, `applications_overview`, `assessment_detail`, `application_detail`, `job_detail` and `task_status`, and each carries the `READ_ONLY` annotation. Two reads are missing from it:

- `job_detail` returns the advertisement **link**, never the stored text. A client that cannot browse cannot read the words of the ad.
- No tool exposes follow-up cadence. `jobwatch/followup/events.py` records it, and only the internal chat agent can reach it.

## What Changes

- Add `career_reader(posting_id)`: the stored advertisement text and posting identity from `service._capture`.
- Add `followup_history(application_id)`: recorded follow-up events and cadence from `followup.events.history` and `application_cadence`.
- Annotate both `READ_ONLY`, using the existing constant, so a client can tell a read from work before it calls.
- Add no write tool, no approval prompt, no model call and no new service.

## Capabilities

### New Capabilities

- `mcp-read-surface`: two additional read-only, per-person reads for the stored advertisement and follow-up cadence.

### Modified Capabilities

None. The chat contract, the approval contract and the assessment capabilities are unchanged.

## Impact

- `pipeline/agentic/mcp_server.py`: one shared read helper and two tools.
- `pipeline/agentic/skills/inspect-jobs/SKILL.md`: confirm the tool names an external agent should use.
- No database migration, no configuration change and no new port.
- Undo: revert the commit. The server keeps its existing fifteen tools and its token verifier.

## Rejected: three tools from the first draft

The first draft proposed `find_jobs`, `career_reader`, `application_status` and `followup_history`. Verification of the registered tool set showed that `jobs_overview`, `job_detail`, `application_detail` and `assessment_detail` already cover search, status and history. A second name for the same read would make a model choose between synonyms, so those three were dropped.
