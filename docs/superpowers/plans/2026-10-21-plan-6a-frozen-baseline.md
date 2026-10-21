# Plan 6a: Frozen baseline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the current pipeline's stored inputs and outputs (postings, evidence bundle, requirement judgments, holistic scores, gate routes, usage) into an immutable, per-person, hash-verified baseline that Plans 2-4 and Plan 6b replay and compare against, before any of them changes a decision.

**Architecture:** One new module `pipeline/agentic/baseline.py` reads stored `agentic_artifacts` only (no model call, no DB write) and writes `<person>/baselines/<baseline_id>/` atomically (staging folder, then rename). `decide()` reads the live profile files, so the module copies those files into the baseline, recomputes every gate decision offline with the profile pinned to that copy (new `apply.paths.pin_profile_dir`), and records `GATE_VERSION`, a sha256 over the gate's source files. Cases that share an advert or an employer get one `group_id`; a deterministic tagger marks the six categories the brief requires; owner labels are written only by a human CLI command. Large shared artifacts (candidate analysis ~3 MB, reference ~7 MB) are stored once per baseline.

**Tech Stack:** Python 3.12, pydantic v2 (`StrictFrozen`), sqlite3 (read-only URI), argparse CLI extension (`register`/`handle`), pytest with the synthetic world from `tests/test_agentic_service.py`.

**Spec:** [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md) (section A 3 "Preserve it as a comparison baseline", section A 5 "Compare the revised system with the current baseline using identical frozen inputs"), [roadmap](2026-10-21-backend-roadmap.md) row 6a, [cross-plan contract](2026-10-21-cross-plan-contract.md) "Phase 2 - Plan 6a", [code map](reference/2026-10-21-codemap.md) section 1.

## Global Constraints

- "Compare the revised system with the current baseline using identical frozen inputs. Include previously rejected jobs, transferable skills, unknown facts, misleading titles, stretch opportunities and explicit exclusions." (brief 5)
- "Keep duplicate advertisements and related employer cases from leaking across evaluation splits." (brief 5; this plan supplies `group_id`, Plan 6b does the split)
- "Missing independent labels must remain explicit; synthetic checks or model self-grades do not establish recommendation quality." (brief 5)
- "The inherited holistic 1-5 score must not remain the sole exclusion mechanism ... Preserve it as a comparison baseline while validating the replacement policy." (brief 3)
- "Do not claim deployment or improved matching accuracy without the corresponding evidence." (brief 5)
- Synthetic data only. Never use live candidate records as fixtures, and the executor never runs `jobwatch baseline freeze` against a real person's data (owner decision 1).
- Per-person isolation: everything lives under `users.user_dir(person)/baselines/`, resolved from `users.current()`; a baseline id of another person is `baseline_not_found`.
- Paid model calls only via approved routes (`require_route`, synthetic transports in tests). This plan makes no model call at all; freeze, load, replay-of-the-baseline-arm and label are offline, and tests patch `jobwatch.llm.LLM.chat_once` and `embed_once` to fail.
- No service, timer or deployment activation; no application submission; no employer contact.
- Model output is never recorded as a person's choice or approval: `OwnerLabel.actor` is `'owner'`, set only by `jobwatch/baseline_cli.py`; no API route, chat tool or MCP tool in this plan can write a label.
- Schema changes additive: no `jobwatch/db.py` migration and no lazy table; new files only under `<person>/baselines/`. `AgenticEvaluation`, `RunKey`, `MatchingCase` and every stored artifact are untouched.
- Run-key rule (contract rule 1): this plan changes none of `_config()`, `default_policy()`, `IMPLEMENTATION_VERSION`, `LOCATION_REFERENCE_HASH`, so no job is re-evaluated. Expected paid re-run cost: 0 jobs x 3 model roles. `pipeline/agentic/service.py` is not edited, and `GATE_VERSION` is never a `RunKey` input.
- Preference-file rule (contract rule 5): nothing under `jobwatch/preferences/` is edited.
- Gate unchanged: `pipeline/agentic/gate.py`, `pipeline/agentic/location.py`, `jobwatch/candidate/person.py` and `jobwatch/reader.py` (the files `GATE_VERSION` hashes) are not edited.
- Private files 0600, directories 0700, written through `apply.paths.safe_write_bytes/ensure_dir`; profile files read through `candidate/_private_io.read_regular_file` (no symlinks followed).
- A baseline holds copies of a person's profile and evidence. It never enters Git, a log, a hosted trace or a model prompt; CLI output prints ids and counts, never candidate text.
- Python 3.12 virtualenv outside the repo: `uv venv --python 3.12 <scratch>/venv && uv pip install --python <scratch>/venv/bin/python -e '.[dev]'`. Test command: `<venv>/bin/python -m pytest -q -p no:cacheprovider <paths>`. Run one pytest process at a time; add `-o faulthandler_timeout=90` to diagnose a hang. Never run `playwright install`.

## Review Focus

1. The person edits `profile.yaml` or `interests_and_criteria.yaml` after the runs and after the freeze: stored decisions and any replay through `pinned_profile` must follow the frozen copy, never the live files. (Task 4 `test_decision_follows_the_frozen_profile_not_later_edits`)
2. The freeze dies half-way (disk error, kill): no readable baseline and no `.staging-*` folder is left. (Task 4 `test_a_failed_freeze_leaves_no_visible_baseline`)
3. The same advert on two boards, one employer written two ways ("Acme Pty Ltd" / "ACME Group"), and postings with a blank employer: duplicates and related employers share one `group_id`; blank employers never merge strangers. (Task 3 grouping tests)
4. Another person's baseline id, or an id such as `../x`, is refused and never reads outside `baselines/`. (Task 4 `test_baselines_are_per_person_and_ids_cannot_escape`)
5. An agent surface (API, chat, MCP, runtime) must not be able to record an owner label. (Task 5 `test_label_writer_is_not_reachable_from_agent_surfaces`)

---

## File structure

| File | Responsibility |
|---|---|
| `pipeline/agentic/baseline.py` (new) | Models, `GATE_VERSION`, grouping, tagging, freeze/load, pinned profile, frozen decision, owner labels |
| `jobwatch/baseline_cli.py` (new) | `jobwatch baseline freeze/list/show/label` (extension module, like `profile_cli.py`) |
| `jobwatch/apply/paths.py` | `pin_profile_dir` context manager consulted first by `profile_dir()` |
| `jobwatch/candidate/evidence.py` | `bundle_from_contents`, shared by `snapshot_evidence` |
| `jobwatch/cli.py` | register `jobwatch.baseline_cli` in `_extensions()` |
| `.github/workflows/backend.yml` | add the new test files to the `synthetic-backend` list |
| `tests/baseline_support.py` (new) | `synthetic_case(...)` helper shared by baseline tests |
| `tests/test_profile_pin.py`, `tests/test_baseline.py`, `tests/test_cli_baseline.py` (new); `tests/candidate/test_evidence.py` | tests |
| `docs/adr/0003-frozen-baseline.md` (next free number), `GLOSSARY.md`, `README.md`, `pipeline/agentic/MATCHING.md`, `pipeline/agentic/CHAT.md`, `docs/examples/frozen-baseline.md` | decision record and documentation |

