# Plan 5: Feedback and selection — Implementation Plan

> **Historical plan:** the owner-approved [remaining-roadmap plan](2026-10-23-finish-backend-roadmap.md)
> supersedes conflicting interfaces, run-key assumptions and workflow below.
> Phase 6 source behavior is documented in [the worked example](../../examples/feedback-selection.md)
> and the [backend contract](../../../pipeline/agentic/CHAT.md).
> Hosted CI is disabled and optional; required local checks and independent review
> govern completion. Preserve this original plan as design history.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person act on the explained shortlist through the native API: reject a job with a reason whose meaning is kept, turn an explicit exclusion into a confirmed rule that the gate, discovery and shortlist enforce at once, answer occasional targeted comparisons and questions, and select jobs and approve their preparation, with every one of those writes made by the person and never by a model.

**Architecture:** A new domain module `pipeline/agentic/feedback.py` owns the append-only `feedback_events` log, the `REJECTION_REASONS` vocabulary and the comparison/question chooser (expected information gain from the preference posterior when its fit is valid, a documented disagreement rule otherwise). `jobwatch/candidate/rules.py` records a confirmed exclusion as an amendment profile version (same scope, no projection, carried forward by later confirmations), which Plan 2's `DecisionPolicy` reads as `ExclusionRule`s. `pipeline/agentic/selection.py` turns a selection into a queued API run that calls `agentic_batch_run(operation='prepare')` under server-built, run-key-bound approvals. Routes live in `pipeline/agentic/feedback_api.py` and `profile_api.py`; every write route needs the `interact` or `approve` scope, which only the human's credential holds.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2 (`StrictFrozen` from `pipeline/agentic/contracts.py`), SQLite (`jobwatch/db.py` migration), pytest with synthetic transports (`tests/test_agentic_service.py` `SyntheticGateway`, `world`).

**Spec:** [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md) (section A.3 "Preference ranking", "Cold start"; A.4 "Interaction and automation"; A.5 "feedback collection and selected-job document preparation"), [roadmap](2026-10-21-backend-roadmap.md) row 5, [cross-plan contract](2026-10-21-cross-plan-contract.md) "Phase 6 — Plan 5" and "Reconciled decisions" (binding; applied here, see "Contract reconciliation" at the end). Code references: [code map](reference/2026-10-21-codemap.md) section 5 and Shared (line numbers as of `ce9e342`; re-verify with grep, Plans 2–4 move them).

**Depends on (merged before this plan runs), with the exact names this plan consumes:**
- Plan 2: `jobwatch/candidate/policy.py` (`ExclusionRule`, `DecisionPolicy`, `policy_for(person, *, approved=None) -> DecisionPolicy | None`, `exclusion_hit(policy, *, family: str | None, company: str, title: str, location_text: str, remote: bool, hours: str) -> ExclusionRule | None`; an `exclusion` fact whose value is `{"kind", "value"}` becomes an `ExclusionRule` with `source_fact_id`), `pipeline/agentic/service.py` (`decision_policy_mode(config) -> Literal['legacy', 'profile']`, `decision_policy_for(config)`, `gate_current(...)`).
- Plan 3: `pipeline/agentic/discovery.py` (`enforce_exclusions(conn, config, *, person=None) -> list[int]`, a no-op unless the mode is `profile`).
- Plan 4: `pipeline/agentic/shortlist.py` (`build_shortlist(conn, config) -> list[ShortlistEntry]`, `latest_entries(conn) -> list[ShortlistEntry]`, `load_entry(conn, posting_id) -> ShortlistEntry | None`), `pipeline/agentic/ranking.py` (`ShortlistEntry` with `entry_id`, `posting_id`, `run_key`, `profile_version`, `unresolved`), tables `shortlist_entries` / `shortlist_impressions`, `GET /api/agent/shortlist[/{posting_id}]`, `jobwatch/preference_service.py` (`pool(conn, config, *, statuses=('eligible',))`, `record_pick`), `PreferenceStore.status()` gating of `ordering`.

Locate them with grep before editing (`grep -rn "def build_shortlist\|def latest_entries\|def enforce_exclusions\|class ExclusionRule\|def policy_for\|def exclusion_hit\|def decision_policy_mode" jobwatch pipeline`); if one is missing, stop and report the failed precondition (EXECUTING.md rule 1).

`PY` below means `<venv>/bin/python`, a Python 3.12 virtualenv outside the repo (EXECUTING.md rule 3).

## Global Constraints

- "Explicit exclusions are rules. Ordinary rejection reasons are feedback whose meaning must be preserved. Never record agent-generated answers as user choices or approval."
- "Use occasional targeted comparisons or questions when answers could materially improve recommendations. Do not require feedback on every job."
- "Generate tailored documents only for user-selected jobs after preparation approval." Selection plus approval authorises `operation='prepare'` for exactly those jobs and nothing else: no employer message, no submission (Submit stays in `jobwatch/apply/submit_confirm.py`).
- "Choice probabilities describe preference among alternatives—not eligibility or hiring probability." "Insufficient feedback must not prevent discovery." "Clearly distinguish provisional ordering from validated personalised predictions."
- "Account for application selection bias": every shown job and prompt is logged so exposure can be joined to the choice later (Plan 6b); this plan applies no correction.
- Synthetic data only: tests never use live candidate records (AGENTS.md); fixtures are the existing synthetic worlds.
- Per-person isolation: every table and file is per person (`users.current()`, `users.user_dir(person)`, 0600 files / 0700 dirs through `apply.paths.safe_write_bytes/ensure_dir`); the person comes only from the bearer token.
- Paid model calls only on approved routes through `jobwatch.llm.LLM` with `execution.require_route`; tests use synthetic transports. Feedback, rules and prompt selection make **no** model call. Selection preparation reuses the same route checks as `chat.career_work`.
- No service, timer or deployment is activated. No application is submitted and no employer is contacted.
- Model output is never recorded as a person's choice or approval: every writer takes `actor: Literal['person']` fixed by the route, reachable only with `interact`/`approve` scope (never the `run` token the agent holds). No chat tool is added; skill files are untouched (`skill_version()` stays stable).
- Schema changes are additive: new tables in the next `jobwatch/db.py` migration (not also lazily); no existing stored model or column changes; approved-version JSON gains only optional keys.
- Run-key / re-evaluation rule (contract rule 1 and decision 4): nothing here may change `service._run_key` inputs. Confirming a rule must not re-key any posting (Task 5 regression test). `DecisionPolicy` fields never enter `RunKey.config_hash` (Plan 2 tests it); if this plan's test nevertheless fails, Plan 2's contract was broken: stop and report it, never ship a silent paid re-run (jobs × three model roles).
- Exclusion rules are enforced only when `pipeline.agentic.decision_policy` is `profile` (contract decision 3). In `legacy` mode a confirmed rule is stored and listed but the gate, the discovery pre-filter and the shortlist do not apply it; the confirmation response says so (`enforcement: 'inactive_legacy_gate'`).
- Preference-file rule (contract rule 5): do not edit `jobwatch/preferences/{features,store,model}.py`, `fit_choice_model.R`, `choice_model.jags`. Use them through their public functions only.
- Statistical operations stay explicit and versioned: expected information gain is a pure function of a stored fit; the cold-start rule is written down in the ADR, not fitted.

## Review Focus

1. A double click or client retry of the same feedback, pick or selection (same `request_id` / `Idempotency-Key`) leaves exactly one event and one run; the same id with a different body is a 409. (Tasks 2, 6, 8.)
2. A rejection reason that is not a taste (`seems_ineligible_for_me`, `ad_looks_wrong`, `duplicate_or_already_seen`) is stored with that meaning, suggests no rule, and is never read as a preference; `other` without the person's words is refused and the words are kept verbatim. (Task 2.)
3. Selecting a job whose ad, profile or policy changed since the shortlist was shown is a 409 `selection_changed`: nothing is queued, no `select` event is written, no paid call is made. (Task 6.)
4. A rule confirmed while a profile draft is open makes that draft's confirmation fail with `proposal_changed` instead of silently dropping the rule, and a later full confirmation keeps every active rule. (Task 4.)
5. A comparison goes stale when an option's ad or the policy changes before the person answers: 409 `comparison_stale`, no pick recorded, prompt closed; and a posterior fitted for another profile is never used (cold-start rule applies). (Tasks 7, 8.)

