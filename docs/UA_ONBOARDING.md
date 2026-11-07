# Jobwatch onboarding guide

> Generated from the project knowledge graph (`.ua/knowledge-graph.json`) at commit `188c4ac`, analyzed 2026-11-08T03:41:40+11:00.
> Read [INTENT.md](../INTENT.md) before changing behaviour; this guide explains the code, it does not replace the product contract.

## 1. Project overview

| | |
|---|---|
| **Project** | jobwatch |
| **Description** | Self-hosted, single-owner career-operations backend: collect job postings, evaluate them against approved evidence and confirmed preferences, prepare application materials, and require exact human approval before any Submit. |
| **Languages** | Python, HTML, JavaScript, CSS, Shell, YAML, Markdown |
| **Frameworks / libraries** | FastAPI, Pydantic, Jinja2, HTMX, LangChain, LangGraph, Deep Agents, Textual, pytest |
| **Commit analyzed** | `188c4ac7fc34414f05860bc22084a49bf62c38af` |

Jobwatch is a profile-driven career-operations backend, not a job-board scraper with a chatbot bolted on. It collects postings, screens them deterministically, evaluates complete ads against approved evidence, explains eligibility and fit, prepares application documents, and stops at a human approval boundary. The primary interface is the authenticated native HTTP agent API in `pipeline/agentic/api.py`; the web board, MCP server, LibreChat adapter, ACP adapter and terminal UI are clients over the same canonical operations.

Three properties shape almost every design decision:

1. **One owner, server-bound identity.** There is no sign-up or multi-person mode. Identity comes from the bearer token or the trusted local backend, never from a model argument or a request parameter.
2. **Evidence before prose.** Candidate claims must trace to approved evidence with exact citations. Model memory, generated files and advisory memory cannot become facts or approvals.
3. **Deterministic gates around paid work.** Screening, eligibility and admission are code. Model calls are budgeted, attributable and bounded; the expensive path runs last and only for promoted jobs.

## 2. Architecture layers

