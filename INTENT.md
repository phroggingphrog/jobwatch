# Jobwatch intent

Recorded from the owner's direction on 2026-10-21. Keep this document public and
candidate-free. Changes to the product goal require the owner's explicit direction.

## Development completion

Owner deployment direction on 2026-10-23:

> I want to deploy and run the current job watch from the repo as its finished, and use libre chat as its UI

> clean start

Deploy the current backend with fresh runtime state and LibreChat as its client.
Preserve existing data separately. LibreChat does not replace native Jobwatch
operations or turn model text into approval. Deployment requires its own local
release checks and observable runtime evidence.

Owner follow-ups:

> stop the old jobwatch services isolated it

> the jobwatch should render it in the chat like how CHATGPT MCP works not direct me into link

> it shuld be configured and the agent shuold render intelligence ui like chatgpt how can we do this? make jobwatch mcp connector?

Keep legacy services stopped and isolated from the fresh runtime. Configure
LibreChat to render Jobwatch's relevant forms, decisions, progress, job results
and documents inside the conversation through an embedded MCP App. Jobwatch
retains server-bound identity, native orchestration and exact-input approval;
model-facing tools must not acquire the human UI's decision authority.

Owner follow-up on 2026-10-23:

> bruh i dont want that i ask you to be fully interactrive for the user this is too much for general user base

The embedded client must make ordinary tasks interactive and discoverable for general users. Model choices use visible controls and selectable configured names; users should not need to type gateway model IDs or understand internal routing. A panel that fails to load does not satisfy this requirement.

Owner's approved complete-frontend direction on 2026-10-23:

> yes that what I mean so theres no need to direct it to the website because the job watch website IS SEPARETELY DIFFERENT FRONT END than this one

> Make LibreChat a complete Jobwatch frontend

LibreChat and the website are separate frontends over the same authoritative backend.
Use fixed, focused conversation cards for profile setup, configured model choices,
explained job results, progress/questions/decisions, verified documents/revisions and
live employer form review. Automatically open the newest relevant card only for the
configured Jobwatch server. Connect each authenticated LibreChat account automatically
to its own isolated Jobwatch identity; preserve the existing owner's mapping and keep
credentials server-side. Friends must not enter or share Jobwatch API keys.

The in-chat application card must show the live employer browser, actual form values
and attachments, allow scoped human corrections/login/verification where supported,
and offer separately confirmed final Submit through the canonical confirmed-Submit
operation. Both frontends share browser ownership and submission processing. Model
text cannot approve, changed review needs fresh confirmation, and uncertain submissions
must never be retried automatically. Unsupported flows remain blocked with a clear
reason inside chat. Preserve old conversation resources and useful text fallbacks;
never use the Jobwatch website as the fallback.

Completion requires a working authenticated public LibreChat journey with synthetic
employer submission and safe refusal cases, two simultaneous isolated accounts,
required local checks and independent review. A passing loopback preview is insufficient.
Reproduce the reported loading timeout and fix its demonstrated cause; extending the
timeout alone is insufficient. Deploy backend/browser ownership before enabling cards,
preserve data, retain the independent website and prepare rollback for both repos.

Owner direction on 2026-10-23:

> can we not include CI as the rules for it to be finished

> I already disabled It

Use the required local verification and review to determine source completion.
Hosted CI is optional and does not gate completion or merge. Keep it disabled
unless the owner requests otherwise. Local failures and review findings still
require accurate reporting and resolution; deployment remains a separate action.

## Profile-dependent behavior

Owner follow-up on 2026-10-22:

> pre filter shouldn't be hardcoded

> yeah can you do an audit where preferences is hardcoded because it shouldn't profile preferences behavior shouldn't be hardcoded

Personal preferences must come from each person's confirmed profile, not inherited
geographic, career, seniority or writing assumptions in shared code. Missing facts
stay unknown. The collector/ingest regional prefilter now reads the confirmed
policy. The [source audit](docs/audits/2026-10-22-profile-preferences.md) preserves
the original findings and records their source repairs across active and retained
paths, separately from reference data and technical controls. Its verification
limits still apply; source repairs do not establish live recommendation quality.
Owner's subsequent direction:

> fix all of the issues then merged into main

This authorizes completing the repairs in GitHub #14 and merging reviewed source into main.
Use confirmed profile policy across collection, eligibility, ordering and writing; scores
remain advisory. Preserve historical decisions for comparison without retaining a live
personal-policy fallback. Source merge does not activate a service, refit a model or submit an application.

