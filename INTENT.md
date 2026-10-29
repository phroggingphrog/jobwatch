# Jobwatch: current product intent

This is the normative product contract, reconciled on 2026-10-30. It states the
intended behavior, not a claim that every requirement is implemented or deployed.
Keep this repository public and candidate-free. Changes to the product goal need
the owner's explicit direction.

Exact owner quotations and superseded requirements are preserved in the
[owner direction history](docs/adr/0011-owner-direction-history.md). That history
is evidence of decisions, not a second set of active requirements.

## Product and delivery boundary

Jobwatch is a profile-driven career-operations backend. It discovers openings,
reads complete ads against each person's approved evidence and preferences,
explains fit and eligibility, and prepares application materials and related
career work. It supports different people and fields without hard-coded candidate
facts, work rights, locations, target roles or writing assumptions.

The primary interface is an authenticated native HTTP agent API. Jobwatch owns
orchestration, durable state and canonical operations. LangChain model/tool
interfaces, LangGraph persistence and human interrupts, and Deep Agents planning,
specialists, scoped files, skills and advisory memory belong inside Jobwatch.
They share identity, accounting, budgets, cancellation and recovery. Framework
capabilities do not create new domain authority or justify duplicate workflows.

The current delivery priority is one reliable Screening → Evaluation slice:
deterministic screening, reusable candidate understanding, a canonical cited
evaluation and eligibility result, measured cost, and unchanged-input reuse.
Complete its acceptance and release evidence before extending career stages.
Documents/Review, Application Preparation and Follow-up remain product scope,
not a claim of current acceptance. Package renaming is not a prerequisite.

Canonical Jobwatch services remain authoritative for collection, evidence,
eligibility, review, documents, packages, applications, interviews and follow-up.
Agents invoke and interpret those services rather than creating parallel state.
Statistical calculations remain deterministic tools; agents explain results and
limitations rather than inventing or silently fitting replacement models.

## Client boundary

Jobwatch is frontend-agnostic. The preferred production client is the separate
Jobwatch web interface or another trusted native API client that supports typed
human approvals. The native API must work without LibreChat. LibreChat remains a
compatibility and testing surface, using standard LibreChat and native Artifacts
rather than a custom renderer fork or an architectural dependency. MCP is an
optional compatibility adapter. Clients share the same canonical backend;
neither a client nor an adapter owns orchestration or human approval authority.

Return useful structured results, progress, questions and documents in chat.
Canonical tool results remain authoritative; optional widgets or Artifacts must
not create a second workflow. Preserve useful text fallbacks and existing data
and owner identity. Do not require friends to share or enter backend API keys;
account mapping and credentials stay server-side and per person.

Accept and retain original uploaded files within explicit limits. Distinguish
receipt from successful reading. Read supported documents and bounded ZIP
contents; explain unreadable files without rejecting the entire conversation.
Generated interfaces, uploaded files and model text never confer approval.

Routine answers and corrections update draft profile state without per-answer
confirmation. An authenticated human chat interaction may confirm an exact,
current, complete profile summary through the canonical confirmation path. Do not
repeatedly request answers already captured. A model's paraphrase is not consent.
Protected operations stay paused when the client cannot supply required human
review. See the [standard-client boundary](docs/adr/0010-standard-chat-client-boundary.md).

## Candidate understanding and discovery

Keep facts and preferences in each person's approved runtime files. Separate
confirmed constraints from recommendations and inferred possibilities. Missing
facts remain explicit gaps; collect what an operation needs before proceeding.
Never manufacture qualifications, experience, achievements or preferences.

Intake combines CVs and chat with structural analysis. Explain suitable fields,
role families, seniority, strengths, gaps and study constraints using cited
evidence. Recommend plausible adjacent fields, not only literal past job titles.
Only confirmed candidate scope and current capacity authorize discovery filters.

Compile discovery sources, queries, exclusions and schedules from that confirmed
profile. Deterministic screening handles clear country/state, remote eligibility,
work-rights, seniority and hours exclusions without per-job model calls. Ambiguous
wording goes to assessment rather than unsupported rejection. Do not repeat paid
reading for postings already excluded by a current deterministic rule.

