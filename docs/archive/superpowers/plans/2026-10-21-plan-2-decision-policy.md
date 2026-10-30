# Plan 2: Decision policy from the confirmed profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive a versioned, hashable decision policy and search strategy from the person's confirmed profile, and make the deterministic gate read that policy instead of one person's constants, regexes and profile files, behind a flag that defaults to today's behaviour.

**Architecture:** A pure module `jobwatch/candidate/policy.py` builds `DecisionPolicy` from the facts of an approved profile version (`policy_for(person, *, approved=None)`; `approved` is a baseline's frozen `approved.json`, defaulting to `intake.current_version(person)`); only facts with basis `evidence` become rules, and only an `exclusion` fact whose value is `{"kind", "value"}` becomes an `ExclusionRule`. `pipeline/agentic/gate.py` `decide(...)` gets an optional `decision_policy` and a `company`; the person-dependent block is split into `_legacy_person_checks` (today's code, kept verbatim as the `legacy` baseline) and `_policy_checks` (reads only the policy; location recomputed from the verified ad quote). `pipeline/agentic/service.py` creates `gate_current(...)`, the one live gate call that the run, the preference pool and (in later plans) the shortlist, rule checks and replay all use, and loads the policy only when `pipeline.agentic.decision_policy` is `profile`; the flag is read outside `_config()` and no `DecisionPolicy` field enters a run key.

**Tech Stack:** Python 3.12, pydantic v2 (`StrictFrozen`), SQLite (one lazily created table), FastAPI, pytest with synthetic data.

**Spec:** [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md) sections 2 and 4, [roadmap](2026-10-21-backend-roadmap.md) Plan 2, [cross-plan contract](2026-10-21-cross-plan-contract.md) "Phase 3 — Plan 2" and "Reconciled decisions" (binding; applied here, see "Contract reconciliation" at the end), [code map](reference/2026-10-21-codemap.md) section 2 (line numbers as of `ce9e342`; re-check before editing).

## Global Constraints