## Owner's words

> native API is my plan

> ok so we need to use the full langchain ecosystem

> need to utilise full deep agents capabilities and the langchain ecosystem framework integrated in and do not focus on front end as current goal is to be dispatched as a chat agent first before integration into website ui ux so need the back end working

## Product

Jobwatch is a profile-driven career-operations backend. It discovers openings,
reads complete job ads against a person's approved evidence and preferences,
explains fit and eligibility, and prepares application materials and related
career work. It supports different people and career fields without putting one
person's facts, work rights, location or target roles into application code.

Routine work should be low effort for the user. A client can show structured
progress, useful results and focused questions or approvals when needed. The user
should not have to supervise every internal agent step.

## Current delivery

The primary interface is Jobwatch's authenticated native HTTP agent API. Jobwatch
owns orchestration and authoritative state. A chat client can start a conversation,
inspect work, answer a question, approve or reject an operation and retrieve its
documents. Website UI integration follows backend delivery. DSH integration is not
part of this scope. MCP is an optional compatibility adapter.

Use the relevant LangChain ecosystem capabilities coherently: LangChain model and
tool interfaces; LangGraph persistence and human interrupts; Deep Agents planning,
specialists, scoped files, skills and advisory memory. Keep shared identities,
budgets, cancellation and recovery across those capabilities. Use local evidence
retrieval and privacy-safe evaluation where they serve an actual workflow.

Existing Jobwatch domain services remain authoritative for collection, evidence,
eligibility, leases, factual review, document verification and package persistence.
Keywords may help discover postings; they do not decide personal fit.

## Boundaries

- An application is submitted only by the owner's own click on the employer's Submit,
  or by Jobwatch pressing it after the owner explicitly confirms that exact reviewed fill
  (board button, or an approved chat `submit_application`). Approval to prepare materials
  does not authorize submission, and auto-fill never submits by itself. The agent does not
  send employer messages or move money.
- Identity comes from authentication. Human responses belong to their exact
  pending interaction and inputs; recovery must not reuse an old approval for new work.
- Personal claims require approved canonical evidence. Advisory memory and model
  guesses cannot become profile facts or override eligibility gates.
- Keep people, profiles, credentials, documents and history isolated. Keep private
  data outside Git and candidate-bearing prompts out of hosted tracing.
- Use approved configured paid model routes, explicit budgets and safe errors.
  Never weaken eligibility or factual gates to manufacture a READY result.

## Success criteria

- An authenticated client can start and resume durable conversations through HTTP,
  handle typed questions and decisions, and reconnect to progress and saved outcomes.
- Agents choose appropriate specialist work and reusable skills, while canonical
  Jobwatch operations enforce evidence, eligibility and package correctness.
- Run and job outcomes distinguish completed conversation turns, READY packages,
  held or archived jobs, deferred work and failures, with useful reasons.
- Authorized users can retrieve verified documents. Restart, retry and cancellation
  preserve identity, approval boundaries and accountable usage.
- Claims of deployment and writing quality require their own evidence. A form map
  does not establish that a browser form was filled; final Submit needs the owner's click or
  their confirmation of that exact filled form.

Operational contracts and setup are in [the backend guide](pipeline/agentic/CHAT.md).
Domain terms live in [GLOSSARY.md](GLOSSARY.md); architecture decisions live in
[docs/adr/](docs/adr/).

## Company research and existing model integration

Owner follow-up on 2026-10-21:

> there shuold be an ability for company_researcher that research the desired skills company based on the job ads

> so when the writer writing a cover letter it can write more naturally why the candidate want its job, and why did the market evaluator and all of the math model missing here

Clarification: **Existing models and their agent integration**.

Company research should connect the complete job ad's desired skills and duties
with cited public employer context. The writer uses this context alongside
approved career interests for specific, natural motivation. Existing structural,
preference and outcome models remain available as distinct, explainable measures;
none can replace eligibility or invent candidate facts or motivations.

Owner clarification:

> not only the cfhat agent i mean for the overall pipeline of this jobwatch

> we dont need to revamp the chat, the chat is just a front end for the agent so the user can use it

> chat is just intercfhangeable like the original web front end it just so itd be able to deploy quickly

Research, evaluation, mathematical models and writing belong to the shared backend
pipeline. Chat is an interchangeable client, alongside the original web interface;
it enables quick delivery without defining a separate career workflow.

## Evidence matching overhaul

Owner direction, followed by **continue then**:

