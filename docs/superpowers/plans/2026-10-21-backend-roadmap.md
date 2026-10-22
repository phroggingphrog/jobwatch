# Jobwatch agreed backend: roadmap

The owner's agreed brief (2026-10-21) covers several subsystems. Each plan below ships working, tested software on
its own and is written as a separate task plan when its turn comes. Plan 1 is written in full:
[2026-10-21-plan-1-profile-intake.md](2026-10-21-plan-1-profile-intake.md).

Starting point: `main` at 9dfdf7a (PRs #5, #7 and #8 merged). Inventory sources: the two read-only maps of
profile/onboarding and of discovery/ranking/feedback/evaluation (session notes), the design and model critique,
and the owner's additions ("it should use semantic reasoning/extraction to filter", confirmed Submit).

Owner clarification on 2026-10-23: required local verification and review determine
completion. Hosted CI is optional and is not a completion or merge gate. The owner
has disabled it; earlier CI requirements in this roadmap and its plans are superseded.

The [remaining-roadmap execution plan](2026-10-23-finish-backend-roadmap.md)
supersedes older launch/workflow assumptions. Phases 1–5 and the browser repair
(PR #23, issue #17) are merged. Phase 6 source is in release review; Phase 7 starts
after its reviewed merge. Each release uses a local `codex/` branch, required local
checks and independent review, followed by the owner-authorized merge. Source
completion excludes deployment, live fitting/migration and the real blind study.

## Workflow being delivered

Upload documents → parse a draft profile → interactive review → user confirms → save approved profile →
automatically discover and assess jobs → ranked, explained shortlist → user selects jobs and approves
preparation → generate documents → human submits (own click, board confirmation or approved API confirmation).

Profile confirmation starts discovery within the scope and budget shown at confirmation. It never authorises
preparation, employer messages or submission.

## Plans, order and dependencies

| # | Plan | Delivers | Depends on |
|---|------|----------|------------|
| 0 | Safety realignment (inside Plan 1, Task 1) | Collection evaluates only; it never drafts without a per-job preparation approval (today `after_collect` runs `operation='prepare'`). Fixes the onboarding `work_rights` string crash. | none |
| 1 | Profile intake and approval | Private uploads; parsed draft profile with direct-evidence / inference / unknown facts and source references; corrections and focused questions; confirmation with shown scope and budget; immutable approved versions with stored evidence snapshots; amendment proposals; native API endpoints. | 0 |
| 6a | Frozen baseline | Freeze the current pipeline's inputs and outputs (postings, evidence bundle, holistic scores, gate routes) for later comparison, before Plans 3–4 change behaviour. | 1 (a versioned profile to freeze against) |
| 2 | Decision policy from the profile | Search strategy derived from the confirmed profile (employment-first when unemployed and no contrary instruction; explicit career/degree focus prioritised; exclusions always rules; ask when missing information is material). Removes person-specific code: `MAX_COMMUTE_KM`, Victoria regexes, `location_fit: melbourne`, entry-level-for-everyone, "student" prompts, owner family lists. Keeps genuine eligibility constraints (work rights, hours limits). | 1 |
| 3 | Field and job discovery | Field discovery: dense retrieval of candidate evidence against O*NET tasks/skills and ESCO skills, through the approved Qwen embedding route, with versioned reference datasets and an investigated ANZSCO 2022 / OSCA correspondence; related occupations become search hypotheses, not qualification proof. Job discovery: title keywords become a recall-only pre-screen; a semantic step (quoted extraction from title and full ad, plus similarity to discovered fields) decides relevance in agentic mode. Semantic dedupe on description similarity across sources. | 2 |
| 4 | Ranking and explained shortlist | Holistic 1–5 score demoted to a comparison baseline (no sole exclusion; low career alignment never rejects an employment-first job). Deterministic importance-weighted coverage from requirement judgments (demonstrated / partial / unknown / contradicted; missing documentation separated from a real gap or conflict). Labels: stronger match / stretch / needs clarification. Documented cold-start ordering rules, shown as provisional. Shortlist entity and API with evidence, transferable skills, objective fit, conditions, mandatory requirements, unresolved facts, rank reason and uncertainty. Preference model: canonical families and neutral priors retained, versioned factual features with missingness/provenance, eligible and evidence-held alternatives, explicit immutable historical-choice migration. Callback stats stay descriptive; time-to-response only investigated when history suffices. | 3, 6a |
| 5 | Feedback and selection | Append-only reasons and reversible posting dismissal; digest-confirmed exclusion amendments; bounded targeted comparisons/questions from a valid posterior or deterministic fallback; durable selected-job preparation through native API and exact-human-confirmed chat; agent output never becomes a user choice. | 4 |
| 6b | Evaluation and monitoring | Runner that replays frozen inputs through baseline and revised pipelines; metrics: missed suitable jobs, unsupported qualification claims, ordering usefulness (precision@k / nDCG on owner labels), exclusion violations, uncertainty handling, cost, latency; leakage-safe grouped splits (duplicates and related employers); dev vs untouched evaluation sets; automated bounded comparisons; eligible model fits; reproducible reports; local full-suite release verification, with hosted CI optional. Missing independent labels stay explicit. | 6a, 4, 5 |

The owner-approved [Phase 5 execution plan](2026-10-22-phase-5-execution.md) supersedes older ranking-model assumptions. Its [source verification report](../../audits/2026-10-22-shortlist-release.md) separates reviewed implementation, actual checks and remaining validation gaps from merge or deployment.

Order: 1 (with 0) → 6a → 2 → 3 → 4 → 5 → 6b. Plan 6a must land before Plans 3–4 change any decision.

## Cross-cutting rules (every plan)

- Reuse canonical services: `snapshot_evidence`/`EvidenceBundle`, `RequirementEvidenceSearch`, `PaidGatewayEmbeddings`,
  `EvidenceJudgment`, `PreferenceStore` + R/JAGS fit, `run_agentic_job(operation=...)`, `APIStore`, `_approval_binding`,
  `compare_matching_runs`, `agentic_activity` / `Execution` usage.
- Per-person isolation, server-bound identity, budgets, cancellation, recovery and private data handling are
  preserved; new state lives under the person's folder with 0600/0700 permissions.
- Statistical fitting and prediction stay explicit domain operations with versioned inputs and outputs; LangChain /
  LangGraph / Deep Agents provide tools, specialist reasoning, durable workflows and interactions.
- No claim of deployment or improved matching accuracy without the corresponding evidence; synthetic checks and
  model self-grades do not establish recommendation quality.
- Each plan records its accepted design in `docs/adr/` before implementation (docs/agents/domain.md) and updates
  GLOSSARY.md for new terms (approved profile, profile version, proposal, shortlist, stretch).

## Research inputs to read during Plans 3–6

- Skill-based occupational transitions (PLOS ONE 2021, e0254722): evidence for skill-similarity occupation graphs.
- Active preference learning (Maystre & Grossglauser, ICML 2017): choosing comparisons that most reduce uncertainty.
- Hierarchical partial pooling of binary trials (Stan case study): per-arm callback rates and evaluation.
- Recommendations as treatments (Schnabel et al., ICML 2016): inverse-propensity correction for selection bias.