The graph groups the codebase into eleven layers. Each layer heading lists its highest-complexity files; the full inventory is in [section 5](#5-file-map).

### Entry Points & Execution Modes

How one jobwatch invocation turns collectors, filters and an execution-mode switch into work.

**Key files**

- `jobwatch/reader.py` — Legacy full-ad AI reader mode: reads complete ads against approved evidence and confirmed per-person policy.
- `jobwatch/cli.py` — Top-level `jobwatch` CLI; discovers optional subcommand packages (apply, outcomes, web, prescreen, notifier, commands).
- `jobwatch/run.py` — One collection run: tiered collectors, dedupe/store, rules filter, publish, prune, then AI dispatch by execution mode.
- `pipeline/graph.py` — Deterministic typed asyncio state graph over SQLite pipeline state; selectable pipeline execution mode.
- `pipeline/screened.py` — Main execution mode: category refresh, retry, title triage, deterministic graph, liveness refresh, then promotes the best shortlisted jobs to the agentic evaluator.
- `jobwatch/execution_mode.py` — Resolves the single effective AI mode (off, reader, pipeline, agentic, screened) while preserving legacy flags.

**Concepts:** `Execution Mode`

### Collection & Deterministic Screening

Source adapters, politeness, dedupe, rules, prescreen, discovery planning and ad capture.

**Key files**

- `jobwatch/util/adtext.py` — Captures and stores full job-ad text so the reader inspects the whole ad rather than a teaser.
- `jobwatch/collectors/jsonld_pages.py` — Employer career pages parsed from schema.org JobPosting JSON-LD, with robots.txt respected.
- `jobwatch/collectors/source_plugins.py` — User-defined source plugins plus built-in feed and GradConnection plugins.
- `jobwatch/filters.py` — Config-driven rules matching from rules.yaml; every decision records which arm and rules fired.
- `jobwatch/prescreen/engine.py` — Generic prescreen engine that parses a posting with stored terms and evaluates stored rules.
- `pipeline/agentic/discovery.py` — Field-guided discovery that enforces exclusions; defaults preserve collection and archive behaviour.

**Concepts:** `Field Hypothesis`, `Liveness Observation`, `Prescreen`, `Relevance Judgment`

### Candidate Understanding & Eligibility

Profile intake and approval, canonical evidence, deterministic policy, preferences and outcomes.

**Key files**

- `jobwatch/candidate/eligibility.py` — Canonical personal eligibility; nothing is inherited about home, level, rights or hours.
- `jobwatch/candidate/intake.py` — Profile intake: private uploads become parsed, sourced profile proposals awaiting human confirmation.
- `jobwatch/candidate/policy.py` — Deterministic decision policy compiled from confirmed profile facts.
- `jobwatch/candidate/contracts.py` — Candidate analysis contracts and typed schemas.
- `jobwatch/candidate/evidence.py` — Canonical approved evidence and exact citations.
- `jobwatch/outcomes/sync.py` — Read-only mail scan that produces outcome proposals and one approval batch.

**Concepts:** `Callback Estimate`, `Canonical Evidence`, `Decision Policy`, `Preference Model`, `Profile Version`, `Search Scope`

### Assessment & Shortlisting

The paid evaluation slice, the deterministic gate, ranking, shortlists and selection.

**Key files**

- `pipeline/agentic/service.py` — Canonical agentic orchestration: admission, budgets, evaluation and document pipeline, gates and resumable artifacts.
- `pipeline/agentic/autonomous.py` — Bounded native assessment: deterministic Screening followed by one Evaluation agent.
- `pipeline/agentic/evaluator.py` — Isolated whole-ad extraction followed by immutable candidate-evidence matching.
- `pipeline/agentic/feedback_prompts.py` — Bounded human questions and genuine three-job-plus-none comparisons.
- `pipeline/agentic/research.py` — Narrow public-job research adapter with immutable facts and fail-closed fetching.
- `jobwatch/util/openrouter_extras.py` — Jev ad screening and ad embeddings through OpenRouter and OmniRoute; public ad text only.

**Concepts:** `Eligibility Gate`, `Evidence Coverage`, `Exact Input Approval`, `Job Attempt`, `Shortlist Label`

### Documents, Packages & Application

Drafting and verification, form preparation, browser work, the confirmed-Submit path and follow-up.

**Key files**

- `jobwatch/apply/prefill_workflow.py` — Owner-authorized application preparation; never follows instructions embedded in page content.
- `jobwatch/web/browser_session.py` — On-demand owner-controlled Chromium sessions streamed by the web app.
- `jobwatch/apply/answers_agent.py` — Prepares every application answer from private, versioned owner sources.
- `jobwatch/apply/browser.py` — Shared application browser workflow independent of either frontend.
- `jobwatch/apply/prefill.py` — Prepares owner-controlled application tabs without ever submitting.
- `jobwatch/apply/prepare.py` — Discovers, answers and prepares an owner application without manual field mapping.

**Concepts:** `Confirmed Submit`, `Ready Package`

### Agent Runtime & Conversation

Chat dispatch, Deep Agents/LangGraph plumbing, budgets, model routing and identity enrollment.

**Key files**

- `pipeline/agentic/chat.py` — Trusted local chat dispatch boundary providing conversation tools and specialist sub-agents.
- `jobwatch/util/llm.py` — OpenAI-compatible gateway client for paid model transport.
- `pipeline/agentic/contracts.py` — Strict serialized contracts for the bounded agentic career-operations pipeline.
- `pipeline/agentic/runtime.py` — Explicit tool registry and conservative shared budgets for agentic roles.
- `jobwatch/util/model_choice.py` — Per-person routing of which model handles which job.
- `pipeline/agentic/deepagents_runtime.py` — Bounded Deep Agents execution using Jobwatch's local paid gateway.

**Concepts:** `Advisory Memory`, `Identity Binding`, `Trust Boundary`

### State, Accounting & Recovery

SQLite stores, fenced artifacts, budget ledgers, incidents and frozen evaluation data.

**Key files**

- `pipeline/agentic/baseline.py` — Frozen baseline: models, gate version, case grouping, tags, freezing and loading.
- `pipeline/agentic/evaluate_runs.py` — Frozen canonical gate and ranking replay with no production writes and no default models.
- `pipeline/agentic/incidents.py` — Durable assessment failures and their independent notification delivery state.
- `pipeline/agentic/persistence.py` — Fenced immutable artifacts and canonical apply rows with a durable ledger outbox.
- `pipeline/agentic/store.py` — Additive SQLite persistence for fenced agentic runs and budget checkpoints.
- `jobwatch/reports/evaluation.py` — Data-minimised deterministic private reports for frozen evaluation replays.

**Concepts:** `Budget Accounting`, `Frozen Baseline`, `Interaction`

### Clients & Adapters

Native HTTP API, web board, MCP, LibreChat, ACP and the terminal UI.

**Key files**

- `jobwatch/web/queries.py` — Read side of the web board: filters, facet counts and the stored AI reading of each ad.
- `pipeline/agentic/tui_screens.py` — Board screens of the terminal app: Today, Jobs, Detail, Review, Applications, Inbox and more.
- `jobwatch/web/app.py` — The Jobwatch web board: FastAPI, Jinja2 and HTMX, loopback only.
- `pipeline/agentic/chatgpt_connector.py` — Read-only ChatGPT connector tools plus MCP Apps widgets.
- `pipeline/agentic/tui.py` — Claude-Code-style terminal UI for the Jobwatch career agent.
- `pipeline/agentic/api.py` — Native authenticated agent HTTP API for threads, runs, events, interactions and artifacts.

### Configuration, Deployment & Operations

Runtime YAML, systemd units, release scripts and operator tooling.

**Key files**

- `scripts/agentic_acceptance.py` — Read-only conservative acceptance audit for agentic READY packages.
- `scripts/seed_profile.py` — Explicit local profile import that copies only named inputs and never logs their text.
- `tools/build_occupation_reference.py` — Rebuilds the public occupation reference from pinned, hash-verified official downloads.
- `.github/workflows/backend.yml` — Hosted CI workflow; the owner has disabled CI and it is not a completion requirement.
- `config/employers.yaml` — Employer registry used by the ATS collectors.
- `config/feeds.yaml` — RSS and Atom feed sources for the generic feed collector.

### Tests & Verification

Pytest suites and support helpers covering the domain services.

**Key files**

- `tests/candidate/test_intake.py` — Tests for profile intake and proposal confirmation.
- `tests/candidate/test_policy.py` — Tests for the confirmed-profile decision policy.
- `tests/conftest.py` — Shared pytest fixtures for the Jobwatch test suite.
- `tests/apply/test_prefill_workflow.py` — Tests for the owner-authorized prefill workflow.
- `tests/candidate/test_evidence.py` — Tests for canonical evidence and citation handling.
- `tests/preferences/test_features_v4.py` — Tests for the versioned v4 preference features.

### Documentation & Governance

Intent, glossary, ADRs, architecture maps and operational guides.

**Key files**

- `AGENTS.md` — Contributor rules: intent first, native backend priority, isolated worktrees and reporting expectations.
- `GLOSSARY.md` — The single domain glossary for career-operations terms.
- `INTENT.md` — Normative product contract for the single-owner continuation: scope, safety, authorization and completion evidence.
- `README.md` — Project overview, architecture summary, documentation index and delivery caveats.
- `SETUP.md` — Detailed installation and setup instructions.
- `docs/adr/0001-native-agent-api.md` — ADR 0001: native Jobwatch agent API.

## 3. Key concepts

These are the terms the code assumes you already understand. The authoritative definitions live in [GLOSSARY.md](../GLOSSARY.md); the summaries below describe how each concept appears in the code.

### Safety and authorization invariants

- **Exact Input Approval** — Human approval bound to the exact current reviewed inputs; changed inputs invalidate it.
- **Confirmed Submit** — The final application action, allowed only through submit_confirm.py against an unchanged, reviewed fill.
- **Identity Binding** — The server-authenticated owner identity carried through every route, tool, checkpoint and artifact.
- **Trust Boundary** — The boundary where model text, uploaded files and page content can never confer human authority.
- **Advisory Memory** — Per-person advisory context that cannot edit approved evidence or override domain gates.
- **Ready Package** — A current package that has met the authoritative eligibility, factual and document gates.

Two code-level consequences are worth memorising. First, `jobwatch/apply/submit_confirm.py` is the only module allowed to press Submit; anything else that reaches a final button is a bug. Second, approval is bound to the exact reviewed inputs, so a changed URL, value or attachment invalidates it rather than silently reusing it.

### Candidate and eligibility

- **Profile Version** — An immutable record of one confirmed or adopted profile, with evidence snapshots.
- **Canonical Evidence** — Approved source material supporting personal claims, with exact citations; model memory is never a substitute.
- **Search Scope** — The confirmed basis, locations, daily assessments and token ceiling within which discovery and assessment may run.
- **Decision Policy** — Search strategy, exclusion rules and eligibility constraints derived from the approved profile, separate from target policy.
- **Eligibility Gate** — Deterministic admission that decides eligibility from confirmed policy, separate from any holistic fit score.
- **Field Hypothesis** — A related occupation found by semantic retrieval from approved facts, used to aim discovery and never as proof of qualification.

### Screening, assessment and ranking

- **Execution Mode** — One effective AI mode (off, reader, pipeline, agentic, screened) chosen per install.
- **Prescreen** — Reversible admit/flag/skip decision applied to saved postings before paid reading.
- **Relevance Judgment** — A stored yes/no/uncertain verdict on whether a posting belongs to the person's fields, with verbatim quotes.
- **Liveness Observation** — A source-bound public observation that a vacancy is still live before any paid work.
- **Job Attempt** — Canonical processing of a posting against captured inputs, identified by its run key.
- **Evidence Coverage** — The importance-weighted fraction of applicable requirements supported by evidence, with an upper bound for unknowns.
- **Shortlist Label** — A versioned presentation category (stronger match, stretch, needs clarification); not eligibility or hiring probability.

### Statistics, accounting and evaluation

- **Preference Model** — A validated local conditional-logit model of human choices among displayed eligible jobs, never hiring probability.
- **Callback Estimate** — A historical Beta-Binomial callback rate with uncertainty, distinct from a forecast for one job.
- **Frozen Baseline** — An immutable per-person snapshot of stored pipeline inputs and outputs with gate routes recomputed under a pinned profile.
- **Budget Accounting** — Reserve, dispatch, settle accounting for model calls that keeps unknown charges conservative and attributable.
- **Interaction** — A pending human question or approval bound to a checkpoint and its exact inputs.

A recurring trap: a fit score or a `Stretch` label is **presentation**, not eligibility, and a callback estimate is historical, not a forecast. `pipeline/decision.py` states the shared rule — fit is advisory; only explicit conflicts exclude. Do not promote a score into a gate.

## 4. Guided tour

Follow these steps in order. Each step names the graph nodes involved so you can jump straight to the source.

### 1. Start with the product contract

Read INTENT.md and GLOSSARY.md first. INTENT.md is normative: it defines the single-owner scope, the Screening -> Evaluation priority, the safety rules and what counts as completion evidence.

Nodes: `INTENT.md`, `GLOSSARY.md`, `AGENTS.md`

### 2. Follow one collection run

jobwatch/run.py is the collection spine: pick a tier, run each collector, dedupe, apply rules, publish to the board, prune, then hand off to the AI step.

Nodes: `jobwatch/run.py`, `jobwatch/collectors/base.py`, `jobwatch/dedupe.py`, `jobwatch/filters.py`, `jobwatch/util/http.py`

### 3. Understand the execution-mode switch

Only one AI mode is effective per install. config/jobwatch.yaml currently sets execution_mode: screened; the switch lives in execution_mode.py and dispatches to screened, graph, reader or the agentic service.

Nodes: `jobwatch/execution_mode.py`, `config/jobwatch.yaml`, `pipeline/screened.py`, `pipeline/graph.py`, `jobwatch/reader.py`

### 4. Build the candidate model

Intake turns uploads into proposals; only a human confirmation creates an immutable profile version. Evidence, eligibility and decision policy are then compiled from that approved version.

Nodes: `jobwatch/candidate/intake.py`, `jobwatch/candidate/approved.py`, `jobwatch/candidate/evidence.py`, `jobwatch/candidate/eligibility.py`, `jobwatch/candidate/policy.py`

### 5. Trace one paid evaluation

The screened mode promotes the best shortlisted jobs into service.run_agentic_job. That path reserves budget, captures the ad, runs the evaluation agent and applies the deterministic gate.

Nodes: `pipeline/agentic/service.py`, `pipeline/agentic/autonomous.py`, `pipeline/agentic/evaluator.py`, `pipeline/agentic/matching.py`, `pipeline/agentic/gate.py`

### 6. Turn results into an explained shortlist

Ranking is presentation of evidence coverage, not eligibility. Selection is a separate human approval that only authorizes preparation.

Nodes: `pipeline/agentic/ranking.py`, `pipeline/agentic/shortlist.py`, `pipeline/agentic/selection.py`, `pipeline/agentic/feedback.py`, `Shortlist Label`

### 7. Walk documents to the Submit boundary

Drafting is followed by deterministic verification, a fresh-context review and packaging. Form preparation stops for exact human review; submit_confirm.py is the only path that presses Submit.

Nodes: `pipeline/agentic/draft.py`, `jobwatch/apply/chain.py`, `jobwatch/apply/verify.py`, `jobwatch/apply/prepare.py`, `jobwatch/apply/submit_confirm.py`

### 8. Read the state and accounting layer

Every paid action is claimed, budgeted and recorded. Incidents are durable, artifacts are hash-checked, and recovery is read-only by design.

Nodes: `pipeline/agentic/store.py`, `pipeline/agentic/persistence.py`, `pipeline/agentic/runtime.py`, `pipeline/agentic/execution.py`, `pipeline/agentic/incidents.py`

### 9. Meet the client surfaces

The native HTTP API is the primary interface; the web board, MCP server, LibreChat adapter, ACP adapter and TUI are clients over the same canonical operations.

Nodes: `pipeline/agentic/api.py`, `jobwatch/web/app.py`, `pipeline/agentic/chat.py`, `pipeline/agentic/mcp_server.py`, `pipeline/agentic/tui.py`

### 10. Verify before believing anything

Frozen baselines and replays are development tools, not acceptance. Tests prove mechanics; a merge or a green suite does not prove the deployed backend works.

Nodes: `pipeline/agentic/baseline.py`, `pipeline/agentic/evaluate_runs.py`, `tests/conftest.py`, `scripts/agentic_acceptance.py`, `docs/architecture/codebase-map.md`

## 5. File map

Every file-level node, grouped by its layer. Complexity is a 1–10 static estimate derived from size and branch count; it is a reading-effort signal, not a defect score.

### Entry Points & Execution Modes

| File | Complexity | Role |
|---|---:|---|
| `jobwatch/reader.py` | 10 | Legacy full-ad AI reader mode: reads complete ads against approved evidence and confirmed per-person policy. |
| `jobwatch/cli.py` | 7 | Top-level `jobwatch` CLI; discovers optional subcommand packages (apply, outcomes, web, prescreen, notifier, commands). |
| `jobwatch/run.py` | 7 | One collection run: tiered collectors, dedupe/store, rules filter, publish, prune, then AI dispatch by execution mode. |
| `pipeline/graph.py` | 7 | Deterministic typed asyncio state graph over SQLite pipeline state; selectable pipeline execution mode. |
| `pipeline/screened.py` | 7 | Main execution mode: category refresh, retry, title triage, deterministic graph, liveness refresh, then promotes the best shortlisted jobs to the agentic evaluator. |
| `jobwatch/execution_mode.py` | 4 | Resolves the single effective AI mode (off, reader, pipeline, agentic, screened) while preserving legacy flags. |

### Collection & Deterministic Screening

| File | Complexity | Role |
|---|---:|---|
| `jobwatch/util/adtext.py` | 9 | Captures and stores full job-ad text so the reader inspects the whole ad rather than a teaser. |
| `jobwatch/collectors/jsonld_pages.py` | 8 | Employer career pages parsed from schema.org JobPosting JSON-LD, with robots.txt respected. |
| `jobwatch/collectors/source_plugins.py` | 8 | User-defined source plugins plus built-in feed and GradConnection plugins. |
| `jobwatch/filters.py` | 8 | Config-driven rules matching from rules.yaml; every decision records which arm and rules fired. |
| `jobwatch/prescreen/engine.py` | 8 | Generic prescreen engine that parses a posting with stored terms and evaluates stored rules. |
| `pipeline/agentic/discovery.py` | 8 | Field-guided discovery that enforces exclusions; defaults preserve collection and archive behaviour. |
| `jobwatch/collectors/ats_workday.py` | 7 | Workday CXS collector that posts to a tenant's job search endpoint and normalizes results. |
| `jobwatch/collectors/jobspy_src.py` | 7 | python-jobspy scraping for LinkedIn, Indeed (Australia) and Google. |
| `jobwatch/collectors/rss.py` | 7 | Generic RSS/Atom job feeds declared in feeds.yaml. |
| `jobwatch/collectors/seek.py` | 7 | Seek public search JSON collector that needs no login. |
| `jobwatch/occupations/datasets.py` | 7 | Versioned local public reference datasets; ordinary reads never download. |
| `jobwatch/occupations/embeddings.py` | 7 | Private, resumable vector caches and paid discovery accounting. |
| `jobwatch/occupations/hypotheses.py` | 7 | Turns approved evidence into occupational search hypotheses; never proof of qualification. |
| `jobwatch/occupations/loaders.py` | 7 | Deterministic public occupation texts; similarities are never qualification proof. |
| `pipeline/agentic/liveness.py` | 7 | Source-bound public vacancy observations taken before any agent or model work. |
| `pipeline/agentic/location.py` | 7 | Offline geographic evidence for exact cited job locations. |
| `pipeline/nodes/ingest.py` | 7 | Pipeline node 1: ingestion and deduplication in plain code, with no model call. |
| `pipeline/vocabulary_research.py` | 7 | Bounded public-page vocabulary research for a person's confirmed goals. |
| `jobwatch/occupations/plan.py` | 6 | Deterministic collector plans derived from occupational hypotheses. |
| `jobwatch/prescreen/store.py` | 6 | Database access for prescreen seeds, terms, rules, overrides, decisions and statistics. |
| `jobwatch/prescreen/sync.py` | 6 | Projects the confirmed profile into prescreen_rules rows (source='profile'). |
| `jobwatch/recall.py` | 6 | AI recall that surfaces wanted jobs whose titles the keyword rules do not know. |
| `jobwatch/util/http.py` | 6 | Polite HTTP client: one session, per-host delay, timeouts, robots.txt for pages and back-off. |
| `pipeline/agentic/discovery_ops.py` | 6 | Typed, person-scoped discovery requests executed on the durable API worker. |
| `pipeline/discovery_vocabulary.py` | 6 | Versioned discovery suggestions kept separate from personal restrictions. |
| `jobwatch/collectors/ats_greenhouse.py` | 5 | Greenhouse job board API collector. |
| `jobwatch/collectors/ats_lever.py` | 5 | Lever postings API collector, including EU region hosts. |
| `jobwatch/collectors/base.py` | 5 | Shared collector context and helpers for every source adapter. |
| `jobwatch/dedupe.py` | 5 | Canonical-URL hash deduplication, then normalized (company, title, city) matching within 30 days. |
| `jobwatch/expiry.py` | 5 | Expires stale job ads so the database does not retain dead postings. |
| `jobwatch/prescreen/lifecycle.py` | 5 | Post-decision posting lifecycle: screen the existing queue and re-admit skipped postings. |
| `pipeline/agentic/discovery_api.py` | 5 | Typed discovery operations; identity is selected by bearer authentication. |
| `pipeline/agentic/discovery_settings.py` | 5 | Per-person operational settings for job discovery. |
| `pipeline/title_triage.py` | 5 | Classifies unlisted titles using only the current user's category snapshot. |
| `jobwatch/discovery_gate.py` | 4 | Discovery requires a confirmed profile scope before any source runs. |
| `jobwatch/fieldgen.py` | 4 | Generates a person's searches.yaml and rules.yaml from their confirmed profile. |

### Candidate Understanding & Eligibility

| File | Complexity | Role |
|---|---:|---|
| `jobwatch/candidate/eligibility.py` | 9 | Canonical personal eligibility; nothing is inherited about home, level, rights or hours. |
| `jobwatch/candidate/intake.py` | 9 | Profile intake: private uploads become parsed, sourced profile proposals awaiting human confirmation. |
| `jobwatch/candidate/policy.py` | 9 | Deterministic decision policy compiled from confirmed profile facts. |
| `jobwatch/candidate/contracts.py` | 8 | Candidate analysis contracts and typed schemas. |
| `jobwatch/candidate/evidence.py` | 8 | Canonical approved evidence and exact citations. |
| `jobwatch/outcomes/sync.py` | 8 | Read-only mail scan that produces outcome proposals and one approval batch. |
| `jobwatch/preferences/features.py` | 8 | Versioned preference features; missing is not false and rubric scores are not labels. |
| `jobwatch/candidate/projection.py` | 7 | Projects the approved profile into the files existing readers consume (profile.yaml, master_resume.md, criteria). |
| `jobwatch/candidate/rules.py` | 7 | Digest-confirmed amendments to the canonical approved exclusion facts. |
| `jobwatch/preferences/model.py` | 7 | Bounded local R/JAGS fitting and fail-closed posterior prediction. |
| `jobwatch/preferences/store.py` | 7 | Append-only owner labels; construction and every GET-side method avoid writes. |
| `jobwatch/profile_check.py` | 7 | Checks the person's own files for misspelled or wrong lines. |
| `pipeline/agentic/candidate_digest.py` | 7 | Private native-tool candidate understanding produced before personal screening. |
| `jobwatch/candidate/analysis.py` | 6 | Structural candidate analysis primitives used by assessment and discovery. |
| `jobwatch/candidate/assessment.py` | 6 | Candidate-first, evidence-bounded assessment through the shared agent runtime. |
| `jobwatch/candidate/intent.py` | 6 | Separates confirmed preferences, restrictions and legal facts without inferring consent. |
| `jobwatch/candidate/person.py` | 6 | Reads settings from the server-bound person's approved profile version. |
| `jobwatch/onboarding.py` | 6 | Turns a person's uploaded documents into their profile files. |
| `jobwatch/outcomes/classify.py` | 6 | Classifies an employer or ATS email into an application outcome. |
| `jobwatch/outcomes/decide.py` | 6 | Owner decisions that apply approved outcome status changes. |
| `jobwatch/preference_service.py` | 6 | Current, independently gated evaluations are the only valid preference alternatives. |
| `jobwatch/preferences/experience.py` | 6 | Approved exact-date tenure only; occupation labels never establish qualification. |
| `pipeline/agentic/attachments.py` | 6 | Receives standard chat file parts without depending on a frontend file store. |
| `pipeline/agentic/matching.py` | 6 | Local requirement-directed retrieval over approved canonical evidence only. |
| `pipeline/agentic/profile_conversation.py` | 6 | Human chat responses to native questions and an exact profile review. |
| `jobwatch/candidate/approved.py` | 5 | Reads the server-bound person's immutable approved inputs. |
| `jobwatch/candidate/inputs.py` | 5 | One bounded, immutable input snapshot shared by runtime, cache identity and the UI. |
| `jobwatch/outcomes/callback.py` | 5 | Callback rate per arm computed as Beta-Binomial with a Beta(1, 15) prior. |
| `jobwatch/outcomes/readiness.py` | 5 | Observed outcome inventory; no-response cases are right-censored, not failures. |
| `jobwatch/candidate/suggestions.py` | 4 | Local TF-IDF retrieval of possible activity links; never confirms a skill. |
| `pipeline/agentic/profile_api.py` | 4 | Native HTTP surface for profile intake and approval; the person always comes from the bearer token. |

### Assessment & Shortlisting

| File | Complexity | Role |
|---|---:|---|
| `pipeline/agentic/service.py` | 10 | Canonical agentic orchestration: admission, budgets, evaluation and document pipeline, gates and resumable artifacts. |
| `pipeline/agentic/autonomous.py` | 9 | Bounded native assessment: deterministic Screening followed by one Evaluation agent. |
| `pipeline/agentic/evaluator.py` | 8 | Isolated whole-ad extraction followed by immutable candidate-evidence matching. |
| `pipeline/agentic/feedback_prompts.py` | 8 | Bounded human questions and genuine three-job-plus-none comparisons. |
| `pipeline/agentic/research.py` | 8 | Narrow public-job research adapter with immutable facts and fail-closed fetching. |
| `jobwatch/util/openrouter_extras.py` | 7 | Jev ad screening and ad embeddings through OpenRouter and OmniRoute; public ad text only. |
| `pipeline/agentic/feedback.py` | 7 | Append-only human feedback kept distinct from eligibility and preference training. |
| `pipeline/agentic/gate.py` | 7 | Deterministic safety and policy admission for agentic evaluations. |
| `pipeline/agentic/jev_skills.py` | 7 | Jev skills inside the evaluator and writer, gated on career facts supplied by the core service. |
| `pipeline/agentic/ranking.py` | 7 | Pure presentation of frozen evidence matches; no eligibility decisions or model calls. |
| `pipeline/agentic/selection.py` | 7 | Person-bound selection approval and a durable preparation outbox; never Submit. |
| `pipeline/agentic/shortlist.py` | 7 | Current account-bound shortlist snapshots built without model calls. |
| `pipeline/agentic/company_research.py` | 6 | Bounded public company context shared by the specialist and the canonical writer. |
| `pipeline/nodes/sort.py` | 6 | Names why the gate archived a job as not a target role. |
| `pipeline/agentic/feedback_api.py` | 5 | Human native operations over the shared feedback and selection services. |
| `pipeline/agentic/model_insights.py` | 5 | Read-only access to existing career models; no fitting or owner-label writes. |
| `pipeline/agentic/shortlist_api.py` | 5 | Authenticated unpaid shortlist views where identity is never a request parameter. |
| `pipeline/cli.py` | 5 | `jobwatch pipeline ...` subcommands for the deterministic pipeline. |
| `pipeline/store.py` | 5 | SQLite pipeline persistence: one state row per job, an event per move and a dead-letter queue. |
| `pipeline/structured.py` | 5 | The only way a pipeline node talks to a model: ask, validate against a strict schema, retry, give up. |
| `pipeline/decision.py` | 4 | Shared assessment semantics: fit is advisory and only explicit conflicts exclude. |
| `pipeline/nodes/extract.py` | 3 | Pipeline node 2: profile and job extraction. |
| `pipeline/nodes/gate.py` | 3 | Pipeline node that applies the canonical admission gate. |
| `pipeline/nodes/evaluate.py` | 1 | Pipeline node 3: semantic fit evaluation against an explicit rubric. |
| `pipeline/schemas.py` | 1 | Typed contracts for the deterministic pipeline. |

### Documents, Packages & Application

| File | Complexity | Role |
|---|---:|---|
| `jobwatch/apply/prefill_workflow.py` | 9 | Owner-authorized application preparation; never follows instructions embedded in page content. |
| `jobwatch/web/browser_session.py` | 9 | On-demand owner-controlled Chromium sessions streamed by the web app. |
| `jobwatch/apply/answers_agent.py` | 8 | Prepares every application answer from private, versioned owner sources. |
| `jobwatch/apply/browser.py` | 8 | Shared application browser workflow independent of either frontend. |
| `jobwatch/apply/prefill.py` | 8 | Prepares owner-controlled application tabs without ever submitting. |
| `jobwatch/apply/prepare.py` | 8 | Discovers, answers and prepares an owner application without manual field mapping. |
| `jobwatch/apply/verify.py` | 8 | Code claim verifier for drafted documents; nothing here calls a model. |
| `jobwatch/interview/ad.py` | 8 | Retrieves complete public ATS descriptions for explicit standalone interview preparation. |
| `jobwatch/interview/browser.py` | 8 | Ephemeral read-only public browser acquisition for standalone interview preparation. |
| `jobwatch/interview/prep.py` | 8 | Posting-bound private interview preparation with durable conservative budgets. |
| `pipeline/agentic/draft.py` | 8 | Bounded candidate-specific drafting, claim verification and PDF packaging. |
| `pipeline/agentic/interview.py` | 8 | Private, evidence-bound interview intelligence authored and reviewed by Deep Agents. |
| `jobwatch/apply/careerops_cv.py` | 7 | CV PDF built from the career-ops ATS template. |
| `jobwatch/apply/chain.py` | 7 | Public draft chain: requirements, drafter, verifier, reviewer and revision. |
| `jobwatch/apply/evidence.py` | 7 | Deterministic evidence extraction with no LLM, plus the read-only profile loader. |
| `jobwatch/apply/jev_forms.py` | 7 | Jev label matching on application forms; answer values are filled by local code. |
| `jobwatch/apply/render.py` | 7 | Renders draft to markdown, HTML and finally PDF. |
| `jobwatch/followup/drafts.py` | 7 | Private replayable follow-up drafts where ledger budgets precede every model call. |
| `jobwatch/followup/events.py` | 7 | Owner-confirmed follow-up history stored in the replayable application ledger. |
| `jobwatch/notifier/channels.py` | 7 | Notification transports, each built from stored config and sending one event. |
| `jobwatch/notifier/service.py` | 7 | Notification channels, outbox and receipts for the owner. |
| `pipeline/agentic/browser_api.py` | 7 | Native application and browser operations shared by the chat and website frontends. |
| `pipeline/agentic/writing_guide.py` | 7 | Writing form derived from the current person's confirmed preferences, never another owner's voice. |
| `jobwatch/apply/career_retrieval.py` | 6 | Finds the owner's career-record facts that answer a form question, by meaning. |
| `jobwatch/apply/requirements.py` | 6 | Posting requirements annotated with provenance tiers. |
| `jobwatch/apply/submit_confirm.py` | 6 | The only confirmed-Submit path, bound to the exact reviewed employer URL, filled values and attachments. |
| `jobwatch/apply/verify_pdf.py` | 6 | Checks the rendered PDF text layer with pdftotext. |
| `jobwatch/followup/tracking.py` | 6 | Read-only follow-up cadence, separate from drafting and sending. |
| `pipeline/agentic/followup.py` | 6 | Evidence-bound follow-up composition with a separate hash-bound reviewer. |
| `pipeline/agentic/review.py` | 6 | Fresh-context independent review of a candidate-specific draft. |
| `jobwatch/notify.py` | 5 | Owner messages: the chat history plus pushing urgent ones to notification channels. |
| `pipeline/agentic/forms.py` | 5 | Builds a conservative form map from validated screening answers. |
| `pipeline/agentic/letter_rules.py` | 4 | Rules applied when composing cover letters and other correspondence. |
| `pipeline/agentic/revisions.py` | 4 | Draft revision handling between the drafter and reviewer. |

### Agent Runtime & Conversation

| File | Complexity | Role |
|---|---:|---|
| `pipeline/agentic/chat.py` | 10 | Trusted local chat dispatch boundary providing conversation tools and specialist sub-agents. |
| `jobwatch/util/llm.py` | 8 | OpenAI-compatible gateway client for paid model transport. |
| `pipeline/agentic/contracts.py` | 8 | Strict serialized contracts for the bounded agentic career-operations pipeline. |
| `pipeline/agentic/runtime.py` | 8 | Explicit tool registry and conservative shared budgets for agentic roles. |
| `jobwatch/util/model_choice.py` | 7 | Per-person routing of which model handles which job. |
| `pipeline/agentic/deepagents_runtime.py` | 7 | Bounded Deep Agents execution using Jobwatch's local paid gateway. |
| `pipeline/agentic/chat_storage.py` | 6 | Local SQLite LangGraph persistence, one private database per Jobwatch person. |
| `pipeline/agentic/configuration.py` | 6 | Canonical configuration for paid execution and read-only candidate readiness. |
| `pipeline/agentic/gateway.py` | 6 | Shared JSON gateway transport for conversation and bounded role models. |
| `pipeline/agentic/task_state.py` | 6 | Plain task state and Stop for one posting. |
| `pipeline/agentic/identity.py` | 5 | Private, idempotent account enrollment performed by the trusted backend. |
| `pipeline/agentic/langgraph_entry.py` | 4 | Serves Jobwatch's own chat graph through a LangGraph server. |
| `jobwatch/users.py` | 3 | Names the single owner and the folders that belong to them. |
| `pipeline/agentic/presentation.py` | 2 | Chat response guidance for Markdown and native LibreChat Artifacts. |

### State, Accounting & Recovery

| File | Complexity | Role |
|---|---:|---|
| `pipeline/agentic/baseline.py` | 9 | Frozen baseline: models, gate version, case grouping, tags, freezing and loading. |
| `pipeline/agentic/evaluate_runs.py` | 8 | Frozen canonical gate and ranking replay with no production writes and no default models. |
| `pipeline/agentic/incidents.py` | 8 | Durable assessment failures and their independent notification delivery state. |
| `pipeline/agentic/persistence.py` | 8 | Fenced immutable artifacts and canonical apply rows with a durable ledger outbox. |
| `pipeline/agentic/store.py` | 8 | Additive SQLite persistence for fenced agentic runs and budget checkpoints. |
| `jobwatch/reports/evaluation.py` | 7 | Data-minimised deterministic private reports for frozen evaluation replays. |
| `pipeline/agentic/api_store.py` | 7 | Private transactional native API state stored beside LangGraph checkpoints. |
| `pipeline/agentic/eval_data.py` | 7 | Private frozen evaluation inputs with write-once grouped splits and audited access. |
| `pipeline/agentic/eval_metrics.py` | 7 | Pure diagnostics for frozen replays with explicit human-label missingness. |
| `jobwatch/db.py` | 6 | SQLite store with WAL and idempotent migrations tracked by PRAGMA user_version. |
| `jobwatch/ledger.py` | 6 | Append-only JSONL ledger that forms the canonical system layer. |
| `pipeline/agentic/eval_fit.py` | 6 | Optional local fit on frozen genuine choices confined to development cases. |
| `pipeline/agentic/evaluation.py` | 6 | Offline tool-trajectory evaluation without candidate text or a model judge. |
| `pipeline/agentic/execution.py` | 5 | Shared invocation identity, cancellation and payload-free local activity records. |
| `pipeline/agentic/private_sqlite.py` | 3 | Private per-person SQLite connection and journal helper. |
| `pipeline/agentic/recovery.py` | 3 | Read-only recovery proposals that cannot release or replay incidents by themselves. |

### Clients & Adapters

| File | Complexity | Role |
|---|---:|---|
| `jobwatch/web/queries.py` | 10 | Read side of the web board: filters, facet counts and the stored AI reading of each ad. |
| `pipeline/agentic/tui_screens.py` | 10 | Board screens of the terminal app: Today, Jobs, Detail, Review, Applications, Inbox and more. |
| `jobwatch/web/app.py` | 9 | The Jobwatch web board: FastAPI, Jinja2 and HTMX, loopback only. |
| `pipeline/agentic/chatgpt_connector.py` | 9 | Read-only ChatGPT connector tools plus MCP Apps widgets. |
| `pipeline/agentic/tui.py` | 9 | Claude-Code-style terminal UI for the Jobwatch career agent. |
| `pipeline/agentic/api.py` | 8 | Native authenticated agent HTTP API for threads, runs, events, interactions and artifacts. |
| `jobwatch/web/actions.py` | 7 | Write side of the web board; every apply-table write goes through existing APIs. |
| `jobwatch/web/ask_cards.py` | 7 | Friendly question cards for the owner's saved form answers. |
| `jobwatch/web/chat_routes.py` | 7 | Chat page hosting one thread on the board. |
| `pipeline/agentic/client_api.py` | 7 | Narrow native operations for the embedded app; ordinary API auth stays unchanged. |
| `pipeline/agentic/librechat.py` | 7 | Optional OpenAI wire adapter; Jobwatch retains identity, state and approvals. |
| `pipeline/agentic/mcp_oauth.py` | 7 | Optional OAuth 2.1 authorization-code with PKCE for the MCP server. |
| `pipeline/agentic/mcp_server.py` | 7 | Authenticated MCP entry point for the Jobwatch career chat agent. |
| `jobwatch/origin_guard.py` | 6 | Origin guard for HTTP surfaces, used by the web board's host and POST checks. |
| `jobwatch/web/preference_routes.py` | 6 | Owner-only explicit preference choices through the board's origin guard. |
| `jobwatch/web/prepare_routes.py` | 6 | Protected application review, streamed browser and one-time missing-fact intake. |
| `pipeline/agentic/acp_agent.py` | 6 | Agent Client Protocol adapter for Toad and other ACP clients. |
| `pipeline/agentic/connector_http.py` | 6 | Authenticated loopback operations for the TypeScript MCP server. |
| `pipeline/agentic/mcp_access.py` | 6 | Cloudflare Access identity for the Jobwatch MCP server. |
| `jobwatch/google/gmail.py` | 5 | Read-only Gmail helpers on the person's own token; there is no send function by design. |
| `jobwatch/google/oauth.py` | 5 | Per-person Google OAuth 2.0 web flow implemented with plain HTTP. |
| `jobwatch/web/accounts_routes.py` | 5 | Connects job-board accounts through the streamed browser. |
| `jobwatch/web/answers_routes.py` | 5 | Owner-only answers page for saved form-field answers. |
| `jobwatch/web/models_routes.py` | 5 | Per-job model selection and gateway key settings page. |
| `jobwatch/web/onboarding_routes.py` | 4 | Welcome page that uploads a CV and builds the profile plus search configuration. |
| `pipeline/agentic/connector_onboarding.py` | 4 | Account-bound onboarding operations for an authenticated MCP client. |

### Configuration, Deployment & Operations

| File | Complexity | Role |
|---|---:|---|
| `scripts/agentic_acceptance.py` | 6 | Read-only conservative acceptance audit for agentic READY packages. |
| `scripts/seed_profile.py` | 6 | Explicit local profile import that copies only named inputs and never logs their text. |
| `tools/build_occupation_reference.py` | 6 | Rebuilds the public occupation reference from pinned, hash-verified official downloads. |
| `.github/workflows/backend.yml` | 1 | Hosted CI workflow; the owner has disabled CI and it is not a completion requirement. |
| `config/employers.yaml` | 1 | Employer registry used by the ATS collectors. |
| `config/feeds.yaml` | 1 | RSS and Atom feed sources for the generic feed collector. |
| `config/jobwatch.yaml` | 1 | Runtime settings: database path, HTTP politeness, collector tiers, execution_mode: screened and agentic budgets. |
| `config/rules.yaml` | 1 | Deterministic exclusion rules consumed by jobwatch/filters.py. |
| `config/searches.yaml` | 1 | Collection search queries and locations. |
| `deploy/README.md` | 1 | Deployment and release documentation. |
| `deploy/release.sh` | 1 | Deployment release helper script. |

### Tests & Verification

| File | Complexity | Role |
|---|---:|---|
| `tests/candidate/test_intake.py` | 8 | Tests for profile intake and proposal confirmation. |
| `tests/candidate/test_policy.py` | 7 | Tests for the confirmed-profile decision policy. |
| `tests/conftest.py` | 6 | Shared pytest fixtures for the Jobwatch test suite. |
| `tests/apply/test_prefill_workflow.py` | 5 | Tests for the owner-authorized prefill workflow. |
| `tests/candidate/test_evidence.py` | 5 | Tests for canonical evidence and citation handling. |
| `tests/preferences/test_features_v4.py` | 5 | Tests for the versioned v4 preference features. |
| `tests/web/test_web.py` | 5 | Tests for the web board routes and rendering. |
| `tests/apply/test_prepare.py` | 4 | Tests for application preparation and form answers. |
| `tests/baseline_support.py` | 4 | Support helpers for frozen baseline tests. |
| `tests/candidate/test_eligibility.py` | 3 | Tests for canonical personal eligibility decisions. |

### Documentation & Governance

| File | Complexity | Role |
|---|---:|---|
| `AGENTS.md` | 1 | Contributor rules: intent first, native backend priority, isolated worktrees and reporting expectations. |
| `GLOSSARY.md` | 1 | The single domain glossary for career-operations terms. |
| `INTENT.md` | 1 | Normative product contract for the single-owner continuation: scope, safety, authorization and completion evidence. |
| `README.md` | 1 | Project overview, architecture summary, documentation index and delivery caveats. |
| `SETUP.md` | 1 | Detailed installation and setup instructions. |
| `docs/adr/0001-native-agent-api.md` | 1 | ADR 0001: native Jobwatch agent API. |
| `docs/adr/0002-profile-intake-and-approval.md` | 1 | ADR 0002: profile intake and approval. |
| `docs/adr/0003-frozen-baseline.md` | 1 | ADR 0003: frozen baseline. |
| `docs/adr/0004-decision-policy-from-confirmed-profile.md` | 1 | ADR 0004: decision policy from the confirmed profile. |
| `docs/adr/0005-field-and-job-discovery.md` | 1 | ADR 0005: field and job discovery. |
| `docs/adr/0006-confirmed-preferences-throughout-pipeline.md` | 1 | ADR 0006: confirmed preferences throughout the pipeline. |
| `docs/adr/0007-ranking-and-explained-shortlist.md` | 1 | ADR 0007: evidence-based ranking and explained shortlist. |
| `docs/adr/0008-feedback-and-selected-preparation.md` | 1 | ADR 0008: human feedback and selected preparation. |
| `docs/adr/0009-frozen-evaluation-and-monitoring.md` | 1 | ADR 0009: frozen evaluation and development monitoring. |
| `docs/adr/0010-standard-chat-client-boundary.md` | 1 | ADR 0010: standard chat clients own presentation. |
| `docs/adr/0011-owner-direction-history.md` | 1 | ADR 0011: owner direction history and superseded requirements. |
| `docs/agents/architecture-inventory.md` | 1 | Static inventory of collection, canonical services and retained compatibility surfaces. |
| `docs/agents/domain.md` | 1 | One domain context, root glossary and architecture-decision conventions. |
| `docs/application-workflows.md` | 1 | Application and reader workflow guide. |
| `docs/architecture/codebase-map.md` | 1 | Architecture and assessment cost map: entry points, paid trace, domain services and repair order. |
| `docs/architecture/source-catalog.md` | 1 | Generated index of code, configuration, assets and tests with static imports. |
| `docs/commands.md` | 1 | Commands and profile workflow reference. |
| `docs/configuration.md` | 1 | Configuration and collector reference. |
| `docs/installation.md` | 1 | Installation and settings guide. |
| `docs/operations.md` | 1 | Data, timers, web board and rollback operations guide. |
| `pipeline/agentic/CHAT.md` | 1 | Native agent API operational contract: schema, profile intake, discovery, runtime, clients and release. |
| `pipeline/agentic/MATCHING.md` | 1 | Requirement evidence matching, retrieval, storage and offline comparison tools. |

## 6. Complexity hotspots

These files carry the most static complexity. Read them with the surrounding tests and the architecture map beside you rather than editing them cold.

| File | Complexity | Why it is dense | Where to look first |
|---|---:|---|---|
| `jobwatch/reader.py` | 10 | Legacy full-ad AI reader mode: reads complete ads against approved evidence and confirmed per-person policy. | Legacy full-ad reader with its own prompt, budget and persistence path |
| `pipeline/agentic/service.py` | 10 | Canonical agentic orchestration: admission, budgets, evaluation and document pipeline, gates and resumable artifacts. | Central orchestrator: admission, budgets, evaluation, packages, gates |
| `pipeline/agentic/chat.py` | 10 | Trusted local chat dispatch boundary providing conversation tools and specialist sub-agents. | Chat tools, specialists and dispatch boundary |
| `jobwatch/web/queries.py` | 10 | Read side of the web board: filters, facet counts and the stored AI reading of each ad. | Read model for the whole board: filters, facets, ad reviews |
| `pipeline/agentic/tui_screens.py` | 10 | Board screens of the terminal app: Today, Jobs, Detail, Review, Applications, Inbox and more. | Read the module docstring and its tests first |
| `jobwatch/util/adtext.py` | 9 | Captures and stores full job-ad text so the reader inspects the whole ad rather than a teaser. | Ad capture, locking and completeness states |
| `jobwatch/candidate/intake.py` | 9 | Profile intake: private uploads become parsed, sourced profile proposals awaiting human confirmation. | Upload parsing, proposal generation and confirmation states |
| `jobwatch/candidate/eligibility.py` | 9 | Canonical personal eligibility; nothing is inherited about home, level, rights or hours. | Read the module docstring and its tests first |
| `jobwatch/candidate/policy.py` | 9 | Deterministic decision policy compiled from confirmed profile facts. | Deterministic decision policy from confirmed facts |
| `pipeline/agentic/autonomous.py` | 9 | Bounded native assessment: deterministic Screening followed by one Evaluation agent. | Deterministic screening followed by a Deep Agents evaluation |
| `jobwatch/apply/prefill_workflow.py` | 9 | Owner-authorized application preparation; never follows instructions embedded in page content. | Browser preparation with exact-approval and expiry rules |
| `jobwatch/web/browser_session.py` | 9 | On-demand owner-controlled Chromium sessions streamed by the web app. | Streamed Chromium sessions and ownership checks |
| `pipeline/agentic/baseline.py` | 9 | Frozen baseline: models, gate version, case grouping, tags, freezing and loading. | Frozen baseline freeze/load and gate versioning |
| `jobwatch/web/app.py` | 9 | The Jobwatch web board: FastAPI, Jinja2 and HTMX, loopback only. | Route surface and rendering for the web board |
| `pipeline/agentic/chatgpt_connector.py` | 9 | Read-only ChatGPT connector tools plus MCP Apps widgets. | Read the module docstring and its tests first |
| `pipeline/agentic/tui.py` | 9 | Claude-Code-style terminal UI for the Jobwatch career agent. | Read the module docstring and its tests first |
| `jobwatch/collectors/jsonld_pages.py` | 8 | Employer career pages parsed from schema.org JobPosting JSON-LD, with robots.txt respected. | Read the module docstring and its tests first |
| `jobwatch/collectors/source_plugins.py` | 8 | User-defined source plugins plus built-in feed and GradConnection plugins. | Read the module docstring and its tests first |
| `jobwatch/filters.py` | 8 | Config-driven rules matching from rules.yaml; every decision records which arm and rules fired. | Read the module docstring and its tests first |
| `jobwatch/prescreen/engine.py` | 8 | Generic prescreen engine that parses a posting with stored terms and evaluates stored rules. | Read the module docstring and its tests first |

## 7. Practical starting points

- **Setup and commands:** [SETUP.md](../SETUP.md), [docs/commands.md](commands.md), [docs/configuration.md](configuration.md).
- **Tests:** `pytest` uses `testpaths = ["tests"]` from `pyproject.toml`; Python is pinned to `>=3.12,<3.13` and dependencies are locked in `uv.lock`.
- **Runtime shape:** `config/jobwatch.yaml` sets `execution_mode: screened`. Collection is independent of the AI mode; only the post-collection hook changes.
- **Entry points:** `jobwatch` (CLI), `jobwatch-agent` (native HTTP API), `jobwatch-mcp` (MCP server), `jobwatch-tui` (terminal UI), `jobwatch-acp` (ACP adapter).
- **Contracts:** [pipeline/agentic/CHAT.md](../pipeline/agentic/CHAT.md) for the native API; [pipeline/agentic/MATCHING.md](../pipeline/agentic/MATCHING.md) for evidence matching.

## 8. Caveats before you change anything

- The continuation keeps the deployed assessment path paused; no source change authorizes activation, timer changes or deployment.
- Hosted CI is disabled by the owner. Passing local checks are required; a green workflow is not a completion claim.
- Never use live candidate records as test fixtures. Use synthetic fixtures under `tests/fixtures/`.
- Keep candidate facts, preferences and credentials in the owner's approved runtime files, never in the repository.
- A merge, a passing test or a plan does not prove the deployed backend works. Verify the owner's actual service before any release claim.

---

_This guide was rendered from `.ua/knowledge-graph.json`. The graph was produced by static inspection (AST imports, module docstrings, repository docs) rather than the understand-anything plugin, which was unavailable in this session. Re-run `/understand --full` after significant structural changes to refresh it._

