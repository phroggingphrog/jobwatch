# JobWatch forensic investigation — 31 Oct 2026 (source-only pass)

Source baseline verified: `main` = `4647ad1b78ce36f71a572c63a48047075c186aa0` (unchanged).
Untracked report; no tracked file, service, database or incident was changed.

## 0. Evidence boundary (read first)

This investigation ran in a cloud container that holds **only the Git checkout**. It had:
no production host, no systemd units or journals, no `~/.local/share/jobwatch-native/jobwatch.db`,
no gateway traces, no saved provider responses and no installed test dependencies (offline `uv`
could not fetch `pyphen`; `pytest`/`yaml` absent). Therefore:

- **No incident row, timestamp, run ID, journal traceback or deployed SHA was observed.**
- Every per-incident attribution below is either a source-level mechanism (CONFIRMED in code)
  or a hypothesis that needs the production queries listed in §F.
- No test was executed. Issue #50's failure is cited from the issue, not reproduced here.

## A. Executive diagnosis

1. **The 34 collection `execution_failed` incidents are not a source defect class — they are an
   observability artefact on top of an unknown exception.** `jobwatch/cli.py:231-233` reports
   `getattr(exc,'code','execution_failed')`. Every exception *inside a collector* is already
   swallowed by `run_collector` (`jobwatch/run.py:62`), and every assessment exception is
   swallowed by the "AI step must never fail a collection run" handler (`run.py:223`). So a
   collection-phase incident can only come from code **outside both handlers**: `dbm.start_run`,
   `discovery.prepare_run`, `Rules(...)`, `tier_collectors`, `publish`, `dbm.prune`, the
   deadline `alert`, `dbm.finish_run` (in `finally`, which can *replace* the original exception),
   or the CLI's own `begin_run/mark_phase`. Of these, only exceptions **without a `.code`**
   become `execution_failed` — principally `sqlite3.OperationalError` (lock contention between
   fast, slow, reader, web and agent processes sharing one DB with a 30 s busy timeout,
   `jobwatch/db.py:516-520`) and plain Python errors in publish/prune. The class is discarded
   in the incident, but the traceback is still re-raised to stderr → **the journal holds the
   answer** (`journalctl --user -u jobwatch-native-{fast,slow}.service`).
2. **Run-level incidents can never be resolved.** Collection incidents have `posting_id NULL`.
   The only resolution path, `incidents.release` (`incidents.py:153`), is reached solely from the
   per-posting retry in `discovery_ops.py:140`. There is no code that sets a NULL-posting
   incident to `released`. Consequence: every failed collector run since 27 Oct (when this
   reporting was introduced, commit `20b6679`, included in the documented live source `9111a0d`)
   is **permanently paused**, even though the latest 20 collections completed. The 34 are a
   cumulative counter, not a current failure rate. Also: each failed run gets its own incident
   (`ident = sha256(run_id:posting_id)`), so one recurring fault (e.g. a lock) yields N incidents.
3. **`token_limit` is a reservation check, not actual spend.** `runtime.py:244-245` raises
   `token_limit` when `job_charged + charge > job_ceiling`, where `charge` includes the
   *requested max output tokens*. A per-job ceiling can trip before tokens are consumed. Daily
   `null` does not affect this per-job ceiling (`discovery_settings.job_limits`).
4. **`turn_limit` conflates two limits.** `deepagents_runtime.py:357-358` maps
   `GraphRecursionError` to `turn_limit`; the recursion limit is `16*role_turn_limit+100`
   (`autonomous.py:768`), i.e. graph steps, not model turns. `autonomous.py:227` raises the real
   model-turn `turn_limit`. The incident cannot tell which one fired.