## File structure

| File | Responsibility |
|---|---|
| `docs/adr/<next>-feedback-and-selection.md`, `GLOSSARY.md` | Task 1. |
| `jobwatch/db.py` | Task 2: next migration, tables `feedback_events` (immutable) and `feedback_prompts`. |
| `pipeline/agentic/feedback.py` | Tasks 2, 5, 7, 8: reasons, recorders, rule suggestions, confirm_rule orchestration, chooser, prompts. |
| `pipeline/agentic/feedback_api.py` | Tasks 3, 6, 8: `mount(app, require, get_config, llm_factory)` for `/api/agent/shortlist/*/feedback`, `/selection`, `/feedback/*`. |
| `jobwatch/candidate/rules.py` | Task 4: rule proposals, digest-bound confirmation, amendment versions. |
| `jobwatch/candidate/intake.py`, `projection.py`, `pipeline/agentic/profile_api.py` | Tasks 4–5: new codes, carry-forward of rules, `/profile/rules` routes. |
| `pipeline/agentic/selection.py`, `pipeline/agentic/api.py` | Task 6: binding, worker, `process()` branch. |
| `pipeline/agentic/shortlist.py` (Plan 4) | Task 2: `build_shortlist` skips rejected postings (lazy import of `feedback`, which imports `shortlist`). |
| `tests/test_feedback.py`, `test_feedback_api.py`, `test_rules_api.py`, `test_selection.py`, `test_feedback_prompts.py`, `tests/candidate/test_rules.py` | One per task area. |

---

### Task 1: ADR and glossary for feedback, rules and selection

**Files:**
- Create: `docs/adr/<next free number>-feedback-and-selection.md` (`ls docs/adr`; Plans 2–4 add theirs first)
- Modify: `GLOSSARY.md` (rows: Feedback event, Rejection reason, Exclusion rule, Rule amendment, Selection, Targeted comparison, Targeted question)

- [ ] **Step 1: Write the ADR** (format of ADR 0002: Date, Status Accepted owner direction, Context, Decision, Consequences, references to the brief and the roadmap). Decisions to record, each in one short bullet:
  1. `feedback_events` is an append-only, person-only log. Kinds `reject`, `select`, `exclude`, `comparison`, `answer`; `actor` is always `person`, `source` is `api`; the shortlist entry, run key and profile version are resolved by the server, never taken from the body.
  2. A rejection hides that posting from the person's shortlist and records `reason_code`, the reason's `meaning` (`preference`, `eligibility`, `data_quality`, `neutral`, `unspecified`) and `REASONS_VERSION`, with the person's words verbatim. It never excludes anything else, never changes a gate result, and only taste reasons feed later preference analysis. A rejection may offer a *suggested* rule; only the person's confirmation creates one.
  3. An exclusion rule is a person-stated `exclusion` fact with value `{"kind": <family|employer|title_term|location|work_type>, "value": <text>}` and id `r<n>`, written by a digest-bound confirmation (`approve` scope) as an amendment profile version: same scope and scope digest, same evidence snapshot, no projection, `proposal_id` null, `amendment` recorded. Later full confirmations carry active rules forward; legacy `interests_and_criteria.yaml` only receives the rule's text under `not_wanted`, never `excluded_families` (so no run key moves). Enforcement is `DecisionPolicy.exclusions` in the gate and discovery pre-filter, and a shortlist rebuild straight after confirmation.
  4. Selection is a deterministic `approve`-scope request bound to each entry's run key and to the same `_approval_binding('prepare_application', …)` the chat uses; it queues one API run that calls `agentic_batch_run(operation='prepare')`; model text cannot select.
  5. Comparisons reuse the three-alternative-plus-none preference sets. With `PreferenceStore.status() == 'valid'` the set is chosen by expected information gain over the stored posterior draws (mutual information between the choice and the parameters, in nats). Otherwise the **cold-start disagreement rule**: among up to nine unseen eligible jobs pick the triple that maximises the smallest pairwise count of clear differences, then the sum of the three counts, then the smallest sorted posting ids; two jobs "clearly differ" on a feature when both values are known and differ by at least half of that feature's range across the candidates, plus one if their families differ; no numeric weights; a triple whose smallest count is 0 is not asked. Prompts: at most one open, at most 3 issued per rolling 7 days; never required. In `preference_picks` the actor column reads `owner` (the person who owns that database); the API check that the caller is the person happens first, and the event log says `person`.
  6. Targeted questions come from `DecisionPolicy.open_questions`, then from unresolved facts shared by at least two of the top ten shortlist entries. An answer is stored verbatim as an `answer` event and changes no profile fact; the person adds it to the profile through the proposal path.
  7. Exposure for selection-bias work: events carry `entry_id` (joins `shortlist_impressions`), and `feedback_prompts` logs what every prompt showed, with posterior probabilities when a valid fit existed. No correction is applied here.
- [ ] **Step 2: Add the GLOSSARY rows**, each one sentence consistent with the ADR (Exclusion rule: "a person-confirmed ExclusionRule stored in an amendment profile version and enforced by the gate, discovery and the shortlist"; Selection: "the person's approve-scope choice of shortlisted jobs for preparation; it authorises preparation only").
- [ ] **Step 3: Commit** `docs: ADR feedback and selection; glossary terms`.

### Task 2: Feedback log, reasons and recorders

**Files:**
- Modify: `jobwatch/db.py` (append one entry to `MIGRATIONS`, the next index after the last at execution time)
- Create: `pipeline/agentic/feedback.py`
- Modify: `pipeline/agentic/shortlist.py` (Plan 4) `build_shortlist`: skip `feedback.rejected_posting_ids(conn)` (import `feedback` inside the function; `feedback` imports `shortlist` at module level)
- Test: `tests/test_feedback.py`

