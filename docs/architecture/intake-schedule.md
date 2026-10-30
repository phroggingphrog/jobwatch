# Intake schedule design

**Status:** Proposed design. This document changes no runtime behavior.

## Goals and verified baseline

The target workflow is:

1. On day 1, collect broadly from every enabled source. Collection uses HTTP and deterministic parsing only. It makes no model calls.
2. After day 1, assess 25 to 50 new postings per day, subject to the daily token budget.
3. Check known active postings each day for liveness. Do not use a model for this check.

The production database was opened read-only at `/home/phroggingphrog/.local/share/jobwatch-native/jobwatch.db`. The command loaded `~/.config/jobwatch-native/agent.env` first and used the SQLite library path supplied for the live environment. It did not access the checkout database.

| Fact | Result |
|---|---:|
| Postings in `postings` | 9,923 |
| Without a row in legacy `ad_reviews` | 9,923 |
| Without a canonical `matches` row | 5,844 |
| Without canonical assessment and with saved `ad_text` | 1 |
| Without canonical assessment and without saved `ad_text` | 5,843 |
| Source rows | 22 source names |
| Example latest run | Run 191, fast tier, 5m 51s; 18 collectors, including ATS, RSS, Reddit |

**Count mismatch:** the requested figure of 4,807 unassessed postings is not current in this database. This schema has no direct `assessed` state. The best available canonical proxy is 5,844 postings without `matches`; it includes any other pipeline states. Legacy `ad_reviews` is empty for all 9,923 postings and is not a valid assessment count for this runtime. The 4,807 figure cannot be verified from the current database.

**Unavailable database facts:** the requested 512,935-token evaluator budget for posting 7621 was not present in the database schema or rows inspected. The current `agentic_runs` table did not contain that run. I could not verify this figure from the live database. The 182,901-token posting cost and 2,000,000 daily limit are supplied task facts. Code currently configures a 2,000,000 batch-token ceiling; the confirmed person's daily ceiling can differ. Treat those task figures as design inputs, not as a fresh database measurement.

## 1. Day-1 bulk discovery

### Collection, deduplication, and storage

Use the existing collector registry and a source-independent contract. Each source adapter returns normalized posting records and a source cursor. The contract must accept ATS, HTML/API, GradConnection, RSS/Atom, and future kinds. RSS records must preserve feed GUID and canonical item URL. Source-specific requests, parsing, retries, and rate limits remain inside adapters.

Collection makes HTTP requests and deterministic parsing only. It must not invoke an embedding model, classifier, candidate digest, or evaluator. Store each normalized record through the canonical posting persistence path. Keep raw source payload only where existing retention rules permit. Record `source`, `source_id`, canonical URL, title, employer, location, work type, posted time, closing time, first-seen time, last-seen time, and the source-specific cursor. Preserve every source sighting separately.

Deduplicate in this order:

1. Exact canonical URL hash.
2. Exact `(source, source_id)` identity.
3. Conservative normalized employer + title + location key within a configurable time window.
4. Optional similarity candidate detection for human or deterministic review only; never merge on uncertain similarity alone.

The existing `postings.url_hash` uniqueness and `dedupe_key` provide useful storage primitives. A source checkpoint records cursor, page/token position, last completed item, counts, and update time in the application database. Commit each page's postings and checkpoint in one transaction. A restart resumes after the last committed source page. A repeated page is safe because upserts and identities are idempotent.

### Resumable run and time limits

Run the bulk pass as a durable multi-invocation campaign. Store a campaign ID, source list and version, per-source cursor, status, attempt count, last error, record counts, and completion time. Each invocation processes one bounded page or source slice. It checkpoints each source before moving on. Failed sources retry with exponential backoff and do not block successful sources. Report partial completion rather than claiming all-source completion.

Respect source-specific rate limits and overall request/time ceilings. Reserve a hard deadline for every invocation. Collection has its own strict share of the fast unit budget. It cannot consume the assessment or liveness reservation. Keep the cursor and last committed page so timeout does not lose completed work.

The source interface and GradConnection/RSS work are reported as being developed in another session. This design assumes they will exist; their availability and API shape are not verified here.

## 2. Deterministic triage before assessment

Run cheap filters over normalized metadata and saved ad text. Do not call a model. Use the confirmed person's approved constraints, including target location, work type and role focus. Unknown or ambiguous values should be flagged, not rejected. Record rule version, inputs, decision, and reason so the result can be replayed.

