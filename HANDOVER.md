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

## Final rollout and acceptance (2026-10-27)

Final runtime code: native1c31a8f (main), MCPb76efdc (jobwatch-mcp-use). Their implementation branches retain all task commits; later documentation-only fast-forwards do not require process restart. Follow-up Python changes were deployed only after the first API run completed and the queue was empty. Agent/connector/web/legacy MCP/MCP services restarted successfully; all five active, agent `/health`200 and web `/healthz`200. Profilev3/scope hashes match the pre-rollout snapshot exactly. Only the two restored Hermes settings differ from the config backup. The final status page distinguishes attempted assessments, completed request execution and ordinary deferrals;3 focused web checks passed.

All three original timers restored. They triggered the real fast collector and reader: collector publishes durable postings (7240 ->7245 observed) with `--collect-only`; reader checked8 advertisements in90.105s, then returned `skipped:busy` because the API pass held the same person review lock. No system-error incident for lock contention. No paused posting received new activity after follow-up rollout (10 paused postings checked).

Actual MCP verification, no application operations:

- First bounded run033433f938de469a91576686ba2dc0c7 completed in about478.5s, no model calls/extra charge. Phase seconds:ingestion98.163, deduplication10.428, screening0.033, ordering26.866, assessment334.254, shortlist5.239. It exposed budget deferrals being labelled held and repeatedly attempting the remaining queue; corrected by890a85f, rather than treating those as successful assessments.
- Final bounded run3b405e180d574dfdb920ba5ce3190f71 completed normally:0 processed/held/ready,20 ordinary daily_budget deferrals,0 model calls,0 charged/spent tokens. Phase seconds:ingestion91.713, deduplication41.014, screening0.293, ordering28.479, assessment10.615, shortlist7.288. Current allowance29792 tokens cannot fund the required model reservation; daily cap remains2000000 and assessment cap40. Historical charged total1970208 retained exactly; assessment-attempt count11 excludes unstarted budget/ad-refresh rows, retaining prior real work/failures.
- Replayed the same final start request ID through MCP: returned the same completed run, no new queue entry. API queue empty at final check.
-10 historical real failures reconciled into paused incidents (deadline/token/turn limits), visible through actual MCP and authenticated JobWatch page. Zero new activity on those paused postings in both the live pass and restored scheduled reader. At final notification snapshot5 handed_off and5 pending, max1 handoff attempt per incident. Pending historical delivery is independent and drains on subsequent scheduled invocations; no assessment retry. No claim that SSH handoff proves end-user receipt.

Verification limit: no new completed job assessment or shortlist was produced because the remaining daily allowance is insufficient. This is explicitly reported as a normal deferral, not a system failure or a successful assessment. Actual prior failures are now visible and paused. Keep next-day work within the same confirmed daily policy; retry a paused posting only on a new explicit selected retry request. There were no application drafts or submissions.

Source checks:133-case native baseline passed before follow-up corrections; affected follow-ups passed45 native incident cases,14 native allowance/deadline cases,50 MCP incident/idempotency/connector cases,29 MCP integration/deadline/shutdown/UI cases and final3 web cases. Earlier41-case MCP integration,16 protocol checks (one optional browser test skipped), TypeScript typecheck/build and deployment rebuild passed. Only pre-existing warning was WeasyPrint HarfBuzz deprecation. Review found and fixed idempotent receipt replay and retry setup re-pausing before rollout. Rollback details and backups above remain valid.

TASK-279 and issue28 record implementation/rollout; TASK-345 remains the separate Telegram relay design TODO. No Telegram bot or outbound channel was enabled. Unavailable archive inventory above remains explicit; no originals were fabricated.

Final compatibility check after allowance correction: existing service daily-cap/lowered-ceiling/empty-batch cases4 passed (77 deselected) in10.50s. Documentation is also recorded in project hub HANDOVER, TASK-279 final summary and issue28 final rollout comment. Source implementation worktrees are clean; no dependency packages were added; temporary synthetic preview server and implementation dependency symlink removed. Original standing timers remain active.

## Continuation investigation (2026-10-27, user: “can you fix it and implement everything alive and continue the job”)

Reused isolated recovery/MCP worktrees; baseline nativee9c8712/MCP49a7887. Current native/MCP services and timers are live, collection continues (7279 postings observed); remaining owner daily allowance29792, charged1970208/2000000. No evidence that historical spending was double-counted. Prior work fixed failure visibility and scheduling but could not produce a completed assessment within the remaining confirmed allowance. Keep that allowance unless the owner explicitly changes it; a text question requests the new daily limit if continuation today is desired.

Concrete additional defect: checkpoint for daily-budget-deferred posting1604 has no reservations,0 job charge,0 role turns, but failed_attempts1. DeepAgents' outer error handler calls execution.fail for invocation_budget_exhausted even though reserve refused before dispatch; service then maps it to normaldaily_budget. Repeated ordinary deferrals can thus become failed_attempt_limit. Cancellation takes the same incorrect counter path. Fix those classifications at the existing role boundary, preserving counters for genuine model errors and all spending. Existing approved checkpoint/spending test requirements cover the regression seam. Also investigate daily remaining allowance being persisted as a permanent batch ceiling despite the independent invocation daily guard; no arbitrary token-estimate/output-cap relaxation.