**Interfaces:**
- Consumes: Plan 4 `shortlist.load_entry(conn, posting_id) -> ShortlistEntry | None` (fields `entry_id`, `run_key`, `profile_version`), `shortlist.latest_entries(conn)`, `shortlist.build_shortlist(conn, config)`; `persistence.latest_result`.
- Produces (all in `feedback.py`):
  - `REASONS_VERSION = 'rejection-reasons-v1'`; `class Reason(StrictFrozen)`: `code, label: str`, `meaning: Literal['preference','eligibility','data_quality','neutral','unspecified']`, `rule_kind: Literal['family','employer','location','work_type'] | None`, `text_required: bool = False`.
  - `REJECTION_REASONS: dict[str, Reason]` with exactly: `not_this_kind_of_work` (preference, family), `not_this_employer` (preference, employer), `location_unsuitable` (preference, location), `hours_or_work_type` (preference, work_type), `pay_too_low` (preference), `level_too_high` (preference), `level_too_low` (preference), `seems_ineligible_for_me` (eligibility), `duplicate_or_already_seen` (neutral), `ad_looks_wrong` (data_quality), `other` (unspecified, `text_required=True`).
  - `class FeedbackError(ValueError)` with `.code` in `CODES`; `STATUS: dict[str,int]` = `person_required` 403, `invalid_reason` 422, `reason_text_required` 422, `invalid_request` 422, `posting_not_shortlisted` 404, `feedback_conflict` 409, `prompt_not_found` 404, `prompt_closed` 409, `comparison_stale` 409, `selection_changed` 409.
  - `class FeedbackEvent(StrictFrozen)`: `id: int, posting_id: int | None, entry_id: str | None, kind, reason_code: str | None, reason_text: str, meaning: str | None, actor: Literal['person'], source: Literal['api'], run_key: str | None, profile_version: int | None, request_id: str, prompt_id: str | None, detail: dict, created_at: str`.
  - `connection(config)` context manager: `jobwatch.db.connect(chat.job_database(config))` (migrates), closed on exit.
  - `record_rejection(conn, person, posting_id: int, *, reason_code: str, reason_text: str, request_id: str, actor: str, source: str = 'api') -> FeedbackEvent`; `record_selection(conn, person, posting_id, *, request_id, actor, detail) -> FeedbackEvent`; `record_exclusion(conn, person, *, rule_id, kind, value, request_id, actor, source_event_id) -> FeedbackEvent`. Every recorder raises `FeedbackError('person_required')` unless `actor == 'person'`, resolves `entry_id/run_key/profile_version` from `shortlist.load_entry(conn, posting_id)`, the posting's entry in the newest shortlist (rejection and selection need one: else `posting_not_shortlisted`), is idempotent on `request_id`, and raises `feedback_conflict` when the same `request_id` arrives with different content.
  - `suggest_rules(conn, posting_id: int, reason_code: str) -> list[dict]` → `[{'kind','value'}]` from the reason's `rule_kind` (employer = `postings.company`, location = `postings.location`, work_type = `postings.work_type`, family = the stored evaluation's `facts.role_family`); empty for any reason without a `rule_kind` or a blank value.
  - `rejected_posting_ids(conn) -> set[int]`; `list_events(conn, *, limit: int = 100) -> list[FeedbackEvent]` newest first.
  - `_rebuild_shortlist(conn, config) -> list[ShortlistEntry]`: the one seam that calls Plan 4's `shortlist.build_shortlist(conn, config)`.