Suggested order:

1. Remove exact duplicates and already assessed, applied, withdrawn, or expired records.
2. Reject out-of-region postings only when location evidence is explicit. Keep remote postings when the profile permits remote work.
3. Reject incompatible hours only when the posting explicitly states full-time-only or another known conflict. Treat unknown hours as neutral.
4. Use approved include/exclude keywords across title and employer. Apply hard exclusions only from confirmed profile policy. Use broad role families and aliases to avoid title-only false negatives.
5. Apply employer allow/deny lists only when the owner has approved the list. Do not infer employer quality.
6. Exclude expired application deadlines. Keep missing deadlines, with lower urgency.
7. Keep uncertain records in a reviewable hold; do not treat deterministic keyword absence as proof of mismatch.

### Real-count result and reduction estimate

The current database has 5,844 postings without `matches`, not 4,807. Only 1 of these has an `ad_text` row. Therefore, full-text keyword, hours, and deadline rules cannot currently be measured across this backlog. The database has 9,923 total postings, and source counts span 22 names. No current per-filter counts were computed, because the stored records do not provide a reliable common assessment or full-text state.

**Expected reduction estimate:** not verifiable from the live data available. Do not claim a numeric reduction until a read-only dry-run applies the proposed rules to the actual backlog and reports distinct counts after each filter. First measure location completeness, employment-type completeness, deadline completeness, and the owner-approved rule matches. Then set a target short-list size from observed results. This avoids inventing a reduction percentage.

## 3. Daily assessment quota and tokens

Expose a configurable daily assessment count from 25 to 50. The existing code already enforces a per-person daily assessment count and daily token ceiling, and it defers work when either limit is reached. The default target can be 25, with a setting up to 50. A run must stop before either budget is exceeded. Unfinished queue items remain queued for a later day.

Rank eligible queue items by a deterministic fit score, then closing-date urgency, then freshness. Fit uses explicit location, work type, target keywords, approved employer preferences, and known exclusion rules. Give higher rank to a closing date that is near but not past. Give newer postings priority within similar fit and urgency. Use stable posting ID as the final tie-breaker. Never use the eventual model score to rank work that has not yet been assessed.

At 182,901 tokens per posting, a 2,000,000-token daily limit allows **10 complete postings** (2,000,000 / 182,901 = 10.93; the eleventh exceeds the limit). Twenty-five postings at that rate need 4,572,525 tokens, or about **4.6 million**. Fifty postings need 9,145,050 tokens. To assess 25 postings within 2,000,000 tokens, average cost must be no more than **80,000 tokens per posting**. For 50 postings, the limit is 40,000 tokens each.

Proposed quality-preserving cost controls:

- Use a small first pass to extract essential facts and evidence citations. Send only uncertain or promising cases to the full evaluator. **Estimate:** 50–70% fewer full evaluator calls, subject to quality evaluation.
- Use a cheaper model only for deterministic-like triage suggestions, then confirm any consequential judgment with the canonical evaluator. **Estimate:** model price and token reduction depend on model and prompt tests; no cost saving is verified.
- Cache stable prompt parts when the provider supports prompt caching. **Estimate:** savings depend on cache-hit rate and provider billing; no cache rate is verified.
- Send shorter, cleaned posting text. Retain requirements, duties, eligibility, location, work type, and closing date. Drop navigation, repeated boilerplate, and unrelated page content. **Estimate:** 20–40% fewer input tokens; validate against unchanged-input assessment quality.
- Keep an input, output, cache, and retry token ledger by phase and posting. Reserve part of the daily allowance for retries and candidate context.

The 25–50 count is a target, not a guarantee. The runtime must report both quota slots and token-budget slots. It must never overspend tokens to meet the count.

## 4. Daily liveness and posting states

Current recovery behavior has a liveness phase before assessment or cached-package completion. `observe_posting` reads the public posting URL through structured/ATS or browser-backed readers. It verifies the posting identity and title. It returns `active`, `closed`, or `unknown`. An unavailable page or unverified identity is `unknown`, not evidence that the posting is active. A closed observation is archived. An active observation with changed ad text pauses further assessment as `snapshot_changed`. The current flow does not implement a separate daily, model-free sweep of all known active postings. The liveness observations are tied to recovery/assessment runs.

