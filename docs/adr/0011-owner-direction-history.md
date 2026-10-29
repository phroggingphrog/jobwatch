# Owner direction history through 2026-10-27

Status: historical record, not the current product specification.

This preserves the previous INTENT.md verbatim below, including superseded
instructions and exact owner quotations. Use [current intent](../../INTENT.md)
for normative requirements. This record does not establish implementation or deployment.

---

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
  does not authorize submission, and auto-fill never submits by itself. In chat the owner's
  conversation may override gates and preferences (owner 2026-10-25) and the agent reasons about it and records the
  override, but it never invents facts, and a confirmation never covers a form that changed after review. The agent does not
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

Owner's follow-up on 2026-10-24:

> if its QnA it can just ask its directly

Ask routine Q&A and onboarding questions directly in chat. Do not render a form or
open an app merely to collect an answer. Fix the normal chat attachment handoff;
reserve generated UI for explicit interactive requests or useful evidence displays.
Canonical review and exact-input human approvals retain their native interfaces.

## Owner-controlled OmniRoute model selection

Owner direction on 2026-10-24:

> just let me configure it myself via omniroute

> can you change it and decide with the current omniroute combo

> also deepseek flash and luna dont forget we can use that too

> bypass and remove the block

Choose Jobwatch role routes from the existing OmniRoute combos, including DeepSeek
Flash and Luna. Accept valid combo names directly instead of requiring an
OpenAI/Claude/Google provider prefix. The owner controls the concrete subscription
and model behind each combo in OmniRoute. Preserve the configured gateway,
per-person settings, existing excluded route classes and independent embedding
policy. Select observed working routes and report unavailable combo paths clearly.

## Vanilla clients and native generated interfaces

Owner direction on 2026-10-24:

> can we revert into vanilla librechat because jobwatch suppose to be front end agnostic for the bot endpoint like hermes but it should be able to received file,a account conenctions and does librechat have genui-dsh like or codex interactive ui render abilities or not

> there shuoldnt be jobwatch cards because how it works suppose to be how codex render its interactive ui and dsh render genui plugin

The owner selected:

> Vanilla LibreChat with native Artifacts

On attachment errors:

> it should support all files or what this is annoying

Use standard LibreChat and its native Artifacts, without Jobwatch-specific cards or a
DSH renderer fork. Jobwatch owns the portable bot endpoint, isolated account mapping,
file receipt and canonical operations. Accept and retain original files within explicit
size limits; distinguish receipt from successful reading. Read supported documents and
bounded ZIP contents; unreadable files receive an honest explanation without rejecting
the whole conversation. Files and generated interfaces never confer approval authority.
Preserve current data and owner identity. This supersedes the earlier custom-client and
fixed-card requirements. Protected operations remain paused when a client cannot provide
the required authenticated human review; do not manufacture an approval through chat or
an Artifact.

Owner's correction on 2026-10-24:

> my approval why need a screen if you can just parse it from tghe conversations

> profile confirmation should be able. from user chat and interactionn for chatbot front end

> why it wouldn't render anything if they tryna have an approval screen

> this is a design flaw

Routine answers and corrections update the unconfirmed draft directly from the person's
own words. Profile confirmation works through authenticated human conversation as well
as native interaction controls: show the actual draft and search scope in chat, then bind
an explicit human reply to that exact review. A separate screen is not required. The
backend authenticates the human channel and checks the current inputs; the model and
Artifacts cannot grant approval. A correction or changed draft needs another review.
This supersedes the per-answer approval and screen-only profile-confirmation design.
Other protected operations, including final Submit, retain their existing review paths.


## Canonical MCP results and interactive widgets

Owner direction on 2026-10-27:

> AI should only show the filtered and approved by the models

The owner approved the canonical-results and interactive-widgets implementation plan
and selected evidence holds **alongside eligible matches**. MCP must present Jobwatch's
existing canonical shortlist and ranking, including clearly labelled unresolved facts;
it must not turn collection, assessment attempts, exclusions or application activity
into recommendations. Evidence holds remain visible but cannot proceed to preparation.
Scores remain advisory and personal preferences come from the confirmed profile.

Keep Jobs, application history, Discovery progress/failures and supported configuration
as distinct surfaces over the same backend. Use the redesigned web dashboard as the
visual reference for contextual MCP Apps widgets. The host assistant handles conversation
and explicit consent through typed canonical operations; it is not a relay for another
onboarding or preparation chatbot. Preparation must bind the exact current eligible
entry/run, remain idempotent and never authorise Submit. Keep the existing separate
reviewed-form Submit confirmation, failure pauses, per-person configuration and spending
history. Verify actual intended-client rendering separately from builds and protocol
checks, and report any remaining host limitation honestly.


## Owner 2026-10-27

> the limit is unreasonable can we just remove this

> and change it into cheaper model like deepseek flash

Per-job assessment limits (tokens per job, time per job, steps per agent) are removable
per person: each is a number or Unlimited in the person's discovery settings, and a new
person starts with finite defaults. Assessment phases (frozen requirements, candidate
evaluation, matching, holistic evaluation) use the `evaluator` role, which a person can
point at the paid OmniRoute combo `deepseek-flash` (`model_choice` profile
`cheap-assessment`). Drafting, reviewing and answers keep their own roles. One absolute
stop per timer run (`JOBWATCH_HARD_STOP_SECONDS`, default 840 s for the 15 min units)
and the daily 'assessments per day' count still apply.

| R | date | CAP | question / deviation | ruling | by | ref |
|---|---|---|---|---|---|---|
| R3 | 2026-10-27 | CAP-2 | May assessment run on a cheaper paid route, and may per-job limits be removed? The hub INTENT 'Mechanisms required' line says paid `openai/`, `claude/`, `google/` combos only. | **CAP-2 assessment may use the paid OmniRoute `deepseek-flash` combo (owner's explicit choice; candidate facts are sent to that provider).** Per-job limits are removable per person. This is the owner's dated override of the 'Mechanisms required' provider list; free and stealth routes stay refused. | owner (chat 2026-10-27, quotes above) | feat/no-limits-cheap-model |


## Recovery-plan client direction (2026-10-30)

Owner supplied the Recovery & Launch Plan and directed implementation against it:

> The native API must work without LibreChat. The preferred production client should be the separate JobWatch web interface or another trusted native API client that properly supports typed human approvals.

> LibreChat remains a compatibility and testing surface, not an architectural dependency.

This supersedes a LibreChat-first reading of earlier client directions. Shared
canonical operations, typed exact-input approvals and the native backend remain
authoritative; no client rewrite is a prerequisite for native assessment acceptance.
