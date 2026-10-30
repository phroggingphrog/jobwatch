# JobWatch — Master Architecture & Development Roadmap

**Document type:** Architecture reference and long-term development guide
**Baseline:** 30 October 2026
**Reference source checkpoint:** `828420e`
**Status:** Target architecture; implementation and deployment must be verified separately

> The checkpoint names the revision this document was written against. It is informational. Do not treat a newer commit as a reason to rewrite this document, and do not treat this document as proof that a component exists at that revision.

---

## 1. Product vision

JobWatch is a self-hosted, API-native autonomous career operations platform.

Its purpose is to help a person discover suitable career opportunities, understand their qualifications and transferable skills, evaluate jobs using evidence, make informed career decisions, prepare applications, and learn from real choices and employment outcomes.

JobWatch extends the Career Ops methodology through:

- Autonomous, specialized agents.
- Persistent, versioned candidate understanding.
- Statistical and Bayesian career intelligence.
- Personalized decision-making and feedback.
- Continuous discovery and workflow execution.
- Durable state, recovery, and auditable operations.
- Multiple interchangeable interfaces and orchestrators.

**Core principle:** Automate career operations and research while preserving verified candidate facts, evidence-based decisions, and human authority over consequential actions.

JobWatch is not a bulk application bot, a chatbot with extra prompts, or a collection of independent agents with competing databases.

## 2. Foundational references

| Foundation | What JobWatch adopts | What remains JobWatch-specific |
|---|---|---|
| Career Ops | Career methodology, evidence-first evaluation, application preparation, tracking and interview workflows | Backend architecture, statistical learning, multi-person operation and canonical approval |
| LangChain | Model interfaces, tools, structured output, integrations and middleware | Candidate evidence and domain policy |
| LangGraph | Stateful orchestration, checkpoints, interrupts, streaming and recovery | Business transaction state, paid-call idempotency and exact submission approval |
| Deep Agents | Autonomous investigation, planning, specialists, skills and context management | Career-domain tools, evidence permissions and evaluation contracts |
| Statistical methods | Structural similarity, Bayesian preference models, outcome analysis and validation | Versioned data, decision integration and product-specific evaluation |

Use the references as design foundations, not as permission to copy every architectural decision.

The original Career Ops implementation is a methodological reference. Its local-first CLI workflow and global fit thresholds are not automatically JobWatch's implementation contracts. Career Ops prohibits application submission outright; JobWatch permits it only through `jobwatch/apply/submit_confirm.py`, bound to exact reviewed inputs and the owner's confirmed action, with no blanket auto-submit permission (`INTENT.md`).

## 3. Architecture principles

1. **Native API first.** The backend owns operations, identity, state and authorization. Web, CLI, LibreChat and MCP are interfaces.
2. **Shared domain truth.** Every orchestrator uses the same candidate facts, job snapshots, evaluations, models and approval records.
3. **Multiple orchestrators, not competing pipelines.** Different workflows may use different execution strategies but must not duplicate business authority.
4. **Deep Agents for open-ended reasoning.** Use agents for research, interpretation, investigation and preparation rather than routine deterministic calculations.
5. **Statistical models remain independent.** Agents consume validated model outputs; they do not invent estimates or silently refit models.
6. **Candidate understanding is reusable.** Build a versioned, evidence-bound digest and reuse it across postings.
7. **Canonical evidence wins.** Agent memory, retrieval similarity and generated summaries cannot override verified source evidence.
8. **Durable and economical execution.** Preserve completed work, prevent duplicate paid dispatch, account for all provider operations and detect unproductive loops.
9. **Human authority is explicit.** Profile confirmation, preparation selection and final submission are distinct decisions.
10. **Implementation is not deployment.** A feature is not complete merely because code, unit tests or a passing synthetic agent trace exists.

## 4. Logical architecture

