# Executing the remaining backend roadmap

The owner-approved [remaining-roadmap plan](2026-10-23-finish-backend-roadmap.md)
supersedes older launch prompts and conflicting phase-plan assumptions. Reuse the
repository setup and work locally on `codex/` branches; the owner explicitly
rejected running another setup workflow for this repository.

## Release order

| Release | State | Tracker |
|---|---|---|
| Phases 1–5 | Merged | Historical phase reports remain unchanged. |
| Browser reliability | Merged in PR #23; full local suite passed | #17 closed. |
| Phase 6 feedback and selected preparation | Implementation and release verification | #21. |
| Phase 7 evaluation and monitoring | Starts after Phase 6 merges | #22. |

The browser [verification report](../../audits/2026-10-23-browser-popup.md)
records 3655 passed, 11 skipped and the independent review. The earlier Phase 5
report preserves its original failed run; do not rewrite historical evidence.

## Ownership and checks

The parent owns shared migrations, native API/chat integration and release-suite
runs. Sol 6.1 implements assigned isolated components and independently reviews
each release. LUNA drafts documentation that the parent verifies against source.
Dependent work runs sequentially; delegation uses disjoint file ownership.

Use invented fixtures and synthetic transports. Keep development checks focused;
run the full local suite on stable release source and the existing real synthetic
R/JAGS checks without loosening thresholds. Record actual commands, results,
review dispositions, remaining limitations and source rollback instructions.

Required local checks and independent review determine completion. Hosted CI is
disabled and optional for every repository PR; never enable it or wait for it as
a merge gate. The owner authorized merging each reviewed release after local
checks pass, then continuing from updated main. A merge is a source operation,
not deployment or proof of real recommendation quality.

## Boundaries and finish

Keep candidate files, credentials, private databases, reports and generated
packages outside Git. Do not activate services/timers, deploy, migrate live human
choices, fit live models, run paid replay, contact employers or submit applications
as a side effect. Final Submit retains its separately confirmed canonical path.

The roadmap finishes after all three remaining releases are reviewed and merged,
required checks pass, and confirmed profile through selected package retrieval
works through native API/chat. Blind quality study and live operations remain
separate. Revert source for rollback while preserving approved versions, feedback,
genuine choices, fits, selections, packages and evaluation records.
