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
- Parsing is a background step. Starting a proposal returns at once with status
  `parsing`, every standing question open (employment status, availability, work
  rights, constraints, exclusions, career focus, location) and each section
  `unknown`; the documents are read by one paid parse per person at a time under a
  180 second deadline. The person may answer while it runs. When it ends it merges
  into the draft under the proposal lock and the revision increments: a fact the
  person stated wins over a parsed fact in a one-answer section (employment status,
  availability, work rights, career focus), answered questions stay closed, and
  existing facts are never rewritten. A failed parse sets `parse_error` and keeps
  the draft and answers. A draft left `parsing` by a dead worker reads back as
  `draft` with `parse_error` `parse_interrupted`. Confirm is refused while
  `parsing` (`proposal_parsing`); further uploads can be added to a draft and are
  merged the same way.
- Candidate text goes only to an approved paid route. Every parse path (API, chat,
  synchronous) checks the gateway and the person's reader model inside intake before
  any text is read or sent, and refuses with `gateway_not_allowed` or
  `model_not_allowed`.
- Guided onboarding in chat is the intended first setup: the agent asks for the
  person's files (their existing `profile/` text files can be offered), starts the
  proposal, asks the open questions while it is read, shows what it found with
  sources, and asks only the remaining gaps. `profile_answer` and `profile_correct`
  record a value only if it is a clause of the person's own words from their latest
  message, or a span their own clause affirms (`not_person_words` otherwise, so a
  negated clause never yields its opposite), and each is a gated tool whose human
  approval is bound to the open draft and the exact words, so the model can neither
  answer for the person nor record anything they did not approve. The
  confirmation is shown with its scope and limits; `profile_confirm` is a gated
  tool whose human approval is bound to the exact proposal and scope digests, so a
  changed draft fails and model text is never approval. A scope with nothing to
  search for (no evidence-backed experience, skill or career focus) is refused as
  `profile_incomplete`.
- An existing hand-made profile is never overwritten. Adopting it
  (`jobwatch profile adopt`) records it as version 1 for overwrite protection and
  history only: **adoption authorises nothing**. An adopted owner onboards through a
  proposal with `base_version` set to the current version (optionally drafted from
  their existing files) and confirms the scope shown.
- Discovery (collection and automatic assessment) runs only when the CURRENT
  version was confirmed with its scope shown (`scope` and a matching
  `scope_digest`, non-empty basis) and the live `profile/` files still match the
  hashes recorded for that version. Otherwise it is skipped with
  `no_confirmed_profile`. A hand edit after confirmation therefore pauses
  discovery until the files match the confirmed version again; confirming a new
  proposal never overwrites a hand edit (`profile_edited_by_hand`). Collection is evaluate-only. The
  scope's daily assessment count and token ceiling bound each person's day.

## Consequences

- Only confirmed content becomes authoritative profile fact; uploads and proposals
  stay private and never alter `profile/` by themselves.
- Evidence and source references are reproducible from versioned snapshots, and a
  prior approval can be inspected after later amendments.
- Owners with hand-made profiles keep their files safe by adopting them, but must
  onboard (guided, optionally from those files) and confirm before discovery runs.
- A person without a confirmed version, an adopted-only version, or a profile that
  was edited by hand since confirmation gets no automatic discovery.
- Confirmation grants no document preparation, employer contact or submission;
  those keep their own approvals, and Submit stays on the owner-confirmed path.
  Per-posting actions the person starts and approves themselves are not gated by it.
- Accepted design is not deployed behaviour; a merge or passing checks does not
  establish a running backend.

See [INTENT.md](../../INTENT.md), [ADR 0001](0001-native-agent-api.md) and
[the backend contract](../../pipeline/agentic/CHAT.md).
