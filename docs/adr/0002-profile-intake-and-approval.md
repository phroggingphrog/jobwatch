# ADR 0002: Profile intake and approval

Date: 2026-10-21

Status: Accepted owner direction (backend brief of 2026-10-21); deployment has its own acceptance criteria.

## Context

The agreed backend brief fixes the workflow: upload, draft profile, review,
confirm, approved profile, automatic discovery, shortlist, selection and
preparation approval, documents, then the human submits. Until now a profile was
a hand-made set of files, and collection could run without any recorded approval
of what to search for. A parsed CV is not authoritative: it can misread, omit or
over-infer, and a CV gap alone does not establish unemployment.

## Decision

- Uploads are stored privately under `<person>/intake/` (directories 0700, files
  0600), separate from `profile/`.
- A parser produces a **Proposal**: facts (section, value, fact basis, source
  references with upload sha256, line and verbatim quote) and questions for missing
  material information. Basis is `evidence`, `inference` or `unknown`.
- The person corrects facts and answers questions (actor `person`); every change
  bumps the proposal revision. Agent-generated answers are never recorded as the
  person's choices or approval.
- Confirmation shows the proposal digest, the search scope (basis, locations,
  `daily_assessments`, `daily_token_ceiling`) and what it authorises (discovery,
  assessment) and does not (document preparation, employer messages, submission).
  Confirm requires the approve scope and both digests.
- Confirm writes an immutable `profile-versions/<n>/` (`approved.json`, projected
  files, evidence snapshot bytes) and projects into `profile/` in the schema
  existing readers use. Later inferred amendments are proposals against a base
  version and need confirmation before replacing approved facts.
- An existing hand-made profile is never overwritten; it must be adopted
  explicitly (`jobwatch profile adopt`) as version 1.
- Discovery runs only for a person with a confirmed version, within the confirmed
  scope and budget. Collection is evaluate-only (Plan 1, Task 1).

## Consequences

- Only confirmed content becomes authoritative profile fact; uploads and proposals
  stay private and never alter `profile/` by themselves.
- Evidence and source references are reproducible from versioned snapshots, and a
  prior approval can be inspected after later amendments.
- Owners with hand-made profiles must adopt once before discovery runs for them.
- A person without a confirmed version gets no automatic discovery.
- Confirmation grants no document preparation, employer contact or submission;
  those keep their own approvals, and Submit stays on the owner-confirmed path.
- Accepted design is not deployed behaviour; a merge or passing checks does not
  establish a running backend.

See [INTENT.md](../../INTENT.md), [ADR 0001](0001-native-agent-api.md) and
[the backend contract](../../pipeline/agentic/CHAT.md).
