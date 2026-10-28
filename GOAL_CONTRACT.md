# Goal contract: jobwatch

Owner-controlled. Workers (OpenHands, Paperclip agents, Claude Code) read it and must not edit it.
To propose a change, write `PROPOSED_CONTRACT_CHANGE.md` in your workspace and say so on the issue.
Derived 2026-10-08 from `TRACK.md` (sections 0 to 2), the owner's career decisions (2026-10-05, reconfirmed
2026-10-07), the owner's "jobwatch is automated career-ops" direction (2026-10-06), and the Codeg jobwatch-builder
brief (2026-10-08). Where those disagree, the owner's newest statement wins.

## Objective

jobwatch is the owner's **automated career-ops** system, not a small keyword watcher:
discover new Melbourne/Victoria openings early, have an AI read the **whole** ad and judge it against the owner's
real profile, show the result on a personal Seek-style web board, then help apply (tailored CV and letter, filled
application form, tracker, follow-ups). The owner always clicks Submit.

## Requested capabilities (the full scope; do not shrink it)

1. Collectors across job boards, ATSs and employer sites, with dedupe and health status per source.
2. AI evaluation of every candidate ad: 1-5 score, archetype, requirement-to-CV match, work-authorisation and
   legitimacy checks, using `~/brain/data/jobwatch/profile/career_ops_profile.md` and the CV. Keyword matching is only
   the first cheap list, never the decision.
3. Owner targets outrank the CV profile: accounting/tax/audit (including graduate, vacation, cadet and internship
   programs); accounts/finance clerical (AP, AR, payroll, bookkeeping); back-office admin and data entry in
   accounting, legal, health, government or council settings; early-career data, business or finance analyst;
   graduate/trainee/vacation programs in business, finance, operations and analytics.
   NOT targets: customer service, hospitality, retail or shop floor.
4. Hard gates: no roles needing citizenship/PR, clearance or unrestricted work rights; no sponsored-only ads;
   Melbourne (or remote) only; entry level; part-time/casual about 24 h/week, except vacation, internship and
   graduate programs, which are wanted even when full-time.
5. Web board (`jobs.phroggingphrog.com`, behind Cloudflare Access): Board, Table, Job, Applications, Inbox, Sources,
   Insights. It is the only alert channel (Matrix was removed).
6. Apply layer: tailored CV and cover letter per job, a reviewer chain, PDF verification, automatic drafts for jobs
   scoring 4.0+ (T28).
7. Form filling (T19, BUI-93): open the application page, fill every field from the answers file, attach CV and
   letter, and **stop before Submit**.
8. Outcome sync and callback statistics, plus the not-target sorting of hidden jobs.

## Acceptance checks

- Progress gate (owner 2026-10-11, "too many test without implementation"): every work batch ends with something the
  owner can see on the live board (or a preview link), or a plain "blocked on X" note. Ship before you verify more.
- Release gate: `.venv/bin/python -m pytest -q` exits 0 once per release, not after every fix. One focused test per change.
- No new harness, replay, ledger or checksum files unless the owner asks by name. At most 3 paid test runs per approval.
- If no vacancy passes evaluation, show the held reasons on the board and stop. Do not tune gates to force a pass.
- The user-visible result is checked for real: a board page loads (`jobwatch-web`, 127.0.0.1:8960, HTTP 200), a real
  draft passes `verify_pdf`, a real form is filled up to (not including) Submit, shown with a screenshot.
- Each issue's own "Done =" condition is met; otherwise the issue is not done.
- Every report states "What still doesn't work", and `TRACK.md` section 0 is kept current.

## Constraints

- Never submit an application, click a final Submit/Apply button, message employers or third parties, or move money.
- Never print, log or commit personal data, secrets, `.env` files, the answers file or the CV.
- No guessed personal values: if the owner must supply something, create an empty template and say so on the issue.
- Model calls only via OmniRoute paid routes (`openai/`, `claude/`, `google/`); no free or stealth routes for
  candidate data.
- Data stays on PhrogVPS: `~/brain/data/jobwatch/` (SQLite DB, `ledger/*.jsonl` canonical for apply tables).
- Smallest change that works; read code before changing it; do not touch Paperclip agents or other projects.
- Log every change in `~/brain/WHAT-HAPPENED.md` with how to undo it.