```text
CLIENT / INTEGRATION LAYER
  Native web interface
  CLI / TUI / ACP
  Pi skill router (.pi/skills/jobwatch, modes over pipeline/agentic/skills)
  LibreChat test adapter
  MCP integration — chat turn tools plus read-only career reads
                |
                v
AUTHENTICATED NATIVE API
  Identity and permissions
  Sessions, requests, streaming
  Typed interactions and approvals
  Run status and artifacts
                |
                v
CAREER ORCHESTRATION
  Scheduled discovery
  Candidate understanding
  Autonomous evaluation
  Batch processing
  Application preparation
  Follow-up and outcome handling
                |
                v
AGENT FRAMEWORK
  Deep Agents — planning, specialists, skills
  LangChain — models, tools, integration
  LangGraph — execution, checkpoints, interrupts
                |
                v
CANONICAL CAREER SERVICES
  Approved profile and policy
  Candidate evidence and digest
  Job collection and snapshots
  Statistical intelligence
  Requirement matching and eligibility
  Shortlists and selections
  Documents and applications
  Tracking and feedback
                |
                v
DATA / EXECUTION INFRASTRUCTURE
  Per-person database and private files
  Immutable source and evaluation records
  Model versions and fitted artifacts
  Checkpoints and paid-call journals
  Events, notifications and audit logs
```

The diagram describes ownership, not a requirement for every component to make HTTP requests to the layer beneath it. Internal orchestrators may invoke canonical domain services directly. External clients use the native API.

## 5. Domain architecture

### A. Candidate intelligence

Responsibilities:

- Ingest CVs, supporting files and conversational answers.
- Maintain proposed facts separately from approved facts.
- Store immutable profile versions and source evidence.
- Map supported activities to occupation reference data.
- Calculate structural career proximity and plausible adjacent fields.
- Access all applicable statistical models and readiness reports.
- Generate a cited, reusable candidate digest.
- Invalidate the digest on relevant changes.

The candidate digest should contain evidence-backed strengths, possible career directions, demonstrated skills, relevant gaps, model interpretations, uncertainty and current policy references.

The digest is not a second candidate database. The approved profile remains authoritative.

### B. Job discovery

Responsibilities:

- Build source and search plans from the confirmed profile.
- Collect jobs from supported job boards and employer ATS systems.
- Normalize and deduplicate postings.
- Preserve full advertisements, source URLs, timestamps and liveness.
- Apply cheap deterministic exclusions.
- Retain ambiguous postings for subsequent assessment.

Collection and assessment are separate operations.

Collect-only mode never requires an LLM. Model-aware candidate understanding is prepared before personal assessment filtering, not independently for every collected posting.

### C. Autonomous evaluation

The evaluation agent receives:

- A current posting snapshot containing the full available ad.
- The current candidate digest.
- Approved constraints and policy.
- Access to canonical evidence retrieval.
- Applicable statistical model outputs and readiness.
- Employer research tools where appropriate.
- A validated completion schema.

The agent may investigate requirements, search supporting evidence, revisit uncertain interpretations and request missing information.

It must not invent candidate facts, change eligibility policy, fabricate citations or submit applications.

Evaluation produces a typed, evidence-backed result containing requirement judgments, coverage, gaps, uncertainty, citations and model context.

Canonical services independently validate the result and establish eligibility.

### D. Ranking and shortlist

A shortlist is built from current validated evaluations.

Keep distinct:

- Eligibility: whether an opportunity is permitted and sufficiently supported.
- Structural relevance: evidence of occupational similarity.
- Preference: how the candidate tends to choose among eligible alternatives.
- Outcome history: what has happened to previous applications.
- Agent judgment: explained fit, trade-offs and uncertainty.

These measures must not be collapsed into a single unvalidated hiring probability.

Use a deterministic, explainable ranking when the preference model is not ready.

Human selections, rejections, restorations and comparison choices are recorded with their displayed context.

### E. Application preparation

Preparation begins only after an authorized selection.

Functions include company research, tailored CVs and letters, factual verification, document rendering, interview preparation and employer form assistance.

All output claims must trace to approved candidate evidence or cited employer information.

Final application submission is a protected operation. Only the canonical confirmation service may submit the exact employer form, attachments and values that the human reviewed and approved.

### F. Outcomes and learning

Maintain durable records of:

- Opportunities shown and their rank.
- Genuine human comparisons and preferences.
- Application submissions and status changes.
- Employer responses and interviews.
- Rejections, offers and follow-ups.
- Model versions and measured predictive performance.

Observations feed statistical evaluation and future recommendation quality.

Learning is dataset-driven and validated, not inferred merely from conversational memory.