- "Unemployed, no contrary instruction: employment-first discovery across permitted fields using relatable skills." / "Explicit career or degree focus: prioritise the requested direction." / "Explicit exclusions: always respect them; unemployment never overrides them." / "Missing information: ask when it materially affects a decision; do not silently treat it as failure." / "Changed circumstances or instructions: update the search strategy using the current confirmed profile and user direction." (brief §2)
- "Remove person-specific assumptions from application code. Preserve genuine eligibility constraints." Genuine eligibility = work rights and hours limits stated by the person. (brief §2)
- "Explicit exclusions are rules." "Never record agent-generated answers as user choices or approval." Policy is read from confirmed facts only; nothing here writes a fact, a rule or an approval. (brief §4)
- Synthetic data only: never copy any live candidate value (the owner's hours, distance, families, suburb) into code, tests, ADR or examples.
- Per-person isolation: `policy_for(person)` reads that person's versions; no module-level cache keyed by anything but person and version.
- Paid model calls only through approved routes with `require_route`; this plan adds none. Tests use the existing synthetic transports.
- No service/timer activation, no submission or employer contact, no change to `jobwatch/apply/submit_confirm.py`.
- Schema changes additive: no stored model changes; `AgenticEvaluation.location_fit` keeps its literal `'melbourne'`; `default_policy()` and the JSON of `TargetPolicy` it returns are unchanged (they are hashed into run keys: `service._run_key` digests `policy.model_dump`; Task 7 pins this with a literal digest).
- Run-key rule (contract rule 1 and decision 4): this plan changes none of `_config()`, the `default_policy()` output, `IMPLEMENTATION_VERSION`, `LOCATION_REFERENCE_HASH`, evaluator prompts. `DecisionPolicy` fields (`exclusions`, `profile_version`, `policy_hash`, `open_questions`) never enter `RunKey.config_hash`; Task 6 tests it. Expected paid re-run cost from this plan: 0 jobs x 3 model roles. The new flag `pipeline.agentic.decision_policy` (`legacy | profile`) defaults to `legacy` and is NOT added to `_config()`.
- Preference-file rule (contract rule 5): do not edit any file under `jobwatch/preferences/`.
- Profile reads come from `intake.current_version(person)` (contract rule 3). Do not edit `jobwatch/candidate/intake.py` (Plan 1 owns it); import it lazily.
- Python 3.12 virtualenv outside the repo; test command `<venv>/bin/python -m pytest -q -p no:cacheprovider <paths>`. Branch `claude/phase-3-decision-policy` from `main`.

## Review Focus

1. Unemployed person who also stated an exclusion: employment-first never lets an excluded job through, and an exclusion stated only as free text is not silently dropped: it becomes an open question until the person says which kind it is (Task 3 `test_unemployment_never_overrides_exclusions` and `test_free_text_exclusion_stays_prompt_text_and_asks`, Task 4 `test_unemployment_does_not_override_exclusion`).
2. Person who stated nothing about location, commute, hours or level: no archive or hold comes from the missing fact; it becomes an open question (Task 3 `test_no_location_facts_means_no_area_limit`, Task 4 `test_no_location_policy_never_blocks_on_location`, Task 5 `test_no_hours_limit_never_archives_on_hours`).
3. Person outside Victoria (synthetic NSW): a Sydney job is not archived, a Melbourne on-site job is; nothing consults the Victorian place data to decide the region (Task 2, Task 4).
4. A fact the parser only inferred ("probably avoids retail", a guessed distance) never becomes a rule (Task 3 `test_inference_and_unknown_facts_never_become_rules`).
5. A citizen or permanent resident is not archived by a plain "citizens and PR only" ad, but a security clearance demand still stops the job; an unknown or visa-limited person keeps today's behaviour exactly (Task 5).

---

### Task 1: Record the design (ADR and glossary)

**Files:**
- Create: `docs/adr/<next free number>-decision-policy-from-confirmed-profile.md` (0003 unless taken at execution time; check `ls docs/adr`)
- Modify: `GLOSSARY.md` (terms: Decision policy, Search strategy, Exclusion rule, Eligibility constraint, Open question, Policy flag)

- [ ] **Step 1: Write the ADR** (Context, Status Accepted, Decision, Consequences, References to brief §2/§4 and owner words "Remove person-specific assumptions from application code"). The Decision section must state, in this order: (a) the policy is built only from approved facts with basis `evidence`; inferred and unknown facts stay questions; (b) it is separate from `TargetPolicy` so run keys do not move; (c) flag `pipeline.agentic.decision_policy: legacy | profile` (default `legacy`, outside `_config()`); with `profile` and no confirmed scope-bearing version the legacy path runs; exclusion rules take effect immediately only with `profile`; (d) the five search rules as implemented (derivation table in Task 3); (e) exclusion kinds: an `exclusion` fact whose value is `{"kind", "value"}` becomes an `ExclusionRule` (with `source_fact_id`); a free-text exclusion stays prompt text (it is not enforced by the gate) and adds the open question `exclusion:<fact_id>` asking the person which kind it is, to be answered through Plan 5's digest-bound rule confirmation; (f) location is recomputed from the verified ad quote because the first model pass never sees the candidate, so the stored label `location_fit='melbourne'` is not trusted as "home region" (renaming it would change evaluator prompts and require a paid re-evaluation); (g) the person-specific branches remain only in `_legacy_person_checks` as the `legacy` comparison baseline and are deleted in a follow-up once the owner has re-confirmed and switched to `profile`; (h) `gate_current` is the one live gate call and every gate caller uses it; (i) `MINIMUM_EXCLUDED_CODES` (two built-in occupation codes hashed into every run key through `TargetPolicy`) is parametrised, not removed, because removing it would re-key every stored job (Task 7); (j) deferred to other plans: collection pre-filter and `_target_first` (Plan 3), holistic-score gate and preference families (Plan 4). Consequences: every wrong rule is visible in `GET /api/agent/profile/policy`.
- [ ] **Step 2: Add the six glossary rows** (one sentence each; "Policy flag" = `pipeline.agentic.decision_policy` with values `legacy` and `profile`).
- [ ] **Step 3: Commit** `docs: ADR decision policy from the confirmed profile`.

### Task 2: Region and commute evidence without a fixed home state

**Files:**
- Modify: `pipeline/agentic/location.py` (add; keep every existing function and the reference hash byte-identical)
- Test: `tests/test_location_policy.py`

**Interfaces:**
- Produces:
  - `CAPITALS: dict[str, str]` (sydney NSW, melbourne VIC, brisbane QLD, perth WA, adelaide SA, hobart TAS, canberra ACT, darwin NT)
  - `regions_named(text: str) -> frozenset[str]` — state codes (case-sensitive word), full state names, capital cities, and, only when the text names no state, a Victorian place from `vic-geo.json` (via `victorian_place`); a state named in the text always wins over place data ("Richmond NSW" is NSW).
  - `location_verdict(quote: str, regions: frozenset[str], *, remote_fit: bool, remote_ok: bool | None) -> Literal['in','outside','remote','unknown']` — empty `regions` -> `'in'`; named regions intersecting `regions` -> `'in'` (alternatives such as "Melbourne VIC or Sydney NSW" count); named regions all outside -> `'outside'`, unless `remote_fit` and the quote has `remote|work from home|anywhere in Australia` and `remote_ok is not False` -> `'remote'`; no region named: remote words with `remote_fit` -> `'remote'`, else `'unknown'`.
  - `commute_km_for(home_place: str | None, location_text: str) -> int | None` — distance only when both `victorian_place(home_place)` and `victorian_place(location_text)` are in `VIC_PLACES`; otherwise None (documented limit: distance data exists for Victoria only).

- [ ] **Step 1: Write the failing tests:**

```python
@pytest.mark.parametrize('text,expect', [('Sydney NSW', {'NSW'}), ('Parramatta, New South Wales', {'NSW'}), ('Melbourne, VIC; Sydney, NSW', {'VIC', 'NSW'}),
    ('Box Hill campus', {'VIC'}), ('Richmond NSW', {'NSW'}), ('Perth WA', {'WA'}), ('Remote, Australia wide', set()), ('Level 3, 1 Example St', set())])
def test_regions_named(text, expect): assert regions_named(text) == frozenset(expect)

@pytest.mark.parametrize('quote,regions,remote_fit,remote_ok,expect', [
    ('Sydney NSW', {'NSW'}, False, None, 'in'), ('Sydney NSW', {'VIC'}, False, None, 'outside'),
    ('Melbourne VIC or Sydney NSW', {'VIC'}, False, None, 'in'),
    ('Work from home anywhere in Australia', {'VIC'}, True, None, 'remote'),
    ('Remote, Sydney NSW', {'VIC'}, True, False, 'outside'),
    ('Level 3, 1 Example St', {'VIC'}, False, None, 'unknown'), ('Anywhere', set(), False, None, 'in')])
def test_location_verdict(quote, regions, remote_fit, remote_ok, expect):
    assert location_verdict(quote, frozenset(regions), remote_fit=remote_fit, remote_ok=remote_ok) == expect

def test_commute_km_for_uses_victorian_data_only():
    assert 5 <= commute_km_for('Box Hill, VIC', 'Carlton VIC') <= 20
    assert commute_km_for('Box Hill, VIC', 'Sydney NSW') is None and commute_km_for(None, 'Carlton VIC') is None
    assert commute_km_for('Sydney NSW', 'Carlton VIC') is None

def test_existing_location_reference_hash_is_unchanged():
    assert location.LOCATION_REFERENCE_HASH == hashlib.sha256(files('pipeline.agentic').joinpath('data/metro-localities.json').read_bytes()).hexdigest()
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_location_policy.py` -> FAIL.
- [ ] **Step 3: Implement** in `location.py` below `km_from_home`, reusing `_PLACE_NAMES`, `victorian_place`, `_km`, `VIC_PLACES` and `jobwatch.place.STATES`. Do not change `cited_victoria_location`, `km_from_home`, `home_place` or the data files (they stay the legacy path).
- [ ] **Step 4: Run** the new file plus `tests/test_localities.py tests/test_agentic_gate.py` -> PASS.
- [ ] **Step 5: Commit** `feat: person-independent region and commute evidence`.

### Task 3: `DecisionPolicy`, search strategy, exclusions, `policy_for`

**Files:**
- Modify: `jobwatch/candidate/policy.py` (keep `default_policy` untouched)
- Create: `tests/candidate/policy_fixtures.py`, `tests/candidate/test_policy.py`

**Interfaces:**
- Consumes: `intake.current_version(person) -> dict | None` (lazy import), `intake._kinds` / `intake._STATUS_VALUE` (employment words; do not copy the regexes), `projection._text`, `projection._work_rights(approved) -> dict`, `contracts.canonicalize_family`, `KNOWN_FAMILIES`, `contracts.StrictFrozen`, `contracts.digest`, `pipeline.agentic.location.regions_named` (Task 2).
- Produces (contract names unchanged):
  - `class ExclusionRule(StrictFrozen)`: `rule_id: str`, `kind: Literal['family','employer','title_term','location','work_type']`, `value: str`, `source_fact_id: str | None = None`, `actor: Literal['person'] = 'person'`
  - `class DecisionPolicy(StrictFrozen)`: `profile_version: int`, `strategy: Literal['employment_first','career_focus','balanced']`, `focus: tuple[str, ...]`, `exclusions: tuple[ExclusionRule, ...]`, `home: dict | None` (`place`, `state`, `country`), `max_commute_km: float | None`, `remote_ok: bool | None`, `work_rights: dict`, `seniority: tuple[str, ...]`, `open_questions: tuple[str, ...]` (codes), `policy_hash: str`, plus additive `regions: tuple[str, ...] = ()` (AU state codes the person will work in; empty = no area limit). A model validator recomputes `policy_hash` (sha256 of the canonical JSON of every other field) and raises `ValueError('policy_hash_mismatch')`.
  - `strategy_for(facts: Iterable[dict]) -> Literal['employment_first','career_focus','balanced']`
  - `rules_from_fact(fact: dict) -> list[ExclusionRule]` (contract decision 6): one rule when the fact is an evidence-basis `exclusion` whose value is a dict `{"kind": <one of the five kinds>, "value": <non-empty text>}`, with `source_fact_id` = the fact id; `[]` for anything else (free text, unknown kind, empty value)
  - `build_policy(approved: dict) -> DecisionPolicy` (pure; `approved` is an `approved.json` dict)
  - `policy_for(person: str, *, approved: dict | None = None) -> DecisionPolicy | None` (contract decision 1) — `approved` is an `approved.json` payload (a baseline's frozen copy) and defaults to `intake.current_version(person)`; None unless the payload has `scope`, `scope_digest` and non-empty `facts`; unreadable files log a warning and return None.
  - `exclusion_hit(policy, *, family: str | None, company: str, title: str, location_text: str, remote: bool, hours: str) -> ExclusionRule | None` (`family=None`: no family known, a `family` rule cannot hit)
  - `describe(person: str, *, mode: str) -> dict` (used by Task 8; `mode` is `legacy` or `profile`)
  - Helpers in `tests/candidate/policy_fixtures.py`: `fact(section, value, basis='evidence', fid=None, actor='person') -> dict`, `approved(*facts, version=2) -> dict` (scope present), `policy_of(*facts, version=2) -> DecisionPolicy`.

Derivation rules (only `basis == 'evidence'` facts; a value is a string or a dict; dict keys win over text; an `exclusion` is a rule only in dict form, contract decision 6):

| Field | Source | Rule |
|---|---|---|
| `strategy` | `career_focus`, `employment_status` | any evidence `career_focus` -> `career_focus`, `focus` = their texts (max 20, 200 chars); else status kinds contain `unemployed` and not `employed` -> `employment_first`; else `balanced` |
| `exclusions` | `exclusion` | `rules_from_fact`: only a dict value `{'kind','value'}` with a kind in the five becomes a rule, as given (a `family` value is passed through `canonicalize_family` and must be in `KNOWN_FAMILIES`, else it is not a rule). Free text and malformed dicts stay prompt text: no rule, and the open question below |
| `regions`, `remote_ok` | `location`, `constraint`, `preference` | union of `regions_named(text)`; "australia-wide/nationwide/anywhere in australia" clears regions; `remote_ok` True for `remote\|work(ing)? from home\|wfh`, False for `no remote\|not remote\|on-?site only\|in-person only` (False wins) |
| `home` | `location` | dict key `home`, or text after `live(s\|d) in\|based in\|reside(s) in\|home:` up to `;`, `.`, ` and `, ` but `; `{'place', 'state' (first region named), 'country': 'AU'}` |
| `max_commute_km` | `constraint`, `location` | dict key, or `(\d+(\.\d+)?)\s*(km\|kilomet\w+)` in a sentence containing `commute\|travel\|within\|from home`; the smallest wins |
| `work_rights` | `work_rights` | `projection._work_rights(approved)`, plus `citizen_or_pr`: `False` if the text says not/non citizen or not PR; else `True` if it says Australian citizen or permanent resident; else key absent |
| `seniority` | `preference`, `career_focus`, `constraint` (dict key `seniority` too) | ladder `entry<junior<mid<senior`; words entry/graduate/intern/trainee/cadet/early-career -> entry, junior -> junior, mid-level/intermediate -> mid, senior/lead/principal/manager/director -> senior; phrases negated by `no\|not\|never\|avoid\|without` within three words are ignored |
| `open_questions` | absence | `employment_status` (no evidence status), `work_rights` (no evidence fact), `location` (no regions and no home), `career_focus` (strategy `balanced` only), `exclusion:<fact_id>` for each evidence-basis `exclusion` fact that did not become a rule (the person is asked which kind it is: employer, kind of work, place, family or title term) |

`exclusion_hit` rules: `family` equals canonical family; `employer` whole-word match in the casefolded company; `title_term` whole-word match in the casefolded title; `work_type` remote <-> `remote`, casual <-> `hours == 'casual'`, full_time <-> `hours == 'full_time_only'`, part_time <-> title matches `part[- ]?time`; `location` (state code) hits only when `regions_named(location_text) == {code}` (alternatives elsewhere survive), a dict-given place token hits on a whole-word match when the text has no `;`, `/`, `|` or `or` alternative.

- [ ] **Step 1: Write the failing tests** in `tests/candidate/test_policy.py` (all facts via `fact(...)`, synthetic person "Alex Example"):

```python
def test_unemployed_without_contrary_instruction_is_employment_first():
    p = policy_of(fact('employment_status', 'Currently unemployed, seeking work'), fact('experience', 'Accounts Assistant, Ledger Co'))
    assert (p.strategy, p.focus) == ('employment_first', ())

def test_career_focus_wins_over_unemployment():
    p = policy_of(fact('employment_status', 'Currently unemployed'), fact('career_focus', 'Junior data analyst roles'))
    assert (p.strategy, p.focus) == ('career_focus', ('Junior data analyst roles',))

def test_unemployment_never_overrides_exclusions():
    p = policy_of(fact('employment_status', 'Currently unemployed'), fact('exclusion', {'kind': 'family', 'value': 'retail'}, fid='f9'))
    assert p.strategy == 'employment_first'
    assert [(r.kind, r.value, r.source_fact_id, r.actor) for r in p.exclusions] == [('family', 'retail', 'f9', 'person')]

def test_inferred_unemployment_and_unknown_status_are_balanced_and_ask():
    p = policy_of(fact('employment_status', 'unemployed', basis='inference'))
    assert p.strategy == 'balanced' and 'employment_status' in p.open_questions

def test_inference_and_unknown_facts_never_become_rules():
    p = policy_of(fact('exclusion', {'kind': 'family', 'value': 'hospitality'}, basis='inference'), fact('constraint', 'commute under 10 km', basis='inference'),
                  fact('work_rights', '40 hours per fortnight', basis='unknown'))
    assert p.exclusions == () and p.max_commute_km is None and 'hours_limit_per_fortnight' not in p.work_rights

@pytest.mark.parametrize('value', ['no remote work', 'casual jobs', 'never in Sydney', 'Acme Pty Ltd', {'kind': 'salary', 'value': 'x'}, {'kind': 'employer', 'value': ''}])
def test_free_text_exclusion_stays_prompt_text_and_asks(value):      # contract decision 6
    p = policy_of(fact('exclusion', value, fid='x1'))
    assert p.exclusions == () and 'exclusion:x1' in p.open_questions

@pytest.mark.parametrize('kind,value', [('family', 'retail'), ('employer', 'Example Co'), ('title_term', 'sales'), ('location', 'NSW'), ('work_type', 'remote')])
def test_a_structured_exclusion_becomes_a_rule_with_its_source_fact(kind, value):
    p = policy_of(fact('exclusion', {'kind': kind, 'value': value}, fid='x2'))
    assert [(r.kind, r.value, r.source_fact_id, r.actor) for r in p.exclusions] == [(kind, value, 'x2', 'person')]
    assert not any(q.startswith('exclusion:') for q in p.open_questions)

def test_a_family_rule_value_must_be_a_known_family():
    p = policy_of(fact('exclusion', {'kind': 'family', 'value': 'not-a-family'}, fid='x3'))
    assert p.exclusions == () and 'exclusion:x3' in p.open_questions

def test_location_and_commute_are_read_from_evidence_text():
    p = policy_of(fact('location', 'I live in Box Hill, VIC; open to Melbourne or remote work'), fact('constraint', 'Will not commute more than 30 km'))
    assert p.home == {'place': 'Box Hill, VIC', 'state': 'VIC', 'country': 'AU'}
    assert (p.regions, p.remote_ok, p.max_commute_km) == (('VIC',), True, 30.0)

def test_no_location_facts_means_no_area_limit():
    p = policy_of(fact('experience', 'Accounts Assistant'))
    assert (p.regions, p.home, p.max_commute_km, p.remote_ok) == ((), None, None, None) and 'location' in p.open_questions

def test_work_rights_come_from_approved_facts():
    p = policy_of(fact('work_rights', 'Student visa, up to 48 hours per fortnight'), fact('work_rights', {'full_time_programs_ok': True}))
    assert p.work_rights['hours_limit_per_fortnight'] == 48 and p.work_rights['full_time_programs_ok'] is True

@pytest.mark.parametrize('text,expect', [('Australian citizen', True), ('Permanent resident of Australia', True),
                                         ('I am not an Australian citizen', False), ('Working holiday visa', None)])
def test_citizen_or_pr_detection(text, expect):
    assert policy_of(fact('work_rights', text)).work_rights.get('citizen_or_pr') is expect

def test_seniority_from_stated_levels_ignores_negated_ones():
    assert policy_of(fact('preference', 'Looking for graduate and junior roles')).seniority == ('entry', 'junior')
    assert policy_of(fact('preference', 'no senior roles please')).seniority == ()
    assert policy_of(fact('experience', 'Senior Accountant, Ledger Co')).seniority == ()

def test_policy_hash_is_stable_and_tracks_content_and_version():
    ex = {'kind': 'family', 'value': 'retail'}
    a, b = policy_of(fact('exclusion', ex)), policy_of(fact('exclusion', ex))
    assert a.policy_hash == b.policy_hash and policy_of(fact('exclusion', ex), version=3).policy_hash != a.policy_hash
    with pytest.raises(ValueError, match='policy_hash_mismatch'):
        DecisionPolicy.model_validate({**a.model_dump(mode='json'), 'policy_hash': '0' * 64})

def test_changed_circumstances_change_the_strategy():
    v2 = policy_of(fact('employment_status', 'Currently unemployed'), version=2)
    v3 = policy_of(fact('employment_status', 'Currently unemployed'), fact('career_focus', 'Nursing'), version=3)
    assert (v2.strategy, v3.strategy) == ('employment_first', 'career_focus')

def test_policy_for_needs_a_confirmed_scope_bearing_version_and_is_per_person(monkeypatch):
    versions = {'fx-a': approved(fact('experience', 'Accounts Assistant')), 'fx-adopted': {'version': 1, 'facts': [], 'adopted_from_files': True}}
    monkeypatch.setattr(intake, 'current_version', lambda person: versions.get(person))
    assert policy_for('fx-a').profile_version == 2 and policy_for('fx-b') is None and policy_for('fx-adopted') is None

def test_policy_for_builds_from_a_pinned_approved_payload(monkeypatch):    # contract decision 1: a baseline's frozen approved.json
    live = approved(fact('exclusion', {'kind': 'family', 'value': 'retail'}), version=3)
    monkeypatch.setattr(intake, 'current_version', lambda person: live)
    frozen = approved(fact('exclusion', {'kind': 'family', 'value': 'accounting'}), version=2)
    pinned, current = policy_for('fx-a', approved=frozen), policy_for('fx-a')
    assert (pinned.profile_version, pinned.exclusions[0].value) == (2, 'accounting') and (current.profile_version, current.exclusions[0].value) == (3, 'retail')
    assert policy_for('fx-a', approved={'version': 1, 'facts': []}) is None
    assert policy_for('fx-a', approved=frozen).policy_hash == pinned.policy_hash          # deterministic
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/candidate/test_policy.py` -> FAIL (names not defined).
- [ ] **Step 3: Implement** the interfaces above in `jobwatch/candidate/policy.py`. `rule_id` = `f"{source_fact_id}:{kind}"`, or the first 12 hex of sha256 of `kind|value` when there is no fact id. `exclusion_hit` is pure and total (never raises on odd text).
- [ ] **Step 4: Run** the same command -> PASS; also `tests/candidate/test_contracts.py tests/candidate/test_acceptance.py` (default policy untouched).
- [ ] **Step 5: Commit** `feat: decision policy and search strategy from the confirmed profile`.

### Task 4: Gate reads the policy: location, commute, exclusions, families

**Files:**
- Modify: `pipeline/agentic/gate.py`
- Test: `tests/test_agentic_gate_policy.py` (imports the `evaluation` fixture: `from test_agentic_gate import evaluation, policy  # noqa: F401`, as `tests/test_agentic_matching.py:15` does)

**Interfaces:**
- Consumes: `DecisionPolicy`, `exclusion_hit` (Task 3); `regions_named`, `location_verdict` (Task 2).
- Produces: `decide(evaluation, *, ad_text, title='', policy: TargetPolicy, captured_complete=True, expected_run_key=None, evidence_bundle=None, commute_km=None, decision_policy: DecisionPolicy | None = None, company: str = '') -> AgenticGateDecision` (contract decision 2: `policy` stays the run-key `TargetPolicy`; the new policy is the keyword `decision_policy`). Wrong types raise `AgenticError('invalid_gate_input')`. With `decision_policy=None` every result is identical to today. Callers outside `service.gate_current` (Task 6) must not call `decide` directly.
- Structure (gate.py lines as of `9458f44`): keep lines 177-251 and 343-354 where they are. Extract lines 253-270 (real job + rights) into `_rights_checks(evaluation, ad_text, title, *, citizen_ok=False)` (Task 5 uses the flag). Move lines 272-341 (location through hours, including `MAX_COMMUTE_KM`, `cited_victoria_location`, the interstate regex, `_family_from_archetype`, `excluded_families()`) unchanged into `_legacy_person_checks(...)` with a comment "legacy baseline; delete after the owner switches the policy flag to profile". Add `_policy_checks(evaluation, ad_text, title, company, dp, commute_km)`.
- `_policy_checks` order: (1) exclusion rules via `exclusion_hit(dp, family=canonicalize_family(facts.role_family), company=company, title=title, location_text=<verified quote or ''>, remote=location_fit=='remote_accessible', hours=facts.hours)` -> `archive/policy_excluded`; (2) location, only when `dp.regions` or a location/commute rule exists: verified `location_evidence` required else `hold/insufficient_evidence`; verdict from `location_verdict(quote, set(dp.regions), remote_fit=evaluation.location_fit=='remote_accessible', remote_ok=dp.remote_ok)`: `outside` -> `archive/hard_gate`, `unknown` -> `hold/insufficient_evidence` unless the program "nominate your office" exception holds (same regex as today, now without the city word); (3) the US/UK/Canada/NZ-only archive, unchanged text (the product is Australia-only); (4) generalised interstate on-site rule: today's regex built from `CAPITALS` whose state is not in `dp.regions`, skipped when `dp.regions` is empty or the matched span names an allowed region; (5) commute: `dp.max_commute_km` and `commute_km` known and `commute_km > dp.max_commute_km` and verdict is not `remote` -> `archive/hard_gate` (no default distance). The stored `location_fit` values `'melbourne'` and `'outside'` are ignored; only `'remote_accessible'` and the verified quote matter. No family allow-list check (TargetPolicy.allowed_families is not consulted) and no `excluded_families()` or archetype regex.
- Level and hours blocks are added in Task 5; until then `_policy_checks` returns None after step (5).

- [ ] **Step 1: Write the failing tests** (helper `retarget(evaluation, ad, quote, **changes)` in the test file rebuilds `run_key.ad_hash`, `requirements.ad_hash` and the citation hash for a new `ad` and quote; `dp = policy_of(...)`):

```python
def test_nsw_person_is_not_archived_for_a_sydney_job(evaluation, policy):
    ev = retarget(evaluation, 'Graduate accounting analyst based in the Sydney NSW office. Australian work rights required.', 'Sydney NSW')
    assert decide(ev, ad_text=SYDNEY_AD, policy=policy, decision_policy=policy_of(fact('location', 'Sydney, NSW'))).route == 'draft'   # legacy label 'melbourne' is ignored; SYDNEY_AD is the ad text passed to retarget

def test_nsw_person_archives_a_melbourne_job(evaluation, policy):
    ev = retarget(evaluation, 'Graduate accounting analyst based in Melbourne VIC. Australian work rights required.', 'Melbourne VIC')
    assert decide(...decision_policy=nsw) == ... ('archive', 'hard_gate')

def test_interstate_onsite_rule_follows_the_persons_regions(evaluation, policy):
    # VIC person: 'Sydney office attendance required' archives (parity); same ad for a NSW person drafts; no regions -> drafts

def test_no_location_policy_never_blocks_on_location(evaluation, policy):
    ev = evaluation.model_copy(update={'location_fit': 'unknown', 'location_evidence': None})
    assert decide(ev, ad_text=AD, policy=policy, decision_policy=policy_of(fact('experience', 'x'))).route == 'draft'

def test_unknown_location_with_regions_holds(evaluation, policy):  # quote 'Level 3, 1 Example St', regions VIC -> ('hold', 'insufficient_evidence')

def test_commute_limit_comes_only_from_the_policy(evaluation, policy):
    dp30, dp_none = policy_of(fact('constraint', 'no more than 30 km commute'), fact('location', 'Melbourne')), policy_of(fact('location', 'Melbourne'))
    # commute_km=40 -> ('archive','hard_gate'); 25 -> draft; dp_none with commute_km=500 -> draft; remote_accessible ad with 40 -> draft

def test_exclusions_are_rules(evaluation, policy):  # rules built from dict facts {'kind', 'value'}; parametrised: family accounting -> policy_excluded; employer 'example' with company='Example Pty Ltd' -> policy_excluded;
    # title_term 'graduate' (title 'Graduate Accountant'); work_type remote with remote_accessible ad; location NSW with quote 'Sydney NSW' -> policy_excluded,
    # same rule with quote 'Sydney NSW or Melbourne VIC' -> draft; employer rule 'sales' with company 'Salesforce Pty' -> draft (whole word only)

def test_unemployment_does_not_override_exclusion(evaluation, policy):
    dp = policy_of(fact('employment_status', 'Currently unemployed'), fact('exclusion', {'kind': 'family', 'value': 'accounting'}))
    assert (decide(evaluation, ad_text=AD, policy=policy, decision_policy=dp).route,) == ('archive',)   # reason policy_excluded; score is 4.0, so the exclusion is the cause

def test_allowed_families_and_live_exclusions_are_not_consulted_on_the_policy_path(evaluation, policy):
    only_acc = TargetPolicy(version='t', allowed_families=('accounting',))
    ev = evaluation.model_copy(update={'facts': evaluation.facts.model_copy(update={'role_family': 'engineering'})})
    assert decide(ev, ad_text=AD, policy=only_acc, decision_policy=policy_of(fact('location', 'Melbourne'))).route == 'draft'   # autouse live profile excludes engineering

def test_policy_path_reads_no_profile_files_or_victoria_constants(evaluation, policy, monkeypatch):
    for name in ('hours_limit_per_fortnight', 'full_time_programs_ok', 'excluded_families', 'cited_victoria_location'):
        monkeypatch.setattr(gate, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(name)))
    assert decide(evaluation, ad_text=AD, policy=policy, decision_policy=policy_of(fact('location', 'Melbourne'))).route == 'draft'

def test_legacy_behaviour_is_unchanged(): the existing tests/test_agentic_gate.py and tests/test_gate_holds.py are run unmodified (step 4)
```

(The executor writes the elided bodies fully; each asserts `(route, reason)` as stated. `AD`, `evaluation`, `policy` come from `tests/test_agentic_gate.py`.)

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_agentic_gate_policy.py` -> FAIL (`decision_policy` unexpected keyword).
- [ ] **Step 3: Implement** the refactor and `_policy_checks` as specified. Pure refactor first (run the existing gate tests green), then add the policy path.
- [ ] **Step 4: Run** `tests/test_agentic_gate_policy.py tests/test_agentic_gate.py tests/test_gate_holds.py tests/test_localities.py` -> PASS with no edit to the two existing gate test files.
- [ ] **Step 5: Commit** `feat: gate location, commute and exclusions follow the decision policy`.

### Task 5: Gate reads the policy: hours, work rights, seniority

**Files:**
- Modify: `pipeline/agentic/gate.py`
- Test: `tests/test_agentic_gate_policy.py` (append)

**Interfaces:**
- Consumes: `DecisionPolicy.work_rights`, `.seniority` (Task 3).
- Produces (all in `gate.py`): `_full_time_exempt(title, ad_text, *, limit, ft_ok)`, `_hours_signals(ad_text, limit)` (live reads removed; the legacy path passes `hours_limit_per_fortnight()` and `full_time_programs_ok()`, the policy path passes the policy's values, resolved once at the top of `decide` so the `unverified_blocker` loop also stops reading files); `_level_signals(title, ad_text) -> (entry: bool, senior_title: bool, years: int | None)` replacing `_entry_signals` (legacy: `senior = senior_title or (years or 0) >= 2`, identical results); `_rights_checks(..., citizen_ok: bool)`; constant `ENTRY_MAX_YEARS = 2` (today's value, now named).
- Policy-path rules in `_policy_checks` after Task 4's steps: **level** only when `dp.seniority` is non-empty: ad level = `facts.seniority`, raised to `senior` by a senior title; archive `hard_gate` when its rank is above the highest stated rank; when the highest stated rank is `junior` or lower also archive `facts.min_years >= ENTRY_MAX_YEARS` or stated years >= `ENTRY_MAX_YEARS`, and hold `insufficient_evidence` when the ad says it is NOT entry level (today's regex). **Hours** only when `limit` is not None: today's excessive-hours and `full_time_only` archives, with the graduate/vacation exemption only when `full_time_programs_ok`. **Rights** `citizen_ok = dp.work_rights.get('citizen_or_pr') is True`: with it, `rule`/`quote_blocking` archive only when the sentence matches `_CLEARANCE = re.compile(r'clearance|vetting|\bNV\s*-?\s*[12]\b|baseline|AGSVA|top secret|\bPV\b', re.I)`, and `rights.requirement in {'citizen_only','citizen_or_pr','unrestricted_work_rights'}` no longer holds (`clearance` still holds). `False` or absent keeps today's behaviour exactly.

- [ ] **Step 1: Write the failing tests** (append):

```python
def test_no_hours_limit_never_archives_on_hours(evaluation, policy):   # full_time_only, non-program ad; dp without work_rights; autouse live profile has a limit -> still 'draft'
def test_hours_limit_from_policy_archives_full_time_only(evaluation, policy):   # dp work_rights '40 hours per fortnight' -> ('archive','hard_gate'); with full_time_programs_ok True and a graduate program ad -> draft
@pytest.mark.parametrize('stated,ad_level,title,years,expect', [
    (('entry','junior'), 'mid', 'Accountant', None, ('archive','hard_gate')),
    (('entry','junior'), 'entry', 'Accountant', 3, ('archive','hard_gate')),
    (('mid',), 'senior', 'Accountant', None, ('archive','hard_gate')),
    (('mid',), 'mid', 'Senior Accountant', None, ('archive','hard_gate')),
    (('mid',), 'mid', 'Accountant', 3, ('draft','eligible')),
    (('senior',), 'senior', 'Senior Accountant', 8, ('draft','eligible')),
    ((), 'senior', 'Senior Accountant', 8, ('draft','eligible'))])
def test_seniority_follows_the_levels_the_person_stated(...): ...
def test_entry_seeker_holds_when_ad_says_not_entry_level(...): ...   # ('hold','insufficient_evidence'); no stated level -> draft
def test_citizen_or_pr_person_is_not_blocked_by_a_plain_citizenship_demand(...):
    # ad 'Australian citizens and permanent residents only', work_rights.requirement 'citizen_or_pr' with that quote:
    # citizen dp -> ('draft','eligible'); visa-limited dp (citizen_or_pr False) and no-fact dp -> ('archive','hard_gate') as today
def test_security_clearance_still_stops_a_citizen(...): ...   # 'Baseline security clearance required' -> route != 'draft', reason in {'hard_gate','verification_required'}
def test_legacy_helpers_keep_their_results(): _level_signals reproduces _entry_signals on the existing gate test ads
```

- [ ] **Step 2: Run** the file -> FAIL.
- [ ] **Step 3: Implement** the helper refactors (`decision_policy=None` results byte-identical) and the policy-path rules above.
- [ ] **Step 4: Run** `tests/test_agentic_gate_policy.py tests/test_agentic_gate.py tests/test_gate_holds.py tests/test_reader_rules.py` -> PASS.
- [ ] **Step 5: Commit** `feat: gate hours, work rights and level follow the decision policy`.

### Task 6: Flag, `gate_current`, service wiring, decision log, Jev knockouts

**Files:**
- Modify: `pipeline/agentic/service.py` (`run_agentic_job`: lines 335-337, 409-418, 453-457), `jobwatch/preference_service.py:39`, `pipeline/agentic/baseline.py` (`decide_frozen`, Plan 6a), `config/jobwatch.yaml` (commented key `decision_policy: legacy` under `pipeline.agentic`)
- Create: `pipeline/agentic/decision_log.py`
- Test: `tests/test_agentic_policy_wiring.py` (reuse `from test_agentic_service import SyntheticGateway, world  # noqa: F401`; `confirm_discovery` from `tests/conftest.py`); append to `tests/test_baseline.py` (Plan 6a)

**Interfaces:**
- Consumes: `policy_for`, `DecisionPolicy` (Task 3), `commute_km_for` (Task 2), Tasks 4-5 `decide(decision_policy=, company=)`; Plan 6a `baseline.decide_frozen(snapshot, evaluation, *, commute_km, decision_policy=None)` and `baseline._active_decision_policy(config, approved)`.
- Produces in `service.py`:
  - `decision_policy_mode(config) -> Literal['legacy', 'profile']` — `agentic_settings(config).get('decision_policy', 'legacy')`; any other value raises `AgenticError('invalid_configuration')`. Not added to `_config()`.
  - `decision_policy_for(config) -> DecisionPolicy | None` — None when the mode is `legacy` or `policy_for(users.current())` is None (then the legacy gate runs).
  - `commute_km_of(decision_policy: DecisionPolicy | None, location: str | None) -> int | None` — `commute_km_for(decision_policy.home['place'] if decision_policy and decision_policy.home else None, location or '')` when `decision_policy` is set (None without a home), else today's `km_from_home(location or '')`; the one commute definition for the evaluator input and the gate.
  - `gate_current(evaluation: AgenticEvaluation, *, posting: Mapping[str, Any], ad_text: str, decision_policy: DecisionPolicy | None, policy: TargetPolicy, captured_complete: bool = True, expected_run_key: RunKey | None = None, evidence_bundle: EvidenceBundle | None = None, commute_km: int | None = None) -> AgenticGateDecision` (contract decision 2) — the single place the live gate is called. `posting` supplies `title`, `company` and `location`; `commute_km=None` means "derive it with `commute_km_of(decision_policy, posting['location'])`". It calls `decide(evaluation, ad_text=ad_text, title=posting['title'], policy=policy, decision_policy=decision_policy, company=posting['company'], captured_complete=..., expected_run_key=..., evidence_bundle=..., commute_km=...)` and nothing else. The run, `preference_service.pool`, Plan 4's shortlist, Plan 5's rule checks, Plan 6a's `decide_frozen` and Plan 6b's replay all call it. Plan 4 adds the keyword `score_policy`.
  - `applicable_knockouts(dp: DecisionPolicy | None) -> frozenset[str]` — None -> `{'citizen_or_pr','five_years'}` (today); with a policy: `five_years` only when `dp.seniority` is non-empty and its highest level is `junior` or lower; `citizen_or_pr` only when `dp.work_rights.get('citizen_or_pr') is not True`.
  - `run_agentic_job` obtains `dp = decision_policy_for(config)`, calls `gate_current(... decision_policy=dp ...)` instead of `decide`, uses `commute_km_of(dp, posting['location'])` for the evaluator input, filters Jev knockouts through `applicable_knockouts`, and treats a previous archive with reason `policy_excluded` like `hard_gate` (re-decided on the saved evaluation, no model call) only when `dp` is set.
- Produces `pipeline/agentic/decision_log.py`: `ensure(conn)` creating `gate_decisions(run_key TEXT, policy_hash TEXT, profile_version INTEGER, route TEXT, reason TEXT, decided_at REAL, PRIMARY KEY(run_key, policy_hash))` (lazy pattern, not a `db.py` migration); `record(conn, run_key, dp, decision) -> None` (`INSERT OR REPLACE`); `latest(conn, run_key) -> dict | None`. Written only when `dp` is set, so `legacy` runs write nothing. Plan 4 reads it to decide whether a held job needs a re-decision.
- `preference_service.pool` replaces its `decide(...)` call with `service.gate_current(..., decision_policy=service.decision_policy_for(config), ...)` so the preference pool matches the live gate.
- `baseline.decide_frozen` (Plan 6a) calls `service.gate_current(...)` with `posting=snapshot['posting']`, `decision_policy=<its decision_policy argument>`, `policy=default_policy()` and the frozen `commute_km`; with `decision_policy=None` its results equal the pre-revision ones.

- [ ] **Step 1: Write the failing tests:**

```python
def test_flag_is_legacy_by_default_and_outside_the_run_key(world):
    conn, config, bundle, add = world
    assert service.decision_policy_mode(config) == 'legacy'
    on = with_flag(config, 'profile')
    assert service.decision_policy_mode(on) == 'profile' and service._config(on) == service._config(config)
    assert key_for(on) == key_for(config)             # same posting, same bundle -> identical RunKey with either value

def test_flag_must_be_legacy_or_profile(world): ... # with_flag(config, True) and with_flag(config, 'yes') -> pytest.raises(AgenticError, match='invalid_configuration')

def test_decision_policy_fields_never_enter_the_run_key(world, monkeypatch):    # contract decision 4
    # key_for(...) computed with policy_for patched to three policies that differ in exclusions, profile_version, open_questions (so policy_hash),
    # under both modes: value, config_hash and candidate_hash of every RunKey are identical
    assert 'DecisionPolicy' not in inspect.getsource(service._run_key) and 'policy_hash' not in inspect.getsource(service._run_key)

def test_profile_mode_gate_uses_the_confirmed_policy(world, monkeypatch):
    # synthetic accounting job; policy_for patched to policy_of(fact('exclusion', {'kind': 'family', 'value': 'accounting'})); run_agentic_job(operation='evaluate')
    # profile -> pipeline_state ARCHIVED, reason 'policy_excluded'; decision_log.latest(conn, run_key) has policy_hash == dp.policy_hash and profile_version == dp.profile_version
    # legacy  -> same job held with reason 'evaluation_complete'; gate_decisions table has no row (or does not exist)

def test_profile_mode_without_a_confirmed_policy_runs_the_legacy_gate(world, monkeypatch):   # policy_for -> None: result equals the legacy result

def test_removing_an_exclusion_releases_the_job_without_a_model_call(world, monkeypatch):
    # run once with the exclusion (archived policy_excluded), swap policy_for to a policy without it, run again:
    # job is no longer archived (held 'evaluation_complete') and the SyntheticGateway call count did not change

def test_gate_current_is_the_only_live_gate_call(world, monkeypatch):           # contract decision 2
    # record the keyword names passed to gate.decide during agentic_batch_run(operation='evaluate') and during preference_service.pool(); both come from gate_current
    # (monkeypatch gate_current to a spy that delegates; both paths hit it with posting/ad_text/decision_policy/policy), and grep: 'decide(' appears in service.py and preference_service.py only inside gate_current

def test_gate_current_derives_commute_and_company_from_the_posting(world): ...  # commute_km=None -> commute_km_of(dp, posting['location']); company reaches decide (employer rule hits)

def test_decide_frozen_goes_through_gate_current(frozen):                       # tests/test_baseline.py (Plan 6a fixture)
    # spy on service.gate_current: decide_frozen(case.snapshot, case.evaluation, commute_km=None) calls it once and returns the same dict as before the switch (decision_policy=None)

def test_freeze_stores_the_decision_policy_when_the_profile_path_is_active(frozen, monkeypatch):    # tests/test_baseline.py
    # flag 'profile' + confirmed profile: freeze_baseline writes decision_policy.json equal to policy_for(person, approved=baseline.frozen_approved(id)).model_dump(mode='json'),
    # Baseline.decision_policy_sha256 is set, and the stored decisions are those of gate_current under that policy; with 'legacy' neither exists

def test_jev_knockouts_follow_the_policy():
    assert service.applicable_knockouts(None) == {'citizen_or_pr', 'five_years'}
    assert service.applicable_knockouts(policy_of(fact('preference', 'graduate roles'))) == {'citizen_or_pr', 'five_years'}
    assert service.applicable_knockouts(policy_of(fact('preference', 'mid-level roles'), fact('work_rights', 'Australian citizen'))) == frozenset()
    assert service.applicable_knockouts(policy_of(fact('experience', 'x'))) == {'citizen_or_pr'}   # no stated level: no seniority knock-out

def test_commute_for_the_evaluator_comes_from_the_policy_home(...): policy home 'Box Hill, VIC' and posting location 'Carlton VIC' -> an int; no home -> None, even when the autouse owner fixture is active

def test_decision_log_is_idempotent_and_per_run_key(tmp_path): record twice -> one row; two policy hashes -> two rows; latest returns the newest
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_agentic_policy_wiring.py` -> FAIL.
- [ ] **Step 3: Implement** as specified. Keep `snapshot_inventory` and `_run_key` untouched.
- [ ] **Step 4: Run** `tests/test_agentic_policy_wiring.py tests/test_baseline.py tests/test_agentic_service.py tests/test_preference_service.py tests/test_agentic_store.py tests/test_agentic_reconciliation.py` -> PASS (the service file is slow; run it alone).
- [ ] **Step 5: Commit** `feat: decision policy flag, gate_current, wiring, decision log and policy-aware knock-outs`.

### Task 7: Parametrise the built-in excluded codes

`MINIMUM_EXCLUDED_CODES` (`jobwatch/candidate/contracts.py`, two six-digit occupation codes) is one of the owner-specific constants the brief wants out of application code (contract decision 6). It is also the default of `TargetPolicy.excluded_codes`, `service._run_key` digests `policy.model_dump(mode='json')` (and `candidate_hash` digests it again), and `candidate/analysis.py` reads it, so deleting it would re-key every stored job (jobs x three model roles) and contradict decision 4. This task makes it a parameter and leaves every existing key byte-identical.

**Files:**
- Modify: `jobwatch/candidate/contracts.py` (`TargetPolicy`), `jobwatch/candidate/policy.py` (`profile_target_policy`)
- Test: `tests/candidate/test_policy.py` (append), `tests/candidate/test_contracts.py` (existing assertions at ~510-520 stay green)

**Interfaces:**
- Produces: `TargetPolicy.require_minimum_excluded_codes: bool = True`, omitted from `model_dump` when `True` (a historical-omitting serialiser, contract rule 4); when `False` the validator no longer demands `MINIMUM_EXCLUDED_CODES` in `excluded_codes`; `MINIMUM_EXCLUDED_CODES` keeps its name and value and stays the default (legacy). `policy.profile_target_policy() -> TargetPolicy`: `version='profile-neutral-v1'`, `allowed_families=KNOWN_FAMILIES`, `excluded_codes=()`, `require_minimum_excluded_codes=False`; it names no person and reads no profile file. Nothing in this plan calls it (Owner decision 6).

- [ ] **Step 1: Write the failing tests:**

```python
def test_default_policy_json_and_hash_are_unchanged():
    dumped = default_policy().model_dump(mode='json')
    assert 'require_minimum_excluded_codes' not in dumped and dumped['excluded_codes'] == ['431111', '541211']
    assert digest(dumped) == PINNED_DEFAULT_POLICY_DIGEST          # literal copied from a run of the unmodified code in a scratch checkout, kept in the test file
def test_minimum_excluded_codes_stay_the_legacy_default_and_stay_immutable_there():
    with pytest.raises(ValidationError): TargetPolicy(version='v1', allowed_families=('accounting',), excluded_codes=('999999',))
def test_profile_target_policy_is_person_independent_and_drops_the_minimum():
    p = profile_target_policy()
    assert p.excluded_codes == () and p.allowed_families == KNOWN_FAMILIES and p.model_dump(mode='json')['require_minimum_excluded_codes'] is False
    assert p == profile_target_policy()                             # no profile read: identical for every person
def test_run_key_for_the_default_policy_is_unchanged(world): ...    # key_for(...) equals the value recorded from the unmodified code (second pinned literal)
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/candidate/test_policy.py tests/candidate/test_contracts.py -k "default_policy or minimum or profile_target"` -> FAIL.
- [ ] **Step 3: Implement** the field, its serialiser and validator change in `contracts.py` and `profile_target_policy()` in `policy.py`. Before editing, record the two pinned literals by running the tests' computations on the unmodified code.
- [ ] **Step 4: Run** `tests/candidate tests/test_agentic_service.py -k "policy or key"` -> PASS.
- [ ] **Step 5: Commit** `refactor: make the built-in excluded codes a parameter without moving any run key`.

### Task 8: Policy endpoint and chat tool

**Files:**
- Modify: `pipeline/agentic/profile_api.py` (route inside `mount`), `pipeline/agentic/chat.py` (read-only tool `profile_policy` next to `profile_status`, added to the `tools=[...]` list at line ~639; no entry in `GATED`; do not edit `pipeline/agentic/skills/**`, which would invalidate pending threads), `pipeline/agentic/CHAT.md`
- Test: `tests/test_profile_api.py`

**Interfaces:**
- Consumes: `policy.describe(person, *, mode)` (Task 3), `service.decision_policy_mode(config)` (Task 6).
- Produces: `GET /api/agent/profile/policy` (scope `read`) -> 200 `{'policy': <DecisionPolicy JSON> | None, 'mode': 'legacy' | 'profile', 'enabled': bool (mode == 'profile'), 'open_questions': [{'code','question','why'}], 'reason': 'no_confirmed_profile'}` (`reason` only when `policy` is None, then `open_questions` is `[]`). Question text for the standing codes comes from `intake._ASK_TEXT`; `exclusion:<id>` reads "Is '<value>' an employer, a kind of work, a place, a job family or a title word? Until you say, it is not applied as a rule." (the person answers through Plan 5's rule confirmation). Chat `profile_policy() -> dict` returns the same dict for the server-bound person.

- [ ] **Step 1: Write the failing tests** (reuse `env`, `proposal`, `h` from the file; confirm through the existing flow as `test_full_profile_flow_over_http` does):

```python
def test_policy_endpoint_without_a_profile(env):
    got = env.get(P + '/policy', headers=h()).json()
    assert got == {'policy': None, 'mode': 'legacy', 'enabled': False, 'open_questions': [], 'reason': 'no_confirmed_profile'}

def test_policy_endpoint_after_confirmation_lists_open_questions(env):
    ...confirm version 1 (experience fact only)...
    got = env.get(P + '/policy', headers=h()).json()
    assert got['policy']['profile_version'] == 1 and got['policy']['strategy'] == 'balanced'
    assert {'employment_status', 'location'} <= {q['code'] for q in got['open_questions']} and all(q['question'] and q['why'] for q in got['open_questions'])

def test_policy_is_per_person(env):   # OTHER token (person fixture-b) sees policy None while fixture-a has one
def test_policy_endpoint_needs_read_scope_only(env):   # a token without 'read' -> 403
def test_policy_mode_mirrors_the_flag(...):   # create_api(config={'agentic': {'enabled': False, 'decision_policy': 'profile'}}) -> mode 'profile', enabled True (verify get_config passes the flag through; adjust the test to the config shape get_config returns)
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_profile_api.py -k policy` -> FAIL (404).
- [ ] **Step 3: Implement** the route, the tool and CHAT.md rows (native contract table: new endpoint; profile section: what the policy contains, that only evidence-basis facts in `{"kind", "value"}` form become rules (free text becomes an open question), the flag `legacy | profile` and its default, and that the response is read-only). Add `policy` to the `profile` capabilities object only if `api.py` lists endpoints there (check `api.py:271-277`).
- [ ] **Step 4: Run** `tests/test_profile_api.py tests/test_chat.py tests/test_auth.py` -> PASS. Run `tests/test_deepagents_runtime.py` once to confirm no test enumerates the chat tool list exactly; if one does, add `profile_policy` there.
- [ ] **Step 5: Commit** `feat: native API and chat tool for the decision policy`.

### Task 9: Neutral wording on the board and in legacy-mode prompts

**Files:**
- Modify: `jobwatch/web/queries.py` (`HIDE_REASONS` labels for `full_time_only` and `out_of_area`, `HIDE_SENTENCE`, the note at ~line 804), `pipeline/nodes/evaluate.py` (SYSTEM, "an entry-level student who works part time"), `pipeline/nodes/extract.py` (SYSTEM, "a student-visa holder living in Australia meets these"), `pipeline/nodes/gate.py` (module docstring only)
- Test: `tests/web/test_ai.py` (update the three assertions at ~451, 452, 551), `tests/test_pipeline.py` (append)

**Interfaces:** display strings only; no stored value, hide-reason key or route changes.

New text: `full_time_only` label "Full-time only: does not fit your hours", sentence "full-time only, which does not fit your hours"; `out_of_area` label "Outside your search area, not remote", sentence "outside your search area, not remote"; note "Hours not stated: check they fit your availability"; evaluate rubric "the level and years the advert asks versus the candidate (use the candidate's own roles and education)"; extract "a candidate who holds any current Australian work visa meets these"; gate docstring "work rights that exclude this candidate".

- [ ] **Step 1: Update the three web assertions to the new text and add:**

```python
def test_legacy_mode_prompts_name_no_one_person():
    from pipeline.nodes import evaluate, extract
    for text in (evaluate.SYSTEM, extract.SYSTEM):
        assert not re.search(r'\bstudent\b|student-visa|Melbourne|Victoria', text, re.I)
```

- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/web/test_ai.py tests/test_pipeline.py -k "hide or label or sentence or prompts or note"` -> FAIL.
- [ ] **Step 3: Change** the strings.
- [ ] **Step 4: Run** `tests/web tests/test_pipeline.py tests/test_pipeline_ingest_browser.py` -> PASS.
- [ ] **Step 5: Commit** `refactor: neutral wording for hours, area and level text`.

### Task 10: Release check, documentation and workflow example

**Files:**
- Create: `docs/examples/decision-policy.md`
- Modify: `README.md` (decision policy section: what it reads, the flag, how to see it), `pipeline/agentic/CHAT.md` (only if Task 8 left gaps), `pipeline/agentic/MATCHING.md` (one paragraph: the gate now has a policy path; update test counts only from an actual run)

- [ ] **Step 1:** Run the full suite once: `JOBWATCH_SETTINGS=/dev/null <venv>/bin/python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=90` (about 20 minutes; the 10 browser-extra collection errors are known, see code map 7.10; report exact counts). Every failure must be fixed or shown to fail identically on `main`.
- [ ] **Step 2:** Write the example from a script run against the test client with synthetic data only: (a) a confirmed profile with an unemployment statement, one structured exclusion, one free-text exclusion and no location -> `GET /api/agent/profile/policy` real output, showing strategy `employment_first` and the open questions `location` and `exclusion:<fact_id>`; (b) three synthetic ads and the gate result for each with `legacy` and with `profile` (draft, `policy_excluded`, hold for unknown location). State plainly that the flag defaults to `legacy` and that no matching-quality claim is made.
- [ ] **Step 3:** Commit `docs: decision policy workflow example`; push the branch and open the PR with: checks and exact results, rulings, limitations (below), unverified items (gate behaviour in `profile` mode against real postings; Victorian-only distance data; no live run), and undo instructions (see Rollback).

## Owner decisions

The executor does not block on any of these; the default applies meanwhile.

1. **Turn the policy on** (`pipeline.agentic.decision_policy: profile`). Default: `legacy`. Turning it on re-decides stored held/archived evaluations with no model call (run keys do not move), exclusion rules start to apply, and a person with no confirmed scope-bearing version stays on the legacy gate. Before switching, classify every free-text exclusion (Plan 5's rule confirmation): `legacy` enforces a free-text family exclusion through the projected `excluded_families` in `interests_and_criteria.yaml`, whereas `profile` enforces only `{"kind", "value"}` rules, so an unclassified one stops being applied (it stays listed as the open question `exclusion:<fact_id>` in `GET /api/agent/profile/policy`).
2. **Re-confirm the owner's own profile through a proposal** so their limits (distance, hours, level, excluded kinds of work) live in approved facts instead of code and files. Default: the owner stays on the legacy gate even with the flag on `profile`, because an adopted version has no facts. The executor must not read the owner's profile files to prefill anything.
3. **Rename the stored `location_fit='melbourne'` and its evaluator prompt wording.** Needs an `IMPLEMENTATION_VERSION` bump, i.e. a paid re-evaluation of every stored job (jobs x 3 model roles). Default: not done; the gate recomputes the region from the verified quote.
4. **Delete `_legacy_person_checks` and the Victorian constants** after steps 1 and 2. Default: kept as the `legacy` baseline.
5. **Model-assisted classification of free-text exclusions** (a paid call per exclusion). Default: none; a free-text exclusion is not a rule, stays prompt text and is reported as the open question `exclusion:<fact_id>` until the person picks its kind (Plan 5).
6. **Wire `profile_target_policy()` into the run** (drops the two built-in excluded occupation codes from candidate analysis for every person). Default: not wired, because it changes the `TargetPolicy` digest and so re-keys every stored job: jobs x three model roles of paid re-evaluation, to be priced as `N non-archived jobs with a stored evaluation` before the owner agrees. Task 7 only makes the change possible.

## Rollback

Revert the merge commit. Nothing else is needed for behaviour: the flag defaults to `legacy` and no stored model, run key, config hash or profile file changed. The only data this plan creates is the lazily created per-person table `gate_decisions`, written only in `profile` mode; remove it with `DROP TABLE IF EXISTS gate_decisions` on each person's database (`users.db_path(person)`). A baseline frozen in `profile` mode also holds `decision_policy.json` (Plan 6a folder; harmless). No other folders are created. Setting `pipeline.agentic.decision_policy: legacy` restores today's gate immediately without a revert.

## Limitations to state in the PR

Distance needs place data, which exists for Victoria only; other states resolve by state name, state code or capital city, and unresolved locations hold instead of archiving. The product remains Australia-only. Free-text facts (location, commute, work rights, level) are read by a documented deterministic grammar; wording it does not recognise becomes an open question, not a rule. A free-text exclusion is never a rule (only `{"kind", "value"}` is), so until the person classifies it the gate does not enforce it. Collection pre-filters (`rules.yaml`, `searches.yaml`, VIC regexes in `filters.py` and `ingest`), `_target_first` and near-duplicate embeddings (Plan 3), the holistic score gate `north_star < 3` and the preference-model families (Plan 4), and legacy `reader`/`fieldgen`/`onboarding` defaults are unchanged.

## Contract reconciliation

Reconciled decisions of the [cross-plan contract](2026-10-21-cross-plan-contract.md) that apply to this plan; all are applied above.

- **1 Pinned profile version:** `policy_for(person, *, approved=None)` (Task 3); Plan 6a's `decision_policy.json` and `frozen_approved` feed it (Task 6 test).
- **2 One live gate call:** this plan creates `service.gate_current(evaluation, *, posting, ad_text, decision_policy, policy, ...)`; `decide()` takes `decision_policy` and `company` (Tasks 4, 6); `run_agentic_job`, `preference_service.pool` and `baseline.decide_frozen` are switched to it. Plans 4, 5 and 6b call it.
- **3 Flag:** `pipeline.agentic.decision_policy: legacy | profile`, default `legacy`; owner-specific checks live in `_legacy_person_checks`; exclusion rules apply only with `profile` (Tasks 1, 4, 6).
- **4 Run key stays stable:** tested in Task 6 (`test_decision_policy_fields_never_enter_the_run_key`); Plan 5 keeps a regression test.
- **5 Gate version:** `policy.py`, `contracts.py`, `location.py` and the data files are in Plan 6a's `GATE_VERSION`; this plan edits `gate.py`, `location.py`, `policy.py` and `contracts.py`, so `GATE_VERSION` changes by itself (no manual bump).
- **6 Exclusion facts to rules:** `rules_from_fact` (Task 3) builds an `ExclusionRule` from a `{"kind", "value"}` exclusion fact; free text stays prompt text and adds the open question `exclusion:<fact_id>`; `MINIMUM_EXCLUDED_CODES` is parametrised (Task 7).
- **16 `location_fit`:** the region is recomputed from the verified quote (Task 4); no later plan reads `'melbourne'` as the home region.

Additive `DecisionPolicy.regions` and `work_rights['citizen_or_pr']`; `open_questions` holds codes (`employment_status`, `work_rights`, `location`, `career_focus`, `exclusion:<fact_id>`) while the API returns `{code, question, why}` objects; Plans 3 and 5 consume the codes.