Propose a standalone daily HTTP liveness worker. It makes no model call. It uses source-native APIs where available, else bounded HTTP requests to the canonical detail URL. Handle signals as follows:

- HTTP 404 or 410: mark withdrawn only when the source response is stable and identity-bound. Retry transient or ambiguous responses before changing state.
- Redirect to a search page, board home page, or unrelated URL: treat as likely withdrawn only after checking the redirect target and source-specific rules.
- Page text such as “no longer available” or “applications closed”: mark expired or withdrawn according to source evidence. Store the matched phrase and response metadata.
- Closing date in the past: mark expired, unless the source confirms an extension or a future date.
- Absence from a source listing: do not mark withdrawn after one miss. Require a configurable number of successful complete listing scans, because pagination, feed truncation, and source filtering can hide an active posting.
- Network errors, 429, 5xx, blocked pages, or failed identity checks: keep the last known state and record `unknown` for this check.

Respect each source's published limits and `Retry-After`. Apply a global cap of **60 HTTP checks per invocation** and a per-host cap of **1 request per second** as initial design values. These are proposed values, not verified source limits. Use a persisted round-robin cursor and prioritize newer active postings, then postings nearing their deadline, then oldest last-check time. Set `N = 7 days` as an initial maximum interval; every active known posting must receive a successful or explicitly unknown check at least once within each 7-day rotation. Revisit `N` after measuring total inventory and source budgets.

Use these lifecycle states in the intake projection:

- `new`: collected, not yet triaged.
- `queued`: passed deterministic filters and awaits assessment.
- `assessed`: canonical assessment completed; preserve the assessment record.
- `applied`: an application was recorded; application state remains authoritative.
- `expired`: evidence shows the deadline passed or applications closed.
- `withdrawn`: the source removed the posting or confirmed it is unavailable.

State transitions must be append-only events or auditable updates. `expired` and `withdrawn` postings stop entering assessment queues. Keep assessed results and application history. An assessed posting that expires remains `assessed` with an expired liveness flag, or projects as `expired` while retaining its assessment. An applied posting that expires remains `applied`; add the liveness outcome without changing application history. Never delete evidence or imply that an application was withdrawn.

## 5. Scheduling and time budgets

Verified timer definitions and current status:

| Timer | Schedule and action | Current status |
|---|---|---|
| `jobwatch-native-fast` | Every 20 minutes, with up to 60 seconds jitter. Runs `jobwatch --user all run --tier fast --collect-only`. | Active and enabled when checked. |
| `jobwatch-native-slow` | Every 2 hours, with up to 15 minutes jitter. Runs `jobwatch --user all run --tier slow --collect-only`. | Active and enabled when checked. |
| `jobwatch-native-reader` | Every 15 minutes at minute 7, with up to 30 seconds jitter. Runs `jobwatch --user all read`. | Inactive and disabled when checked. |

A direct `systemctl --user list-timers` showed only fast and slow timers. The reader unit file exists but is disabled. The reader timer must not be activated as part of this design task.

Proposed run order:

1. The fast collector performs bounded source collection and liveness work. It checkpoints each source.
2. It stops collection when its reserved collection slice ends. The `--collect-only` service remains collection-only.
3. The reader/assessment worker processes liveness first for its rotation slice, then deterministic triage, then at most the daily count and token allowance of queued assessments.
4. The slow collector handles slow sources separately. It does not consume the assessment reservation.

For the 780-second fast unit budget, reserve **300 seconds for collection**, **240 seconds for liveness**, **210 seconds for assessment**, and **30 seconds for final checkpoint and reporting**. These are proposed budgets, not observed current splits. Use hard monotonic deadlines; terminate the current bounded page or posting before the phase deadline. Collection must not borrow unused assessment time. If deployment needs assessment in the same fast invocation, change the service contract explicitly; do not silently change `--collect-only`.

Issue #37 documents the current failure: collection can consume all 780 seconds and leave no assessment time. Issue #35 reports a collection run gap and requests monitoring. The current timers were active for fast and slow, but reader was stopped. Add a watchdog that checks each required timer's `ActiveState=active`, `UnitFileState=enabled`, and next trigger. Alert if a required timer is inactive, disabled, has no next trigger, or misses 2 expected windows. Check service completion timestamps separately; an active timer alone does not prove a successful run. Keep this check read-only and never auto-start a timer.

## 6. Failure handling and reporting

Send one sanitized alert-webhook report per run summary. Do not include candidate data, credentials, raw posting text, or secret URLs.