## 6. Statistical intelligence architecture

Statistical models should be independent, versioned calculation services.

| Model | Purpose | Decision boundary |
|---|---|---|
| Structural occupational model | Suggest transferable occupations and career directions | Not proof of qualification |
| Bayesian choice model | Learn personal preferences from genuine comparison choices | Not hiring probability |
| Beta-Binomial callback model | Describe resolved application callback outcomes and uncertainty | Not a calibrated per-job forecast |
| Response-time / survival model | Future estimation of response timing with censored observations | Not yet a fitted production model |
| Market demand / saturation model | Future analysis of role demand, unique vacancies and changes over time | Requires historical data and validation |
| Typed decision classifiers | Narrow classification and verification tasks | Cannot override approved evidence or policy |

For each model, preserve:

- Input data version and provenance.
- Statistical specification and priors.
- Feature definitions and missingness handling.
- Training and holdout separation where applicable.
- Diagnostics and uncertainty.
- Validation metrics and acceptance criteria.
- Readiness status.
- Refit and invalidation rules.

If a model is unavailable, untrained, stale or invalid, report that status explicitly.

**Rule:** The LLM interprets statistical evidence. Statistical code calculates it. Canonical services decide which outputs are permitted in product operations.

## 7. Orchestrator ownership

| Orchestrator | Execution foundation | Responsibility |
|---|---|---|
| Discovery | Deterministic scheduler / LangGraph | Collect and normalize jobs |
| Candidate Understanding | Deep Agents | Synthesize evidence and applicable model results into a digest |
| Screening | Deterministic domain services | Enforce confirmed constraints cheaply |
| Evaluation | Deep Agents | Investigate job fit using canonical tools |
| Batch Assessment | LangGraph | Schedule independent job evaluations and preserve progress |
| Application Preparation | Deep Agents + LangGraph | Research, draft, review and request approval |
| Follow-up | LangGraph + agents when needed | Track deadlines and prepare communications |
| Model Evaluation | Deterministic statistical services | Fit, test and report models when permitted |

An orchestrator coordinates operations. It never becomes another authoritative source of candidate facts, application state or eligibility.

Specialized subagents are permitted when they contribute independent useful work. A coordinating agent must not simply call an entire legacy evaluator and repeat its work.

## 8. Shared data contracts

All orchestrators should agree on the following conceptual contracts.

**CandidateContext:** authenticated person, approved profile version, evidence references, confirmed policy and provenance.

**CandidateDigest:** candidate context reference, source hashes, model versions, findings, exact citations, readiness, advisory hypotheses and validity status.

**PostingSnapshot:** stable posting identity, original source, captured full text, liveness and content hash.

**EvaluationRequest:** candidate digest reference, posting snapshot, tool permissions, run identity, model configuration and idempotency key.

**EvaluationResult:** requirement judgments, evidence citations, eligibility-relevant findings, uncertainty, model context, validation outcome and usage.

**ModelSnapshot:** model and dataset versions, fit status, diagnostics, predictions where valid, uncertainty and limitations.

**WorkflowRun:** orchestrator, state, checkpoint, identity, retries, cancellation, accounting and recovery metadata.

**HumanAuthorization:** exact operation, actor, approved inputs, revision, expiry and invalidation conditions.

Define these once and reuse them through all interfaces.

## 9. State and persistence rules

Maintain three separate categories of information.

**Domain state:** candidate facts, jobs, model artifacts, evaluations, applications, decisions and outcomes. This is authoritative.

**Agent working state:** plans, messages, retrieved context, tool outputs, specialist work and checkpoint state. This supports execution, not factual authority.

**Execution/accounting state:** runs, leases, paid provider requests, idempotency keys, retries, charge records, failures and notification delivery.

LangGraph checkpoint restoration is not automatically equivalent to exactly-once external execution. Paid calls and consequential side effects require explicit journaling and reconciliation.

A restart must not turn a previously completed paid request into another paid request without a legitimate new operation.

## 10. Development roadmap

### Phase 0 — Architecture reconciliation

Goal: establish one verified implementation baseline.

Deliverables:
- Current source and deployment inventory.
- Domain ownership map.
- Framework adoption map.
- Redundant-wrapper assessment.
- Preserved backups and rollback procedure.

