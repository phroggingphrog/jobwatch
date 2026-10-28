# Candidate/evidence foundation — approved isolated design

Owner approval in this DSH conversation, 2026-10-09: **"I approve"**, responding to the [first-slice proposal](</home/phroggingphrog/Documents/Codex/2026-10-09/you-re-right-the-original-concept/outputs/FIRST-SLICE-DESIGN-PROPOSAL.md>). This records approval of that slice, not live cutover or acceptance of BUI-196's separate pending card. Work item BUI-258, parent analysis BUI-248.

## Intent and authority

Canonical [INTENT.md](</home/phroggingphrog/apps/jobwatch/INTENT.md>) wins over this design and all plans; file still marked draft, root card left untouched. Frozen relevant text:

> An **agentic career-ops system**: AI agents do the career work for each job (read the whole ad, judge it against the
> owner's real profile, research when useful, write tailored applications, prepare the form). Only *collecting* jobs is a
> fixed script. It is **not** a keyword watcher and **not** a fixed pipeline that calls a model per step.

> - **CAP-2 Agentic evaluation.** An agent reads the *whole* ad and evaluates it against `career_ops_profile.md` + CV with
>   the career-ops rubric (`oferta.md`/`_shared.md`): 1-5 score, archetype, requirement-to-CV match, work rights,
>   legitimacy, owner targets and hard gates. Success: each evaluated job shows the agent's reasoning on its Job page.

> - CAP-2 and CAP-3 are done by agents (the owner said "agentic system"), not one fixed prompt per step.
> - Models only through paid OmniRoute `openai/`, `claude/`, `google/` combos.

> - Keyword match as the decision. Template-like drafts. Submitting applications or contacting employers (the owner
>   always submits). Customer service, hospitality, retail or shop-floor roles as targets.

## Deliverable and boundaries

A callable, read-only candidate analysis foundation inside current jobwatch, ready for subsequent role tools. It supports CAP-2 but is **not itself CAP-2 completed**. Deterministic reference math remains an agent tool, never the decision-making pipeline.

Reuse current CV/profile extraction (without changing legacy callers), exact primary-source evidence and archived structural DWA/GWA analysis concepts. Do not import historic service modules or duplicate tracker V11. Derived results bind evidence, reference, mapping and owner-policy versions; canonical evidence stays immutable.

Components: confined evidence snapshot; pinned/licence-recorded reference snapshot; strict supplied mapping validation; structural candidate analyser; explicit current target-policy projection. Mapping confirmation state remains visible. Unknown, absent or ambiguous data stays unavailable/unknown, never guessed.

No model inference in this slice. Semantic selection is a future bounded paid-route tool, not an unrestricted endpoint. No DB/ledger migration, browser operation, timer, runtime feature enablement or provider-state persistence. No archived profiles, secrets, answers or personal data copied.

## Data flow

1. Read only allowlisted primary CV/profile and optional taxonomy/evidence annotations under an explicit root. Reject symlink/path escape, malformed/duplicate identifiers and unsupported quotes. Return source/content digests and exact spans; omit header contacts from analytic items. Taxonomy cannot establish a fact by quoting itself.
2. Load an explicit JSON reference export with schema version, source versions, actual licence identifiers and raw-content digest. Missing file returns unavailable; malformed/inconsistent reference fails with safe codes. Preserve GWA hierarchy and many-to-many crosswalk ambiguity rather than fabricating an ANZSCO code.
3. Validate supplied mapping records against source IDs/hashes and reference IDs/hash. Suggested and confirmed are separate provenance states. No raw model justifications in public result/errors.
4. Compute candidate DWA coverage, GWA similarity, evidence IDs, gaps and proposals from the validated inputs. No profile quote or contact text in returned analysis metadata. Excluded/non-target occupations may appear only in a named diagnostic surface; recommendation list includes only allowed families and positive supported proximity. Structural similarity is not eligibility, mastered skill or callback probability.
5. Produce stable result identity from every bound input. New evidence/reference/policy/mapping changes the key; never dispatch a draft, stage transition or new target.

Candidate-first person analysis is separate from JD-only requirement importance: subsequent evaluator freezes importance without profile access, then matches to this snapshot. Whole-ad evaluation, the role runtime, preference/outcome feedback, employer cards, independent golden/shadow acceptance and T19 prefill remain separate unfinished slices, not deferred product requirements.

## Education and targets

Current enrolment is not mastery. Completed/current/unknown status remains explicit. Official curriculum quotations describe learning outcomes only; no credential or mastered-skill claim can arise from them. Unsupported taxonomy facts reject. Current owner targets govern recommendations; exclusions cannot be weakened by learned/model/reference metadata. Employer industry does not automatically exclude a wanted accounting/back-office occupation.

## Acceptance

Two fictional candidates produce different supported paths. Unknown DWA/source IDs, stale digests, invented quotes/credentials, missing references and ambiguous crosswalks reject or stay unknown. Excluded roles never enter recommendations. Stable inputs are deterministic and input changes invalidate identity. Private source text never enters public metadata/logs/git/issues; no filesystem writes from the foundation. Existing graph/ledger/collectors remain unchanged; full synthetic regression suite passes in isolation.

## Provenance, branch and release

Branch `phase/01-agentic-career-ops` reconciled with main `7bfbc3598b852475044b91b5b23b249decc1df8a` through merge `78be468402f27f74c9812d43cfc4991aaf436b3b`; production main not changed by this session. Preserve existing untracked plan-review note. Source reuse must carry source paths/hashes, attribution/licences where applicable, and adaptation notes. No heavy dependency or new service.

Public archive has ten synthetic senior-AI reference cases; those labels are not this owner's target golden set. The private 122-case fleet corpus remains unverified. Do not claim actual profile analysis or real CAP acceptance from synthetic foundation tests.

Rollback: leave isolated commits unapplied or revert scoped candidate-foundation commits; no live data/state to undo. Live cutover requires separate owner approval.