Owner budget instruction received during this continuation: “yeah i dont mind set the confirmed daily limit into unlimited and this should be into configuration settings for user”. This explicitly supersedes the prior daily token cap for this person. Implement per-user `config/discovery.json` with JSONnull meaningUnlimited, accessible through native authenticated settings, typed MCP get/set and Preferences. Preserve confirmed profile facts/history and historical spending; keep existing per-job/per-run limits,40 daily assessment allowance and first-failure pause. Other accounts keep their own saved/default limits. No Telegram activation/application operations implied.

Additional measured duplicate work:7 candidate artifacts share exactly1 candidate-assessment identity; all7 match the CURRENT evidence/policy/model hash. Read-only validated reuse probe succeeded. ba4b447 adds bounded same-person, hash/schema/citation-validated persisted candidate reuse across batches, rejecting stale/corrupt artifacts; job-specific evaluation still runs independently. Red regression reproduced duplicate re-analysis;20 focused tests passed after correction and90 broader relevant checks passed (2 chat-upload cases deselected in that run). Follow-up nativevenv check of those2 plus quota/cancel/modelerror cases:5 passed; earlier two failures came from an incorrect old-install virtualenv and are not attributed to baseline. d0c7c89 prevents quota/cancel from consuming failed-attempt budget;97841be keeps configured batch ceilings independent of daily remainder. No past charges reset.

### Continuation implementation verified

Native commits:d0c7c89 quota/cancel counters;97841be configured batch ceilings;ba4b447 same-person validated candidate reuse;ad0c344 Preferences setting;d43eb4e per-user nullable daily-token configuration/effective scope;5654aef authenticated native settings routes/readable Unlimited copy;b5f3dd1 re-admits only unstarted ordinary quota deferrals to a fresh configured batch. The latter was proven red (new invocation still token_limit under old tiny allocation) then green, retaining the old batch charge and all artifacts. Partially spent checkpoints and paused actual failures are not automatically cleared.

Checks before deployment:90 relevant native checks passed (two separately checked native upload cases excluded there);32 settings/API/allowance/web cases passed;36 final settings/resume/checkpoint/reuse cases passed. MCP integration after common cherry-picks60 passed, TypeScript typecheck/build and17 protocol tests passed (one optional browser test skipped). Preferences/native prior suite14 passed. Browser verified Unlimited ->321 finite ->Unlimited saves against isolated synthetic DB;375/768/1440 widths, no overflow, radio keyboard focus, screenshots inspected. UI gate PASS: existing shell/type/colors/spacing, labelled working controls, safe error state, actual form roundtrip, no new dependencies. Design remains calm operational1/1/1.

Unlimited is JSONnull in the person's config/discovery.json, not an infinite floating-point value or a reset of historical charges. Confirmed profile/history stays unchanged and is validated before applying the operational override. Native GET/POST `/api/agent/discovery/settings`, MCP get_discovery_settings/set_discovery_settings and Preferences share the same store. Invalid/foreign identity fields and malformed limits are refused. Retry contexts include effective settings, so changing the budget after enqueue requires a current retry context. Daily40 assessment count and configured job/run ceilings remain active. User explicitly authorized Unlimited for daily tokens only.

### Live Unlimited deployment and continuation

Native main fast-forwardede9c8712 ->e8e28bf; MCP branch49a7887 ->b661b5e, preserving branch differences. All-person API queues checkedempty and reader inactive before deployment; only reader timer temporarily stopped. Public-only collector allowed to finish independently. Restarted native agent/web/legacy MCP/connector, rebuilt and restarted published MCP; all five active, native/web health200. Deployment build passed; final MCP focused compatibility19 cases passed after the last checkpoint fix. Reader timer restored after starting the API pass; all original timers remain enabled.

Actual MCP list now19 tools, including get_discovery_settings/set_discovery_settings. User-authorized setting saved through typed MCP as daily_token_ceiling:null; independent get and discovery_status verify Unlimited,40 daily assessment cap and1970208 prior charged tokens retained. Original config/discovery.json did not exist; absence recorded in the original designated backup directory as owner-discovery-before-unlimited-state.json. Original confirmed profilev3 SHA matches exactly; only effective operational scope changed as authorized, not the archived confirmed scope/history or profile files.

Started actual bounded discovery runfcab66ee64b0408a82e9758141e0c6ad (idempotency key owner-approved-unlimited-live-20261027-1). It assesses ordinary queued postings, not the10 paused historical failures. No application work requested. Outcome pending; continue until actual assessment output or an explicitly visible real failure, within configured job/run deadlines and token ceilings.

Undo this continuation: stop only the reader timer while inspecting active work; revert task continuation commits separately on native/MCP branches to pre-continuatione9c8712/49a7887, rebuild MCP and restart affected idle services. Restoring no per-user override returns the previously confirmed2M cap; do that only as an explicit configuration rollback, preserving all new/historical spend and artifacts. Never clear paused failures or the approved profile as rollback. Original reliability service drop-ins and Hermes route remain in place. Telegram design TASK-345 remains design-only.