Layout written per baseline (all 0600 files, 0700 folders):

```
<user_dir>/baselines/<baseline_id>/
  baseline.json            # Baseline; written last inside the staging folder
  approved.json            # copy of intake.current_version(person) at freeze time
  profile/<file>           # copies of the profile files (PROFILE_FILES) at freeze time
  cases/<case_id>.json     # FrozenCase with the large fields replaced by blob_refs
  blobs/<sha256>.json      # candidate analysis, reference text, evidence contents; each stored once
  labels.jsonl             # OwnerLabel lines, appended by the owner's CLI only (not covered by content_sha256)
```

## Owner decisions

The executor does not block on these; the default applies meanwhile.

1. **When to freeze the real baseline.** It must be frozen before Phase 3 (Plan 2) code is deployed, because gate changes silently re-apply to stored evaluations (code map 1.3.3). Default: the executor freezes nothing on real data. After merging this phase the owner runs `jobwatch --user <name> baseline freeze` once; `baseline show` reports `gate_state: pre_revision` when the gate source still equals `PRE_REVISION_GATE_VERSION`.
2. **Owner labels.** Plan 6b can only report quality on cases the owner labels (`suitable`, `relevance 0-3`, `exclusion_violation`). Default: none; reports say `owner_labels_required`. Who labels, and how many, is the owner's call.
3. **Tag heuristics** (task 3, also in the ADR) are selection aids for coverage of the six categories, not judgments. Default: as written; the owner can add tags per case through `baseline label --tag`.
4. **Size.** Default `--limit 500`, hard cap 1000 (the cap of `evaluation._matching_cases`). Default: 500.
5. **Backups.** `baselines/` holds candidate-bearing copies inside the person's folder and is covered by normal folder backups. Default: leave it there; no separate export.
6. **GATE_VERSION source list** is the contract's four files; the extra gate dependencies are recorded beside it (contract issue 1). Default: as in this plan until the controller reconciles.

---

### Task 1: ADR and glossary for the frozen baseline

**Files:**
- Create: `docs/adr/0003-frozen-baseline.md` (use the next free number at execution time; keep the title)
- Modify: `GLOSSARY.md` (append rows)

- [ ] **Step 1: Write the ADR** in the format of `docs/adr/0002-profile-intake-and-approval.md` (Date, Status `Accepted owner direction (backend brief of 2026-10-21); delivery has its own acceptance criteria`, Context, Decision, Consequences, Alternatives rejected, References: brief 3 and 5, INTENT.md "Preserve the inherited holistic score as a comparison baseline", code map section 1). Decision section must state each of these, in plain sentences:
  - A frozen baseline is an immutable per-person folder (layout above), created only by `freeze_baseline`, never edited; only `labels.jsonl` grows.
  - Inputs and outputs come from stored `snapshot`, `structural_inputs`, `evaluation`, `candidate`, `model_insights` artifacts of the newest run per posting that has both a snapshot and an evaluation; no model is called and no DB row is written.
  - The gate route is not stored today and `decide()` reads the live profile, so the route is recomputed offline at freeze time under a pinned copy of the profile files; `GATE_VERSION` (sha256 over `gate.py`, `location.py`, `person.py`, `reader.py`) and the hashes of the other gate dependencies are recorded with it. Replays must use `pinned_profile`.
  - Environment variable pinning was rejected because `profile_dir()` ignores `JOBWATCH_PROFILE_DIR` for every person but the default one.
  - `group_id` unions cases by `content:<ad hash>`, `dedupe:<postings.dedupe_key>` and `employer:<normalised company>`; an empty employer never merges.
  - The six tags and their exact rules (copy the table from Task 3). State that they are heuristics, that no stored exclusion other than a family rule exists yet (`explicit_exclusion` is therefore `policy_excluded` only until Plans 2 and 5), and that owner tags are added through labels.
  - Owner labels: `actor='owner'`, written by the CLI only, append-only, latest line per case wins, history kept; nothing is imputed.
  - What this does not establish: nothing about matching quality; a baseline is an input to Plan 6b.
  Consequences: disk use is a few MB per baseline thanks to blob sharing; any edit to a gate file changes `GATE_VERSION`; a freeze made after the gate was revised is flagged by `gate_state: revised`.
- [ ] **Step 2: Append to `GLOSSARY.md`** four rows: `Frozen baseline` (immutable per-person snapshot of the pipeline's stored inputs and outputs, with gate routes recomputed under a pinned profile, used for like-for-like comparison), `Frozen case` (one posting's inputs, outputs, group, tags and usage inside a baseline), `Gate version` (sha256 over the gate's source files; changes by itself when the gate changes), `Owner label` (the owner's own suitability, relevance or exclusion judgment of a frozen case; never produced by a model).
- [ ] **Step 3: Commit** (docs only, no application tests needed)

```bash
git add docs/adr/0003-frozen-baseline.md GLOSSARY.md
git commit -m "docs: ADR 0003 frozen baseline and glossary terms"
```

### Task 2: Pin the profile folder; build an evidence bundle from stored contents

**Files:**
- Modify: `jobwatch/apply/paths.py` (`profile_dir`, new `pin_profile_dir`)
- Modify: `jobwatch/candidate/evidence.py` (`snapshot_evidence` delegates to new `bundle_from_contents`)
- Test: `tests/test_profile_pin.py` (new), `tests/candidate/test_evidence.py`

**Interfaces:**
- Produces:
  - `pin_profile_dir(path: str | Path) -> ContextManager[Path]` in `jobwatch/apply/paths.py`. While active, `profile_dir()` returns `path` before any environment or person logic, so `person.py`, `place.py`, `render._candidate`, `location._profile_home` and `reader` all read the pinned folder. `path` must be an existing absolute directory (`ValueError` otherwise). Nesting restores the outer pin on exit. It is a `contextvars.ContextVar`: synchronous code only, threads started inside do not inherit it. Because `guard_write` compares against `profile_dir()`, the pinned folder is read-only to code while pinned.
  - `bundle_from_contents(contents: dict[str, bytes]) -> EvidenceBundle` in `jobwatch/candidate/evidence.py`: the same build and failure mapping as the second half of `snapshot_evidence` (names outside `_ALLOWED`, or contents that do not build, raise `CandidateError('source_invalid')`).

- [ ] **Step 1: Write the failing tests**

`tests/test_profile_pin.py` (synthetic profile files written with `yaml.safe_dump`):

