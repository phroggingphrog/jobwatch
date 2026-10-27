# Career Ops and Jobwatch: pinned source comparison

Compared 2026-10-28. Career Ops clone:
`/home/phroggingphrog/projects/references/career-ops`, commit
`b5e4c26f21efee31559296495d794c9a9564a714`.
Jobwatch deployed baseline `9111a0d`; pending development is separately described
in [the codebase map](codebase-map.md). TASK-279 retains release status.

This is a domain-by-domain comparison, not a claim that both implementations have
identical features, deployment guarantees or policies. No upstream installation,
candidate-data import, hosted tracing, signature or community notification occurred.

| Career Ops source at pinned revision | Jobwatch counterpart | Comparison / implementation consequence |
|---|---|---|
| [MANIFESTO.md](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/MANIFESTO.md) | INTENT, approved evidence, exact Submit | Preserve candidate control, evidence, explainability and human consent. Upstream's economic/community positions do not override the owner's approved paid gateway or native confirmed-Submit operation. |
| [DATA_CONTRACT.md](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/DATA_CONTRACT.md) | users, intake/profile versions, evidence snapshots, runtime directories | Both separate user data from system code. Jobwatch adds authenticated per-person isolation and native state ownership. Advisory chat history is not a verified profile. |
| [.agents/skills/career-ops/SKILL.md](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/.agents/skills/career-ops/SKILL.md) | native API, chat and service dispatch | Upstream modes route procedures through agent CLIs. Jobwatch needs durable stage agents calling canonical operations; a client chat specialist is not an automatic reader stage. |
| [modes/intake.md](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/modes/intake.md), compact user brief | intake + new Candidate Understanding stage | Jobwatch first confirms facts, then lets an agent digest primary evidence and applicable mathematical/statistical models. The resulting cited digest is reused, not generated per posting. |
| [scan.mjs](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/scan.mjs), [title-keywords.mjs](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/title-keywords.mjs) | collectors, Rules, prescreen | Deterministic early collection/filtering. Jobwatch personal filtering waits for a current digest; collect-only never purchases it. Missing understanding permits storage with a pending marker instead of falling back to old personal defaults. |
| [modes/triage.md](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/modes/triage.md) | compact screening policy + optional judgment | Upstream triage deliberately reads one compact brief and emits a short verdict. Jobwatch clear seniority/location/rights/hours checks need no per-job model. Do not copy score thresholds, salary estimates or title preferences into personal policy. |
| [modes/oferta.md](https://github.com/career-ops-hq/career-ops/blob/b5e4c26f21efee31559296495d794c9a9564a714/modes/oferta.md) A role, B match, C strategy, D compensation/demand, E customization, F interview, G legitimacy, H answer drafts | native evaluation then separate documents/interview/application operations | Report blocks are not a required series of paid agent calls. Jobwatch's historical A–G labels differ; map semantics rather than pretending letters match. Keep the first evaluation slice separate from document generation and submission. |
| oferta two-pass evidence ordering and primary-source boundary | extraction freeze → canonical retrieval → exact evidence judgments | Both protect assessment from preference-driven requirement rewriting. Jobwatch additionally binds source hashes and retrieved records in code; those constraints must be accepted at completion rather than failing only after paid summary. |
| CV generation/factual gate and report machine summaries | draft/review, ATS/PDF verification, immutable package | Shared principle: tailor truth rather than invent claims. Jobwatch has typed artifacts, exact draft review and package hashes. Native schemas must match canonical validators. |
| apply / tracker / followup / interview / offer / patterns modes | browser/confirmed Submit, applications/events, followup/interview/outcomes | Existing operations are mapped in the codebase document; do not report all modes as autonomous stages already delivered. |
| patterns / calibrate methods | structural 60/40 proximity, R/JAGS preference model, Beta-Binomial callbacks | Jobwatch's statistical models are additional canonical services, not equivalent to upstream prose modes. Agents must access their outputs/readiness; no extra supervisor should recalculate them in prose. |
| No corresponding core Jev route in inspected workflow | public-ad/duplicate/form-label Jev and inactive candidate-bearing checks | Jev is a Jobwatch integration, not an upstream requirement. Keep actual route availability explicit and candidate data on approved routes. |

## Concrete corrections carried into execution

Candidate Understanding precedes personal filtering and exposes model outputs or
readiness honestly. Its manifest binds person, profile/evidence, model/reference,
history, policy and implementation. The deterministic policy projection contains
only approved constraints; learned advice is separate. No numeric experience cap
is fabricated from an approved level or raw duration. Explicit confirmed numeric
rules remain supported.

Native Evaluation follows the cheap gate directly. The old multi-role evaluator
and coordinator overhead do not run on this path. Validation feedback identifies
the field needing correction; exact unsupported citations remain refused. The
saved overlength report now fails at the producing schema. The digest and per-job
costs are separate and total usage remains accounted, including classifiers and
embeddings. No new limit is imposed on the owner's Unlimited configuration.

Source comparison and synthetic mechanics do not prove DeepSeek assessment quality,
the 3–6-call target, safe live recovery or deployment. Those remain release checks
on the OpenSpec checklist and TASK-279.

The requested [DeepWiki manifesto/governance page](https://deepwiki.com/career-ops-hq/career-ops/1.4-manifesto-community-and-governance)
was read first. Its signature bots, governance and community publication machinery
are unrelated to this runtime repair and were not imported or executed.
