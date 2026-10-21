# Executing the roadmap phases with agents

This file is for an executor agent (or the person launching one) running one phase of the
[backend roadmap](2026-10-21-backend-roadmap.md) unattended in a cloud session. Each phase has a
self-contained implementation plan in this folder. The spec every plan argues from is
[the agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md).

## Phases

| Phase | Roadmap plan | Plan file | Starts when |
|---|---|---|---|
| 1 | 1 (with 0) Profile intake and approval | [2026-10-21-plan-1-profile-intake.md](2026-10-21-plan-1-profile-intake.md) | done |
| 2 | 6a Frozen baseline | `2026-10-21-plan-6a-frozen-baseline.md` | Phase 1 merged |
| 3 | 2 Decision policy from the profile | `2026-10-21-plan-2-decision-policy.md` | Phase 2 merged |
| 4 | 3 Field and job discovery | `2026-10-21-plan-3-discovery.md` | Phase 3 merged |
| 5 | 4 Ranking and explained shortlist | `2026-10-21-plan-4-ranking-shortlist.md` | Phase 4 merged |
| 6 | 5 Feedback and selection | `2026-10-21-plan-5-feedback-selection.md` | Phase 5 merged |
| 7 | 6b Evaluation and monitoring | `2026-10-21-plan-6b-evaluation.md` | Phase 6 merged |

Run one phase per session, in order. A phase starts from `main` only after the previous phase's pull
request is merged; check `git log origin/main` for that phase's merge before starting.

## Launch prompt

Paste this into a new Claude Code cloud session on `phroggingphrog/jobwatch` (replace `N` and the plan
file). It is complete on its own; the session needs nothing from earlier conversations.

```text
Execute Phase N of the Jobwatch roadmap. Read docs/superpowers/plans/EXECUTING.md, then the plan
docs/superpowers/plans/<plan file>, its spec, AGENTS.md and INTENT.md. Follow EXECUTING.md exactly:
use superpowers:subagent-driven-development with Sonnet subagents, work on branch
claude/phase-N-<slug> from current main, run the full suite, push, open a pull request and watch it.
Do not merge, deploy, activate services or timers, submit applications or contact anyone.
```

## Rules for the executor

1. **Preconditions.** Confirm the previous phase is merged into `main` and the plan file exists. If
   not, stop and report which precondition failed.
2. **Branch.** `git fetch origin main && git checkout -B claude/phase-N-<slug> origin/main`.
3. **Environment.** Python 3.12 virtualenv outside the repo:
   `uv venv --python 3.12 <scratch>/venv && uv pip install --python <scratch>/venv/bin/python -e '.[dev]'`.
   Chromium is preinstalled at `/opt/pw-browsers`; keep Playwright pinned as in `pyproject.toml`, never
   run `playwright install`. Test command: `<venv>/bin/python -m pytest -q -p no:cacheprovider`.
   The full suite takes about 20 minutes.
4. **Method.** Use superpowers:subagent-driven-development: one Sonnet implementer per task, a Sonnet
   task reviewer after each, scoped re-review after fixes, a final whole-branch review, one fix
   dispatch. Keep the ledger in `.superpowers/sdd/<plan>/progress.md` (git-ignored). The owner asked
   for Sonnet subagents; do not use a more expensive model unless a fix round escalates.
5. **Rulings, not stalls.** Decide ambiguities against the spec and record each as
   `Ruling: <decision> — <why> — <cost if wrong>` in the ledger; copy the list into the PR body.
6. **Stop and ask the owner only for:** an irreversible or destructive operation, a security-sensitive
   action, any outward action other than pushing the phase branch and opening its PR, or a plan so
   broken that every path is a guess.
7. **Never:** merge to `main`, deploy, enable/start services or timers, change live candidate data,
   use live candidate records as fixtures, send candidate data to unapproved model routes or hosted
   tracing, submit applications except through `jobwatch/apply/submit_confirm.py`, contact employers,
   or count model output as a person's choice or approval.
8. **Finish.** Full suite green (or each failure shown to be pre-existing on `main`, with evidence);
   push; open the PR with: summary, the checks run and their exact results, rulings, remaining
   limitations, what is unverified, and undo instructions (revert the merge commit; list any data
   folders or tables the phase creates and how to remove them). Subscribe to the PR and fix CI or
   review comments. GitHub Actions in this repository have not been starting; say so in the PR if
   checks stay queued, and rely on the local full-suite result.
9. **Report.** End with the PR link, the full-suite line, and anything the owner must decide.

## Automating the sequence

Each phase needs the previous one merged, and merging is the owner's decision, so phases are
launched one at a time:

- **Manual:** after merging phase N's PR, open a new cloud session and paste the launch prompt for
  phase N+1.
- **Scheduled:** a scheduled task that runs the launch prompt once a day; the executor stops at
  rule 1 if the previous phase is not merged yet, so an early run costs one short session. Set it up
  only when the owner asks for it.