```python
def test_pin_redirects_the_person_readers(tmp_path, monkeypatch):
    # live (hours_limit_per_fortnight 48, via JOBWATCH_PROFILE_DIR) and frozen (20) folders
    assert person.hours_limit_per_fortnight() == 48
    with paths.pin_profile_dir(frozen):
        assert paths.profile_dir() == frozen and person.hours_limit_per_fortnight() == 20
    assert paths.profile_dir() == live and person.hours_limit_per_fortnight() == 48

def test_pin_applies_to_a_non_default_person(tmp_path, monkeypatch):
    # JOBWATCH_DATA_DIR=tmp_path; users.create_user_dirs('friend'); inside users.use('friend'):
    #   own = paths.profile_dir() == tmp_path/'users'/'friend'/'profile'
    #   pinned inside the with-block == frozen; after it == own

def test_pinned_folder_is_read_only_to_code(tmp_path):
    with paths.pin_profile_dir(frozen):
        with pytest.raises(paths.ProfileWriteError):
            paths.safe_write_text(frozen / 'x.txt', 'y')

def test_pins_nest_and_restore(tmp_path): ...   # outer A, inner B, back to A, then unpinned

@pytest.mark.parametrize('bad', ['relative/dir', 'missing'])
def test_pin_needs_an_existing_absolute_directory(tmp_path, bad):
    # 'missing' -> str(tmp_path / 'missing'); pytest.raises(ValueError)
```

`tests/candidate/test_evidence.py` (uses `write_cv` from `.fixtures`):

```python
def test_bundle_from_contents_equals_snapshot_evidence(tmp_path):
    expected = snapshot_evidence(write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n"))
    assert bundle_from_contents(dict(expected.contents)) == expected
    verify_evidence_snapshot(bundle_from_contents(dict(expected.contents)))

def test_bundle_from_contents_refuses_unknown_names_and_empty_contents():
    with pytest.raises(CandidateError, match='source_invalid'):
        bundle_from_contents({'notes.txt': b'x'})
    with pytest.raises(CandidateError):
        bundle_from_contents({})
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_profile_pin.py tests/candidate/test_evidence.py` → FAIL (`AttributeError: pin_profile_dir`, `ImportError: bundle_from_contents`).
- [ ] **Step 3: Implement** `pin_profile_dir` (module-level `ContextVar[Path | None]`, `profile_dir()` returns it first when set) and `bundle_from_contents` (move the try/except build block out of `snapshot_evidence`; `snapshot_evidence` reads sources then returns `bundle_from_contents(contents)`; behaviour and error codes unchanged).
- [ ] **Step 4: Run** the two files plus `tests/candidate tests/test_agentic_gate.py tests/test_gate_holds.py tests/test_users.py` → PASS (the refactor must not change any existing result).
- [ ] **Step 5: Commit**

```bash
git add jobwatch/apply/paths.py jobwatch/candidate/evidence.py tests/test_profile_pin.py tests/candidate/test_evidence.py
git commit -m "feat: pin the profile folder and rebuild evidence bundles from stored contents"
```

### Task 3: Baseline models, gate version, grouping and tags

**Files:**
- Create: `pipeline/agentic/baseline.py` (first part), `tests/baseline_support.py`
- Test: `tests/test_baseline.py` (new)

**Interfaces:**
- Consumes: `pipeline.agentic.contracts` (`StrictFrozen`, `AgenticEvaluation`, `AgenticGateDecision`, `RunKey`, `SourceCitation`, `Requirement`, `RequirementMatch`, `EvidenceJudgment`), `pipeline.agentic.runtime.validate_model_payload`, `jobwatch.dedupe._norm/_COMPANY_NOISE`.
- Produces (names fixed by the contract unless marked *additive*):
  - `TAGS = ('previously_rejected', 'transferable_skills', 'unknown_facts', 'misleading_title', 'stretch', 'explicit_exclusion')`
  - `class FrozenCase(StrictFrozen)` with `model_config` allowing `model_`-prefixed field names: `case_id: str`, `posting_id: int`, `group_id: str`, `tags: tuple[str, ...]`, `snapshot: dict`, `structural_inputs: dict`, `evaluation: dict`, `candidate: dict | None`, `model_insights: dict | None`, `decision: dict`, `commute_km: float | None`, `usage: dict`; *additive:* `run_key: str`, `group_keys: tuple[str, ...] = ()`, `stored: dict = {}`, `blob_refs: dict[str, str] = {}`.
  - `class Baseline(StrictFrozen)`: `baseline_id`, `created_at`, `git_commit`, `gate_version`, `implementation_version`, `matching_version`, `profile_version: int`, `profile_files_sha256: dict[str, str]`, `case_ids: tuple[str, ...]`; *additive:* `person: str`, `policy: dict`, `gate_dependencies: dict[str, str]`, `runtime_config_sha256: str`, `evidence_bundle_hash: str | None`, `approved_sha256: str`, `case_sha256: dict[str, str]`, `content_sha256: str`, `summary: dict`.
  - `gate_sources() -> dict[str, str]`: dotted module name to sha256 of its `.py` bytes for `pipeline.agentic.gate`, `pipeline.agentic.location`, `jobwatch.candidate.person`, `jobwatch.reader` (path from `importlib.util.find_spec(name).origin` through the overridable `_module_path(name) -> Path`).
  - `gate_dependencies() -> dict[str, str]` *additive*: the same shape for `jobwatch.candidate.contracts`, `jobwatch.candidate.policy` and the data files `pipeline.agentic/data/vic-geo.json`, `pipeline.agentic/data/metro-localities.json`.
  - `current_gate_version() -> str` = sha256 of `json.dumps(gate_sources(), sort_keys=True, separators=(',', ':'))`; `GATE_VERSION = current_gate_version()` at import; `PRE_REVISION_GATE_VERSION: str` *additive*, the literal value of `GATE_VERSION` at this release (Step 3).
  - `group_keys_for(posting: Mapping, ad_hash: str) -> tuple[str, ...]` *additive*: `content:<ad_hash>`; `dedupe:<postings.dedupe_key>` only when both the company and title parts of the key are non-empty; `employer:<_norm(company, _COMPANY_NOISE)>` only when non-empty.
  - `group_ids(keys: Mapping[str, Iterable[str]]) -> dict[str, str]` *additive*: union-find over shared keys; the id is `'group:' + sha256('\n'.join(sorted(all keys of the members)))[:32]` (at most 128 characters, independent of input order).
  - `tag_case(case: FrozenCase) -> tuple[str, ...]`, in `TAGS` order, from the validated evaluation (`validate_model_payload(AgenticEvaluation, case.evaluation)`), `case.decision`, `case.stored` and `case.snapshot['posting']['title']`. Status of a match = `judgment.status`, or for a historical match without `judgment`: `strong`->demonstrated, `partial`->partial, `missing`->unknown. Rules:

| Tag | Rule |
|---|---|
| `previously_rejected` | `decision.route == 'archive'`, or `stored.run_status == 'archived'`, or `stored.application_status == 'skipped'` |
| `transferable_skills` | some match has status `partial` and at least one evidence citation |
| `unknown_facts` | some match has status `unknown`, or `matching_diagnostics.ad_uncertainties` is non-empty, or `location_fit == 'unknown'` |
| `misleading_title` | title matches `\b(?:entry[ -]level\|junior\|graduate\|intern(?:ship)?\|trainee\|cadet(?:ship)?)\b` and (`facts.seniority` in {mid, senior} or `facts.min_years >= 2`); or title matches `\b(?:senior\|lead\|principal\|head of\|director)\b` and `facts.seniority` in {entry, junior} and (`min_years` is None or < 2) |
| `stretch` | no match is `contradicted`, at least one match is `demonstrated`, and some `critical` or `high` requirement is `partial` or `unknown` |
| `explicit_exclusion` | `decision.reason == 'policy_excluded'` |

  - `tests/baseline_support.py`: `synthetic_case(case_id='c-1', *, posting_id=1, title='Junior Analyst', company='Synthetic Alpha', requirements=(('r1', 'high', 'demonstrated'),), seniority='junior', min_years=None, location_fit='melbourne', uncertainties=(), route='draft', reason='eligible', stored=None, group_keys=()) -> FrozenCase`. It builds an `AgenticEvaluation` like `tests/test_agentic_gate.py::evaluation` (AD, AD_HASH, five synthetic dimensions, `JobFacts`) with one stated `Requirement` (jd_signal quoting the ad) and one `RequirementMatch` per `(id, importance, status)`; status `demonstrated` = match `strong` + one citation (`source_id='master_resume.md'`, 64-hex hash) + judgment; `partial` = `partial` + citation + `risk='r'`, `mitigation='m'` + judgment with `open_question='q'`; `unknown` = `missing`, no evidence, risk/mitigation, judgment with `open_question`; `contradicted` = `missing`, judgment with one `contradiction_evidence` citation and `open_question`; `legacy_missing` = `missing` with no `judgment`. `decision` is an `AgenticGateDecision` dump (`global_score=4.0`); `snapshot = {'run_key': ..., 'posting': {'title','company','location':'Melbourne VIC','url','source'}, 'full_ad': AD, 'text_kind': 'full', 'sources': {}, 'contents': {}}`; `usage={'charged_tokens': 100, 'actual_tokens': None, 'latency_seconds': 1.0}`, `commute_km=None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_baseline.py`

```python
def test_tags_are_the_six_contract_tags():
    assert baseline.TAGS == ('previously_rejected', 'transferable_skills', 'unknown_facts',
                             'misleading_title', 'stretch', 'explicit_exclusion')

@pytest.mark.parametrize('kwargs, tag, expected', [...])   # one row per rule below, expected True/False
def test_tag_rules(kwargs, tag, expected):
    assert (tag in baseline.tag_case(synthetic_case(**kwargs))) is expected
```
Rows (each `tag` asserted true and the near miss false): `previously_rejected`: `route='archive', reason='hard_gate'` true; `stored={'run_status': 'archived'}` true; `stored={'application_status': 'skipped'}` true; clean draft false. `transferable_skills`: `[('r1','high','partial')]` true; `[('r1','high','demonstrated')]` false. `unknown_facts`: `[('r1','high','unknown')]`, `[('r1','high','legacy_missing')]`, `uncertainties=('hours',)`, `location_fit='unknown'` true; clean false. `misleading_title`: `title='Junior Analyst', seniority='senior'` true; `title='Junior Analyst', min_years=3` true; `title='Senior Analyst', seniority='entry'` true; `title='Senior Analyst', seniority='senior'` false; `title='Analyst', seniority='mid'` false. `stretch`: `[('r1','high','partial'), ('r2','preferred','demonstrated')]` true; `[('r1','high','contradicted'), ('r2','preferred','demonstrated')]` false; `[('r1','preferred','partial'), ('r2','high','demonstrated')]` false; `[('r1','high','demonstrated')]` false. `explicit_exclusion`: `route='archive', reason='policy_excluded'` true; `reason='hard_gate'` false.

```python
def test_gate_sources_are_the_four_contract_modules():
    assert set(baseline.gate_sources()) == {'pipeline.agentic.gate', 'pipeline.agentic.location',
                                            'jobwatch.candidate.person', 'jobwatch.reader'}
    assert re.fullmatch(r'[0-9a-f]{64}', baseline.GATE_VERSION) and baseline.GATE_VERSION == baseline.current_gate_version()

def test_gate_version_changes_by_itself_when_a_gate_source_changes(tmp_path, monkeypatch):
    # copy gate.py to tmp_path, append one byte, monkeypatch baseline._module_path to return the copy for 'pipeline.agentic.gate'
    assert baseline.current_gate_version() != baseline.GATE_VERSION

def test_gate_dependencies_list_the_extra_inputs():
    assert set(baseline.gate_dependencies()) == {'jobwatch.candidate.contracts', 'jobwatch.candidate.policy',
        'pipeline.agentic/data/vic-geo.json', 'pipeline.agentic/data/metro-localities.json'}

def test_pre_revision_gate_version_is_a_digest():
    assert re.fullmatch(r'[0-9a-f]{64}', baseline.PRE_REVISION_GATE_VERSION)
```

Grouping (keys written as literals):

```python
def test_duplicate_adverts_share_a_group():          # A{content:c1, employer:acme} B{content:c1, employer:other} C{content:c2, employer:solo}
    g = baseline.group_ids(...); assert g['A'] == g['B'] != g['C']
def test_related_employer_cases_share_a_group():     # A{content:c1, employer:acme} B{content:c2, employer:acme}
def test_grouping_is_transitive():                   # A(c1,acme) B(c1,beta) C(c9,beta) share; D(c5,delta) apart
def test_group_id_ignores_input_order_and_fits_the_comparison_limit():   # shuffled input equal; len(id) <= 128
def test_blank_employer_never_merges_strangers():
    k = baseline.group_keys_for({'company': 'Pty Ltd', 'dedupe_key': '|junior analyst|melbourne'}, 'h1')
    assert k == ('content:h1',)
def test_company_spellings_normalise_to_one_employer_key():
    a = baseline.group_keys_for({'company': 'Acme Pty Ltd', 'dedupe_key': ''}, 'h1')
    b = baseline.group_keys_for({'company': 'ACME Group', 'dedupe_key': ''}, 'h2')
    assert 'employer:acme' in a and 'employer:acme' in b
def test_models_carry_the_contract_fields():
    # every contract field name of FrozenCase and Baseline is in model_fields
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_baseline.py` → FAIL (`ModuleNotFoundError: pipeline.agentic.baseline`).
- [ ] **Step 3: Implement** the signatures above in `pipeline/agentic/baseline.py`; `tests/baseline_support.py` as specified. Then print the digest with `<venv>/bin/python -c "from pipeline.agentic.baseline import current_gate_version as v; print(v())"` and write it as the literal `PRE_REVISION_GATE_VERSION` with the comment "GATE_VERSION when the frozen-baseline release was made; a baseline whose gate_version differs was frozen after the gate was revised".
- [ ] **Step 4: Run** `tests/test_baseline.py` → PASS.
- [ ] **Step 5: Commit**

```bash
git add pipeline/agentic/baseline.py tests/baseline_support.py tests/test_baseline.py
git commit -m "feat: frozen baseline models, gate version, grouping and tags"
```

### Task 4: Freeze, load and replay-pinning