- Campaign start: campaign ID, sources due, backlog, run deadline, and configured quotas.
- Each source checkpoint: source name, pages/items fetched, new/updated/duplicate counts, cursor position, elapsed time, rate-limit wait, and source status.
- Triage: counts entering and leaving each deterministic rule, queued count, ambiguous count, and rule-set version.
- Assessment: selected count, completed/held count, charged tokens by phase, remaining daily tokens, retries, and reason for each deferred group.
- Liveness: checked count, active/closed/unknown counts, status codes grouped by class, next rotation due, and oldest unchecked age.
- Completion: overall complete/partial/failed state, last successful source, checkpoint, elapsed time, and next action.
- Timer watchdog: timer active/enabled status, next trigger, last service result, and missed windows.

Count a repeated error by a stable key `(step, source, error class, normalized reason)`, not by changing request IDs. Increment only after a failed attempt. Reset the consecutive count after a successful source step. Report first failure in run summary; notify on the first occurrence, then on 3 consecutive occurrences and each 10 additional consecutive failures. Persist the count and last alert time so restarts do not reset it. Do not count expected `429` waits as hard failures when the source recovers within its retry policy.

The current database has `source_health.consecutive_failures` and `alerted` for collector health. It also has agentic incidents and notification attempt fields. Exact production webhook routing and threshold behavior were not verified in this read-only investigation. Treat the alert delivery mapping and thresholds above as proposals.

## 7. Incremental implementation plan

Each step should be a small, independent pull request. This document does not authorize implementation or runtime activation.

1. **Measure and define states.** Add a read-only backlog report for exact counts, missing-field completeness, and duplicate candidates. Define projection and transition invariants without changing live rows. Test reports against a synthetic database and a read-only production query.
2. **Source adapter contract and durable checkpoints.** Add idempotent source records and per-source/page checkpoint storage. Test resume after interruption, duplicate pages, cursor errors, and atomic checkpoint/posting commit.
3. **Day-1 bulk campaign.** Add bounded campaign invocations and source ordering. Test all-source completion, partial failure, restart resume, time deadline enforcement, and proof that no model client initializes.
4. **Deterministic triage and queue ranking.** Add rule versioning, explainable decisions, and stable ranking. Test location uncertainty, part-time unknowns, employer overrides, deadline boundaries, duplicate handling, and no false rejection on missing data. Run a shadow dry-run and report real filter counts before enabling queue effects.
5. **Daily quota and cost controls.** Enforce the 25–50 configurable count alongside the daily token ceiling. Add phase-level accounting and token-safe deferral. Test the 2,000,000-token boundary, 183,000-token average case, retry reserve, and unchanged-input reuse. Benchmark each proposed prompt or text reduction; treat all savings as estimates until measured.
6. **Model-free liveness worker.** Add source-kind HTTP rules, rotation, rate limits, and auditable state projection. Test 404, 410, redirects, closure phrases, expired deadlines, missing-listing confirmation, 429, 5xx, and identity mismatch. Assert that no model or browser escalation runs in the HTTP-only path unless a source adapter explicitly requires a non-model active-workday check.
7. **Scheduling and watchdog.** Add separate bounded service steps and timer health checks. Test phase deadlines, collection cannot consume the assessment reservation, disabled timer alerting, missed-window detection, and no automatic timer activation.
8. **Alert summaries and repeated-error policy.** Add sanitized report payloads and persistent error keys. Test first failure, 3 consecutive failures, recovery reset, 10-failure repeat alerts, and webhook delivery failure without secret leakage.

Do not merge multiple steps merely to reduce pull-request count. Run each step through focused tests, review, and a dry-run before later steps depend on it. Do not activate timers or enable automatic assessment without explicit release approval.

## Sources and limits

Verified against the current checkout and live database on 2026-10-30: `pipeline/agentic/discovery_ops.py`, `pipeline/agentic/service.py`, `pipeline/agentic/liveness.py`, `pipeline/agentic/discovery_settings.py`, `jobwatch/db.py`, `config/jobwatch.yaml`, the three user systemd timer/service files, and the read-only production SQLite database.

GitHub issues: [#35](https://github.com/phroggingphrog/jobwatch/issues/35), [#36](https://github.com/phroggingphrog/jobwatch/issues/36), and [#37](https://github.com/phroggingphrog/jobwatch/issues/37).