Completion: no uncertainty over which revision is under repair and which components own each operation.

### Phase 1 — Framework and protocol stabilization

Goal: one correct native Deep Agents evaluation path.

Deliverables:
- Verified provider-native tool messages.
- Actionable nested validation feedback: an invalid payload must name the failing entry and the rule it broke, never a misleading shape hint.
- Consistent output schemas and canonical validation.
- Correct evidence retrieval.
- Checkpoint recovery and paid-call replay.
- No legacy evaluation loop inside the native agent.
- Reproduction tests for known failures.

Completion: reliable synthetic execution and targeted recovery tests.

### Phase 2 — Candidate and model intelligence

Goal: one reusable, model-aware understanding of each candidate.

Deliverables:
- Candidate digest with evidence provenance.
- All applicable model outputs/readiness.
- Current screening-policy projection.
- Source-version invalidation.
- Zero-call unchanged-input reuse.
- Separate cold-digest and per-job cost attribution.

Completion: candidate understanding is reused safely across job evaluations.

### Phase 3 — Native evaluation acceptance

Goal: prove real model usefulness rather than mock compliance.

Deliverables:
- A genuine completed evaluation.
- Valid citations and canonical eligibility.
- Provider tool and usage trace.
- Verified unchanged-input replay.
- Representative-case human-reviewed evaluation.
- Measured efficiency against the 3–6-call target, without imposing that target as a hard execution ceiling.

Completion: real provider assessment is correct, repeatable, accountable and sufficiently efficient.

### Phase 4 — Controlled production recovery

Goal: safely restore scheduled native assessment.

Deliverables:
- Required full local checks.
- Reviewed release commit.
- Deployment verification and rollback.
- Controlled production canary.
- Observed scheduled execution.
- Notifications, identity, usage and recovery checks.

Completion: automatic assessment is observed working, not merely configured.

### Phase 5 — Usable Career Ops product

Goal: complete the candidate-facing workflow.

Deliverables:
- Conversational intake and explicit profile confirmation.
- Job discovery and explained shortlist.
- Durable feedback and selection.
- Selected application preparation.
- Human-reviewed documents and forms.
- Interviews, follow-ups and outcome tracking.

Completion: the user can accomplish the workflow without developer intervention.

### Phase 6 — Statistical optimization and expansion

Goal: grow from automated workflow into adaptive career intelligence.

Deliverables:
- Preference-model calibration.
- Structural match evaluation.
- Outcome and response-time analysis.
- Market demand and saturation research.
- Typed decision-classifier evaluation.
- Versioned retraining and model comparison.

Completion: new intelligence improves measured decision quality against appropriate baselines.

The first usable milestone is Phase 5's discovery and shortlist experience after Phase 4 recovery. Advanced statistical expansion is not a prerequisite for that milestone.

## 11. Architecture decision rules

Before adding any dependency, agent, module or workflow, ask:

1. Is this career-domain logic, statistical logic, framework capability or client presentation?
2. Does an authoritative component already own the information?
3. Does the installed framework already provide the required mechanism?
4. Would a deterministic function be clearer and cheaper?
5. Does the proposed agent add useful reasoning or merely another model-call layer?
6. How will the result survive cancellation and restart?
7. How are candidate identity, evidence, credentials and approvals protected?
8. What proves the feature works with a real provider and realistic workflow?
9. How will costs, regressions and predictive quality be measured?
10. Can the change be isolated and rolled back?

Avoid adding an agent when the real requirement is a database query, a schema validator, a statistical calculation or a scheduler.

Avoid converting an agent into a fixed series of unnecessary model roles merely to make the architecture appear structured.

## 12. Required quality gates

Every meaningful change should pass the relevant categories:

**Contract:** schema consistency, identity, permissions and versioning.

**Evidence:** citation accuracy, no invented qualifications, explicit uncertainty.

**Behavior:** realistic task completion, correct stage transitions and human interactions.

**Recovery:** interruption, retry, cancellation, stale inputs and replay.

**Efficiency:** model-call counts, token accounting, context growth and reuse.

**Statistics:** data integrity, held-out performance, calibration and uncertainty.

**Integration:** equivalent authoritative results through supported native API clients.