**Files:**
- Modify: `pipeline/agentic/baseline.py`, `tests/baseline_support.py` (add the `frozen` fixture)
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: Task 2 (`pin_profile_dir`, `bundle_from_contents`), Task 3, `jobwatch.candidate.intake.current_version`, `jobwatch.candidate.evidence._ALLOWED` and `snapshot_evidence`, `jobwatch.candidate.policy.default_policy`, `pipeline.agentic.location.km_from_home`, `pipeline.agentic.gate.decide`, `pipeline.agentic.persistence._read_artifact`, `pipeline.agentic.service._config`, `IMPLEMENTATION_VERSION`, `pipeline.agentic.matching.MATCHING_VERSION`, `pipeline.agentic.contracts.parse_budget_checkpoint_json`.
- Produces:
  - `PROFILE_FILES = tuple(dict.fromkeys(_ALLOWED + ('interests_and_criteria.yaml',)))`
  - `freeze_baseline(conn: sqlite3.Connection, config, *, posting_ids: list[int] | None = None, limit: int = 500) -> Baseline`
  - `load_baseline(baseline_id: str) -> tuple[Baseline, list[FrozenCase]]` (cases sorted by `posting_id`; large fields inflated, each blob read once per call so cases share one object)
  - `list_baselines() -> list[Baseline]` (oldest first; ignores folders without `baseline.json` and dot-folders)
  - `pinned_profile(baseline_id: str) -> ContextManager[Path]`: verifies `profile/` against `Baseline.profile_files_sha256`, then `pin_profile_dir(<baseline>/profile)`.
  - `decide_frozen(snapshot: dict, evaluation: dict, *, commute_km: float | None) -> dict`: rebuilds the bundle with `bundle_from_contents` from `snapshot['contents']`, calls `decide(AgenticEvaluation, ad_text=snapshot['full_ad'], title=snapshot['posting']['title'], policy=default_policy(), captured_complete=snapshot['text_kind'] == 'full', expected_run_key=RunKey(snapshot['run_key']), evidence_bundle=bundle, commute_km=None if commute_km is None else round(commute_km))` and returns `AgenticGateDecision.model_dump(mode='json')`; on failure `{'error': 'evidence_snapshot_invalid' | 'invalid_gate_input' | 'decision_unavailable'}`. Reproducible only inside `pinned_profile`; Plan 6b calls it for the revised arm.
  - Error codes (`AgenticError(code)`): `invalid_limit`, `no_profile_version`, `no_cases`, `baseline_exists`, `baseline_not_found`, `baseline_corrupt`, `invalid_baseline_id` (id must match `^bl-\d{8}T\d{6}Z-[0-9a-f]{8}$`).
  - Helpers fixed by tests: `_utcnow() -> str` (ISO seconds, UTC), `_git_commit(root: Path | None = None) -> str` (`git rev-parse HEAD`, 5 s timeout, no shell, `'unknown'` on any failure). Every file in the staging folder is written through the module-level name `safe_write_bytes`.

**Algorithm of `freeze_baseline`:**
1. `limit` int 1..1000 and `posting_ids` (if given) a list of at most 1000 positive ints, else `invalid_limit`. `person = users.current()`; `intake.current_version(person)` is None → `no_profile_version`.
2. Select: from `agentic_runs` (table missing → `no_cases`) take, per posting, the newest run (highest `generation`, then `rowid`) that has both a `snapshot` and an `evaluation` row in `agentic_artifacts`; postings with runs but none such are counted in `summary['skipped']['no_evaluation']`; requested `posting_ids` without any run count as `no_run`. Order by chosen run `rowid` descending, keep `limit`, then sort by `posting_id`. Zero cases → `no_cases`.
3. Create `baselines/.staging-<hex>`; copy each present `PROFILE_FILES` entry into `profile/` (read with `candidate._private_io.read_profile_source`; `cv.md` symlink alias is stored under its canonical name; unreadable → `AgenticError('profile_unreadable')`), write `approved.json` (canonical JSON of the current version). Under `pin_profile_dir(staging/'profile')`: `policy = default_policy().model_dump(mode='json')`, `evidence_bundle_hash` from `snapshot_evidence(staging/'profile')` (None if it raises `CandidateError`), then per case: read artifacts with `_read_artifact` (a hash or JSON failure is skipped and counted `artifact_invalid`; an evaluation failing `validate_model_payload(AgenticEvaluation, ...)` is counted `evaluation_invalid`); `commute_km = km_from_home(posting['location'] or '')` as float or None; `decision = decide_frozen(...)`; `stored = {'run_status','run_reason','generation','stage','stage_reason','application_status'}` from `agentic_runs`, `pipeline_state` and `applications` (missing tables give None); `usage = {'charged_tokens': BudgetCheckpoint.job_charged or None, 'actual_tokens': None, 'latency_seconds': sum of finished.at - started.at over agentic_activity pairs for the run key, or None}`.
4. Group keys from `group_keys_for(posting_row, ad_hash)`, then `group_ids`; build each `FrozenCase` (`case_id = f'c-{posting_id}-{run_key[:8]}'`, `tags = tag_case(case)`).
5. Write blobs (`blobs/<sha256 of file bytes>.json`) for `candidate`, `structural_inputs['reference_utf8']` and `snapshot['contents']`, replacing them in the case file by `None`, `None` and `{}` with `blob_refs` naming `'candidate'`, `'structural_inputs.reference_utf8'`, `'snapshot.contents'`; write each case file (canonical JSON, sorted keys) and record its sha256.
6. `summary = {'cases', 'skipped': {...}, 'routes': {draft, archive, hold, error}, 'tags': {tag: n for every TAGS entry}, 'groups', 'largest_group', 'evidence_mismatch' (cases whose `run_key.evidence_hash` differs from `evidence_bundle_hash`), 'decision_errors'}`. `content_sha256 = digest({'cases': case_sha256, 'profile': profile_files_sha256, 'approved': approved_sha256})`; `baseline_id = 'bl-' + created_at as %Y%m%dT%H%M%SZ + '-' + content_sha256[:8]`; `runtime_config_sha256 = digest(service._config(config))`; write `baseline.json` last; `os.rename` the staging folder to `baselines/<id>` (exists → `baseline_exists`). Any exception removes the staging folder.

- [ ] **Step 1: Write the failing tests** in `tests/test_baseline.py`. Put the fixture `frozen(world)` in `tests/baseline_support.py` (it does `from test_agentic_service import SyntheticGateway, world  # noqa: F401`; both test modules import `frozen, world` from it so pytest registers them). It adds postings 42 (`'Synthetic Alpha'`), 43 (`'Synthetic Alpha Pty Ltd'`), 44 (`'Synthetic Beta'`, `low=True`); runs `agentic_batch_run([42, 43, 44], config, conn, evidence_bundle=bundle, llm=LLM(transport=gateway, keys=['synthetic']), operation='evaluate')` with `gateway = SyntheticGateway(bundle)`; opens a read-only connection `ro = sqlite3.connect(f'file:{config.db_path}?mode=ro', uri=True)` with `row_factory = sqlite3.Row`; patches `LLM.chat_once`, `LLM.chat` and `LLM.embed_once` to raise `AssertionError` after the batch; returns `types.SimpleNamespace(conn, ro, config, bundle, gateway, add)`. In the tests below `ro`, `config`, `gateway` stand for those attributes.

