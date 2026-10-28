# Phase 01 issue handoff map

Design approval: BUI-209, explicit no Blockers. Plan author: BUI-210. Implementation must await Staff plan check; no owner plan confirmation is requested.

## Owner takeover — supersedes dispatch instructions (2026-10-09)

Owner comment on BUI-210 assigns Codex in desktop chat the original-concept coverage check, current-implementation inspection, and implementation/verification in an isolated checkout. Preserve the approved design, research and eight plans. Paperclip stops at the current planning artifact: do not create or dispatch Build/Release issues, including after BUI-216 resolves. No live cutover is authorized. BUI-216 completed with structural changes required on the original candidate. The revised eight plans now pass GSD structure checks; Staff closing review remains required, not implicitly approved. BUI-196 and full goal-contract acceptance remain incomplete; scope is not reduced. Codex should use the sequence below as technical reference, reconcile omissions against GOAL_CONTRACT.md, and retain offline/live safety boundaries.

## Historical proposed Build graph — reference only, do not instantiate
All children belong to jobwatch project c590d533-f3dd-4f21-a0d9-253f862c4281, parent BUI-196 (3ef02c58-85bf-46e3-9dde-d967a8506bea), carry Builder Staff review policy, and explicitly use `/home/phroggingphrog/workspace/builder/jobwatch-agentic`, branch phase/01-agentic-career-ops rather than project default production checkout.

Engineer 30867a67-aaa2-4c4f-b14d-ff8998d29739: one issue per plan.
- Wave 1: Build 01-01.
- Wave 2: Build 01-02 and 01-03, each blocked by 01-01.
- Wave 3: Build 01-04 and 01-05, each blocked by both wave-2 issues.
- Wave 4: Build 01-06, blocked by both wave-3 issues.
- Wave 5: Build 01-07 and 01-08, each blocked by 01-06.
- QA 8f5080b3-be8e-46ab-8b0b-3d28fa339e47: Verify 01 offline, blocked by every Build. Full suite, synthetic board/browser walkthrough, actual synthetic PDF verification, adversarial acceptance and Staff code-review child. Write 01-VERIFICATION.md with offline results and explicit pending live checks; never claim whole phase complete.
- Release 8f3d9002-cc8f-44e2-9bcf-299cc9b7ca4f: Ship 01 cutover, blocked by offline Verify. PR if remote exists; request_board_approval for exact merge/restart/config enablement/backlog snapshot and bounded live batches. No live operation on planning approval. Record approved operation scope and rollback. This is cutover only: do not archive phase while real acceptance remains pending.
- QA: Verify 01 live acceptance, blocked by Release cutover. Read-only >=20 qualifying real packages, per-job evaluation/review/verify_pdf/current hash checks, HTTP 200 at 127.0.0.1:8960 plus actual board walkthrough including holds, unknowns and ready PDFs. Write 01-LIVE-VERIFICATION.md and update main verification table. If fewer qualify, exact shortfall and a real assigned correction/collection follow-up, no relaxed gates or parent completion. No form typing; T19 separately unbuilt.
- Release: Ship 01 finalize, blocked by live QA. TRACK section 0, existing local todo, ~/brain/WHAT-HAPPENED.md with undo; archive phase, learnings and roadmap only after full phase acceptance. Preserve personal data exclusively on host; no evidence document with candidate data in git/issues.

BUI-196 remains incomplete: neither planning nor handoff establishes live acceptance/finalization. The owner takeover supersedes the earlier requirement for BUI-210 to instantiate this issue graph. BUI-210's revised artifact incorporates BUI-216 findings (typed task structure and shared budget wire contract); Staff closing review findings remain Codex handoff evidence, not permission to dispatch implementation issues. No automatic Build/Release handoff is authorized.

## Verification ownership
Build proves local unit slices, QA proves integrated code and board offline, Release owns authorized mutations, live QA proves actual >=20 outcome, Release finalizes durable records. This explicit offline/live split avoids a Verify→Ship deadlock: live proof cannot precede authorized cutover, and cutover cannot precede offline checks. Neither offline Verify nor cutover alone satisfies BUI-196.