Prepare and reuse candidate understanding from canonical evidence and existing
structural, preference and outcome models, recording limitations. Report cold
preparation cost separately from per-job work. Reuse must invalidate on relevant
input changes; stale evidence must not authorize paid dispatch or READY results.

## Assessment and selected preparation

Read the complete ad. Match material requirements to approved primary evidence
before judging fit. Distinguish supported experience, partial or transferable
evidence, trainable gaps and unsupported mandatory requirements. Preserve exact
citations, uncertainty, canonical validation and eligibility policy. Canonical
primary evidence wins over an auxiliary matcher's miss or an agent summary.

Use existing company research and models to connect cited employer context and
job requirements with approved candidate interests. Never invent motivation,
employer facts or model certainty. Evidence matching is not merely keyword
matching and must not produce unsupported rejections or claims.

Present ranked, explained shortlists before expensive document preparation.
Explain fit, gaps, eligibility and trade-offs. Do not substitute one opaque score
for the evidence or bulk-generate packages for every discovered job. Explicit
selection starts canonical preparation; accept, reject, reorder and feedback
remain durable and scoped to the authenticated person.

Use bounded correction and safe replay for provider failures. The current
assessment acceptance target is a valid canonical evaluation within 3–6 total
per-job model calls, with all classifier/child work counted, plus zero additional
paid operations for unchanged-input reuse. The call range is an efficiency target,
not a runtime cap or a substitute for quality acceptance. Numeric call count
without a valid result is failure. Preserve failed attempts and accounting; do
not repeat paid candidate experiments without a concrete repair and authorization.

## Safety and authorization

- Preserve per-person isolation and server-bound identity across every route,
  tool, checkpoint, file and account connection. Model arguments cannot select
  another person's identity.
- Keep candidate data on approved paid routes and out of hosted tracing. Use
  synthetic fixtures, never live candidate records, for tests.
- Canonical operations enforce evidence, eligibility, review and package gates.
  Advisory memory, skills, generated files and agent prose cannot bypass them.
- Routine conversation is not approval of a protected operation. Approval binds
  to the exact reviewed current inputs through its canonical human path.
- Final Submit is allowed only through `jobwatch/apply/submit_confirm.py`, bound
  to the actual reviewed employer URL, filled values and attachments, with expiry
  and invalidation when reviewed inputs change. No blanket auto-submit permission.
- Employer login, CAPTCHA, verification and unsupported flows remain explicit
  human checkpoints. Do not contact an employer or retry uncertain submission
  automatically. A form map or draft is not evidence of a filled or submitted form.

## Completion and operational evidence

An authenticated client must be able to start and resume durable conversations,
answer typed questions, make authorized decisions, retrieve verified documents
and reconnect to saved progress. Restart, retry and cancellation must preserve
identity, exact-input approvals and accountable usage.

Distinguish completed conversation turns, canonical evaluations, READY packages,
held/archived jobs, deferred work and failures. Report useful reasons. Completion
requires the relevant local checks and review; hosted CI is optional and must not
be re-enabled without explicit direction.

Source changes do not authorize service activation or deployment. Before any
release, verify the exact candidate, preserve configuration/data and rollback,
run the required release checks, and observe the owner's actual deployed service.
Observe one bounded reader outcome before restoring automatic assessment.
Preserve collection, incidents, usage records, person identity and owner settings.
A passing synthetic test, merge or historical deployment instruction is not proof
that the current backend works in production.

## Contract and architecture references

- [Backend operational contract](pipeline/agentic/CHAT.md)
- [Domain ownership and architecture inventory](docs/agents/domain.md)
- [Glossary](GLOSSARY.md)
- [Architecture decisions](docs/adr/)
- [Historical owner directions](docs/adr/0011-owner-direction-history.md)

Keep implementation, acceptance and deployment status in their existing change
and issue records rather than appending another dated requirement to this file.
