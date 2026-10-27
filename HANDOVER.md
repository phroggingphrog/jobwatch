# JobWatch discovery reliability — 2026-10-27

Owner-approved plan: visible failures, reliable assessment and one confirmed profile.
Policy: report the first actual assessment failure and pause that posting; continue unrelated work. Retry only on an explicit typed request. Keep existing daily spending limits. Show incidents in JobWatch/MCP and attempt Hermes handoff immediately. Telegram relay is a design TODO only.

## Current deployment and prior work

- Native runtime: `/home/phroggingphrog/apps/jobwatch-native`, main `05cf019`; native agent18914, legacy MCP18918, native collector/reader timers.
- Published MCP: `/home/phroggingphrog/projects/.worktrees/jobwatch-native-mcp-use`, branch jobwatch-mcp-use `8096035`; connector18940 and MCP18942. Preserve the branch differences when deploying common fixes.
- Cloudflare OAuth: enabled loopback/localhost callback registration and verified login; endpoint remains authenticated through Cloudflare Access.
- Invocation budget: `030d0bb` made direct dispatch use configured limits;37 focused checks and live continuation verified.
- Superseded UI approach: `39a1ecc`, `0ffc654`, `7978075` added profile approval views. These were superseded by direct typed onboarding operations (`1d28cad`, `f5eceed`), with the coordinating assistant handling real user consent;38 focused checks passed.
- Profile: one active confirmed version3. Version2 confirmed the reviewed onboarding; version3 enabled archived writing references with all prior facts and scope preserved. Earlier versions are history, not separate active profiles.
- Archive:62 career-library files hash-verified,130 readable career facts,6 templates,7 style analyses,6 anonymised/layout references,2 letter examples. Source manifest lists10 unavailable entries and1 deliberately excluded source; never claim those recovered.
- Reference activation: MCP `cef5ba2`/`8096035`, native `5d0927f`/`05cf019`;15 focused tests on each branch. References are style/form only and cannot override current facts or preferences.

## Observed failure and scope of this change

Collector exceeded15-minute systemd deadline. Reader assessed1 posting, held it, then deferred19 at batch deadline. Timers retry periodically; deadline failures are absent from error alerts, and legacy Error rows are hidden from normal Chat. Expired checkpoints can be discarded. Unstarted deferrals must stay distinct from actual failures.

Implementation, focused verification, deployment evidence and rollback will be appended here and on TASK-279 / GitHub issue28. No drafting or submission during verification.

## TODO: notification relay design

Telegram first, with future transports using typed failure/completion/action-required events. Design per-person account linking/revocation, private credentials, durable delivery/backoff, deduplication/receipts, and optional interactive actions through authenticated JobWatch APIs. Do not create a bot or enable Telegram messaging in this change.

## Rollback plan

Keep source commits and service configuration backups. Revert only this task's commits independently in native and MCP checkouts; restore unit drop-ins and reload systemd. Preserve incident/history data and confirmed profile versions. Check active work before restarting services.

## Implementation and focused verification (2026-10-27)

Common commits:75967ce durable incidents; b9f7d89 bounded handoff and proven successful phases;1bcf2b0 shared phase deadlines/transport bounds/paused assessment queue; cdb396c cancellation propagation;6c86489 historical failure reconciliation;6a45e42 owner-only legacy Hermes route;36df70a CLI integration, failed registry state and API service-exit hook. Typed discovery queue/status/start/retry and shared-shell status page follow in the next source commit. Retry executes evaluation only, checks current profile/ad/config identity twice, and retains historical charges/checkpoints. No chatbot or application drafting is involved.

Agent checks:265 runtime/transport/extras/collector/adtext cases;13 focused timing/checkpoint cases;30 incident/notification cases;12 final CLI/shutdown cases. Protocol checks:16 passed (1 existing optional browser test skipped), TypeScript typecheck/build passed;5 connector auth/schema/person-context cases passed. Final combined regression run is in progress. UI reuses existing shell colors/type/spacing; sections distinguish paused incidents from recent invocation state; refresh is read-only. Design dials1/1/1 match the operational page and existing layout.

Live preflight: confirmed profile remainsv3;7240 postings and7 attempted assessments/1948988 charged tokens observed. No active API queued/running run. Existing fast collector was allowed to finish (success); all three timers temporarily stopped for rollout. Native settings lacked both Hermes route keys despite old install having them. Read-only SSH verified existing handoff directory writable; restored only existing two keys to native settings. Configuration and unit drop-in backup: `/home/phroggingphrog/backups/jobwatch/20261027-145400-discovery-reliability`. Restore `settings.env` from there to undo route repair. Do not log values.

Separate relay design card: TASK-345 (To Do), `/home/phroggingphrog/projects/backlog/backlog/tasks/task-345 - JobWatch-design-Telegram-capable-notification-relay.md`; no bot or Telegram outbound messaging enabled.

### Final source checks before rollout

Native combined regression:133 passed in378.02s (one pre-existing WeasyPrint HarfBuzz deprecation warning). Reviewed retry receipt/setup corrections:d2cbf2b/a435269; stable concurrency regression:a8becb6. Focused latest native integration17 passed. MCP branch after common cherry-picks:41 Python integration cases passed in32.62s; TypeScript typecheck/build and16 protocol cases passed (one optional browser case skipped). Manual Chromium synthetic UI verification:375/768/1440 widths, no overflow, real refresh navigation, focusable keyboard target, theme toggle; screenshots inspected. Existing shell reused without new colors/fonts/layout system. UI gate PASS: real controls and empty/error states; shared navigation/focus/theme behavior checked; no fabricated claims, decorative assets or new dependencies. No live candidate fixtures.
