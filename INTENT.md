# Jobwatch intent

Recorded from the owner's direction on 2026-10-21. Keep this document public and
candidate-free. Changes to the product goal require the owner's explicit direction.

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

- The human alone submits applications. The agent does not send employer messages
  or move money. Approval to prepare materials does not authorize submission.
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
  does not establish that a browser form was filled; final Submit remains human-only.

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
