# Jobwatch agreed backend brief (owner, 2026-10-21)

This is the specification every roadmap plan argues from. Section A is the owner's brief, verbatim. Section B records the owner's later directions, verbatim, which take precedence where they are more specific.

## A. The brief (verbatim)

Jobwatch: agreed backend implementation brief
Implement the following agreed design in `phroggingphrog/jobwatch`. Inspect current main and the existing work in PRs #5 and #7 before editing. Reuse completed functionality and reconcile overlapping changes.
1. Product and workflow
Jobwatch is an automated career-operations backend with a native HTTP API. Chat and the website are interchangeable clients. Focus on the shared backend.
The agreed workflow is:
Upload documents → parse a draft profile → interactive review → user confirms → save approved profile → automatically discover and assess jobs → present ranked shortlist → user selects jobs and approves preparation → generate application documents → human submits.
Profile confirmation starts ongoing discovery and assessment within the search scope and budget shown during confirmation. It does not authorise document preparation, employer messages or submission.
Include plausible stretch opportunities in the shortlist, clearly distinguished from stronger matches.
2. Candidate profile and decision policy
Keep uploaded documents and parsed proposals private and separate from the approved candidate profile.
Show extracted experience, education, evidenced skills, possible transferable skills, employment status, availability, preferences, practical constraints and exclusions. Distinguish direct evidence, inference and unknown information. A CV gap alone does not establish unemployment.
Allow corrections and focused questions before confirmation. Only confirmed contents become authoritative profile facts. Preserve source references and versioned evidence snapshots. Later inferred amendments require confirmation before replacing approved facts.
Apply these search rules:

* Unemployed, no contrary instruction: employment-first discovery across permitted fields using relatable skills.
* Explicit career or degree focus: prioritise the requested direction.
* Explicit exclusions: always respect them; unemployment never overrides them.
* Missing information: ask when it materially affects a decision; do not silently treat it as failure.
* Changed circumstances or instructions: update the search strategy using the current confirmed profile and user direction.

Remove person-specific assumptions from application code. Preserve genuine eligibility constraints.
3. Field discovery and statistical ranking
Implement two connected stages: discovering suitable occupational fields, then finding and ranking actual jobs.
Field discovery: extend semantic retrieval to candidate evidence versus occupational tasks and skills. Existing Qwen retrieval for individual advertisements is not sufficient by itself. Reuse approved retrieval infrastructure. Version reference datasets and mappings; investigate current Australian classifications and available O*NET/ESCO correspondences. Related occupations are search hypotheses, not qualification proof.
Ability assessment: retain requirement-level evidence judgments: demonstrated, partial, unknown and contradicted. Exact citations must remain verifiable. Separate missing documentation from an actual skills gap or explicit conflict.
Preference ranking: improve the existing hierarchical Bayesian conditional-logit model rather than duplicating it. Expand narrow family categories and incomplete factual features. Learn from genuine user choices and rejection reasons. Choice probabilities describe preference among alternatives—not eligibility or hiring probability.
Employer outcomes: preserve the existing descriptive statistics. Investigate time-to-response modelling only when sufficient reliable history exists. Pending applications are not negative outcomes. Account for application selection bias and uncertainty before allowing predictions to influence ranking.
Cold start: deliver useful evidence-based shortlists immediately. Insufficient feedback must not prevent discovery. Clearly distinguish provisional ordering from validated personalised predictions. Document the initial ordering rules rather than inventing unexplained numerical weights.
The inherited holistic 1–5 score must not remain the sole exclusion mechanism. In particular, low career alignment must not automatically reject a suitable employment-first opportunity. Preserve it as a comparison baseline while validating the replacement policy.
4. Interaction and automation
Automatically collect, deduplicate, assess, rank and refresh opportunities within confirmed limits.
Each shortlist entry should explain:

* Relevant candidate evidence and transferable skills.
* Why it fits the current search objective.
* Practical conditions, mandatory requirements and unresolved facts.
* Whether it is a stronger match, stretch opportunity or needs clarification.
* Why it ranks where it does, including uncertainty.

Use occasional targeted comparisons or questions when answers could materially improve recommendations. Do not require feedback on every job.
Explicit exclusions are rules. Ordinary rejection reasons are feedback whose meaning must be preserved. Never record agent-generated answers as user choices or approval.
Use the existing LangChain, LangGraph and Deep Agents integration for tools, specialist reasoning, durable workflows and interactions. Statistical fitting and prediction remain explicit domain operations with versioned inputs and outputs.
Preserve dedicated company research, market/model insights, evidence-grounded writing and factual review in the shared pipeline. Generate tailored documents only for user-selected jobs after preparation approval.
5. Evaluation, delivery and acceptance
Compare the revised system with the current baseline using identical frozen inputs. Include previously rejected jobs, transferable skills, unknown facts, misleading titles, stretch opportunities and explicit exclusions.
Measure missed suitable jobs, unsupported qualification claims, useful shortlist ordering, exclusion violations, uncertainty handling, cost and latency. Keep duplicate advertisements and related employer cases from leaking across evaluation splits. Separate development examples from untouched evaluation examples.
Automate bounded comparisons, model fitting when eligible, monitoring and reproducible reports. Missing independent labels must remain explicit; synthetic checks or model self-grades do not establish recommendation quality.
Deliver the native API workflow, profile approval/versioning, automatic discovery, explained shortlists, feedback collection and selected-job document preparation. Preserve identity isolation, budgets, cancellation, recovery and private data handling.
Provide reviewed source changes, appropriate implementation checks, examples of the resulting workflow, remaining limitations and rollback instructions. Follow repository release requirements. Do not claim deployment or improved matching accuracy without the corresponding evidence.
Research starting points:
[Skill-based occupational transitions](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0254722), [active preference learning](https://proceedings.mlr.press/v70/maystre17a.html), [hierarchical modelling and evaluation](https://mc-stan.org/learn-stan/case-studies/pool-binary-trials-rstanarm.html), [recommendation selection bias](https://proceedings.mlr.press/v48/schnabel16.html).

## B. Later owner directions (verbatim, binding)

- Confirmed Submit: "its allright if it closes the owners open browwser, so basically it can submit either th eowner click the submit button OR with an explicit confirmation by user" — implemented in `jobwatch/apply/submit_confirm.py`; never submit through any other path.
- Semantic filtering: "it should use semanntic reasoning/extraction to filter out how about that" — the relevance decision in discovery uses semantic extraction, not title keywords alone (roadmap Plan 3).
- Discovery gate: "Job discovery should only be able to be turned on when the current profile already firm".
- Onboarding: "yeah thats why initial setup the AGENT will guide you and ask all relevant files and basically ask you questions to set up the profile (onboarding)".
- Onboarding: "should be interactive and processing your data/profile while asking".
- Development agents: "If you are running subagents can you use Sonnet instead?"