> well then we need to revamped this and check what we can imporve it on the rnd in llm wiki or any personal knowledge

Match each ad requirement to approved primary evidence before judging career
desirability. Distinguish demonstrated support, partial support, unknown facts and
explicit contradiction. Preserve exact citations and make unresolved questions
visible. Find differently worded and transferable evidence without treating word
overlap, occupation similarity or model confidence as qualification proof.

Keep ability, personal preferences, practical eligibility and historical outcomes
separate. Preserve the inherited holistic score as a comparison baseline; change
automatic exclusion policy only after a reviewed comparison including jobs the
old matcher archived. Research references and typed outputs do not establish
matching accuracy. Track implementation and remaining experiments in GitHub #6.

Owner's embedding-model choice, 2026-10-21:

> qwen

Use Qwen3 Embedding 8B through the existing paid OmniRoute route for canonical
candidate-evidence retrieval. Approval is specific to embeddings; the chat route
allowlist, budgets, per-person credentials and human approval boundaries remain.

## Profile intake and discovery

Owner direction on 2026-10-21, on when discovery may run and how a profile is set up:

> Job discovery should only be able to be turned on when the current profile already firm

> yeah thats why initial setup the AGENT will guide you and ask all relevant files and basically ask you questions to set up the profile (onboarding)

> should be interactive and processing your data/profile while asking

Discovery runs for a person only while their current profile version is confirmed and carries a
confirmed search scope. Initial setup is guided by the agent, which asks for the relevant files and
asks the person questions while their documents are processed in the background. Confirmation does not
authorise document preparation, employer messages or submission. See [ADR 0002](docs/adr/0002-profile-intake-and-approval.md)
and [the worked example](docs/examples/profile-intake.md).

## Semantic field and posting discovery

Owner direction on 2026-10-21:

> it should use semanntic reasoning/extraction to filter out how about that

Title keywords may widen recall by adding postings for full-ad fetching; they
never exclude a posting from semantic assessment or decide personal fit. Related
occupations are search hypotheses, not proof of qualification. Similarity
thresholds remain uncalibrated, and the current implementation makes no
matching-accuracy claim. See [ADR 0005](docs/adr/0005-field-and-job-discovery.md).

## Confirmed Submit

Owner direction on 2026-10-21:

> yeah its allright if it closes the owners open browwser, so basically it can submit either th eowner click the submit button OR with an explicit confirmation by user

Auto-fill may close the owner's open browser for the same person. A confirmation binds to
the reviewed fill: run, package, browser target, page URL, owner revision, attached PDFs,
the one recognised final control, and the values of the form's visible input, select and
textarea fields read back from the page. Hidden inputs and captcha responses are not part
of it, and contenteditable or custom widgets are not read; an owner click or keypress in the
page still voids a confirmation, scrolling does not. It is refused if any bound part changed,
after one use, or 15 minutes after a chat approval. A chat approval names the posting and
binds to the fill. Review the actual form and attachments in the in-chat application card
or the independent website before approving. See `jobwatch/apply/submit_confirm.py`.

## Ranked and explained shortlists

Owner approved implementation of Phase 5 on 2026-10-22:

> Build a ranked shortlist that explains **what the evidence supports, what remains uncertain, and why each job appears where it does**.

Use the confirmed profile and canonical eligibility operation. Evidence labels and
provisional ordering explain the frozen requirement judgments; preferences, missing
facts and practical conditions remain distinct. Neutral priors stay neutral, and only
a valid genuine-choice fit can personalise within evidence tiers. The owner selected
explicit historical-choice migration tooling that preserves original records; no live
migration or fitting follows from implementation. The approved scope and interfaces
are recorded in the [Phase 5 plan](docs/superpowers/plans/2026-10-22-phase-5-execution.md).

## Contextual inline interfaces

Owner's latest direction on 2026-10-24:

> i ask you to port the DSH GEN UI and see how it works and make the agent can do it right

> not by making an APP but by rendering based on what it needs

Render the interface appropriate to each reply, mixed with normal conversation, using
DSH GenUI's SchemaJSON components and renderer. Ordinary onboarding questions can be
focused forms rather than a persistent dashboard. Keep the backend portable: another
frontend can consume the same answer format through its own renderer. Preserve normal
host file attachments and model selection. Generated interfaces carry no approval or
submission authority; canonical human review and confirmed Submit remain separate.
This direction supersedes the earlier requirement for a dashboard-style MCP App as
the ordinary conversation interface. Existing saved resources remain readable.