5. **`deadline_exceeded` has at least six producers** (`service.py:564` pre-read MIN_READ_SECONDS
   check, `runtime.py:201`, `execution.py:73`, `deepagents_runtime.py:200/226`, `liveness.py:77/112/120`,
   `adtext.py:294`). Historically the fast unit shared 780 s (`run.py:141`) between collection and
   assessment (#37); `service.py:564` then holds a job with `deadline_exceeded` *before any model
   call* when collection left < MIN_READ_SECONDS. That mechanism is removed only where the
   `--collect-only` drop-ins (`deploy/jobwatch-native-{fast,slow}-reliability.conf`) are actually
   installed; the separate reader unit still splits 780 s per person (`cli.py:189-193`).
6. **`invalid_model_payload` / `invalid_evaluation` (4602, 2143)**: the repo's own record
   (`docs/architecture/assessment-failures.md`) already establishes a **schema-contract defect**
   (tool schema advertised an arbitrary dict while canonical completion required five exact
   dimensions; validator misattributed the failing field to `matches`), fixed in source at
   `81fd5d2`, plus later **provider noncompliance** (missing required fields; one trailing `}` →
   `invalid_native_response`) at `998f116`. Whether 4602/2143 predate `81fd5d2` must be checked
   against their `created_at`; if they do, they are fixed-in-source, not deployed (live was `9111a0d`).

Largest incident share: (1)+(2) — 34/60 are run-level and structurally unresolvable.

## B. Failure evidence matrix

| # | Root cause | Incidents | Source | Confidence | Status |
|---|---|---|---|---|---|
| R1 | Exception class discarded; only non-`.code` exceptions outside per-collector/AI handlers reach `execution_failed` | 34 collection | `cli.py:231-233`, `run.py:62,223,231-243` | Mechanism CONFIRMED; actual exception UNKNOWN (journal needed) | Active in source |
| R2 | NULL-posting incidents have no release/resolve path; one incident per failed run | 34 collection (+any `reader`/`discovery` run-level) | `incidents.py:124-131,153-168`, `discovery_ops.py:140` | CONFIRMED | Active |
| R3 | `finish_run` in `finally` can mask the original exception | subset of R1 | `run.py:239-243` | CONFIRMED possible | Active |
| R4 | `prepare_run` failure → `DiscoveryError('discovery_failed')` → code not in `FAILURE_REASONS` → **no incident at all**; `SystemExit`/SIGTERM bypass `except Exception` | silent | `discovery.py:106-110`, `occupations/__init__.py:19-22`, `incidents.py:113` | CONFIRMED | Active (under-reporting) |
| R5 | Shared 780 s unit: collection consumes budget, job held `deadline_exceeded` before read | some of 14 deadline | `run.py:141-165`, `service.py:563-564`, #37 | Strong hypothesis | Mitigated only where collect-only drop-ins installed; reader still shares per-person |
| R6 | `token_limit` on reserved (input + max output) not actual | 4 token | `runtime.py:236-250` | Mechanism CONFIRMED; per-incident needs ledger | Active |
| R7 | `turn_limit` ambiguity (graph recursion vs model turns) | 6 turn | `deepagents_runtime.py:357-358`, `autonomous.py:227,768` | CONFIRMED ambiguity | Active |
| R8 | Tool schema ≠ canonical validator; misdirected correction | 4602 / 2143 (if pre-`81fd5d2`) | `autonomous.py:358-383,622-634` | CONFIRMED in repo record | Fixed in source, not deployed |
| R9 | Provider omits required fields / emits extra brace | later acceptance runs | assessment-failures.md | CONFIRMED by saved metadata (per doc) | Provider-side; correctly fails closed |
| R10 | #50: Blocked fallback reads `posting["url"]` | none of the 60 shown | `adtext.py:998-1000` | Reader passes a fetcher (`reader.py:1427`) → `url` not read; reader SQL lacks `p.url` (`reader.py:1337`) so a `fetcher=None` caller with reader rows *would* IndexError. Pipeline ingest rows include `url`. | Test-fixture failure confirmed by #50; production path latent |

## C. Execution ownership map (as in source)

```
systemd timers ── fast/slow (collect-only drop-in?) ── cli.run → jobwatch.run.run
                │      collectors (run_collector, swallows) → ingest/dedupe → Rules/prescreen (metadata)
                │      publish → prune → [assess=True only without drop-in] → service.after_collect
                └─ reader ── cli.read → expiry.sweep → service.after_collect
native API/agent (jobwatch-agent) ── discovery_ops (retry/after_collect, own incidents phase='discovery')
service.run_agentic_job: liveness → candidate_digest (current/ensure) → prescreen Engine → observe_posting
   → autonomous/deepagents runtime (gateway, JobBudget, execution scope) → canonical validator
   → gate → package (finalize) ; incidents.report on any FAILURE_REASON
```
Competing paths: three entry points into `after_collect` (fast/slow with assess, reader, API);
`effective_mode` selects agentic / pipeline / reader-legacy at runtime; prescreen runs both in
`run_collector` (metadata) and in `run_agentic_job`. Incidents are written by four different
catch sites with different phases (`collection`, `reader`, `discovery`, `assessment`/`liveness`).

## D. Prioritised repair plan

**P0**
1. *Preserve causal class.* `cli.py` (both branches), `discovery_ops.py:154`, `service.py:879`:
   store `error_class` (type name only, `_CODE`-safe) in `agentic_invocations` and the incident;
   keep `reason` stable. Test: raise `sqlite3.OperationalError` from a fake `publish` → incident
   has `error_class='OperationalError'`. Rollback: column is additive.
2. *Run-level incident lifecycle.* Add `resolve_run_incidents(conn, phase)` called on the next
   `end_run(state='completed')` for the same unit/phase (mark `superseded`, keep row). Test: failed
   run then successful run → 0 paused NULL-posting incidents, history retained.
3. *Do not mask in `finally`.* Wrap `dbm.finish_run` failure so the original exception wins.

**P1**
4. Split `token_limit` into `token_reservation_limit` vs actual; record reserved/actual/charged
   per call in the ledger. 5. Map `GraphRecursionError` to `graph_step_limit`. 6. Deploy
   `81fd5d2`-or-later contract repair only after a measured acceptance (§E).

**P2**
7. Give run-level failures one incident per (unit, error_class) per window (dedupe).
8. Report `DiscoveryError` codes (add to `FAILURE_REASONS` or map) so R4 is not silent.
9. Fix #50 by selecting `p.url` in `reader._BASE_SQL` and using `posting.get` semantics in the fallback; regression on a sqlite3.Row without `url`.

**P3**
10. One entry point for assessment scheduling (reader unit or API, not collector + reader + API).

## E. Acceptance sequence
Offline: tests for 1–3, 7–9 with synthetic fixtures; then
`tests/test_discovery_incidents.py`, `test_collection_budget.py`, `test_native_completion_contract.py`.
Production (owner-authorised, one posting): confirm deployed SHA; collect-only units run with
0 new run-level paused incidents; one `max_assessments=1` evaluate reaches canonical
evaluation + gate; ledger reconciles reserved/actual/charged; rerun with unchanged inputs = 0 paid ops.

## F. Remaining uncertainty — queries to run on the host (read-only)

```
git -C ~/apps/jobwatch-native rev-parse HEAD ; ~/apps/jobwatch-native/.venv/bin/pip show jobwatch
systemctl --user list-timers 'jobwatch*' ; systemctl --user cat jobwatch-native-fast.service
journalctl --user -u jobwatch-native-fast.service -u jobwatch-native-slow.service --since 2026-10-27 | grep -A30 Traceback
sqlite3 ~/.local/share/jobwatch-native/jobwatch.db "SELECT reason,phase,posting_id IS NULL,date(created_at,'unixepoch'),count(*) FROM agentic_incidents WHERE state='paused' GROUP BY 1,2,3,4"
sqlite3 … "SELECT i.run_id,v.unit,v.state,v.last_successful_phase FROM agentic_incidents i LEFT JOIN agentic_invocations v USING(run_id) WHERE i.phase='collection'"
```
Unverified: deployed SHA; whether drop-ins are installed; actual collector exceptions;
which limit/ceiling values applied to 1562/1602/1745; whether 4602/2143 predate `81fd5d2`.