```python
def test_freeze_writes_a_private_hash_verified_baseline(frozen):
    b = freeze_baseline(ro, config)
    assert len(b.case_ids) == 3 and all(re.fullmatch(r'c-4[234]-[0-9a-f]{8}', c) for c in b.case_ids)
    assert b.gate_version == baseline.GATE_VERSION and b.person == users.current()
    assert b.profile_version == 2 and set(b.profile_files_sha256) <= set(baseline.PROFILE_FILES)
    # every file mode 0o600, every folder 0o700, under users.user_dir()/'baselines'/b.baseline_id
    loaded, cases = load_baseline(b.baseline_id)
    assert loaded == b and [c.posting_id for c in cases] == [42, 43, 44]
    by = {c.posting_id: c for c in cases}
    assert (by[42].decision['route'], by[42].decision['reason']) == ('draft', 'eligible')
    assert (by[44].decision['route'], by[44].decision['reason']) == ('archive', 'score_below_threshold')
    assert by[44].stored['run_status'] == 'archived' and by[42].stored['run_reason'] == 'evaluation_complete'
    assert by[42].evaluation['global_score'] == 4.3 and by[44].evaluation['global_score'] == 2.7
    assert 'previously_rejected' in by[44].tags and all(c.tags == baseline.tag_case(c) for c in cases)
    assert by[42].usage['charged_tokens'] > 0 and by[42].usage['actual_tokens'] is None and by[42].usage['latency_seconds'] > 0
    assert by[42].group_id == by[43].group_id != by[44].group_id        # 'Synthetic Alpha' and 'Synthetic Alpha Pty Ltd'
    assert by[42].snapshot['full_ad'] and by[42].candidate and by[42].structural_inputs['reference_utf8']

def test_freeze_calls_no_model_and_writes_no_database_row(frozen): ...   # ro connection succeeded; gateway.calls length unchanged; chat_once/embed_once patched to fail

def test_large_shared_artifacts_are_stored_once(frozen):
    # blobs/ holds at most 3 files; max size of cases/*.json < 200_000 bytes; loaded cases share one reference string object (is)

def test_tampered_baseline_is_refused(frozen):
    # flip a byte in a cases/*.json -> load_baseline raises AgenticError 'baseline_corrupt'
    # flip a byte in profile/profile.yaml -> pinned_profile(...).__enter__ raises 'baseline_corrupt'

def test_decision_follows_the_frozen_profile_not_later_edits(world):
    # posting 42 with its ad text extended by ' Full-time position, 38 hours per week. ' via adtext.save_text BEFORE evaluating;
    # evaluate (stored: held / evaluation_complete, no hours limit then);
    # write profile.yaml candidate.work_rights.hours_limit_per_fortnight = 48; freeze -> case.decision == archive / hard_gate
    # and summary['evidence_mismatch'] == 1 (profile.yaml is in the evidence bundle);
    # remove the limit from the live profile.yaml:
    #   decide_frozen(case.snapshot, case.evaluation, commute_km=None)['route'] == 'draft'            (live profile)
    #   inside pinned_profile(id): decide_frozen(...) == the stored case.decision                      (frozen profile)

def test_commute_is_measured_from_the_frozen_home(world):
    # profile.yaml candidate.location 'Brunswick, VIC' at freeze: case.commute_km == 5.0 for posting location 'Melbourne VIC';
    # live profile later changed to 'Geelong, VIC': km_from_home('Melbourne VIC') != 5 live, == 5 inside pinned_profile

def test_decide_frozen_reports_an_unbuildable_snapshot(frozen):
    assert decide_frozen({**case.snapshot, 'contents': {}}, case.evaluation, commute_km=None) == {'error': 'evidence_snapshot_invalid'}

def test_a_failed_freeze_leaves_no_visible_baseline(frozen, monkeypatch):
    # monkeypatch baseline.safe_write_bytes to raise OSError on its 3rd call
    # pytest.raises(OSError); list_baselines() == []; no entry under baselines/ at all (no .staging-*)

def test_baselines_are_per_person_and_ids_cannot_escape(frozen):
    # users.create_user_dirs('friend'); with users.use('friend'): load_baseline(b.baseline_id) -> 'baseline_not_found', list_baselines() == []
    # for bad in ('../x', 'bl-20260101T000000Z-zzzzzzzz', ''): 'invalid_baseline_id'

def test_freeze_refuses_without_a_profile_version_or_cases(world):
    # users.create_user_dirs('friend'): freeze for friend -> 'no_profile_version'
    # owner with a profile version but no agentic runs -> 'no_cases'; baselines/ not created

def test_unreadable_artifacts_are_skipped_and_counted(frozen):
    # corrupt one evaluation.json on disk -> freeze succeeds with 2 cases, summary['skipped'] == {'artifact_invalid': 1}
    # insert a bare agentic_runs row for a posting with no artifacts -> skipped['no_evaluation'] == 1

@pytest.mark.parametrize('limit', [0, 1001, True, '5'])
def test_limit_is_validated(frozen, limit): ...    # 'invalid_limit'

def test_git_commit_is_unknown_outside_a_checkout(tmp_path):
    assert baseline._git_commit(tmp_path) == 'unknown'
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_baseline.py -k "freeze or tampered or decision or commute or failed or per_person or limit or git or shared or skipped or unbuildable"` → FAIL (`AttributeError: freeze_baseline`).
- [ ] **Step 3: Implement** the signatures and the algorithm above. Reading is read-only: no `AgenticStore.ensure`, no `PersistenceAdapter`, no `dbm.connect`. Inflation uses a per-call `dict[str, Any]` blob cache. `Baseline.git_commit = _git_commit()`.
- [ ] **Step 4: Run** `tests/test_baseline.py tests/test_agentic_gate.py tests/test_agentic_matching.py` → PASS (each freeze test runs a three-job synthetic batch, about 15 s).
- [ ] **Step 5: Commit**

```bash
git add pipeline/agentic/baseline.py tests/test_baseline.py
git commit -m "feat: freeze the stored pipeline inputs and outputs into a verified baseline"
```

### Task 5: Owner labels

