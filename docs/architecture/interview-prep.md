# Interview preparation briefing from last-30-days research

Status: design proposal. This document does not claim that all proposed behavior exists.

## Purpose

For one shortlisted posting, produce a private, cited interview briefing. Use the saved job description as the primary source for role context. Add public research about the employer and field from the 30 days before the briefing date. Run the briefing only when a person requests it or when the posting reaches the shortlist. Never run it for every posting.

The briefing supports interview preparation. It does not change the posting, assessment, shortlist, eligibility, or application state. It does not contact an employer. It must not read candidate profile files or the CV unless a separate, explicit interview-preparation workflow supplies approved evidence for personal story suggestions.

## Relevant `last30days-skill` ideas

The inspected skill describes research across Reddit, X, YouTube, TikTok, Hacker News, Polymarket, GitHub, and web search. It supports optional sources such as Instagram, LinkedIn, Bluesky, and others. It finds recent material, ranks evidence using recency, engagement, source diversity, and corroboration, then creates a sourced briefing. It also reports unavailable sources and uncertainty. These are descriptions from the skill and documentation. The exact ranking weights and every provider’s current behavior were not independently verified.

The repository is MIT-licensed. Its skill documents optional keys for ScrapeCreators, OpenAI, xAI, OpenRouter, Perplexity, Parallel, Brave, Apify, and social accounts. The exact minimum key set and price for a particular run are not fixed by the skill. **Not verified:** average API spend, request latency, and token use for a normal run. A run can use paid data providers and model calls. It can take multiple external requests; exact time depends on enabled sources and service response. Do not run its code for this design.

Jobwatch should adapt the evidence and synthesis pattern, not copy the unverified or social-scraping implementation. Prefer company websites, official newsrooms, public RSS/Atom, official APIs, government releases, reputable news RSS, job postings, and public salary sources. Reddit, social pages, and scraped pages are optional only if separately approved and permitted. The source plugin interface named in the task, `docs/architecture/source-plugins.md`, was not present in the checked-out worktree or current `main` branch. Its exact interface is therefore **not verified**. The design below requires an adapter boundary and must map to that PR’s interface before implementation.

## Current Jobwatch capability

The product intent defines a profile-driven career backend. It makes deterministic screening, reusable candidate understanding, cited evaluation, eligibility, and unchanged-input reuse the current priority. It names interview preparation as product scope, not proof of accepted or deployed behavior.

The checkout already contains interview preparation structures:

- `jobwatch/interview/prep.py` runs posting-bound preparation and stores run results.
- `jobwatch/interview/inputs.py` stores explicit owner inputs, such as interview invitations, panelist profiles, story bank, coffee-chat notes, and prior-round notes.
- `pipeline/agentic/interview.py` defines cited interview sections, including process, audience, story bank, technical preparation, company signals, compensation, and provenance.
- `pipeline/agentic/research.py` provides bounded public search and fetch abstractions. It defines research intents for employer identity, role context, desired skills, compensation, interview process, and interview questions.
- `pipeline/agentic/company_research.py` creates bounded public company context from a saved advertisement and research adapter.
- Assessment output is stored in `ad_reviews`, including verdict, fit, role match, reasons, pros, cons, flags, and structured report JSON. This does not establish that all fields are available through the posting shortlist interface.
- `jobwatch/db.py` contains private interview input and run tables.

The current interview skill says to use `prepare_interview` only after human approval, preserve citations, separate reported questions from guesses and general advice, and never invent personal experience. The proposed briefing can reuse these boundaries. This design does not read CV or profile files.

## Input and eligibility

Input: one saved posting ID that currently has shortlisted status and a complete saved job description. Resolve its immutable posting identity, company name, title, URL, acquisition details, and text hash from canonical Jobwatch records. Include the existing assessment result as context only. Do not treat model assessment text as fact about the employer or the person.

If the description is missing, stale, or too short, report that limitation. Do not silently fetch an alternate advertisement without recording its URL and retrieval date. If the posting is no longer shortlisted, require a person request and show that status changed.

## Briefing structure

Every claim has a source title, direct URL, publication or posting date, retrieval date, and evidence excerpt or stable content hash. If a date is unknown, label it `date unknown`; do not present it as recent. Separate sections into **Facts**, **Inferences**, and **Unknowns**.

1. **What the role really needs**
   - Summarize duties and required skills from the saved job description.
   - Separate explicit requirements from inferred priorities.
   - Give likely interview questions. Label these as inferred questions, not reported questions, unless a dated source reports them.
   - Link each requirement to the exact job-description passage and URL.
2. **The company: last 30 days**
   - Recent news, products, funding or budget, hiring signals, culture, and reviews.
   - Use dated public sources. Treat company claims as company-reported facts. Treat media reports as attributed reports. Mark opinions and reviews as opinions, not verified facts.
   - If a topic has no reliable recent source, say `No reliable source found in this window`.
3. **The field: last 30 days**
   - Trends, tools, and salary signals relevant to the role and location.
   - Distinguish observed salary ranges from inferred expectations. Include currency, geography, employment type, sample period, and source where present.
   - Do not infer a salary from an unrelated role or location without marking the inference.
4. **Questions the person can ask**
   - Tailor questions to verified company and role evidence.
   - Cite the evidence that motivates each question. Do not imply private knowledge or claim that an inference is confirmed.