**Release:** reviewed source, tests, deployed revision, observed live behavior and rollback.

Passing unit tests establishes only the relevant unit-test evidence. A valid provider assessment, actual deployment and successful user journey require separate verification.

## 13. Scope and non-goals

Do not make the following prerequisites for the existing recovery work:

- Rebuilding JobWatch around LibreChat.
- Returning to MCP-first architecture.
- Replacing the per-person domain database with agent memory.
- Creating another autonomous supervisor over the same evaluation work.
- Automatically retraining every statistical model.
- Replacing validated Bayesian methods with LLM-generated scores.
- Performing an unrequested framework or database migration.
- Loosening evidence, eligibility or submission safeguards.
- Enabling hosted CI, deployment or paid experiments merely because source code changed.

Future infrastructure upgrades should be proposed separately with evidence that they resolve a real limitation.

## 14. Reference sources

### Primary product references

- [JobWatch INTENT.md](https://github.com/phroggingphrog/jobwatch/blob/main/INTENT.md) — authoritative product direction.
- [JobWatch architecture inventory](https://github.com/phroggingphrog/jobwatch/blob/main/docs/architecture/codebase-map.md) — implemented module ownership and recorded limitations.
- [JobWatch Career Ops comparison](https://github.com/phroggingphrog/jobwatch/blob/main/docs/architecture/career-ops-comparison.md) — comparison against a pinned donor revision.
- [JobWatch native assessment failures](https://github.com/phroggingphrog/jobwatch/blob/main/docs/architecture/assessment-failures.md) — known protocol, validation and cost failures.
- [JobWatch candidate digest lifecycle](https://github.com/phroggingphrog/jobwatch/blob/main/docs/architecture/candidate-digest.md) — reusable candidate understanding design.
- [TASK-279 / Issue #31](https://github.com/phroggingphrog/jobwatch/issues/31) — immediate native assessment recovery.

### External architecture references

- [Career Ops reference implementation](https://github.com/career-ops-hq/career-ops) — career methodology and workflow patterns.
- [CareerOps Manifesto](https://career-ops.org/manifesto) — evidence, candidate control and responsible career automation.
- [LangChain documentation](https://docs.langchain.com/oss/python/langchain/overview) — model and tool foundations.
- [LangGraph documentation](https://docs.langchain.com/oss/python/langgraph/overview) — stateful orchestration and durable execution.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) — checkpoints and stores.
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) — human-in-the-loop workflow mechanics.
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview) — autonomous harness architecture.
- [Deep Agents profiles](https://docs.langchain.com/oss/python/deepagents/profiles) — installed-version-compatible customization must be verified.
- [Deep Agents repository](https://github.com/langchain-ai/deepagents) — source and implementation reference.

The installed JobWatch version is the compatibility baseline. Upstream documentation may describe features newer than the installed release. Verify APIs against the pinned package before implementing.

## 15. Maintenance of this architecture reference

This document describes intended architecture and development direction. It must not become a competing source of product requirements or operational status.

Maintain these separately:

- **Product intent:** `INTENT.md`.
- **Architecture:** this reference and accepted architecture decisions.
- **Implementation:** source code and tests.
- **Work in progress:** issues, OpenSpec tasks and reviewed change records.
- **Release truth:** deployment manifests, runtime configuration and observed operational evidence.

When a substantial architecture decision changes, document the rationale, affected boundaries, compatibility, data implications and migration path before implementation.

When a feature is completed, update its implementation and acceptance records. Do not mark this architecture roadmap complete solely because the corresponding module exists.

**On staleness.** This document deliberately does not repeat the inventory of the codebase. A list of modules and commits inside a design document goes stale within days. Name an owner and a boundary here; name a file and a revision in the code, the card or the commit message. Update the checkpoint line only when the architecture itself changes, not when the code moves.

---

## Guiding statement

**JobWatch is an autonomous, evidence-grounded career operations platform. Career Ops defines the workflow methodology; Deep Agents provides flexible autonomous reasoning; LangChain provides model and tool integration; LangGraph provides durable orchestration; canonical JobWatch services preserve domain truth; and independent statistical models provide validated decision intelligence.**

Every new capability should strengthen this architecture rather than introduce another independent workflow or source of truth.