**Files:**
- Modify: `pipeline/agentic/baseline.py`
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: Task 4 (`load_baseline`, baseline folder layout), `apply.paths.safe_write_bytes`.
- Produces:
  - `class OwnerLabel(StrictFrozen)`: `case_id: str`, `actor: Literal['owner']`, `suitable: bool | None = None`, `relevance: int | None = Field(default=None, ge=0, le=3)`, `exclusion_violation: bool | None = None`, `note: str = Field(default='', max_length=2000)`, `labelled_at: str`; *additive:* `tags: tuple[str, ...] = ()` (owner-added, each in `TAGS`).
  - `label_case(baseline_id: str, case_id: str, *, actor: Literal['owner'], suitable: bool | None = None, relevance: int | None = None, exclusion_violation: bool | None = None, note: str = '', tags: tuple[str, ...] = ()) -> OwnerLabel`: appends one JSON line to `labels.jsonl` (read, append, rewrite through `safe_write_bytes`, under an `fcntl` lock on `labels.lock`); `labelled_at = _utcnow()`. Errors: `owner_required` (actor is not `'owner'`), `baseline_not_found`, `unknown_case` (no `cases/<case_id>.json`), `empty_label` (no judgment field and no tag), `invalid_tag`, `invalid_label` (relevance outside 0-3 or note too long).
  - `load_labels(baseline_id: str) -> dict[str, OwnerLabel]` (latest line per case; absent file is `{}`; nothing is imputed), `label_history(baseline_id: str) -> list[OwnerLabel]` (append order), `effective_tags(case: FrozenCase, labels: Mapping[str, OwnerLabel]) -> tuple[str, ...]` (union of `case.tags` and the label's tags, in `TAGS` order).

- [ ] **Step 1: Write the failing tests**

```python
def test_label_requires_the_owner_actor(frozen):
    for actor in ('agent', 'person', '', None):
        with pytest.raises(AgenticError, match='owner_required'):
            label_case(bid, case_id, actor=actor, suitable=True)
    assert load_labels(bid) == {}

def test_label_is_private_append_only_and_latest_wins(frozen):
    first = label_case(bid, cid, actor='owner', suitable=False, note='first')
    second = label_case(bid, cid, actor='owner', suitable=True, relevance=3, exclusion_violation=False)
    assert load_labels(bid)[cid] == second and label_history(bid) == [first, second]
    # labels.jsonl mode 0o600; baseline.json and every case file byte-for-byte unchanged by labelling

@pytest.mark.parametrize('kwargs, code', [({'relevance': 4}, 'invalid_label'), ({'relevance': -1}, 'invalid_label'),
    ({}, 'empty_label'), ({'tags': ('not_a_tag',)}, 'invalid_tag'), ({'note': 'x' * 2001, 'suitable': True}, 'invalid_label')])
def test_bad_labels_are_refused(frozen, kwargs, code): ...

def test_unknown_case_and_unknown_baseline_are_refused(frozen):   # 'unknown_case', 'baseline_not_found'

def test_owner_tags_extend_the_deterministic_tags(frozen):
    label_case(bid, cid, actor='owner', tags=('misleading_title',))
    assert 'misleading_title' in effective_tags(case, load_labels(bid))

def test_label_writer_is_not_reachable_from_agent_surfaces():
    for name in ('api', 'chat', 'profile_api', 'mcp_server', 'deepagents_runtime', 'api_store'):
        text = (ROOT / 'pipeline' / 'agentic' / f'{name}.py').read_text()
        assert 'pipeline.agentic.baseline' not in text and 'from .baseline' not in text and 'label_case' not in text
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_baseline.py -k label` → FAIL (`AttributeError: label_case`).
- [ ] **Step 3: Implement** the signatures above; `content_sha256` does not cover `labels.jsonl` (labels are the only mutable part).
- [ ] **Step 4: Run** `tests/test_baseline.py` → PASS.
- [ ] **Step 5: Commit**

```bash
git add pipeline/agentic/baseline.py tests/test_baseline.py
git commit -m "feat: owner labels for frozen cases, written only by the owner"
```

### Task 6: `jobwatch baseline` command

**Files:**
- Create: `jobwatch/baseline_cli.py`
- Modify: `jobwatch/cli.py` (`_extensions()` tuple), `.github/workflows/backend.yml` (add `tests/test_profile_pin.py`, `tests/test_baseline.py`, `tests/test_cli_baseline.py` to the `synthetic-backend` list)
- Test: `tests/test_cli_baseline.py` (new)

**Interfaces:**
- Consumes: Tasks 4-5, `jobwatch.config.load_config`, `config.db_path` (follows `--user`). The handler reads `baseline.PRE_REVISION_GATE_VERSION` and `baseline.current_gate_version()` as module attributes at call time (tests monkeypatch them).
- Produces `register(sub)` and `handle(args) -> int | None` in the style of `jobwatch/profile_cli.py` (`args.cmd == 'baseline'`, sub-action in `args.baseline_action`):
  - `baseline freeze [--limit N] [--posting-id ID ...]`: opens the person's DB read-only (`sqlite3.connect(f'file:{path}?mode=ro', uri=True)`, `row_factory = sqlite3.Row`), prints `froze <baseline_id>: <n> cases, <m> skipped`; when `current_gate_version() != PRE_REVISION_GATE_VERSION` it also prints to stderr `warning: the gate source differs from the pre-revision release; this baseline captures the revised gate`.
  - `baseline list`: one line per baseline `<id>  <created_at>  cases=<n>  profile_version=<v>  gate=<pre_revision|revised>`; none prints `no baselines`.
  - `baseline show <id> [--cases]`: JSON with the `Baseline` fields except `case_sha256`, plus `labels: {'labelled': n, 'unlabelled': m}`, `gate_state` (`pre_revision` when `gate_version == PRE_REVISION_GATE_VERSION`, else `revised`), `gate_changed_since_freeze` (`gate_version != current_gate_version()`), `missing_tags` (tags with zero cases); `--cases` appends one line per case `<case_id> <posting_id> <route>/<reason> <tags>`. No candidate text is printed.
  - `baseline label <id> <case_id> [--suitable yes|no|unsure] [--relevance 0..3] [--exclusion-violation yes|no|unsure] [--note TEXT] [--tag TAG ...]`: calls `label_case(..., actor='owner')` (running the command is the owner's own act), prints `labelled <case_id>`; `unsure` is `None`.
  - Any `AgenticError` prints its code to stderr and returns 1; other `OSError`/`ValueError`/`sqlite3.Error` print `baseline_operation_unavailable` and return 1.

- [ ] **Step 1: Write the failing tests** (`from baseline_support import frozen, world  # noqa: F401`; `cli.main([...])` with `capsys`; `monkeypatch.setenv('JOBWATCH_DB', str(frozen.config.db_path))` so the CLI opens the world's database)

```python
def test_cli_end_to_end(frozen, capsys):
    run(['baseline', 'freeze', '--limit', '2'])                      -> rc 0, out matches r'^froze bl-\d{8}T\d{6}Z-[0-9a-f]{8}: 2 cases, 0 skipped$'
    run(['baseline', 'list'])                                         -> one line with 'cases=2', 'profile_version=2', 'gate=pre_revision'
    run(['baseline', 'show', bid, '--cases'])                         -> JSON: summary['cases'] == 2, labels == {'labelled': 0, 'unlabelled': 2},
                                                                         gate_state == 'pre_revision', gate_changed_since_freeze is False,
                                                                         set(missing_tags) <= set(TAGS); two case lines
    run(['baseline', 'label', bid, cid, '--suitable', 'yes', '--relevance', '3', '--tag', 'stretch'])  -> 'labelled <cid>'
    run(['baseline', 'show', bid])                                    -> labels == {'labelled': 1, 'unlabelled': 1}
    # when env JOBWATCH_PRINT_TRANSCRIPT=1 each command and its output is also printed with capsys.disabled()

def test_freeze_warns_when_the_gate_source_changed(frozen, capsys, monkeypatch):
    monkeypatch.setattr(baseline, 'PRE_REVISION_GATE_VERSION', '0' * 64)
    # rc 0; stderr contains 'warning: the gate source differs'; show reports gate_state 'revised'

def test_cli_errors_print_the_code_and_exit_one(tmp_path, monkeypatch, capsys):
    # friend with no profile: cli.main(['--user','friend','baseline','freeze']) == 1, 'no_profile_version' in err, out == ''
    # cli.main(['baseline','show','../x']) == 1 with 'invalid_baseline_id'
    # cli.main(['baseline','label', bid, cid, '--relevance', '9']) == 1 with 'invalid_label'

def test_label_command_is_the_only_label_caller():
    # grep jobwatch/ and pipeline/ python sources: 'label_case(' appears only in baseline.py and baseline_cli.py
```

- [ ] **Step 2: Run to verify they fail** — `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/test_cli_baseline.py` → FAIL (`error: argument cmd: invalid choice: 'baseline'`).
- [ ] **Step 3: Implement** `baseline_cli.py`, add `"jobwatch.baseline_cli"` to the `_extensions()` tuple, update `backend.yml`.
- [ ] **Step 4: Run** `tests/test_cli_baseline.py tests/test_cli_profile.py tests/test_baseline.py tests/test_profile_pin.py` → PASS.
- [ ] **Step 5: Commit**

```bash
git add jobwatch/baseline_cli.py jobwatch/cli.py .github/workflows/backend.yml tests/test_cli_baseline.py
git commit -m "feat: jobwatch baseline freeze, list, show and label"
```

### Task 7: Release check, documentation and workflow example

**Files:**
- Create: `docs/examples/frozen-baseline.md`
- Modify: `README.md` (CLI list and a "Frozen baseline" subsection after "Profile workflow"), `pipeline/agentic/MATCHING.md` (one paragraph under "Remaining experiment before policy promotion": freeze the inputs first with `jobwatch baseline freeze`, group duplicates/employers by `group_id`, labels are the owner's, no numbers changed), `pipeline/agentic/CHAT.md` ("Backup, release and undo": `baselines/` is candidate-bearing, not exposed through the API, included in folder backups)

- [ ] **Step 1: Prove the plan left the frozen surfaces alone.** Run `git diff --stat origin/main -- pipeline/agentic/gate.py pipeline/agentic/location.py jobwatch/candidate/person.py jobwatch/reader.py pipeline/agentic/service.py jobwatch/preferences` → no output. Run `<venv>/bin/python -c "from pipeline.agentic.baseline import GATE_VERSION as g, PRE_REVISION_GATE_VERSION as p; assert g == p, 'a gate source changed'"` → exits 0. If either fails, revert the offending edit; this plan must not change a decision.
- [ ] **Step 2: Run the full suite** once: `<venv>/bin/python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=90` (about 20 minutes, nothing else running). If collection errors come from `tests/apply/test_prefill*.py` or `test_prepare.py` because the `browser` extra is missing, install it with `uv pip install --python <venv>/bin/python -e '.[dev,browser]'` (never `playwright install`). Record the exact pass/skip/fail line. A failure must be shown to also fail on `origin/main` before it is called pre-existing.
- [ ] **Step 3: Capture the example.** Run `JOBWATCH_PRINT_TRANSCRIPT=1 <venv>/bin/python -m pytest -q -p no:cacheprovider -s tests/test_cli_baseline.py::test_cli_end_to_end` and write `docs/examples/frozen-baseline.md` from that output: the `freeze`, `list`, `show --cases`, `label` and second `show` commands with their real output (ids shortened to eight characters and an ellipsis, as in `docs/examples/profile-intake.md`), a note that the data is invented and no model was called, when to freeze (before Plan 2 is deployed), how `gate_state` reads, and the undo (`rm -rf <user_dir>/baselines/<id>`).
- [ ] **Step 4: Update README, MATCHING.md and CHAT.md** as listed. Do not change any figure in MATCHING.md (the "2,594 passed" line is updated only from an actual run; if Step 2's count differs, say so in the PR and leave the figure).
- [ ] **Step 5: Commit, push, open the PR** per `docs/superpowers/plans/EXECUTING.md` rule 8: summary, the checks run with exact results, rulings, limitations (no real baseline frozen; labels absent; tags are heuristics; `explicit_exclusion` limited to family rules; replays need `pinned_profile`), unverified items (behaviour on a real person's data), and undo.

```bash
git add docs/examples/frozen-baseline.md README.md pipeline/agentic/MATCHING.md pipeline/agentic/CHAT.md
git commit -m "docs: frozen baseline workflow example and release notes"
```

## Rollback

Revert the merge commit. The phase creates no database table and no migration. The only runtime data is `<user_dir>/baselines/` for any person on whom `jobwatch baseline freeze` was run; remove one baseline with `rm -rf <user_dir>/baselines/<baseline_id>` or all with `rm -rf <user_dir>/baselines`. Nothing else reads these folders, no stored artifact, run key, preference set or profile file was changed, and no re-evaluation or paid call is triggered by adding or removing them.

## Self-review

- **Spec coverage:** frozen identical inputs and outputs (tasks 3-4); the six required categories (task 3 tags + `missing_tags` in task 6); duplicate advert and related employer grouping (task 3); holistic score and gate route kept as the baseline (task 4: `evaluation.global_score`, recomputed `decision`, `stored`); gate version and pinned profile (tasks 2-4); owner labels with missing ones explicit (task 5); cost and latency inputs (`usage`, task 4); private data handling and isolation (constraints, tasks 4-5); ADR, glossary, example and rollback (tasks 1, 7). Splits, metrics and reports are Plan 6b by design.
- **Step scan:** every code step names its signature, file and the tests that pin it; `freeze_baseline` is the only step with an algorithm, given as numbered decisions.
- **Type consistency:** `FrozenCase`, `Baseline`, `OwnerLabel`, `GATE_VERSION`, `tag_case`, `group_ids`, `pin_profile_dir`, `bundle_from_contents`, `decide_frozen`, `pinned_profile`, `label_case` are spelled identically in every task and in the contract; additive fields are marked.
- **Review Focus:** all five lines have a named test (tasks 3, 4, 5).
- **Proportion:** tests assert behaviour; only the freeze algorithm and the tag table are spelled out because tests alone do not determine them.

## Contract issues

1. `GATE_VERSION` as defined hashes four files, but `decide()` also depends on `jobwatch/candidate/contracts.py` (`KNOWN_FAMILIES`, `canonicalize_family`, `excluded_families`), `jobwatch/candidate/policy.py` (`default_policy`) and the data files `pipeline/agentic/data/vic-geo.json` and `metro-localities.json`. This plan keeps `GATE_VERSION` exactly as in the contract and records the extra hashes in `Baseline.gate_dependencies`; proposed change: add them to the contract's definition (Plan 2 will extend `candidate/policy.py` anyway).
2. Rule 2 says the gate version is "stored with every recorded route". Live routes are not stored today and recording one per run would need a schema change; this plan stores `gate_version` once per baseline, where every route is recomputed together. Proposed: read the rule as "every baseline route".
3. `pinned_profile` pins the profile folder only. Plan 2's `policy_for(person)` reads `intake.current_version(person)`, which a profile pin does not cover; the baseline folder therefore keeps `approved.json`, and Plan 2 must make `policy_for` (and `decide_frozen`) accept a pinned approved version, otherwise a replay would use the live approved facts.