5. **Sources, dates, and gaps**
   - List every source used, its date, link, source type, and retrieval time.
   - Record searches with no useful result, unavailable adapters, and evidence older than 30 days.

## Collection and ranking

Use the modular source adapter contract from the open collectors pull request once available. The adapter returns normalized records with source ID, title, URL, publisher, published date, retrieved date, content or excerpt, source type, location, and optional engagement values. It must expose terms/robots policy and freshness metadata. Do not let a model choose arbitrary URLs or fetch destinations. Reuse Jobwatch’s bounded public research and safe-fetch rules where the plugin contract permits.

Use deterministic filters first: publication date within 30 days; relevance to the employer, posting, or field; language and location where known; deduplicate canonical URLs and content hashes. Rank with an explainable score: topical match, freshness, source quality, and independent corroboration. Engagement can be a weak tie-breaker only. Do not equate popularity with truth. Prefer first-party sources for company facts and independent sources for context. Preserve source-specific provenance and conflicting reports. The model may summarize and propose inferences from supplied records. It must not collect data, invent citations, or turn inference into fact.

Start with 2-4 queries per briefing and fetch at most 6-10 pages total, subject to adapter limits. Prefer feeds and official APIs. Keep adapter-specific request pacing, caching, terms, and robots controls outside the synthesis model. Do not bypass access controls. If an allowed source returns `403`, `429`, or repeated server errors, stop that source for the run. Do not retry rapidly.

## Trigger, cache, and privacy

Trigger only on a person request or a shortlist transition. Use an idempotency key from posting ID, posting text hash, briefing schema version, research window end date, and source configuration. A shortlist transition must not trigger duplicate work when the same key already has a result.

Cache public research by normalized company identity and query window for 7 days. Reuse fresh company records across postings for the same company. Cache field research by normalized field/topic and window. Keep each record’s original date and URL. A cache hit does not extend the source publication date. Refresh after 7 days or on explicit request. The briefing itself remains posting-bound and includes the posting text hash.

Store only public evidence, citations, generated briefing, and run metadata in Jobwatch’s private durable store. Do not send CV text, profile files, private interview notes, or candidate identifiers to source adapters. If personal story matching is added later, keep it in the existing private interview workflow and use approved evidence snapshots. Do not publish briefing content to logs or shared tracing.

## Model calls and cost budget

Collection is pure HTTP and makes no model calls. Synthesis uses one bounded writer call and one bounded citation/claim reviewer call. A no-model deterministic briefing can still return the sourced role facts and source list if model calls are disabled or unavailable.

Proposed maximum: **12,000 model tokens per briefing**, including input and output across both calls. Reserve at most 8,000 input and 4,000 output tokens. Trim and deduplicate evidence before the writer call. The reviewer receives the draft and citation records only. If the evidence exceeds the cap, rank and truncate it deterministically, then state that sources were omitted by the evidence limit. Never exceed the cap silently. Record actual and reserved token use separately from assessment charges.

This is a design budget, not a measured cost. Model price depends on the configured paid model and is **not verified** here. At 25-50 postings per day, running for every posting would cost up to 300,000-600,000 tokens per day at the cap. That is 15%-30% of the 2,000,000-token daily limit, before other workflows. The shortlist-only or person-request trigger must therefore enforce a separate briefing pool. Example: reserve 200,000 tokens per day for briefings, which allows at most 16 full-cap briefings; unused briefing budget returns to the shared pool only under explicit accounting policy. Do not take tokens from the assessment budget. If the briefing pool is exhausted, defer the briefing or return cached/deterministic evidence and state the reason. The limit of 25-50 daily postings does not imply 25-50 briefings.

## Failure and safety behavior

- Missing, stale, conflicting, or undated evidence must remain visible.
- A source failure must not block access to the saved posting or assessment.
- Do not claim comprehensive coverage. Report enabled sources and source failures.
- Do not present reviews, sentiment, hiring signals, or salary estimates as verified company facts.
- Do not contact the company, submit applications, alter status, or make decisions for the person.
- Keep the briefing private and tied to the authenticated owner and posting.

## Acceptance criteria

1. The feature accepts one shortlisted posting and never scans all postings.
2. A person can request it. A shortlist transition can trigger it once per idempotency key.
3. Every factual claim has a dated source link or an explicit missing-date label.
4. Facts and inferences appear in separate, labelled sections.
5. The briefing covers role needs and likely questions, company research, field research, person questions, provenance, and gaps.
6. Company research cache keys use normalized company identity and expire after 7 days. Field research has a separate reusable cache.
7. Collection makes zero model calls. Synthesis uses no more than 12,000 tokens per briefing.
8. Briefing reservations use a separate budget and do not consume the assessment budget.
9. Source adapters enforce their configured request limits and expose source failures and provenance.
10. Tests use synthetic postings and public, non-candidate fixtures. They verify citation validation, recency, cache reuse, token caps, trigger deduplication, and failure reporting.

## Repository evidence

Read-only checkout review used `INTENT.md`, `docs/architecture/source-catalog.md`, `pipeline/agentic/interview.py`, `pipeline/agentic/research.py`, `pipeline/agentic/company_research.py`, `jobwatch/interview/prep.py`, `jobwatch/interview/inputs.py`, `jobwatch/db.py`, and the interview-prep skill. No CV or profile files were read. No code from `last30days-skill` was run.
