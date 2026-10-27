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

## Deployment stage (2026-10-27)

Native main fast-forwarded05cf019 ->4068886; MCP branch fast-forwarded8096035 ->6dc2551 (typed MCP dd837f3 plus common cherry-picks; no branch reset). Native/MCP implementation worktrees remain fix/discovery-failure-reporting and fix/discovery-mcp-operations. Published MCP rebuilt successfully in serving checkout with synthetic build configuration; service environment supplies actual runtime configuration.

Installed `50-discovery-reliability.conf` for agent/fast/slow/reader under user systemd configuration, then daemon-reloaded. Fast/slow ExecStart verified `--collect-only`; reader alone assesses. All four have ExecStopPost failure reconciliation. Timers were stopped without killing active work; last preflight verified all collector/reader units inactive and API queue empty. Restarted agent/native-web/connector/MCP/legacy-MCP. Agent `/health`200, web `/healthz`200; connector protocol authenticated operations respond (it has no `/health` route;404 is expected there). Live discovery page303 requires normal sign-in; authenticated MCP status succeeds. Profilev3 and scope SHA256 exactly match pre-deployment snapshot.

Live MCP advertises discovery_status/start_discovery/retry_assessment, with no chatbot relay. Historical unresolved job286 deadline_exceeded is now durably paused and Hermes handoff succeeded exactly once (handed_off means SSH acceptance only). Bounded live start admitted run033433f938de469a91576686ba2dc0c7 through actual MCP; no documents or applications requested. Acceptance outcome pending. At admission existing usage was12 attempts/1970208 charged tokens against unchanged40/2000000 daily limits.

Undo: check active work; stop only the three timers; revert this task's source commits in reverse order on their own native/MCP branches (or create rollback branches from original05cf019/8096035 preserving branch-specific history), rebuild MCP and restart idle services. Remove only four new50-discovery-reliability.conf files; existing40-sqlite-runtime.conf backups are retained. Restore backed-up native settings.env, daemon-reload, restore original active timers. Preserve candidate profile/archive, incident rows, checkpoints and spend records. Never reset spending or confirmed data for rollback.

### Explicit unavailable archive inventory

Source: local source-import `20261023T164432Z/extracted/MANIFEST.json`, `missing_registry_sources` (10). These original sources remain unavailable; corresponding current derived/confirmed material is not evidence that these originals were recovered:

| Registry document | Missing archive-relative source |
| --- | --- |
| profile_yaml | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/profile.yaml |
| master_resume_md | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/master_resume.md |
| skills_taxonomy_yaml | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/transferable_skills_taxonomy.yaml |
| career_ops_md | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/career_ops_profile.md |
| search_profile_yaml | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/search_profile.yaml |
| interests_yaml | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/interests_and_criteria.yaml |
| voice_dna_md | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/voice_dna.md |
| profile_readme_md | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/README.md |
| schema_json | archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile/schema.json |
| tracker_db | archive/job-data-20261004/tracker.db |

The separate excluded registry entry `letter_loe_2023_excluded` remains deliberately excluded. Live reference recheck after rollout:19 style/template references,2 letter examples,130 readable career facts,0 failed active style reads. Active canonical profilev3 remains the single confirmed profile, with previous versions retained as history.

### Acceptance follow-up corrections

Source review of real runtime codes found per-job token/attempt limits were omitted from incident classification. bedc63a fixes that distinction; daily/invocation allowance exhaustion stays a normal deferral.45 focused native checks and50 MCP incident/idempotency/connector checks passed. Deployment waits for current bounded work to settle. The live run also showed finished daily-budget/ad-refresh rows being counted as assessed; a focused correction is being verified to retain all charged spending while reporting those as deferrals.

Acceptance follow-up source checks:890a85f excludes normal daily-budget and ad-refresh rows from assessment counts without changing token totals; refreshes the second pass outcome before deciding whether to stop the batch; budget refusals now defer current and remaining jobs without inflating processed/held.14 focused native cases passed;29 MCP integration/deadline/shutdown/UI cases passed after cherry-pick. MCP incident follow-up50 cases passed. Actual first live invocation remains bounded600s and is allowed to finish before service restart. As of380s, paused286 had zero new activity; charged token total stayed1970208. This run exposed the reporting issue rather than producing a new completed assessment, because model reservations exceed the remaining daily allowance. No limit increase, spending reset or application action.