- Migration SQL: `feedback_events(id INTEGER PRIMARY KEY AUTOINCREMENT, posting_id INTEGER, entry_id TEXT, kind TEXT NOT NULL CHECK(kind IN ('reject','select','exclude','comparison','answer')), reason_code TEXT, reason_text TEXT NOT NULL DEFAULT '', meaning TEXT, reasons_version TEXT, actor TEXT NOT NULL CHECK(actor='person'), source TEXT NOT NULL, run_key TEXT, profile_version INTEGER, request_id TEXT NOT NULL UNIQUE, prompt_id TEXT, detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)` with `BEFORE UPDATE`/`BEFORE DELETE` triggers `RAISE(ABORT,'immutable')` and an index on `(posting_id, kind)`; and `feedback_prompts(id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('comparison','question')), subject_json TEXT NOT NULL, basis TEXT NOT NULL, expected_gain REAL, set_id TEXT, profile_version INTEGER, created_at TEXT NOT NULL, closed_at TEXT, closed_reason TEXT CHECK(closed_reason IN ('answered','dismissed','stale')))`. No foreign key to `postings` (retention pruning deletes postings; a person's feedback must survive it).

- [ ] **Step 1: Write the failing tests** in `tests/test_feedback.py`. Fixture `shortlisted(world)`: `conn, config, bundle, add = world`; add postings 1–4 (distinct companies, e.g. `add(1, company='Alpha Pty Ltd')`); `agentic_batch_run([1,2,3,4], config, conn, evidence_bundle=bundle, llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']), operation='evaluate')`; `entries = _rebuild_shortlist(conn, config)`. Reuse Plan 4's shortlist fixture if it has one.

```python
def test_migration_creates_immutable_feedback_tables(tmp_path):
    conn = db.connect(tmp_path / 'x.db')
    assert conn.execute('PRAGMA user_version').fetchone()[0] == len(db.MIGRATIONS)
    conn.execute("INSERT INTO feedback_events(kind,actor,source,request_id,created_at) VALUES('reject','person','api','r1','t')")
    for sql in ('UPDATE feedback_events SET kind=\'select\'', 'DELETE FROM feedback_events'):
        with pytest.raises(sqlite3.IntegrityError): conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):          # actor CHECK: only the person
        conn.execute("INSERT INTO feedback_events(kind,actor,source,request_id,created_at) VALUES('reject','agent','api','r2','t')")

def test_rejection_keeps_the_reason_meaning_and_the_words_verbatim(shortlisted):
    ev = record_rejection(conn, 'p', 1, reason_code='other', reason_text='Too far from my kids school', request_id='a', actor='person')
    assert ev.reason_text == 'Too far from my kids school' and ev.meaning == 'unspecified'
    assert record_rejection(..., 2, reason_code='pay_too_low', ...).meaning == 'preference'
    assert ev.entry_id == entries_by_posting[1].entry_id and ev.run_key == entries_by_posting[1].run_key   # server-resolved

def test_other_needs_words_and_unknown_codes_are_refused(shortlisted):   # 'reason_text_required' / 'invalid_reason'; table empty

@pytest.mark.parametrize('actor', ['agent', 'owner', '', None])
def test_only_the_person_can_record(shortlisted, actor):   # each recorder -> 'person_required'; no row

def test_same_request_id_is_one_event_and_a_different_body_conflicts(shortlisted):
    # identical retry returns the same id; different reason_code with the same request_id -> 'feedback_conflict'

def test_ineligibility_and_data_quality_suggest_no_rule_but_taste_does(shortlisted):
    assert suggest_rules(conn, 1, 'seems_ineligible_for_me') == [] and suggest_rules(conn, 1, 'ad_looks_wrong') == []
    assert suggest_rules(conn, 1, 'not_this_employer') == [{'kind': 'employer', 'value': 'Alpha Pty Ltd'}]
    assert suggest_rules(conn, 1, 'location_unsuitable') == [{'kind': 'location', 'value': 'Melbourne VIC'}]

def test_a_rejected_job_leaves_the_shortlist_without_touching_its_gate_state(shortlisted):
    before = conn.execute('SELECT run_key,status,reason FROM agentic_runs ORDER BY posting_id').fetchall()
    record_rejection(conn, 'p', 1, reason_code='not_this_employer', reason_text='', request_id='a', actor='person')
    assert 1 not in {e.posting_id for e in _rebuild_shortlist(conn, config)} and rejected_posting_ids(conn) == {1}
    assert conn.execute('SELECT run_key,status,reason FROM agentic_runs ORDER BY posting_id').fetchall() == before
```

- [ ] **Step 2: Run to verify failure** — `PY -m pytest -q -p no:cacheprovider tests/test_feedback.py` → FAIL (no module / no table).
- [ ] **Step 3: Implement** the migration, `feedback.py` and the one-line skip in the shortlist builder. Recorders write inside `BEGIN IMMEDIATE`; the idempotency check compares `(kind, posting_id, reason_code, reason_text)` for the same `request_id`. Reason text is stripped, at most 2000 characters, otherwise `invalid_request`. The `meaning` and `REASONS_VERSION` are copied into the row at write time so later vocabulary changes never rewrite history.
- [ ] **Step 4: Run** `tests/test_feedback.py tests/test_db_maintenance.py tests/test_dedupe.py` and the Plan 4 shortlist tests → PASS.
- [ ] **Step 5: Commit** `feat: append-only feedback log with rejection reasons that keep their meaning`.

### Task 3: Feedback API

**Files:**
- Create: `pipeline/agentic/feedback_api.py`
- Modify: `pipeline/agentic/api.py` (call `feedback_api.mount(app, require, get_config, llm_factory)` beside `profile_api.mount`; extend `capabilities` with `feedback=dict(reasons=sorted(REJECTION_REASONS), prompts_per_week=PROMPTS_PER_WEEK)` once Task 7 defines the constant, else a literal 3 replaced there)
- Test: `tests/test_feedback_api.py`

**Interfaces:**
- Consumes: Task 2; `require(scope)`; `get_config(person)`.
- Produces (person from the token, `_Body` = `extra='forbid', strict=True`):
  - `POST /api/agent/shortlist/{posting_id}/feedback` (scope `interact`) body `{request_id: str (1..128), kind: Literal['reject'], reason_code: str, reason_text: str = ''}` → 201 `{'event': FeedbackEvent, 'suggested_rules': [{'kind','value'}], 'shortlist_rebuilt': True}`. Calls `_rebuild_shortlist` after the write (database only).
  - `GET /api/agent/feedback?limit=` (scope `read`, 1..200) → `{'events': [...], 'reasons': [{'code','label','meaning','rule_kind','text_required'}]}`.
  - `FeedbackError` → `JSONResponse({'error': code}, STATUS[code])` through an exception handler as `profile_api` does.

- [ ] **Step 1: Failing tests** (HTTP with `TestClient`, `create_api(config=config, credentials={RUN: Principal(p), APPROVE: Principal(p, {'read','interact','approve'}), OTHER: Principal(q, …)}, llm_factory=spy)` where `spy` raises if called; copy the harness of `tests/test_agentic_service.py::test_native_api_prepares_existing_pipeline_package`):

```python
def test_reject_over_http_records_a_person_event_and_suggests_a_rule(api):
    r = api.post(f'/api/agent/shortlist/1/feedback', headers=h(APPROVE), json={'request_id': 'k1', 'kind': 'reject', 'reason_code': 'not_this_employer'})
    assert r.status_code == 201 and r.json()['event']['actor'] == 'person' and r.json()['event']['source'] == 'api'
    assert r.json()['suggested_rules'] == [{'kind': 'employer', 'value': 'Alpha Pty Ltd'}]

def test_the_agent_run_token_cannot_record_feedback(api):   # RUN token -> 403 {'error':'scope_required'}; feedback_events empty
def test_a_body_cannot_set_actor_or_source(api):            # json includes 'actor': 'person' -> 422 invalid_request
def test_another_persons_token_cannot_reject_my_posting(api):  # OTHER -> 404 posting_not_shortlisted
def test_feedback_makes_no_model_call_and_changes_no_gate_state(api):  # spy untouched; agentic_runs rows identical
def test_double_submit_is_one_event_and_a_changed_body_is_409(api):
def test_rejected_job_is_gone_from_get_shortlist_at_once(api):  # GET /api/agent/shortlist (Plan 4) lacks posting 1 right after the 201
def test_listing_returns_the_persons_own_words_and_the_reason_vocabulary(api):
```

- [ ] **Step 2: Run** `PY -m pytest -q -p no:cacheprovider tests/test_feedback_api.py` → FAIL. **Step 3: Implement** `mount` (open the database with `feedback.connection(get_config(person))` inside the handler; run under `users.use(person)` like `profile_api.call`). **Step 4: Run** `tests/test_feedback_api.py tests/test_profile_api.py` and `tests/test_agentic_service.py -k "native_api"` → PASS.
- [ ] **Step 5: Commit** `feat: native API to reject shortlisted jobs with a reason`.

### Task 4: Rule amendments as profile versions

**Files:**
- Create: `jobwatch/candidate/rules.py`
- Modify: `jobwatch/candidate/intake.py` (add codes `rule_not_found`, `rule_invalid`, `rule_exists`, `profile_not_confirmed` to `CODES`; in `confirm`, after `facts, open_questions = _reconciled(cur)` append the active rule facts of `last` that are not already present by id; add `"amendment"` to the key list in `versions()`)
- Modify: `jobwatch/candidate/projection.py` (a dict `exclusion` fact with a rule `kind` contributes its `value` text to `not_wanted` and nothing to `excluded_families`)
- Modify: `pipeline/agentic/profile_api.py` `STATUS` (add: `rule_not_found` 404, `rule_invalid` 422, `rule_exists` 409, `profile_not_confirmed` 409)
- Test: `tests/candidate/test_rules.py`, `tests/candidate/test_projection.py`, `tests/candidate/test_intake.py` (carry-forward)

**Interfaces:**
- Consumes: `intake._locked, _write_private, _numbers, _approved, _versions_root, _root, _scope_digest, current_version, discovery_scope, DOES_NOT_AUTHORISE` (module-private helpers used only by `rules.py`; keep the underscore and say so in a comment); `contracts.KNOWN_FAMILIES, canonicalize_family`.
- Produces (`rules.py`):
  - `RULE_KINDS = ('family','employer','title_term','location','work_type')`.
  - `propose_rule(person: str, *, kind: str, value: str, source_event_id: int | None = None) -> dict` and `propose_withdraw(person: str, rule_id: str) -> dict`, each storing `intake/rules/<16 hex>.json` (0600) and returning the confirmation `{'rule_proposal_id', 'rule_digest', 'change': {'op','kind','value','rule_id'}, 'base_version': int, 'takes_effect': 'on_confirmation', 'authorises': [], 'does_not_authorise': DOES_NOT_AUTHORISE}`. Value is stripped and whitespace-collapsed, 1..200 characters; `family` must canonicalise into `KNOWN_FAMILIES`. Requires `discovery_scope(person)` (a confirmed, scope-bearing current version) else `profile_not_confirmed`.
  - `confirmation(person, rule_proposal_id) -> dict` (same shape; `proposal_changed` if the current version is no longer `base_version`).
  - `confirm_rule(person, rule_proposal_id, *, rule_digest: str, actor: Literal['person']) -> dict` → `{'version': n, 'rule_id': str, 'op': str}`. Under `versions.lock`: re-check digest and base version, then write `profile-versions/<n+1>/` as a copy of the previous version's files (each through `_write_private`) with a new `approved.json`: `version`, `proposal_id: None`, `base_version: n`, `actor: 'person'`, `amendment: {'op','rule_id','rule_digest'}`, `confirmed_at`, facts = previous facts ± the rule fact, and `scope`, `scope_digest`, `uploads`, `evidence_bundle_hash`, `file_sha256` copied unchanged. Idempotent: a repeat with the same digest returns the version it created. Rule fact: `{id: 'r<k>', section: 'exclusion', value: {'kind','value'}, basis: 'evidence', sources: [], note: 'stated by person; rule', actor: 'person'}`, `k` one more than any rule id in any version (ids are never reused).
  - `active_rules(person: str) -> list[dict]` → `[{'rule_id','kind','value','version','confirmed_at'}]` from the current version; `pending_rules(person) -> list[dict]`.

- [ ] **Step 1: Failing tests** (fixture `confirmed`: user `sam`, `model_choice.set_models({'reader': 'claude/sonnet'}, 'sam')`, patched `SERVER_URL`, a fake-transport `LLM`, then `intake.propose` + `confirmation` + `confirm` exactly as `tests/candidate/test_intake.py::full` and `ok` do):

```python
def test_a_proposed_rule_changes_nothing_until_confirmed(confirmed):   # version number, active_rules, version dirs unchanged
def test_confirming_writes_an_amendment_version_with_the_same_scope(confirmed):
    out = rules.confirm_rule(p, c['rule_proposal_id'], rule_digest=c['rule_digest'], actor='person')
    v2 = intake.current_version(p)
    assert out['version'] == v2['version'] == v1['version'] + 1 and v2['proposal_id'] is None
    assert v2['scope'] == v1['scope'] and v2['scope_digest'] == v1['scope_digest'] and v2['file_sha256'] == v1['file_sha256']
    assert v2['evidence_bundle_hash'] == v1['evidence_bundle_hash'] and v2['amendment']['op'] == 'add'
    assert v2['facts'][-1] == {... 'id': 'r1', 'value': {'kind': 'employer', 'value': 'Acme Pty Ltd'}, 'actor': 'person' ...}
    assert intake.discovery_scope(p) == intake.SearchScope.model_validate(v1['scope']) and previous version dir bytes unchanged
def test_confirm_needs_the_shown_digest_and_a_person(confirmed):   # wrong digest -> proposal_changed; actor='agent' -> person_required; nothing written
def test_confirming_twice_mints_one_version(confirmed):
def test_a_version_that_moved_on_refuses_the_old_confirmation(confirmed):
def test_withdraw_removes_the_rule_in_a_new_version_and_ids_are_not_reused(confirmed):   # add r1, withdraw r1, add again -> r2
@pytest.mark.parametrize('kind,value,code', [('salary','x','rule_invalid'), ('employer','','rule_invalid'), ('employer','x'*201,'rule_invalid'), ('family','not-a-family','rule_invalid')])
def test_invalid_rules_are_refused(confirmed, kind, value, code):
def test_duplicate_rule_is_refused_ignoring_case(confirmed):   # 'rule_exists'
def test_unconfirmed_or_adopted_profiles_refuse_rules(person):   # no version and adopt_existing-only version -> profile_not_confirmed
def test_a_later_full_confirmation_keeps_active_rules_and_drops_withdrawn_ones(confirmed, fake_llm):
def test_a_rule_confirmed_during_an_open_draft_makes_that_draft_stale(confirmed):   # intake.confirm of the draft -> proposal_changed; version count unchanged
def test_a_confirmed_rule_becomes_an_exclusion_rule_in_the_policy(confirmed):          # contract decision 6, consumed from Plan 2
    # after confirm_rule(employer 'Acme Pty Ltd'): policy_for(p).exclusions == (ExclusionRule(rule_id='r1:employer', kind='employer', value='Acme Pty Ltd', source_fact_id='r1', actor='person'),)
    # and 'exclusion:r1' is not among its open_questions
def test_rules_are_private_to_the_person():   # intake/rules/ under each user_dir; modes 0600/0700; the other person sees none
```
  In `test_projection.py`: `test_rule_facts_project_to_not_wanted_text_only` — `project(approved)` with a `family` rule `retail` gives `not_wanted == ['retail']` and `excluded_families == []`.

- [ ] **Step 2: Run** `PY -m pytest -q -p no:cacheprovider tests/candidate/test_rules.py tests/candidate/test_projection.py` → FAIL. **Step 3: Implement.** **Step 4: Run** `tests/candidate tests/test_profile_api.py tests/test_cli_profile.py` → PASS.
- [ ] **Step 5: Commit** `feat: confirmed exclusion rules as amendment profile versions`.

### Task 5: Rules API and immediate enforcement

**Files:**
- Modify: `pipeline/agentic/profile_api.py` (routes below), `pipeline/agentic/feedback.py` (`confirm_rule`), and only where a gap is proven by the tests: Plan 2's `jobwatch/candidate/policy.py` / `pipeline/agentic/gate.py` and Plan 3's `pipeline/agentic/discovery.py` pre-filter
- Test: `tests/test_rules_api.py`

**Interfaces:**
- Consumes: Task 4; Task 2 `record_exclusion`, `_rebuild_shortlist`; Plan 2 `policy_for(person)`, `ExclusionRule`, `exclusion_hit(policy, *, family, company, title, location_text, remote, hours)`, `service.decision_policy_mode(config)`, `service.gate_current`; Plan 3 `discovery.enforce_exclusions(conn, config, *, person=None) -> list[int]`; `service.after_collect`.
- Produces:
  - `POST /api/agent/profile/rules` (scope `interact`) body `{op: 'add'|'withdraw' = 'add', kind?, value?, rule_id?, source_event_id?: int}` → 201 the confirmation dict of Task 4.
  - `GET /api/agent/profile/rules` (scope `read`) → `{'rules': active_rules, 'pending': pending_rules}`.
  - `POST /api/agent/profile/rules/{rule_proposal_id}/confirm` (scope `approve`) body `{rule_digest}` → 201 `{'version', 'rule_id', 'op', 'shortlist_rebuilt': True, 'enforcement': 'active' | 'inactive_legacy_gate', 'archived_by_prefilter': [posting ids]}` (`enforcement` is `active` when `service.decision_policy_mode(config) == 'profile'`, else `inactive_legacy_gate`).
  - `feedback.confirm_rule(person, config, rule_proposal_id, *, rule_digest, actor) -> dict`: `rules.confirm_rule`, then `record_exclusion` (`request_id = 'rule:' + rule_proposal_id`, so a retry after a crash completes the remaining steps), then, in `profile` mode, `discovery.enforce_exclusions(conn, config)` (the ids it archived are returned as `archived_by_prefilter`), then `_rebuild_shortlist`. Withdrawals record kind `exclude` with `detail {'op': 'withdraw'}`; the postings the pre-filter archived under a withdrawn rule come back through Plan 3's `reconsider`.
  - No new matcher: rule matching is Plan 2's `exclusion_hit`, called by the gate (via `gate_current`) and by Plan 3's pre-filter (contract decision 6).

- [ ] **Step 1: Failing tests** in `tests/test_rules_api.py` (fixtures: `shortlisted` of Task 2 plus the HTTP harness of Task 3, with `pipeline.agentic.decision_policy: profile` in the test config except where a test says `legacy`; a person confirmed with `conftest.confirm_discovery`):

```python
def test_rule_flow_over_http(api):   # POST rules -> confirmation; confirm with APPROVE -> 201 version+1; GET /profile/ shows it; GET rules lists it; withdraw flow
def test_rule_routes_need_the_right_scopes(api):   # RUN token POST rules -> 403; interact-only token confirm -> 403 (needs approve)
def test_confirming_records_an_exclude_event_by_the_person(api):   # kind 'exclude', actor 'person', detail has rule_id
def test_a_rejection_alone_never_excludes(api):   # reject employer 'Alpha' with reason not_this_employer; policy_for(p).exclusions unchanged; another Alpha posting is still evaluated
def test_confirmed_rule_removes_matching_shortlist_entries_at_once_without_a_model_call(api):
    # after confirm: GET /shortlist lacks Alpha's postings; spy llm_factory never called; agentic_runs rows unchanged
def test_confirmed_rule_stops_new_postings_before_any_paid_call(world):
    # decision_policy 'profile'; add posting 5 for 'Alpha Pty Ltd'; service.after_collect with a counting transport -> posting 5 archived with reason
    # 'excluded_by_rule' (Plan 3's pre-filter), transport saw 0 requests for it; a posting that reaches the gate instead is archived 'policy_excluded'
def test_legacy_mode_stores_the_rule_but_says_it_is_not_enforced(api):
    # decision_policy 'legacy' (default): confirm -> 201 with enforcement 'inactive_legacy_gate', archived_by_prefilter [], GET /shortlist still lists Alpha's postings; active_rules lists the rule
def test_withdrawing_a_rule_brings_prefiltered_postings_back(world): ...   # profile mode: withdraw -> Plan 3 reconsider moves the 'excluded_by_rule' posting back to 'ingested'
@pytest.mark.parametrize('rule,posting,blocked', [
    (('employer','Acme'), {'company': 'Acme Pty Ltd'}, True), (('employer','Acme'), {'company': 'Acmeville'}, False),
    (('title_term','sales'), {'title': 'Sales Assistant'}, True), (('title_term','sales'), {'title': 'Salesforce Administrator'}, False),
    (('location','Geelong'), {'location': 'Geelong VIC'}, True), (('location','Geelong'), {'location': 'Melbourne VIC'}, False),
    (('work_type','casual'), {'work_type': 'casual'}, True), (('work_type','casual'), {'work_type': 'FT'}, False),
    (('family','retail'), {'family': 'retail'}, True), (('family','retail'), {'family': 'accounting'}, False)])
def test_each_rule_kind_matches_as_a_person_would_expect(rule, posting, blocked):   # calls policy.exclusion_hit(policy_of(rule fact), family=..., company=..., title=..., location_text=..., remote=..., hours=...); employer/title: case-insensitive whole words; work_type casual maps to hours='casual'
def test_confirming_a_rule_does_not_change_any_run_key(world):
    # service._run_key for posting 1 before and after confirm_rule is identical (same bundle, policy_for(p) rebuilt); the contract's regression test (decision 4)
```

- [ ] **Step 2: Run** `PY -m pytest -q -p no:cacheprovider tests/test_rules_api.py` → FAIL.
- [ ] **Step 3: Implement** the routes and `confirm_rule`. Then run the enforcement tests and close only the gaps they show: (a) a rule kind the gate or the pre-filter does not enforce → fix it in Plan 2's `exclusion_hit` or at the existing call seam, never with a second matcher; (b) shortlist entries survive → fix `build_shortlist` to re-decide stored evaluations through `gate_current` with `decision_policy_for(config)` (database only). If the run-key test fails, Plan 2 hashed a `DecisionPolicy` field into `RunKey.config_hash`: that breaks contract decision 4, so stop and report it; do not add a flag or accept a paid re-run.
- [ ] **Step 4: Run** `tests/test_rules_api.py tests/candidate tests/test_agentic_gate.py tests/test_agentic_service.py tests/test_profile_api.py` → PASS.
- [ ] **Step 5: Commit** `feat: confirm exclusion rules over the API; gate, discovery and shortlist enforce them at once`.

### Task 6: Job selection and preparation approval

**Files:**
- Create: `pipeline/agentic/selection.py`
- Modify: `pipeline/agentic/feedback_api.py` (route), `pipeline/agentic/api.py` (`process()` branch)
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: `chat._approval_binding`, `skill_version`, `job_connection`; `service.snapshot_inventory`, `service.agentic_batch_run`, `service._config`; `execution.require_route`, `APIStore.create_thread/enqueue`; Task 2 `record_selection`; Plan 4 `shortlist.load_entry(conn, posting_id)` (the posting's entry in the newest shortlist).
- Produces:
  - `MAX_SELECTION = 10`; `class SelectionError(ValueError)` with `.code` in `invalid_request` 422, `not_shortlisted` 404, `selection_changed` 409, `agentic_disabled` 409 (add to `feedback.STATUS`).
  - `build_selection(conn, config, posting_ids: list[int], expected_run_keys: dict[str, str]) -> dict` → `{'selection_id': sha256 of posting ids and run keys, 'posting_ids', 'bindings': [binding], 'entries': {str(pid): {'entry_id','run_key'}}}`. Requires `set(map(str, posting_ids)) == set(expected_run_keys)`, 1..`MAX_SELECTION` distinct ids, each with a shortlist entry whose `run_key` equals the expected key, equals the current `snapshot_inventory(...)[0]['run_key']`, and equals `_approval_binding('prepare_application', {'posting_id': pid}, cfg)['run_key']`.
  - `run(*, person, config, llm, execution, selection: dict) -> dict`: under the person's `career-chat/dispatch.lock` (same non-blocking flock as `chat.dispatch`; busy → `RuntimeErrorSafe('person_busy')`), re-derive each binding and raise `RuntimeErrorSafe('approval_inputs_changed')` on any difference, run the route checks of `chat.career_work` (every configured role model, embedding model), set `execution.approvals[('prepare_application', pid)] = binding`, call `agentic_batch_run(ids, config, conn, expected_run_keys=…, operation='prepare', llm=llm, llm_drafter=llm, llm_reviewer=llm)`, and return `{'status': 'complete', 'outcomes': [{'posting_id','run_key','status','reason'} …] + deferred items with their `reason`, 'usage': execution.usage(), 'answer': '', 'interactions': [], 'interrupts': [], 'tools': [], 'todos': []}`.
  - `POST /api/agent/shortlist/selection` (scope `approve`, header `Idempotency-Key`) body `{posting_ids: list[int], expected_run_keys: dict[str, str]}` → 202 `{'run_id','state','selection_id'}`. Order: `build_selection`; `APIStore.create_thread(skill_version())`; `enqueue(thread, {'selection': {...}}, key)`; then `record_selection` per posting with `request_id = f'{key}:{pid}'` and `detail {'run_id','selection_id'}`. A retry repeats the first three idempotently.
  - `api.process()`: `if 'selection' in payload: result = selection.run(person=…, config=cfg, llm=llm_factory(person) if llm_factory else configured_llm(cfg), execution=execution, selection=payload['selection'])` else the existing dispatcher call.

- [ ] **Step 1: Failing tests** (HTTP harness with the synthetic gateway as in `test_native_api_prepares_existing_pipeline_package`; four shortlisted postings; `entry_keys = {str(e.posting_id): e.run_key}`):

```python
def test_selection_prepares_only_the_selected_jobs(api):
    r = api.post('/api/agent/shortlist/selection', headers={**h(APPROVE), 'Idempotency-Key': 's1'}, json={'posting_ids': [1, 2], 'expected_run_keys': {'1': k1, '2': k2}})
    assert r.status_code == 202
    done = wait(api, r.json()['run_id'])
    assert {o['posting_id']: o['status'] for o in done['result']['outcomes']} == {1: 'ready', 2: 'ready'}
    assert packages(conn) == {1, 2} and no draft/package rows for postings 3, 4
    assert events(conn, 'select') -> two rows, actor 'person', entry_id equal to the shortlist entries'
def test_selection_needs_approve_scope(api):   # RUN token and an interact-only token -> 403; nothing queued
def test_stale_run_key_is_refused_and_nothing_is_queued_recorded_or_paid(api):   # wrong key -> 409 selection_changed; api_runs empty; no select event; spy transport 0 calls
def test_posting_not_on_the_shortlist_is_refused(api):   # 404 not_shortlisted
def test_a_changed_ad_between_request_and_run_is_refused_by_the_binding(world):   # selection.run after adtext.save_text -> RuntimeErrorSafe('approval_inputs_changed'); no package
def test_selection_is_idempotent_and_a_changed_body_conflicts(api):   # same key+body -> same run_id, 2 events; same key, other ids -> 409 idempotency_conflict
def test_selection_never_submits(api, monkeypatch):   # submit_confirm.queue / settle patched to raise -> not called; no employer fetch beyond the existing liveness observer
def test_draft_limits_defer_extra_jobs_with_a_reason(api):   # drafts_per_run=1, select 2 -> one ready, one deferred 'draft_batch_limit' in outcomes
def test_rejected_job_cannot_be_selected(api):   # reject posting 1, then select [1] -> 404 not_shortlisted
```

- [ ] **Step 2: Run** `PY -m pytest -q -p no:cacheprovider tests/test_selection.py` → FAIL. **Step 3: Implement.** **Step 4: Run** `tests/test_selection.py tests/test_agentic_service.py tests/test_deepagents_runtime.py tests/test_submit_confirm.py` → PASS.
- [ ] **Step 5: Commit** `feat: select shortlisted jobs and approve their preparation through the API`.

### Task 7: Choosing the next comparison or question

**Files:**
- Modify: `pipeline/agentic/feedback.py`
- Test: `tests/test_feedback_prompts.py`

**Interfaces:**
- Consumes: `preference_service.pool(conn, config) -> (identity, alternatives)` and `PreferenceStore` (`status`, `list_sets`, `create_set`), `model.transform_features`, `features.family_index, NAMES` (read-only); Plan 2 `policy_for(person).open_questions`; Plan 4 `shortlist.latest_entries(conn)` (each entry's `unresolved`). Two seams for tests: `_pool(conn, config)` and `_preference_store(conn)`.
- Produces:
  - `PROMPTS_PER_WEEK = 3`, `MAX_OUTSTANDING = 1`, `QUESTION_COOLDOWN_DAYS = 30`; optional override `feedback.prompts_per_week` read from the settings **outside** `service._config()` (0 turns prompts off).
  - `class ComparisonOption(StrictFrozen)`: `posting_id: int, title: str, company: str, entry_id: str | None`. `class Comparison(StrictFrozen)`: `prompt_id: str, set_id: str, options: tuple[ComparisonOption, ...]` (3), `basis: Literal['information_gain','cold_start_disagreement']`, `expected_information_gain: float | None`, `ordering: Literal['provisional','personalised']`, `why: str`, `created_at: str`. `class TargetedQuestion(StrictFrozen)`: `prompt_id, text, source: Literal['open_question','shared_unresolved'], created_at`.
  - `information_gain(fit: dict, alternatives: list[dict], *, max_draws: int = 1000) -> float`: per posterior draw `u_j = alpha[family_index(j) - 1] + beta · transform_features(features_j, fit['preprocessing'])`, outcome probabilities `softmax([u_1, u_2, u_3, 0])` (the outside option has utility 0, as in `predict_set`); result = H(mean probabilities) − mean H(probabilities), in nats, over at most the first `max_draws` draws.
  - `cold_start_triple(alternatives: list[dict]) -> tuple[int, int, int] | None` (rule in the ADR; `None` when the best smallest pairwise count is 0).
  - `next_comparison(conn, person: str, config=None, *, now: datetime | None = None) -> Comparison | None` (optional `config`, loaded under `users.use(person)` when omitted). Returns the open comparison if one exists; `None` when at the weekly cap, with fewer than three unseen eligible alternatives (not in any existing set, not rejected), or no informative triple. Candidates: the nine newest unseen alternatives. A valid fit (`status == 'valid'`, fit `profile_hash` equal to the alternatives', draws usable) picks the triple of largest `information_gain` (ties: smallest sorted ids); anything else, including a fit for another profile, uses `cold_start_triple`. Creates the set with `PreferenceStore.create_set`, inserts the `feedback_prompts` row (`subject_json` = options and, when the fit was used, each option's mean choice probability; `ordering` `personalised` only with a valid fit), returns the `Comparison`.
  - `next_question(conn, person, config=None, *, now=None) -> TargetedQuestion | None`: same cap and single-outstanding rule shared with comparisons; source order `open_questions`, then an unresolved string shared by at least two of the ten best-ranked entries (case-insensitive, ties alphabetical); skips a subject answered or dismissed within `QUESTION_COOLDOWN_DAYS`.
  - `outstanding_prompt(conn) -> dict | None`, `prompts_this_week(conn, now) -> int`.

- [ ] **Step 1: Failing tests** (pure ones need no database; fits are synthetic dicts shaped like `tests/preferences/test_core.py::test_prediction_arithmetic_in_memory_fixture_only`: `draws {'beta': [...], 'alpha': [...]}`, `preprocessing` with `centers`, `scales`, `missing_rates`):

```python
def test_information_gain_is_zero_when_the_posterior_cannot_tell_the_alternatives_apart():   # identical draws -> approx 0
def test_information_gain_is_larger_for_the_set_the_posterior_disagrees_about():   # half the draws coverage +3, half -3; coverage 0/.5/1 set > a set with equal coverage
def test_information_gain_probabilities_match_predict_set():   # mean outcome probabilities equal predict_set(...)['alternatives'][j]['choice_probability']['mean'] (Stub store as in test_core)
def test_cold_start_rule_is_deterministic_and_has_no_weights():   # fixed features -> expected triple; shuffling input order or ties gives the same ids; all-equal features -> None
def test_valid_fit_chooses_by_information_gain_otherwise_cold_start(monkeypatch):   # status 'valid' -> basis 'information_gain', ordering 'personalised'; 'insufficient_data' -> 'cold_start_disagreement', 'provisional'
def test_a_fit_for_another_profile_is_not_used():   # fit.profile_hash differs -> cold start, no exception
def test_fewer_than_three_unseen_alternatives_ask_nothing(): ...
def test_one_open_prompt_and_a_weekly_cap(conn):   # second call returns the same prompt; after answering/closing, 3 issued in 7 days then None; 8 days later allowed again (frozen now)
def test_a_comparison_logs_what_was_shown_and_the_probabilities_when_a_fit_was_valid(conn):
def test_rejected_and_rule_excluded_postings_are_never_offered(conn):
def test_no_feedback_at_all_never_blocks_the_shortlist(conn):   # zero events, no fit: build_shortlist works, next_comparison returns a cold-start Comparison or None, never raises
def test_question_prefers_open_questions_then_shared_unresolved_and_respects_the_cooldown(conn):
```

- [ ] **Step 2: Run** `PY -m pytest -q -p no:cacheprovider tests/test_feedback_prompts.py` → FAIL. **Step 3: Implement** (standard library plus the existing numpy-free arithmetic of `predict_set`; draws validated like `predict_set`, a malformed fit means cold start). **Step 4: Run** `tests/test_feedback_prompts.py tests/preferences tests/test_preference_service.py` → PASS (the R test stays skipped).
- [ ] **Step 5: Commit** `feat: choose targeted comparisons by information gain, with a documented cold-start rule`.

### Task 8: Prompt API (comparisons and questions)

**Files:**
- Modify: `pipeline/agentic/feedback_api.py`, `pipeline/agentic/feedback.py`
- Test: `tests/test_feedback_api.py` (extend)

**Interfaces:**
- Consumes: Task 7; `preference_service.record_pick(conn, config, set_id, selected, request_id)` (re-checks that every option is unchanged and the context hash matches; `PreferenceError('stale_set')` → `comparison_stale`).
- Produces (all scope `interact`, person from the token):
  - `POST /api/agent/feedback/next` → 200 `{'prompt': {'type': 'comparison', …Comparison} | {'type': 'question', …TargetedQuestion} | None, 'reason': None | 'rate_limited' | 'not_enough_alternatives' | 'nothing_to_ask'}`. Comparison first, then question.
  - `POST /api/agent/feedback/comparisons/{prompt_id}/pick` body `{request_id, selected: int | None}` (`None` = none of these) → 200 `{'event': FeedbackEvent}`.
  - `POST /api/agent/feedback/questions/{prompt_id}/answer` body `{request_id, text: str (1..2000)}` → 200 `{'event': FeedbackEvent}`.
  - `POST /api/agent/feedback/prompts/{prompt_id}/dismiss` → 200 `{'closed': 'dismissed'}`; records no event and no choice; counts toward the weekly cap.
  - `feedback.answer_comparison(conn, person, config, prompt_id, selected, *, request_id, actor) -> FeedbackEvent`: prompt must be open and a comparison (`prompt_closed`); `selected` must be an option's posting id or `None` (`invalid_request`); then `record_pick(...)`; then the `comparison` event (`posting_id` = selection or null, `detail {'set_id','selected','basis'}`); then close the prompt `answered`. A stale set closes the prompt `stale` and raises `comparison_stale`. Each step is idempotent so a retry completes the rest.
  - `feedback.answer_question(conn, person, prompt_id, text, *, request_id, actor) -> FeedbackEvent`: `answer` event with the person's words verbatim; changes no profile fact.

- [ ] **Step 1: Failing tests:**

```python
def test_comparison_round_trip(api):   # POST next -> comparison with 3 options; pick one -> 200; preference_picks row (actor 'owner'), feedback_events kind 'comparison' actor 'person'; prompt closed 'answered'
def test_none_of_these_is_a_genuine_answer(api):   # selected null -> pick row selected NULL, event posting_id NULL
def test_the_agent_token_cannot_pick_or_answer(api):   # RUN token on pick/answer/next/dismiss -> 403; no pick row
def test_pick_must_be_an_option(api):   # posting not among options -> 422 invalid_request; nothing recorded
def test_a_comparison_goes_stale_when_an_option_changes(api):   # adtext.save_text on an option, then pick -> 409 comparison_stale; no pick; prompt closed 'stale'; the next call may issue a new one
def test_double_pick_is_idempotent_and_a_changed_pick_conflicts(api):   # same request_id: one pick row, one event; other selected -> 409 feedback_conflict
def test_dismiss_records_no_choice_but_counts_toward_the_cap(api):
def test_question_answer_is_verbatim_and_leaves_the_profile_untouched(api):   # intake.current_version unchanged; event.reason_text == text
def test_next_reports_why_nothing_is_offered(api):   # too few alternatives -> reason 'not_enough_alternatives'; fourth in a week -> 'rate_limited'
def test_prompts_make_no_model_call(api):   # spy untouched across the whole flow
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the four routes and the two functions (extend `STATUS`/`CODES` where needed). **Step 4: Run** `tests/test_feedback_api.py tests/test_feedback_prompts.py tests/web/test_preferences.py tests/test_preference_service.py` → PASS.
- [ ] **Step 5: Commit** `feat: native API for targeted comparisons and questions`.

### Task 9: Release check, documentation and workflow example

**Files:**
- Modify: `pipeline/agentic/CHAT.md` (new section "Feedback, rules and selection": a route table with scopes like the profile table, error codes, the rule that agents hold no `interact`/`approve` token), `README.md` (profile workflow steps for rejecting, rules, selection, prompts), `pipeline/agentic/MATCHING.md` (one paragraph: comparisons and the cold-start rule; the full-suite figure only from the real run), `.github/workflows/backend.yml` (add the new test files to the `synthetic-backend` list)
- Create: `docs/examples/feedback-selection.md`

- [ ] **Step 1:** Run the full suite once: `JOBWATCH_SETTINGS=/dev/null PY -m pytest -q -p no:cacheprovider` (about 20 minutes; ignore the ten Playwright collection errors only if the `browser` extra is not installed, and say so). Record the exact passed/failed/skipped line; show any failure to be pre-existing on `origin/main` with evidence.
- [ ] **Step 2:** `git diff --stat origin/main -- pipeline/agentic/skills jobwatch/preferences` must be empty (no skill or preference-file edits; `skill_version()` and `versions()` unchanged).
- [ ] **Step 3:** Write `docs/examples/feedback-selection.md` in the style of `docs/examples/profile-intake.md`: shortlist, reject with a reason, suggested rule, rule confirmation (digest shown), shortlist after the rule, next comparison, pick, selection, run polling, the READY outcomes. Capture real responses from a one-off script run against the synthetic world with `TestClient` (keep the script outside the repo); shorten ids as the existing example does; say plainly that no hosted model and no real person's record was used.
- [ ] **Step 4:** Update CHAT.md, README, MATCHING.md, the CI list. State in CHAT.md that board actions (`hide`, `save`) are not feedback events.
- [ ] **Step 5: Commit** `docs: feedback, rules and selection workflow; release check`; push the branch, open the PR with checks and exact results, rulings, limitations, unverified items and the undo steps below.

## Owner decisions (the executor uses the default and does not block)

1. **Prompt rate.** Default: one open prompt, at most 3 issued per rolling 7 days, never required (`feedback.prompts_per_week` overrides; 0 disables).
2. **Answers to targeted questions.** Default: recorded verbatim, no profile change. Making an answer a profile amendment needs a small digest-bound confirmation like rules; owner to say whether to add it.
3. **Undoing a rejection.** Default: none; a rejection is permanent for that posting (the contract has no undo event kind). Owner to say if an `unreject` kind should be added.
4. **Rule enforcement needs `pipeline.agentic.decision_policy: profile`.** Default: `legacy`, so a confirmed rule is stored and listed but not applied (the confirmation says `inactive_legacy_gate`). Switching to `profile` is Plan 2's owner decision; it costs no model call and moves no run key.
5. **Chat parity.** Default: no feedback or selection chat tool (a model-callable writer of choices needs a gated human interrupt like `profile_confirm`); the API is the only writer.
6. **Real posterior.** The information-gain path is verified only with synthetic fits; no valid owner fit exists in CI (no R/JAGS). Its behaviour on the owner's real fit is unverified until they have 20 train and 5 holdout answered sets.

## Rollback

Revert the merge commit. Left behind, all private to the person and harmless to older code:
- Database: tables `feedback_events` (immutable by trigger) and `feedback_prompts`; `PRAGMA user_version` stays at the new migration number, which older code accepts. To remove: back up, then `DROP TRIGGER` for the two `feedback_events` triggers, `DROP TABLE feedback_events; DROP TABLE feedback_prompts;` and set `PRAGMA user_version` back by one. Preference sets and picks created by comparisons are the person's genuine answers and are kept (they are immutable by design).
- Files: `<person>/intake/rules/` (delete the folder). Amendment versions are the newest `profile-versions/<n>/` whose `approved.json` has an `amendment` key; older code reads them as normal versions. To undo a rule, delete only trailing amendment version directories (never one a later non-amendment version builds on) and confirm `discovery_scope(person)` still returns the previous scope.
- API runs for selections stay in `career-chat/state.sqlite`; prepared packages are normal packages and are untouched by the revert.

## Self-review

- Spec coverage: rejection reasons with meaning (Task 2–3); explicit exclusions as rules, enforced at once (4–5); targeted comparisons by expected information gain with a cold-start rule, rate-limited (7–8); selection plus preparation approval, documents only for selected jobs (6); agent output never a person's choice (actor fixed, scope-gated, tests in 3, 5, 6, 8); exposure logging for selection bias (2, 7); insufficient feedback never blocks discovery (7); examples, rollback and limitations (9, above).
- Type consistency: `FeedbackEvent`, `Comparison`, `TargetedQuestion`, `Reason` are defined once (Tasks 2, 7) and used unchanged in 3, 5, 6, 8; recorder signatures match their call sites in Tasks 5, 6, 8; rule fact shape is identical in Tasks 4 and 5 and the ADR.
- Limitations stated: board `hide`/`save` are not feedback events; no chat tools; answers do not change the profile; rejection is permanent; selection is not training data for the choice model; selection-bias correction is Plan 6b's.

## Contract reconciliation

Reconciled decisions of the [cross-plan contract](2026-10-21-cross-plan-contract.md) that apply to this plan; all are applied above.

- **3 Flag for the profile policy:** exclusion rules take effect immediately only with `pipeline.agentic.decision_policy: profile`; the confirmation response states `enforcement` (Task 5).
- **4 Run key stays stable:** `DecisionPolicy` fields never enter `RunKey.config_hash`; Task 5 keeps the regression test `test_confirming_a_rule_does_not_change_any_run_key`, and the earlier flag-gated fallback is removed.
- **6 Exclusion facts to rules:** a confirmed rule is an evidence-basis `exclusion` fact with value `{"kind", "value"}` and id `r<n>`, which Plan 2's `rules_from_fact` turns into an `ExclusionRule` with `source_fact_id` (Task 4 test `test_a_confirmed_rule_becomes_an_exclusion_rule_in_the_policy`); matching is Plan 2's `exclusion_hit`, and the discovery pre-filter is Plan 3's `enforce_exclusions` (Task 5).
- **7 Relevance is stored:** `discovery.enforce_exclusions(conn, config, *, person=None)` is called after a rule is confirmed (Task 5).
- **10 Ranking modules:** shortlist reads go through `shortlist.build_shortlist`, `latest_entries` and `load_entry`; feedback, selection and prompt routes live in `pipeline/agentic/feedback_api.py` (Tasks 2, 3, 6, 8).
- **12 Preference features:** `preference_picks.actor` stays `'owner'` (the existing immutable table); comparisons write `owner` there after the API's person check, and the event log carries `person` (Task 8).
- **14 Signature additions:** `next_comparison(conn, person, config=None)` (Task 7).
- **15 Migrations:** `feedback_events` and `feedback_prompts` take the next free `MIGRATIONS` index at execution (Task 2).

Routes `/feedback/next`, `/feedback/comparisons/*/pick`, `/feedback/questions/*/answer`, `/feedback/prompts/*/dismiss`, `GET /feedback` and `GET /profile/rules` are additions to the contract's list.
