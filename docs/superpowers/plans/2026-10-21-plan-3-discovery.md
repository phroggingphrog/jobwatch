# Plan 3: Field and job discovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover a person's suitable occupational fields by semantic retrieval of their approved facts against versioned reference datasets, turn those fields into the collectors' search plan, decide a posting's relevance from its full ad (quoted extraction plus similarity to the discovered fields) instead of title keywords, and deduplicate the same vacancy across sources by description similarity.

**Architecture:** A new package `jobwatch/occupations/` holds public, hash-verified reference data (`datasets.py`, `loaders.py`), the embedding cache and budget helpers (`embeddings.py`), `field_hypotheses` (`hypotheses.py`) and the `SearchPlan` (`plan.py`). `pipeline/agentic/discovery.py` holds the posting-side steps (relevance, exclusion pre-filter, screening, semantic dedupe, ordering) and re-exports every contract name. All embeddings go through the existing `PaidGatewayEmbeddings` (Qwen route, `require_route`, `JobBudget`); the legacy `openrouter_extras.embed` path stays only behind `legacy` flag values. Every new behaviour is behind the flags `pipeline.agentic.search_plan` (default false), `pipeline.agentic.relevance: off | shadow | on` (default `shadow`: judged and stored, nothing archived, and nothing at all happens until the owner has run `refresh`), `pipeline.agentic.dedupe: legacy | semantic` and `pipeline.agentic.ordering: legacy | hypotheses` (defaults `legacy`); numeric tuning lives in `pipeline.discovery.*`. Nothing here enters the `RunKey`.

**Tech Stack:** Python 3.12, numpy (already imported by `service.py`), pydantic v2 `StrictFrozen`, SQLite (`jobwatch/db.py` migration), FastAPI, pytest with synthetic transports (`tests/test_agentic_service.py` `SyntheticGateway`, `world`).

**Spec:** [agreed backend brief](../specs/2026-10-21-agreed-backend-brief.md) (section A.3 "Field discovery and statistical ranking" and A.4 "Automatically collect, deduplicate, assess…"; section B "Semantic filtering"), [roadmap](2026-10-21-backend-roadmap.md) Plan 3 row, [cross-plan contract](2026-10-21-cross-plan-contract.md) "Phase 4 — Plan 3" and "Reconciled decisions" (binding; applied here, see "Contract reconciliation" at the end), [code map](reference/2026-10-21-codemap.md) section 3 (line numbers there are as of `ce9e342`; verify before editing).

**Depends on (merged before this plan runs):** Plan 1 (`intake.current_version`, `discovery_scope`), Plan 6a (baseline; do not change its files), Plan 2 (`jobwatch/candidate/policy.py`: `DecisionPolicy`, `ExclusionRule`, `policy_for(person, *, approved=None) -> DecisionPolicy | None`, `exclusion_hit(policy, *, family: str | None, company: str, title: str, location_text: str, remote: bool, hours: str) -> ExclusionRule | None`; `pipeline/agentic/service.py`: `decision_policy_mode(config) -> Literal['legacy', 'profile']`, `gate_current`). Before Task 1 run `grep -rn "def policy_for\|class DecisionPolicy\|class ExclusionRule\|def exclusion_hit\|def decision_policy_mode" jobwatch pipeline`; if any is missing, stop and report the failed precondition (EXECUTING.md rule 1).

## Global Constraints

- "Field discovery: extend semantic retrieval to candidate evidence versus occupational tasks and skills. Existing Qwen retrieval for individual advertisements is not sufficient by itself. Reuse approved retrieval infrastructure. Version reference datasets and mappings; investigate current Australian classifications and available O*NET/ESCO correspondences. Related occupations are search hypotheses, not qualification proof."
- Owner, on semantic filtering: "it should use semanntic reasoning/extraction to filter out how about that" (spelling as the owner wrote it). Title keywords may help discover postings; they never decide personal fit.
- "Explicit exclusions are rules." "Never record agent-generated answers as user choices or approval." "Automatically collect, deduplicate, assess, rank and refresh opportunities within confirmed limits." "Preserve identity isolation, budgets, cancellation, recovery and private data handling." "Do not claim deployment or improved matching accuracy without the corresponding evidence."
- Synthetic data only: tests never read a live candidate record, never reach a real model or the network; reference-data tests use tiny invented files, plus the public bundled reference already in the repo.
- Per-person isolation: hypotheses, plans, vectors of ads and judgments live under `users.user_dir(person)` / the person's DB (0700/0600 via `apply.paths.ensure_dir` / `safe_write_bytes`). Only public reference text and its vectors are shared, under `users.base_dir()/'reference'`.
- Paid calls only on approved routes: embeddings through `PaidGatewayEmbeddings` with the configured `pipeline.agentic.embedding_model` (`execution.require_route(..., embedding=True)`), the relevance model call through `run_role` (`require_route`); tests use synthetic transports. Candidate text goes only to the Qwen embedding route and is never in a chat prompt of this plan; no hosted tracing.
- No service or timer is activated by a source change; the timer path only runs new code when a `pipeline.agentic` discovery flag is turned on, or (`relevance: shadow`, the default) after the owner has run `refresh`. No submission, no employer contact, no document preparation.
- Model output is never recorded as a person's choice or approval: relevance judgments and archive reasons are system records; this plan writes nothing to `applications`, `application_events`, preference or feedback tables.
- Schema changes are additive: one `jobwatch/db.py` migration (next index at execution time) creates all new tables; no lazy `ensure()` for them. New stored models are `StrictFrozen` with defaults; no existing stored model changes.
- Run-key rule (contract rule 1): nothing in this plan changes `_config()`, the `TargetPolicy`, `IMPLEMENTATION_VERSION`, `RUBRIC_VERSION` or `LOCATION_REFERENCE_HASH`, so no stored evaluation is re-run. Discovery settings live in `pipeline.agentic.{search_plan,relevance,dedupe,ordering}` and `pipeline.discovery.*`; `service._config` reads neither (it picks named keys only; Task 4 pins this with a test). With the default `relevance: shadow` and no `refresh` having been run, `screen_step` finds no cached hypotheses or plan, makes no call and returns `{}` (Task 7 `test_default_shadow_costs_nothing_before_refresh`). Expected paid cost of turning flags on or running `refresh`: no existing job is re-evaluated; per newly ingested posting at most 4 embedding inputs (about 2,000 tokens) plus, only below the similarity threshold, one short relevance model call (at most the first 12,000 characters of the ad plus 1,500 output tokens reserved, settled to actual usage, typically 3,000-5,000); a one-time shared reference index (about 450 tokens per occupation record; roughly 0.5M tokens for the bundled 1,074 ANZSCO occupations, more for each further dataset). `search_plan: true` changes which postings are collected and so can raise the number of new evaluations, still capped by `scope.daily_assessments` and `scope.daily_token_ceiling`.
- Preference-file rule (contract rule 5): this plan touches none of `jobwatch/preferences/features.py, store.py, model.py, fit_choice_model.R, choice_model.jags`.
- Python 3.12 virtualenv outside the repo (`uv venv --python 3.12 <scratch>/venv && uv pip install --python <scratch>/venv/bin/python -e '.[dev]'`). Test command everywhere below: `<venv>/bin/python -m pytest -q -p no:cacheprovider <paths>`. Ten files under `tests/apply/` need the `browser` extra and fail at collection without it; ignore them unless it is installed.

## Review Focus

Failure modes the spec implies that are most likely to bite a person; each has a test in the named task.

1. A misleading title: the title names a target role but the duties are another field (or the title sounds unrelated but the duties are the person's work). The decision uses the full ad, so a good-sounding title never rescues a clearly unrelated ad and a dull title never archives a related one. (Task 7 `test_misleading_title_is_judged_by_the_full_ad`.)
2. The model answers `no` with a quote that is not in the ad, or paraphrased. An unverifiable quote must never archive anything; the posting proceeds as `uncertain`. (Task 7 `test_no_without_a_verified_quote_becomes_uncertain`.)
3. The embedding or model route is unavailable, refused, or out of budget mid-screen. Nothing is archived, the postings still go on to evaluation exactly as before, and the day's budget is not blown. (Task 7 `test_route_outage_archives_nothing_and_pending_jobs_still_evaluate`.)
4. A profile whose facts are all inference/unknown, or a machine with no reference data. The answer is an explicit error (`no_profile_facts`, `reference_unavailable`), never an empty list presented as "no fields" and never invented hypotheses. (Task 5.)
5. Duplicate false positives: one ad template for different cities or stores, the same company's distinct requisitions from one source, a recruiter reposting another company's ad. These must not be merged; a true cross-source repost with differently spelled company must be. (Task 8.)

---

### Task 1: ADR and glossary for field and job discovery

**Files:**
- Create: `docs/adr/NNNN-field-and-job-discovery.md` (NNNN = lowest unused four-digit number in `docs/adr/` at execution time; use the same number everywhere below)
- Modify: `GLOSSARY.md` (rows: Field hypothesis, Reference dataset, Search plan, Relevance judgment, Recall pre-screen, Semantic duplicate)

- [ ] **Step 1: Write the ADR** in the format of `docs/adr/0002-profile-intake-and-approval.md` (Date 2026-10-21, Status "Accepted owner direction (backend brief of 2026-10-21); deployment and matching quality have their own acceptance criteria", Context, Decision, Consequences, References). The Decision section records these decisions, each one short paragraph:
  1. **Fields.** A person's approved facts (sections `experience, education, skill, transferable_skill, career_focus`; basis `evidence` or `inference`, never `unknown`) are embedded as queries (new query kind `field_from_evidence`) and compared with occupation documents (title, description, tasks, skills) embedded as plain documents. An occupation's score is the mean of its three highest fact similarities. The result is a `FieldHypothesis` list; `is_qualification_proof` is the constant `False`; it is a search hypothesis only.
  2. **Strategy.** `DecisionPolicy.strategy` shapes the list: `employment_first` ranks by evidence only across all permitted fields; `career_focus` gives two thirds of the slots (rounded up) to the focus ranking and the rest to evidence; `balanced` alternates. Explicit exclusions always remove hypotheses. The bundled `Occupation.excluded` flag and `MINIMUM_EXCLUDED_CODES` are the owner's local annotations and are not used.
  3. **Reference data.** Public, versioned, hash-verified datasets under `<data>/reference/<dataset>/<version>/` (`<data>` = `users.base_dir()`), never committed. The bundled `jobwatch/candidate/data/occupation-reference.json` (ANZSCO 2022 occupations with O*NET activity weights) is always available; O*NET tasks/skills, ESCO and OSCA are optional and each has a `PINNED` spec. The result of the investigation (Task 2) is recorded in this ADR.
  4. **Search plan.** `SearchPlan` queries come from hypothesis titles and `policy.focus`, locations from `policy.home` and the confirmed scope; with `pipeline.agentic.search_plan: true` Seek, Jora and JobSpy read a derived overlay of `searches.yaml` instead of the owner's lists. `searches.yaml` stays the fallback.
  5. **Relevance.** Title keywords become a recall pre-screen that can only add postings for detail fetching. The relevance decision reads the full ad: similarity of the ad passages to the hypotheses' reference vectors; at or above `similar_at` the answer is `yes`; below it, one candidate-free model extraction returns `yes/no/uncertain` with verbatim quotes. `no` requires at least one quote verified against the title/ad; otherwise `uncertain`. Similarity alone never archives. `no` archives with reason `not_relevant` only in `relevance: on`; in `shadow` (the default) the judgment is only stored; `uncertain` proceeds.
  6. **Exclusion pre-filter.** Employer, title-term, location and work-type rules from `DecisionPolicy.exclusions` archive an ingested posting as `excluded_by_rule` before any paid call (family rules stay in the gate). Exclusion rules take effect only with `pipeline.agentic.decision_policy: profile` (contract decision 3), whatever the relevance mode; with `legacy` the pre-filter does nothing.
  7. **Semantic duplicates.** Two live postings from different sources are the same vacancy when the cosine of their mean passage vectors is at least `duplicate_cosine`, the normalised company names are equal or one's tokens contain the other's, titles share Jaccard ≥ 0.6, and the cities match (or both are remote). The newer, non-READY copy is archived `duplicate_of:<id>`. Pairs failing a test are different vacancies.
  8. **Embedding path.** `semantic` dedupe and `hypotheses` ordering replace `_near_duplicates` and `_target_first` behind flags (defaults `legacy`); the legacy code is not removed in this plan.
  9. **Cost and versioning.** No run-key input changes. Judgments are stored in table `posting_relevance` per `(posting, ad_hash, plan_hash)` and read back with `discovery.latest_judgment(conn, posting_id) -> RelevanceJudgment | None` (Plans 4 and 6b read it); vectors per `(text hash, model)`.
  10. **Not claimed.** `similar_at` (0.60) and `duplicate_cosine` (0.95, the value `_near_duplicates` already uses) are uncalibrated design choices; no accuracy claim is made. Calibration needs owner labels (Plan 6b). Alternatives rejected: title keywords alone (the owner rejected them), an LLM call for every posting (cost), a trained classifier (no labels), BM25 hybrid (kept as future work).
  Add a section `## Reference dataset investigation` containing only the line `Completed in Task 2.` for now.
- [ ] **Step 2: GLOSSARY rows** (one sentence each, consistent with the ADR): Field hypothesis ("a related occupation found by semantic retrieval from approved facts, used as a search hypothesis; never proof of qualification"); Reference dataset ("public, versioned, hash-verified occupation data under `<data>/reference/`"); Search plan ("the queries and locations collectors use, derived from field hypotheses and the decision policy"); Relevance judgment ("a stored yes/no/uncertain verdict on whether a posting's full ad belongs to the person's fields, with verbatim quotes"); Recall pre-screen ("title keywords that may only add postings for detail fetching, never exclude one from the semantic step"); Semantic duplicate ("the same vacancy listed by different sources, found by description similarity plus company, title and city agreement").
- [ ] **Step 3: Commit** `docs: ADR NNNN field and job discovery`.

### Task 2: Investigate the reference datasets; record them; fetch tooling

This task researches the current state of the datasets (it cannot be answered from memory), records the findings in the ADR and pins them in code.

**Files:**
- Create: `jobwatch/occupations/__init__.py`, `jobwatch/occupations/datasets.py`, `tests/occupations/__init__.py`, `tests/occupations/test_datasets.py`
- Modify: the ADR from Task 1 (section `## Reference dataset investigation`)

**Interfaces:**
- Produces `jobwatch/occupations/__init__.py`: `ALGORITHM_VERSION = 'field-discovery-v1'`; `class DiscoveryError(ValueError)` with `.code: str` (fixed codes only; message is the code).
- Produces `jobwatch/occupations/datasets.py`:
  - `class FileSpec(StrictFrozen)`: `name: str`, `url: str`, `sha256: str | None`, `bytes: int | None` (`StrictFrozen` from `jobwatch.candidate.contracts`)
  - `class DatasetSpec(StrictFrozen)`: `dataset: Literal['onet','esco','osca']`, `version: str`, `source_url: str`, `licence: str`, `attribution: str`, `files: tuple[FileSpec, ...]`, `enabled: bool = True`, `notes: str = ''`, `columns: dict = {}` (the OSCA column map, see Task 3)
  - `PINNED: dict[str, DatasetSpec]` (filled from the investigation)
  - `reference_root() -> Path` (`users.base_dir() / 'reference'`); `dataset_dir(dataset: str, version: str) -> Path`
  - `class DatasetManifest(StrictFrozen)`: `dataset, version, source_url, licence, retrieved_at: str`, `sha256: dict[str, str]` (file name → hex), exactly the contract's manifest
  - `read_manifest(dataset, version) -> DatasetManifest | None`; `verify_dataset(dataset: str, version: str) -> DatasetManifest` (raises `DiscoveryError('dataset_missing' | 'dataset_manifest_invalid' | 'dataset_hash_mismatch')`); `status() -> dict[str, dict]` (per `PINNED` dataset: `{'state': 'ready'|'missing'|'mismatch'|'disabled', 'version', 'licence'}`; no network)
  - `fetch_dataset(spec: DatasetSpec, *, opener=None, trust_on_first_use: bool = False) -> DatasetManifest` (`opener(url) -> bytes`, default uses `requests` with a 120 s timeout; refuses non-https or hosts other than those in `spec.files` / `spec.source_url` (`dataset_url_refused`); caps a file at 300 MiB (`dataset_too_large`); a pinned `sha256` mismatch deletes the file and raises `dataset_hash_mismatch`; `sha256 is None` without `trust_on_first_use` raises `dataset_unpinned`; writes with `apply.paths.safe_write_bytes`, then the manifest last)
  - `main(argv=None) -> int` for `python -m jobwatch.occupations.datasets status | verify <dataset> | fetch <dataset> [--trust-on-first-use]` (prints computed hashes so the owner can pin them)

- [ ] **Step 1: Write the failing tests** in `tests/occupations/test_datasets.py` (opener injected, `JOBWATCH_DATA_DIR` is a tmp dir through the autouse fixture):

```python
def spec(sha=None, url='https://data.example.invalid/a.csv'):
    return DatasetSpec(dataset='onet', version='t1', source_url='https://data.example.invalid/', licence='CC BY 4.0',
                       attribution='Test', files=(FileSpec(name='a.csv', url=url, sha256=sha, bytes=None),))

def test_fetch_refuses_hash_mismatch_and_leaves_nothing():
    with pytest.raises(DiscoveryError, match='dataset_hash_mismatch'):
        fetch_dataset(spec(sha='0' * 64), opener=lambda url: b'x,y\n1,2\n')
    assert not (dataset_dir('onet', 't1') / 'a.csv').exists()

def test_unpinned_fetch_needs_trust_on_first_use_then_records_the_hash():
    with pytest.raises(DiscoveryError, match='dataset_unpinned'):
        fetch_dataset(spec(), opener=lambda url: b'x\n')
    m = fetch_dataset(spec(), opener=lambda url: b'x\n', trust_on_first_use=True)
    assert m.sha256['a.csv'] == hashlib.sha256(b'x\n').hexdigest()
    assert stat.S_IMODE((dataset_dir('onet', 't1') / 'a.csv').stat().st_mode) == 0o600
    assert stat.S_IMODE(dataset_dir('onet', 't1').stat().st_mode) == 0o700
    assert verify_dataset('onet', 't1') == m

def test_verify_detects_tampering():
    fetch_dataset(spec(), opener=lambda url: b'x\n', trust_on_first_use=True)
    (dataset_dir('onet', 't1') / 'a.csv').write_bytes(b'tampered\n')
    with pytest.raises(DiscoveryError, match='dataset_hash_mismatch'):
        verify_dataset('onet', 't1')

@pytest.mark.parametrize('url', ['http://data.example.invalid/a.csv', 'https://elsewhere.example.invalid/a.csv'])
def test_fetch_refuses_non_https_and_foreign_hosts(url):
    with pytest.raises(DiscoveryError, match='dataset_url_refused'):
        fetch_dataset(spec(url=url), opener=lambda u: b'x')

def test_status_never_touches_the_network_and_reports_missing(monkeypatch):
    monkeypatch.setattr(datasets, 'PINNED', {'onet': spec()})
    assert status()['onet']['state'] == 'missing'
```
- [ ] **Step 2: Run** `<venv>/bin/python -m pytest -q -p no:cacheprovider tests/occupations/test_datasets.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `datasets.py` per the interfaces (hash with `hashlib.sha256`; manifest JSON is `DatasetManifest.model_dump_json`; `main` returns 0/1 and prints one line per file).
- [ ] **Step 4: Run** the test file → PASS.
- [ ] **Step 5: Investigate the datasets** (research, not memory). For each item write down the finding with its source URL and the date you read it; unknowns are stated as unknown, never guessed. Use WebFetch/WebSearch or `curl` through the configured proxy (never disable TLS verification or unset `HTTPS_PROXY`; see `/root/.ccr/README.md` and `curl -sS "$HTTPS_PROXY/__agentproxy/status"` for proxy problems).
  1. **O\*NET:** the current database release and date (`https://www.onetcenter.org/database.html`; the repo pins 31.0 in `jobwatch/candidate/data/source-manifest.json`), the CSV/text file names and column headers of the occupation data, task statements (core vs supplemental flag) and skills (importance scale) files, the licence (CC BY 4.0 per `ATTRIBUTION.md`; confirm the attribution wording), file sizes.
  2. **ESCO:** the current classification version and release date, the English CSV package contents (`occupations_en.csv`, `skills_en.csv`, `occupationSkillRelations_en.csv` or their current names and headers), whether the package can be downloaded by a script or only through a web form, the licence and attribution requirement.
  3. **Australian classifications:** (a) whether ABS ANZSCO 2022 has a newer revision than the pinned 2022 structure of June 2023; (b) whether ABS has released OSCA (Occupation Standard Classification for Australia): version, release date, licence, download URLs, workbook layout (sheet numbers, column letters of code, title, description), and the ANZSCO-to-OSCA correspondence workbook and its layout; (c) whether Jobs and Skills Australia publishes the Australian Skills Classification (skills, tasks and technologies linked to occupations) with a licence that allows local use, as a possible source of Australian task and skill text.
  4. **Correspondences:** which are available and loaded here: O*NET-SOC to ANZSCO (bundled, built from ESCO/ISCO and the ABS tables), ESCO to O*NET-SOC (O*NET Resource Center crosswalk, hosted `ESCO_to_ONET-SOC.xlsx`, already in the manifest), ANZSCO 2022 to OSCA (ABS), ESCO occupation to ISCO group (inside ESCO files). For each: one-to-one or many-to-many, and whether the ABS/O\*NET text calls it exact or broad.
  5. For each dataset decide `enabled` (usable: licence permits local derived vectors, structure understood, files reachable) or `enabled=False` with the reason. Datasets whose licence is unclear are `enabled=False`.
- [ ] **Step 6: Record and pin.** Fill `## Reference dataset investigation` in the ADR with a table (dataset, version, release date, files with sizes, licence and attribution text, correspondences, decision, source URL read on date) and a paragraph per unknown. Fill `PINNED` with the exact URLs; set `sha256`/`bytes` for every file whose bytes you could download and hash, otherwise `None`. Fill `DatasetSpec.columns` for OSCA with the column map Task 3 consumes (`{'structure': {'sheet': int, 'code': 'A', 'title': 'B', 'description': 'C'}, 'correspondence': {'sheet': int, 'anzsco': 'A', 'osca': 'C'}}` shape; use the real letters).
  **If a download is blocked by the network** (HTTP 403/407/timeout from the proxy, or the host is not reachable): do not work around the proxy and do not stop. Record per URL the exact failure (`status`, host) in the ADR table with the state `unverified: download blocked here`; keep researching from documentation pages that are reachable (`WebSearch`/`WebFetch` may work where file downloads do not); set `sha256=None` for the unreachable files; and tell the owner in the PR that they run `python -m jobwatch.occupations.datasets fetch <dataset> --trust-on-first-use` on a machine with access, review the printed hashes, then commit the pinned values. If even documentation is unreachable, the only known-good pins are the O\*NET 31.0 and ABS ANZSCO 2022 / ESCO crosswalk entries from `source-manifest.json`; add those, set every other dataset `enabled=False` with `notes='not investigated: network blocked; owner to complete'`, and say so in the ADR. In every case the later tasks run on the bundled reference plus synthetic fixtures, so nothing downstream waits on a download.
- [ ] **Step 7: Run** the Task 2 tests again → PASS. **Commit** `feat: pin reference datasets and add a verified fetch tool; record the dataset investigation`.

### Task 3: Reference loaders and occupation records

**Files:**
- Create: `jobwatch/occupations/loaders.py`, `tests/occupations/fixtures.py`, `tests/occupations/test_loaders.py`

**Interfaces:**
- Consumes: `datasets.PINNED`, `datasets.verify_dataset`, `datasets.dataset_dir`; `jobwatch.candidate.reference.load_reference(path) -> ReferenceBundle | None` and the bundled path `Path(jobwatch.candidate.__file__).with_name('data') / 'occupation-reference.json'`.
- Produces `loaders.py`:
  - `class OccupationRecord(StrictFrozen)`: `scheme: Literal['anzsco2022','onet','esco','osca']`, `code: str`, `title: str`, `text: str` (≤ 1,800 characters; this is what is embedded), `family: str | None = None` (bundled policy annotation only), `dataset_version: str`; property `id -> f'{scheme}:{code}'`
  - `class Correspondence(StrictFrozen)`: `a: str`, `b: str` (record ids), `kind: Literal['exact','broad']`
  - `class LoadedReference(StrictFrozen)`: `records: tuple[OccupationRecord, ...]`, `correspondences: tuple[Correspondence, ...]`, `versions: dict[str, str]`, `skipped: dict[str, str]` (dataset → fixed code), `records_hash: str` (sha256 of the canonical JSON of `(scheme, code, text)` triples)
  - `record_text(title: str, description: str = '', tasks=(), skills=(), *, limit: int = 1800) -> str` (`"{title}. {description} Tasks: a; b. Skills: c, d."`, whitespace collapsed, cut at the last space before `limit`)
  - `read_sheet(path: Path, number: int) -> Iterator[dict[str, str]]` (stdlib `zipfile` + `xml.etree`, rows as `{column letters: value}`; same technique as `tools/build_occupation_reference.py:sheet`, which is left unchanged so its rebuild stays byte-deterministic)
  - `load_bundled(path=None) -> tuple[list[OccupationRecord], list[Correspondence], str]`: one record per `Occupation` (scheme `anzsco2022`; text = title plus the 12 highest-weight activity titles, ties by id; `family` copied; the `excluded` flag is ignored), plus a `broad` correspondence `onet:<soc>` ↔ `anzsco2022:<code>` per bundled crosswalk
  - `load_onet(directory: Path, version: str)`, `load_esco(directory, version)`, `load_osca(directory, version, columns: dict)`: each returns `(records, correspondences)`; missing required columns raise `DiscoveryError('dataset_schema_changed')`
  - `load_reference_records(*, only: tuple[str, ...] | None = None) -> LoadedReference`: bundled always; each enabled `PINNED` dataset only if `verify_dataset` passes and its loader succeeds, otherwise recorded in `skipped` with the error code; correspondences whose endpoints are not both loaded are dropped; `functools.lru_cache`d by `(dataset versions, bundled hash)` so repeated calls do not re-parse
- Loader rules: O\*NET text = title + description + up to 12 tasks (`Task Type == 'Core'` first, then by `Task ID`) + the 10 skills with the highest `IM` (importance) `Data Value`; ESCO text = preferred label + description + up to 15 essential skill labels (alphabetical); OSCA text = title + description. Use the real file and column names recorded in the ADR (Task 2); the fixtures below use those names.

- [ ] **Step 1: Write the failing tests** in `tests/occupations/test_loaders.py`; `tests/occupations/fixtures.py` provides `write_onet(dir)`, `write_esco(dir)`, `write_xlsx(path, sheets)` (a minimal `.xlsx` with shared strings) and registers a fixture dataset directory through `datasets.fetch_dataset` with an injected opener, using the column names from the ADR:

```python
def test_bundled_reference_gives_one_record_per_occupation():
    records, links, version = load_bundled()
    assert len(records) == 1074 and all(r.scheme == 'anzsco2022' and len(r.text) <= 1800 and r.text.startswith(r.title) for r in records)
    assert load_bundled()[0] == records                                      # deterministic

def test_record_text_cuts_on_a_word_boundary():
    t = record_text('Accountant', 'x ' * 2000)
    assert len(t) <= 1800 and not t.endswith(' ') and t.startswith('Accountant.')

def test_onet_loader_orders_core_tasks_first_and_keeps_top_skills(tmp_path_dataset):
    recs, _ = load_onet(write_onet(tmp_path_dataset), 'fx')
    r = {x.code: x for x in recs}['13-2011.00']
    assert r.text.index('Core task A') < r.text.index('Supplemental task B') and 'Mathematics' in r.text

def test_esco_loader_uses_essential_skills_only(tmp_path_dataset):
    recs, links = load_esco(write_esco(tmp_path_dataset), 'fx')
    assert 'keep accounting records' in recs[0].text and 'optional skill' not in recs[0].text

def test_missing_columns_fail_closed_and_other_datasets_still_load(fixture_datasets):
    broken = write_onet(fixture_datasets / 'onet', drop_column='Task')
    out = load_reference_records()
    assert out.skipped['onet'] == 'dataset_schema_changed' and len(out.records) >= 1074

def test_unverified_dataset_is_not_loaded(fixture_datasets):
    (fixture_datasets / 'onet' / 'task_statements.csv').write_bytes(b'tampered')
    assert load_reference_records().skipped['onet'] == 'dataset_hash_mismatch'

def test_osca_loader_uses_the_recorded_column_map(tmp_path):
    write_xlsx(tmp_path / 's.xlsx', {1: [['Code', 'Title', 'Description'], ['2111', 'Accountant', 'Prepares accounts']]})
    recs, _ = load_osca(tmp_path, 'fx', {'structure': {'sheet': 1, 'code': 'A', 'title': 'B', 'description': 'C'}, ...})
    assert recs[0].id == 'osca:2111'

def test_correspondences_with_an_unloaded_endpoint_are_dropped():
    assert all(c.a in ids and c.b in ids for c in load_reference_records().correspondences)
```
(`fixture_datasets` points `datasets.PINNED` at fixture specs via monkeypatch and fetches them with an injected opener; define it in `fixtures.py`.)
- [ ] **Step 2: Run** `tests/occupations/test_loaders.py` → FAIL. **Step 3: Implement** `loaders.py` and the fixtures. **Step 4: Run** → PASS (the real bundled file is public data; no candidate record is read).
- [ ] **Step 5: Commit** `feat: occupation records from the bundled reference, O*NET, ESCO and OSCA loaders`.

### Task 4: Embedding layer, vector caches and discovery budget

**Files:**
- Modify: `pipeline/agentic/gateway.py` (`embed_queries`), `jobwatch/db.py` (append one `MIGRATIONS` entry: index = `len(MIGRATIONS) + 1` at execution time), `pipeline/agentic/service.py` (`_spent_today`)
- Create: `jobwatch/occupations/embeddings.py`, `tests/occupations/test_embeddings.py`; extend `tests/occupations/fixtures.py`

**Interfaces:**
- Produces `gateway.py`: `QUERY_INSTRUCTIONS: dict[str, str] = {'requirement': 'Given a job requirement, retrieve candidate career evidence demonstrating relevant skills or experience.', 'field_from_evidence': "Given a statement of a person's work experience or skills, retrieve the occupations whose duties and required skills it relates to."}`; `PaidGatewayEmbeddings.embed_queries(self, texts, kind='requirement')` (same `Instruct: …\nQuery:{text}` format; unknown `kind` → `RuntimeErrorSafe('invalid_request')`); `embed_query` unchanged.
- Migration entry creates: `text_embeddings(key TEXT NOT NULL, model TEXT NOT NULL, dims INTEGER NOT NULL, vector BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(key, model))`; `posting_relevance(posting_id INTEGER NOT NULL REFERENCES postings(id) ON DELETE CASCADE, ad_hash TEXT NOT NULL, plan_hash TEXT NOT NULL, relevant TEXT NOT NULL CHECK(relevant IN ('yes','no','uncertain')), method TEXT NOT NULL, similarity REAL NOT NULL, mode TEXT NOT NULL, judgment_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(posting_id, ad_hash, plan_hash))`; `discovery_spend(id INTEGER PRIMARY KEY, at REAL NOT NULL, purpose TEXT NOT NULL, charged_tokens INTEGER NOT NULL)` plus an index on `discovery_spend(at)`.
- Produces `embeddings.py`: `text_key(text: str) -> str` (sha256 hex); `normalise(vectors) -> numpy.ndarray` (float32, rows L2-normalised); `class VectorCache(conn, model)` (DB table, `get_many(keys) -> dict[str, ndarray]`, `put_many(items)`, `prune(days: int) -> int`); `class VectorStore(root: Path, model: str)` (content-addressed `<root>/<model-slug>/<key[:2]>/<key>.f32`, same `get_many/put_many`; files 0600, dirs 0700 via `safe_write_bytes`); `embed_cached(embedder, cache, texts: dict[str, str]) -> dict[str, ndarray]` (embeds only keys missing from `cache`, via `embedder.embed_documents`, writes each batch of 32 to the cache as it completes); `reference_store() -> VectorStore` (`datasets.reference_root()/'vectors'`, model from config); `make_embedder(llm, config, budget) -> PaidGatewayEmbeddings` (model = `service._config(config)['embedding_model']`, `DiscoveryError('embedding_not_configured')` when `None`); `@contextmanager discovery_budget(conn, purpose: str, *, token_ceiling: int, seconds: float = 300.0)` yielding a `JobBudget` (own `BatchBudget`, run key `sha256(purpose + uuid)`), recording `discovery_spend(at=time.time(), purpose, charged_tokens=budget.charged_tokens)` on exit including on error; `discovery_tokens_since(conn, start: float) -> int`.
- Modifies `service._spent_today(conn, scope_day_start)`: tokens = existing sum + `discovery_tokens_since(conn, scope_day_start)`; jobs unchanged.
- Extends `fixtures.py`: `hash_vector(text, dims=64)` (bag of lower-cased words hashed with sha256 into `dims` buckets, never the zero vector), `hash_transport(calls=None, *, chat=None, fail_after=None)` (`/embeddings` → hash vectors with `usage.prompt_tokens = 10 * len(input)`; any other URL → `chat(body)` or `AssertionError`; raises after `fail_after` embedding calls), `approved_llm(transport) -> LLM` (`LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)`).

- [ ] **Step 1: Write the failing tests** in `tests/occupations/test_embeddings.py`:

```python
def test_default_query_instruction_is_unchanged():              # same assertions as tests/test_agentic_matching.py
    calls = []; ad = PaidGatewayEmbeddings(approved_llm(hash_transport(calls)), QWEN_EMBEDDING_MODEL, job())
    ad.embed_queries(['reconcile accounts'])
    assert calls[0]['input'][0] == f"Instruct: {QUERY_INSTRUCTIONS['requirement']}\nQuery:reconcile accounts"

def test_field_kind_uses_its_own_instruction_and_unknown_kind_is_refused():
    ad.embed_queries(['ledgers'], kind='field_from_evidence')
    assert calls[-1]['input'][0].startswith('Instruct: Given a statement of a person')
    with pytest.raises(AgenticError, match='invalid_request'): ad.embed_queries(['x'], kind='nope')

def test_vector_cache_is_per_model(conn):
    VectorCache(conn, 'm1').put_many({'k': normalise([[1, 0]])[0]})
    assert 'k' in VectorCache(conn, 'm1').get_many(['k']) and VectorCache(conn, 'm2').get_many(['k']) == {}

def test_embed_cached_pays_once_per_new_text(conn):
    cache = VectorCache(conn, QWEN_EMBEDDING_MODEL)
    embed_cached(ad, cache, {'a': 'ledger', 'b': 'coffee'}); n = len(calls)
    embed_cached(ad, cache, {'a': 'ledger', 'b': 'coffee'}); assert len(calls) == n

def test_reference_store_is_private_and_resumes_after_a_failure(tmp_path):
    store = VectorStore(tmp_path / 'ref', QWEN_EMBEDDING_MODEL)      # transport fails on the 2nd embedding call
    with pytest.raises(AgenticError): embed_cached(failing_adapter, store, {str(i): f'text {i}' for i in range(40)})
    done = len(store.get_many([str(i) for i in range(40)]))
    assert 0 < done < 40 and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (tmp_path / 'ref').rglob('*.f32'))
    embed_cached(working_adapter, store, {str(i): f'text {i}' for i in range(40)})   # embeds only the missing ones
    assert len(store.get_many([str(i) for i in range(40)])) == 40

def test_discovery_spend_counts_against_the_daily_token_ceiling(conn):
    with discovery_budget(conn, 'test', token_ceiling=100_000) as b: adapter(b).embed_documents(['one ledger'])
    spent = discovery_tokens_since(conn, 0)
    assert spent > 0 and service._spent_today(conn, 0)[1] == spent

def test_budget_ceiling_stops_embedding(conn):
    with discovery_budget(conn, 'test', token_ceiling=50) as b, pytest.raises(AgenticError, match='token_limit'):
        adapter(b).embed_documents(['x' * 4000])

def test_wrong_gateway_is_refused():                              # llm.base_url != model_choice.SERVER_URL
    with pytest.raises(AgenticError, match='gateway_not_allowed'): make_embedder(LLM(transport=t, keys=['s'], base_url='http://127.0.0.1:9/v1'), cfg, b)

def test_discovery_settings_never_enter_the_run_key():
    base = make_config(settings={'pipeline': {'agentic': {'enabled': True}}})
    on = make_config(settings={'pipeline': {'agentic': {'enabled': True, 'relevance': 'on', 'search_plan': True, 'dedupe': 'semantic', 'ordering': 'hypotheses'},
                                            'discovery': {'similar_at': 0.7}}})
    assert service._config(base) == service._config(on)
```
- [ ] **Step 2: Run** `tests/occupations/test_embeddings.py` → FAIL. **Step 3: Implement** the gateway change, migration, `embeddings.py`, `_spent_today` change and fixtures. **Step 4: Run** the new tests plus `tests/test_agentic_matching.py tests/test_dedupe.py tests/test_db_maintenance.py tests/test_interview_subjects.py` (existing tests that exercise the gateway and migrations) → PASS.
- [ ] **Step 5: Commit** `feat: embedding query kinds, vector caches, discovery budget and relevance tables`.

### Task 5: Field hypotheses from the approved profile

**Files:**
- Create: `jobwatch/occupations/hypotheses.py`, `tests/occupations/test_hypotheses.py`; extend `tests/occupations/fixtures.py` with `toy_reference()` (a `LoadedReference` of 8 records whose texts are written so the hash embedder separates them: ANZSCO `221111 Accountant`, `551111 Bookkeeper`, `551311 Payroll Officer`, `431111 Barista`, `261312 Software Developer`, `254411 Nurse`, `811111 Cleaner`, plus `onet:13-2011.00 Accountants and Auditors` with a `broad` correspondence to `anzsco2022:221111`), `write_approved(person, facts, version=1)` (writes `profile-versions/<version>/approved.json` with `{'schema', 'version', 'facts'}` through `safe_write_bytes`), `make_policy(**over) -> DecisionPolicy` (defaults: `strategy='employment_first'`, `focus=()`, `exclusions=()`, `policy_hash` valid), `fact(section, text, basis='evidence', fid=None) -> dict`.

**Interfaces:**
- Consumes: `loaders.load_reference_records`, `embeddings.{VectorStore, reference_store, embed_cached, discovery_budget, make_embedder, normalise}`, `intake.current_version(person)`, `policy.policy_for(person)`, `service.configured_llm`.
- Produces `hypotheses.py`:
  - `EVIDENCE_SECTIONS = ('experience', 'education', 'skill', 'transferable_skill', 'career_focus')`
  - `class FieldHypothesis(StrictFrozen)`: `scheme: str`, `code: str`, `title: str`, `similarity: float` (rounded to 4 places), `supporting_facts: tuple[str, ...]`, `rationale: str`, `is_qualification_proof: Literal[False] = False`, plus additive `related: tuple[str, ...] = ()` (ids of directly corresponding records in other schemes); property `id`
  - `field_hypotheses(person: str, *, limit: int = 15, llm=None, config=None, policy=None) -> tuple[FieldHypothesis, ...]`: `policy` defaults to `policy_for(person)` (`None` → `DiscoveryError('no_policy')`); `llm` defaults to `service.configured_llm(config)`; `config` defaults to `load_config()` under `users.use(person)`
  - `cached_hypotheses(person: str) -> tuple[FieldHypothesis, ...] | None` and `cached_doc_keys(person: str) -> dict[str, str]` (hypothesis id → `text_key(record.text)`, used by Task 7); both read the cache only, never call a model
  - `select(strategy: str, evidence_ranked: list, focus_ranked: list, limit: int) -> list` (pure; `employment_first` → first `limit` of evidence; `career_focus` → first `ceil(2*limit/3)` of focus, then evidence, no repeats; `balanced` → alternate evidence/focus; falls back to evidence when there are no focus items)
- Algorithm: queries = one per usable fact (`ProfileFact` of an `EVIDENCE_SECTIONS` section, `basis` in `evidence|inference`, non-empty text via `candidate.projection._text`) embedded with `embed_queries(kind='field_from_evidence')`, plus one combined query `skills: a; b; …` (all `skill` and `transferable_skill` fact texts, cut at 1,500 characters; its supporting facts are those facts' ids, first 8). Record vectors come from the shared `reference_store()` (built lazily with `embed_cached` under `discovery_budget(conn, 'reference-index', token_ceiling=settings['embedding_token_ceiling'])`; a build interrupted by budget or deadline raises `DiscoveryError('reference_index_incomplete')` and resumes next call). Evidence score of a record = mean of its top `min(3, n)` query similarities (cosine of normalised vectors); `supporting_facts` = the facts behind those top similarities (combined query expands to its facts), in score order, de-duplicated. Focus ranking = same record vectors against `policy.focus` strings (kind `field_from_evidence`) taking the max similarity. Exclusions applied before selection: any record whose title casefold contains a `title_term` rule value, or whose `family` equals a `family` rule value (`canonicalize_family`). After selection, greedy collapse: walk the ranked list; skip a record that directly corresponds (either direction, one hop) to an already selected record and add its id to that record's `related`. `rationale` is deterministic text: `Closest approved facts: <ids>. Similarity <x>. Strategy <strategy>. A search hypothesis only; it is not evidence that you qualify.` (no model text, no fact text).
- Cache: `users.user_dir(person)/discovery/hypotheses/<key>.json` (0600) holding `{'key','profile_version','policy_hash','algorithm','datasets','hypotheses','doc_keys'}` and `latest.json` naming the key; `key = sha256` of the canonical JSON of `(ALGORITHM_VERSION, policy_hash, profile_version, embedding model, limit, sorted dataset versions, bundled reference hash)`.

- [ ] **Step 1: Write the failing tests** in `tests/occupations/test_hypotheses.py` (`monkeypatch.setattr(loaders, 'load_reference_records', lambda **k: toy_reference())`, `reference_store` pointed at `tmp_path`, hash transport):

```python
LEDGER = fact('experience', 'Reconciled supplier ledgers and prepared journals', fid='f1')

def test_related_occupations_rank_above_unrelated(person):
    write_approved(person, [LEDGER, fact('skill', 'bookkeeping ledgers journals', fid='f2')])
    got = field_hypotheses(person, llm=approved_llm(hash_transport()), config=cfg, policy=make_policy())
    titles = [h.title for h in got]
    assert titles[0] in {'Accountant', 'Bookkeeper'} and titles.index('Barista') > titles.index('Accountant')

def test_every_hypothesis_is_marked_not_proof_and_cites_only_approved_usable_facts(person):
    write_approved(person, [LEDGER, fact('availability', 'weekdays', fid='f3'), fact('skill', 'unverified guess', basis='unknown', fid='f4')])
    for h in field_hypotheses(...):
        assert h.is_qualification_proof is False and set(h.supporting_facts) <= {'f1'}
    with pytest.raises(ValidationError): FieldHypothesis(..., is_qualification_proof=True)

def test_explicit_exclusions_remove_title_terms_and_families(person):
    p = make_policy(exclusions=(ExclusionRule(rule_id='r1', kind='title_term', value='bookkeeper', source_fact_id=None, actor='person'),))
    assert 'Bookkeeper' not in [h.title for h in field_hypotheses(person, ..., policy=p)]

def test_career_focus_prioritises_the_focus_and_employment_first_does_not(person):
    write_approved(person, [LEDGER])
    focus = make_policy(strategy='career_focus', focus=('software developer programming',))
    assert field_hypotheses(person, ..., policy=focus, limit=3)[0].title == 'Software Developer'
    assert field_hypotheses(person, ..., policy=make_policy(), limit=3)[0].title != 'Software Developer'

def test_corresponding_records_collapse_into_one_hypothesis_with_related(person):
    got = field_hypotheses(person, ...)
    acc = next(h for h in got if h.title in {'Accountant', 'Accountants and Auditors'})
    assert sum(h.title in {'Accountant', 'Accountants and Auditors'} for h in got) == 1 and len(acc.related) == 1

def test_result_is_cached_per_profile_version_and_dataset_version(person):
    first = field_hypotheses(person, ...); n = len(calls)
    assert field_hypotheses(person, ...) == first and len(calls) == n and cached_hypotheses(person) == first
    write_approved(person, [LEDGER, fact('skill', 'payroll', fid='f9')], version=2)
    field_hypotheses(person, ..., policy=make_policy(profile_version=2)); assert len(calls) > n

def test_no_usable_facts_is_an_error_not_an_empty_list(person):
    write_approved(person, [fact('skill', 'guess', basis='unknown')])
    with pytest.raises(DiscoveryError, match='no_profile_facts'): field_hypotheses(person, ...)

def test_missing_reference_is_an_error(person, monkeypatch):
    monkeypatch.setattr(loaders, 'load_reference_records', lambda **k: LoadedReference(records=(), ...))
    with pytest.raises(DiscoveryError, match='reference_unavailable'): field_hypotheses(person, ...)

def test_budget_exhaustion_leaves_a_resumable_partial_index(person):          # token_ceiling tiny
    with pytest.raises(DiscoveryError, match='reference_index_incomplete'): field_hypotheses(person, ...)
    assert 0 < len(list(reference_dir.rglob('*.f32')))

def test_person_b_never_reads_person_as_hypotheses(person, other): assert cached_hypotheses(other) is None
def test_cache_files_are_private(person): ...   # 0600 files, 0700 discovery/ directories
```
- [ ] **Step 2: Run** `tests/occupations/test_hypotheses.py` → FAIL. **Step 3: Implement** `hypotheses.py`. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: field hypotheses from approved facts by semantic retrieval against reference occupations`.

### Task 6: Search plan, collector overlay, recall-only title filter, run preparation

**Files:**
- Create: `jobwatch/occupations/plan.py`, `pipeline/agentic/discovery.py` (first part: contract re-exports, `settings`, `refresh`, `prepare_run`, `main`), `tests/occupations/test_plan.py`
- Modify: `jobwatch/pipeline.py` (`run` and `run_collector`)

**Interfaces:**
- Produces `plan.py`:
  - `class SearchPlan(StrictFrozen)`: `profile_version: int`, `policy_hash: str`, `queries: dict[str, tuple[str, ...]]` (keys are the `searches.yaml` sections `seek`, `jora`, `jobspy`), `locations: tuple[str, ...]`, `hypotheses: tuple[str, ...]` (ids), `plan_hash: str`
  - `search_plan(policy, hypotheses, *, extra_locations: tuple[str, ...] = (), max_queries: int = 12) -> SearchPlan`: queries = `policy.focus` strings (≤ 80 characters) then `query_for(h.title)` for each hypothesis, lower-cased, de-duplicated, capped at `max_queries`, the same list for each collector; locations = `home_text(policy.home)` (`", ".join(place, state)`) then `extra_locations`, de-duplicated; `plan_hash` = sha256 of the canonical JSON of every other field
  - `query_for(title: str) -> str` (drops parenthetical qualifiers, `nfd`, `n.e.c.`, collapses spaces)
  - `searches_overlay(plan: SearchPlan, base: dict, policy=None) -> dict`: copy of `base` where `seek.keywords`, `jora.keywords` are the plan queries, `jobspy.searches` is `[{'term': q}, …]`, `location`/`seek.where`/`jora.where`/`jobspy.location` are the first plan location when there is one (other locations stay in the plan for clients; limitation documented in CHAT.md); when `policy.remote_ok` is true and `policy.home` has a country, `seek.remote = {'enabled': True, 'keywords': first 4 queries, 'where': country}` and `jobspy.searches` gains `{'term': q, 'location': country, 'is_remote': True}` for the first 4; all other collector settings (`enabled`, `sites`, `hours_old`, pacing) are kept; no city name is hard-coded
  - `title_matches_plan(title: str, plan: SearchPlan) -> bool`: true when the title contains (whole words, case-folded) all tokens of a query of ≤ 2 tokens, or shares at least 2 non-stopword tokens with any longer query (stopwords: `a an and at for in of the to with senior junior graduate assistant officer`); documented as an uncalibrated recall heuristic
  - `save_plan(person, plan)` / `load_plan(person) -> SearchPlan | None` (`users.user_dir(person)/discovery/search-plan.json`, 0600)
- Produces `discovery.py` (this task): re-exports `FieldHypothesis, field_hypotheses, SearchPlan, search_plan` (the RelevanceJudgment names are added in Task 7); `settings(config) -> dict` reading the four mode flags from `pipeline.agentic` and the numbers from `pipeline.discovery`, with defaults `{'search_plan': False, 'relevance': 'shadow', 'dedupe': 'legacy', 'ordering': 'legacy', 'similar_at': 0.60, 'duplicate_cosine': 0.95, 'screen_per_run': 40, 'reconsider_per_run': 20, 'embedding_token_ceiling': 2_000_000, 'screen_token_ceiling': 300_000, 'relevance_model': None}`, invalid values raise `DiscoveryError('invalid_configuration')` (`search_plan` a bool, `relevance` ∈ off|shadow|on, `dedupe` ∈ legacy|semantic, `ordering` ∈ legacy|hypotheses, `similar_at` in (0,1), `duplicate_cosine` in (0.5,1], ints in range); `refresh(person, config, *, llm=None, conn=None, seconds=240.0) -> dict` (requires `intake.discovery_scope(person)` and `policy_for(person)`; runs `field_hypotheses`, `search_plan` with `extra_locations` from the scope, saves the plan; returns `{'profile_version', 'hypotheses': n, 'plan_hash', 'datasets': versions}`; raises `DiscoveryError`); `prepare_run(conn, config) -> Config`; `recall_filter(base, config)`; `main(argv=None)` for `python -m pipeline.agentic.discovery refresh|status --user NAME` (`refresh` is the owner's explicit paid step; `status` prints flags, dataset states, plan hash and counts, no model call).
- `prepare_run(conn, config)`: returns `config` itself when `settings['search_plan']` is false, the mode is not `agentic`, or `intake.discovery_scope(users.current())` is `None`. Otherwise loads the stored plan; when it is missing or its `profile_version`/`policy_hash` differ from `policy_for`, calls `refresh` inside `try`, and on any exception logs only the exception class and uses the stored plan or none; with a plan returns `dataclasses.replace(config, searches=searches_overlay(plan, config.searches, policy), extra={**config.extra, 'search_plan': plan})`. It never raises.
- Modifies `jobwatch/pipeline.py`: `run` calls `config = discovery.prepare_run(conn, config)` right after the connection is opened (inside the existing `try`); `run_collector` builds `CollectorContext(title_relevant=discovery.recall_filter(rules.title_relevant, config))`. `recall_filter` returns `base` unchanged when `config.extra` has no `search_plan`; otherwise `lambda t: base(t) or title_matches_plan(t, plan)` (it only widens: seniority and off-target keywords no longer drop a title the plan matches, because the semantic step and the gate decide fit).

- [ ] **Step 1: Write the failing tests** in `tests/occupations/test_plan.py`:

```python
def test_queries_come_from_focus_and_hypotheses_deduplicated_and_capped():
    plan = search_plan(make_policy(focus=('data analyst',)), hyps(['Accountant (General)', 'Bookkeeper', 'Accountant (General)'] + [f'Role {i}' for i in range(20)]))
    assert plan.queries['seek'][:3] == ('data analyst', 'accountant', 'bookkeeper') and len(plan.queries['seek']) == 12
    assert plan.queries['seek'] == plan.queries['jora'] == plan.queries['jobspy']

def test_plan_hash_is_stable_and_changes_with_policy_or_hypotheses(): ...

def test_overlay_replaces_terms_keeps_collector_settings_and_uses_the_persons_home():
    base = {'location': 'Elsewhere, XX', 'seek': {'enabled': True, 'max_pages': 2, 'keywords': ['old']}, 'jobspy': {'sites': ['indeed'], 'searches': [{'term': 'old'}]}}
    out = searches_overlay(search_plan(make_policy(home={'place': 'Sydney', 'state': 'NSW', 'country': 'Australia'}), hyps(['Accountant'])), base)
    assert out['seek']['keywords'] == ['accountant'] and out['seek']['max_pages'] == 2 and out['seek']['where'] == 'Sydney, NSW'
    assert out['jobspy']['sites'] == ['indeed'] and out['jobspy']['searches'] == [{'term': 'accountant'}]
    assert 'Melbourne' not in json.dumps(out) and 'old' not in json.dumps(out['seek']['keywords'])

def test_remote_ok_adds_remote_searches(): ...      # seek.remote.enabled and jobspy is_remote entries

def test_recall_filter_only_widens():
    base = lambda t: t == 'Payroll Officer'
    f = recall_filter(base, cfg_with_plan(['bookkeeper']))
    assert f('Payroll Officer') and f('Senior Bookkeeper - urgent') and not f('Barista')

def test_prepare_run_is_a_no_op_when_the_flag_is_off(conn, cfg):
    assert prepare_run(conn, cfg) is cfg                 # and no embedding call was made

def test_prepare_run_needs_a_confirmed_scope_and_never_raises(conn, cfg_on, monkeypatch):
    assert prepare_run(conn, cfg_on) is cfg_on            # no confirmed profile
    confirm_discovery(cfg_on); monkeypatch.setattr(discovery, 'refresh', boom)
    assert prepare_run(conn, cfg_on) is cfg_on            # refresh failed: legacy searches stay

def test_prepare_run_resumes_a_partial_reference_index(...): ...   # first call raises reference_index_incomplete (caught), second completes

def test_collectors_read_the_overlay(...):                 # make_ctx(FakeHttp(seek fixture), searches=overlay) -> seek.collect: params['keywords'] are the plan queries

def test_invalid_discovery_settings_are_refused(): ...     # relevance='sometimes', similar_at=1.5 -> DiscoveryError('invalid_configuration')
def test_defaults_change_no_collection_or_archive_behaviour():       # contract decision 8
    d = settings(make_config()); assert (d['search_plan'], d['relevance'], d['dedupe'], d['ordering']) == (False, 'shadow', 'legacy', 'legacy') and d == DEFAULTS
def test_flags_are_read_from_pipeline_agentic_and_tuning_from_pipeline_discovery():
    d = settings(make_config(settings={'pipeline': {'agentic': {'relevance': 'on', 'dedupe': 'semantic'}, 'discovery': {'similar_at': 0.7}}}))
    assert (d['relevance'], d['dedupe'], d['similar_at']) == ('on', 'semantic', 0.7)
```
- [ ] **Step 2: Run** `tests/occupations/test_plan.py` → FAIL. **Step 3: Implement.** **Step 4: Run** it plus `tests/test_collect_pipeline.py tests/test_collectors.py tests/test_filters.py` → PASS.
- [ ] **Step 5: Commit** `feat: search plan from field hypotheses; collectors read it; title keywords only widen recall`.

### Task 7: Semantic relevance, exclusion pre-filter and screening before paid evaluation

**Files:**
- Modify: `pipeline/agentic/discovery.py`, `pipeline/agentic/service.py` (`after_collect`), `jobwatch/web/queries.py` (`HIDE_REASONS`, `PL_HIDE_REASON`)
- Test: `tests/occupations/test_relevance.py`, `tests/occupations/test_screening.py`; extend `tests/occupations/fixtures.py` with `posting(**over) -> dict` and a `relevance_chat(answers)` chat handler that returns `{'tool': 'complete_relevance', 'arguments': …}` (the `{'choices': [{'message': {'content': json}}], 'usage': {…}}` shape used by `SyntheticGateway`)

**Interfaces:**
- Consumes: Task 4 (`embed_cached`, `VectorCache`, `VectorStore`, `discovery_budget`), Task 5 (`cached_hypotheses`, `cached_doc_keys`), Task 6 (`settings`, plan hash via `load_plan`), `service._capture`, `service._config`, `service.configured_llm`, `evaluator._find_in_ad`, `runtime.{RoleSpec, Tool, run_role}`, `pipeline.store.move` / `Stage`, Plan 2 `policy_for(person)`, `exclusion_hit(policy, *, family, company, title, location_text, remote, hours)` and `service.decision_policy_mode(config)`.
- Produces in `discovery.py`:
  - `class RelevanceJudgment(StrictFrozen)`: `posting_id: int`, `relevant: Literal['yes','no','uncertain']`, `quotes: tuple[str, ...]` (each ≤ 300 characters, verbatim from the title or the full ad), `similarity: float`, `matched_hypotheses: tuple[str, ...]` (up to 3 ids, best first), `reason: str`, plus additive `method: Literal['embedding','extraction','none'] = 'embedding'`, `ad_hash: str = ''` (`content_hash(ad_text.encode())`, the same digest as `RunKey.ad_hash` for the same advert text, so Plan 6b can tell whether a stored judgment belongs to a frozen advert), `plan_hash: str = ''`
  - `class RelevanceExtraction(StrictFrozen)` (the model's terminal arguments): `relevant: Literal['yes','no','uncertain']`, `field_title: str` (≤ 120), `quotes: tuple[str, ...]` (≤ 5, each ≤ 300), `reason: str` (≤ 300)
  - `ad_passages(title: str, ad_text: str, *, size: int = 1500, overlap: int = 150, limit: int = 4) -> list[str]` (windows of the raw ad; the text embedded for window 0 is `f'{title}\n' + window`)
  - `@dataclass class ScreenContext`: `embedder`, `ad_cache: VectorCache`, `reference: dict[str, numpy.ndarray]` (hypothesis id → vector, from `cached_doc_keys` and `reference_store()`), `llm`, `budget`, `model: str`, `similar_at: float`, `plan_hash: str`
  - `judge_relevance(posting, ad_text: str, policy, hypotheses, *, context: ScreenContext | None = None) -> RelevanceJudgment`: no hypotheses or no `context` → `uncertain` (`method='none'`). Else similarity = max cosine between any passage vector and any hypothesis reference vector; `matched_hypotheses` = top 3. If `similarity >= context.similar_at` → `yes`, `method='embedding'`, quote = first 300 characters of the best-matching raw window. Otherwise one `run_role(RoleSpec(name='jd_requirements', model=context.model, tools=(Tool('complete_relevance', RelevanceExtraction, lambda a, _: a),), terminal_tools=('complete_relevance',), system_prompt=…), {'title', 'ad_text' (the first 12,000 characters), 'candidate_fields': [hypothesis titles], 'strategy': policy.strategy}, context.budget, context.llm, max_turns=3, max_output_tokens=1_500)`; the prompt says the ad is untrusted data, asks whether the daily duties belong to any of the listed fields or a plausibly related one, requires verbatim quotes of the duties, and states that `no` needs at least one quote. The context carries **no candidate fact text**. Each model quote is resolved with `evaluator._find_in_ad(quote, f'{title}\n{ad_text}')`; unresolved quotes are dropped; a `yes`/`no` with no resolved quote becomes `uncertain` (`reason='quote_not_verified'`). Model/route errors (`RuntimeErrorSafe`) → `uncertain` (`reason='model_unavailable'`, no raise). Similarity alone never yields `no`.
  - `exclusion_rule_hit(posting, policy) -> ExclusionRule | None`: calls Plan 2 `exclusion_hit(policy, family=None, company=posting['company'], title=posting['title'], location_text=posting['location'], remote=bool(posting.get('remote')), hours='casual' if posting.get('work_type') == 'casual' else '')` (`family=None`: family rules stay in the gate; `postings.work_type` is the collectors' `FT | PT | casual`, and only `casual` maps onto the gate's `hours` vocabulary, so full-time and part-time rules are applied by the gate after evaluation); no local matcher.
  - `enforce_exclusions(conn, config, *, person=None) -> list[int]` (contract decision 7; Plan 5 calls it right after a rule is confirmed, `after_collect` calls it every run before any paid call): the exclusion pre-filter alone. It returns `[]` and does nothing unless `service.decision_policy_mode(config) == 'profile'` and `policy_for(person)` exists, whatever the relevance mode; otherwise every posting in stage `ingested` (`pipeline_state`) whose capture kind is `full` and that `exclusion_rule_hit` matches moves to `ARCHIVED` with `reason='excluded_by_rule'` (output names the rule id) via `pipeline_store.move`, and the moved ids are returned. Cheap, no model, no embedding.
  - `screen_step(conn, config, *, person=None, llm=None) -> dict` (never raises; `{}` when `relevance == 'off'`, and `{}` with only a logged code when `policy_for`, `cached_hypotheses` or `load_plan` is missing, which is the state of every person until `refresh` has run): builds the `ScreenContext` under `discovery_budget(conn, 'screen', token_ceiling=settings['screen_token_ceiling'])`; for each posting in stage `ingested`, oldest `updated_at` first, up to `screen_per_run`, whose capture kind is `full`, calls `judge_relevance` unless a row exists for `(posting_id, ad_hash, plan_hash)` and stores the judgment in `posting_relevance` with `mode`; in `on` mode `no` → `pipeline_store.move(conn, pid, 'relevance', Stage.INGESTED, Stage.ARCHIVED, output={…judgment…}, reason='not_relevant')`; `shadow` (the default) records only. Returns `{'judged': n, 'archived': n, 'uncertain': n, 'deferred': code?}`; an embedding/budget error stops the loop with `deferred=<code>` and archives nothing for unjudged postings.
  - `reconsider(conn, config, *, person=None) -> int`: up to `reconsider_per_run` archived postings, not closed, with reason `not_relevant` (only when `relevance == 'on'`) or `excluded_by_rule` (only in `profile` mode) whose newest judgment's `plan_hash` differs from the current plan, or whose rule is no longer in the policy, are re-judged under the current policy; if no longer `no`/rule hit they move back `ARCHIVED → INGESTED` with reason `NULL`.
  - `restore_archived(conn, reasons=('not_relevant', 'excluded_by_rule')) -> int` (owner undo: moves every such archived posting back to `ingested`; exposed as `python -m pipeline.agentic.discovery restore --user NAME`).
  - `latest_judgment(conn, posting_id) -> RelevanceJudgment | None` (contract decision 7; the newest `posting_relevance` row by `created_at`, parsed from `judgment_json`; None when the table or row is missing; Plans 4 and 6b read it) and `latest_judgment_row(conn, posting_id) -> dict | None` (`{'judgment': RelevanceJudgment, 'mode': str, 'created_at': str}`, for the API).
- `after_collect` change: after `ingest.run` and the duplicate step, `excluded = discovery.enforce_exclusions(conn, config)`, then `rel = discovery.screen_step(conn, config)` and `discovery.reconsider(...)`; then recompute `jobs, tokens = _spent_today(...)`, `room`, `left`; if `room <= 0 or left <= 0` return `{'deferred': 'daily_budget', 'relevance': rel}` (rel omitted when empty). The result of `agentic_batch_run` gains a `'relevance'` key only when `rel` is non-empty and `'excluded_by_rule'` (the count) only when `excluded` is non-empty, so results with the defaults and no `refresh` are byte-identical to today's.
- Web: append `("not_relevant", "Not relevant to your fields")` and `("excluded_by_rule", "Excluded by your rule")` to `HIDE_REASONS` (after `other_field`, so they join `NOT_TARGET_KEYS`) and map `PL_HIDE_REASON['not_relevant'] = 'not_relevant'`, `['excluded_by_rule'] = 'excluded_by_rule'`.

- [ ] **Step 1: Write the failing tests.** `test_relevance.py` (hash transport; `ctx` fixture builds a `ScreenContext` over `toy_reference` hypotheses with `similar_at=0.6`):

```python
def test_misleading_title_is_judged_by_the_full_ad():
    related = posting(title='Operations Support Officer'); text = 'Reconcile supplier ledgers and prepare journals. ' * 8
    assert judge_relevance(related, text, pol, hyps, context=ctx).relevant == 'yes'              # dull title, related duties
    unrelated = posting(title='Accountant'); text2 = 'Clean offices and restock bathrooms overnight. ' * 8
    out = judge_relevance(unrelated, text2, pol, hyps, context=ctx_with_chat(relevance_chat({'relevant': 'no', 'quotes': ['Clean offices and restock bathrooms overnight.']})))
    assert out.relevant == 'no' and out.method == 'extraction' and all(q in text2 for q in out.quotes)

def test_no_without_a_verified_quote_becomes_uncertain():
    out = judge_relevance(..., context=ctx_with_chat(relevance_chat({'relevant': 'no', 'quotes': ['This sentence is not in the ad']})))
    assert out.relevant == 'uncertain' and out.reason == 'quote_not_verified'

def test_similarity_alone_never_yields_no():              # low similarity, no llm available
    assert judge_relevance(..., context=ctx_without_llm).relevant == 'uncertain'

def test_embedding_yes_quotes_are_verbatim_and_bounded():
    out = judge_relevance(...); assert out.quotes and all(q in text and len(q) <= 300 for q in out.quotes)

def test_extraction_request_carries_no_candidate_facts():
    judge_relevance(..., context=ctx_recording_chat(requests)); blob = json.dumps(requests)
    assert 'Reconciled supplier ledgers' not in blob and 'Accountant' in blob          # field titles yes, approved fact text no

def test_model_route_error_is_uncertain_not_an_exception(): ...
def test_ad_passages_are_verbatim_windows_with_overlap(): ...
```
`test_screening.py` (uses `world` from `tests/test_agentic_service.py`: `from test_agentic_service import world, SyntheticGateway`; flags set through `make_config(settings={'pipeline': {'agentic': {...}, 'discovery': {...}}})`; hypotheses written with Task 5's cache helper):

```python
def test_off_mode_changes_nothing(world): ...        # screen_step == {}, no posting_relevance rows, no model or embedding call
def test_shadow_records_but_never_archives(world): ...    # rows exist with mode 'shadow'; every posting still 'ingested'
def test_on_archives_no_as_not_relevant_and_lets_uncertain_proceed(world): ...   # reason == 'not_relevant'; uncertain stays 'ingested' and is evaluated by after_collect
def test_excluded_employer_is_archived_even_when_very_similar(world): ...        # decision_policy 'profile', relevance 'shadow'; rule employer 'Synthetic Alpha' (dict fact) -> enforce_exclusions returns its id, reason 'excluded_by_rule', zero embedding calls for it
def test_casual_work_type_rule_hits_at_the_prefilter_but_full_time_waits_for_the_gate(world): ...   # work_type 'casual' posting archived by a casual rule; an 'FT' posting is not archived by a full_time rule here
def test_exclusion_prefilter_does_nothing_in_legacy_mode(world): ...              # same rule, decision_policy 'legacy' (default) -> enforce_exclusions == [], posting stays 'ingested'
def test_enforce_exclusions_is_the_prefilter_alone_and_needs_no_hypotheses(world): ...   # no refresh, no embedding route: still archives the rule hit; returns [] when no rule matches
def test_default_shadow_costs_nothing_before_refresh(world): ...                 # default settings, no cached hypotheses/plan: screen_step == {}, no model or embedding call, no posting_relevance row, after_collect result has no 'relevance' key
def test_latest_judgment_returns_the_typed_newest_judgment(world): ...           # two rows for one posting (older ad_hash, newer plan_hash): returns a RelevanceJudgment with method/ad_hash/plan_hash of the newest; unknown posting or missing table -> None
def test_latest_judgment_row_carries_mode_and_created_at(world): ...
def test_partial_ad_text_is_not_judged(world): ...    # capture kind 'partial' -> skipped
def test_route_outage_archives_nothing_and_pending_jobs_still_evaluate(world):
    transport = hash_transport(fail_after=0)
    out = after_collect(...)       # screening defers
    assert out['relevance']['deferred'] and no posting archived and run_agentic_job called for the ingested jobs
def test_screening_is_bounded_and_counted(world): ...  # screen_per_run=2 judges 2; discovery_spend row; a spent day returns {'deferred': 'daily_budget', ...} before any call
def test_relevance_archive_is_a_system_record_not_a_person_choice(world): ...    # applications and application_events stay empty
def test_judgment_is_stored_once_per_ad_and_plan_and_rejudged_on_change(world): ...
def test_reconsider_restores_a_posting_when_the_plan_now_covers_it_or_the_rule_is_gone(world): ...   # not_relevant (mode on) and excluded_by_rule (profile mode)
def test_restore_archived_is_the_undo(world): ...
def test_relevance_flag_leaves_run_keys_unchanged(world): ...   # snapshot_inventory run_key identical with relevance 'off' and 'on'
def test_board_labels_not_relevant(): assert q.ai_from_pipeline({'id': 1, 'pl_stage': 'archived', 'pl_data': '{}', 'pl_reason': 'not_relevant', 'pl_at': 'x'})['hide_reason'] == 'not_relevant'
def test_status_reports_similarity_quantiles(world): ...    # python -m pipeline.agentic.discovery status prints counts per verdict and min/median/max similarity
```
- [ ] **Step 2: Run** both files → FAIL. **Step 3: Implement.** **Step 4: Run** them, `tests/test_agentic_service.py`, `tests/web/test_ai.py` → PASS.
- [ ] **Step 5: Commit** `feat: semantic relevance (shadow by default) and exclusion pre-filter before paid evaluation`.

### Task 8: Semantic duplicates and hypothesis-based ordering

**Files:**
- Modify: `pipeline/agentic/discovery.py`, `pipeline/agentic/service.py` (`after_collect` dispatch)
- Test: `tests/occupations/test_dedupe.py`

**Interfaces:**
- Consumes: Task 4 (`embed_cached`, `VectorCache`), Task 7 (`ScreenContext`, `ad_passages`), `jobwatch.dedupe._norm, _COMPANY_NOISE, _TITLE_NOISE, city_of`, `sightings` table (sources per posting).
- Produces in `discovery.py`:
  - `ensure_ad_vectors(conn, context, posting_ids, *, limit) -> dict[int, numpy.ndarray]`: mean of the passage vectors (up to 4 windows), re-normalised; embeds at most `limit` ads per call, the oldest-checked first; shared by screening, dedupe and ordering so an ad is embedded once
  - `same_vacancy_structured(a: dict, b: dict, cosine: float, *, min_cosine: float) -> bool`: `cosine >= min_cosine` and company names (normalised with `_COMPANY_NOISE`) both non-empty and equal or one's token set contained in the other's, title Jaccard (normalised with `_TITLE_NOISE`) ≥ 0.6, `city_of` equal or both `remote`, and the two postings share no `sightings.source`
  - `semantic_duplicates(conn, config, *, context, limit: int = 100) -> int`: compares each newly vectored, non-READY, not-yet-checked posting (stages `ingested`/`dlq`) with every live non-archived posting that has a vector; the newer (higher id) copy of a duplicate pair moves to `ARCHIVED` with `reason=f'duplicate_of:{older_id}'` and `output={'duplicate_of', 'cosine', 'basis': 'semantic'}`; records `near_dup_checked(posting_id, ad_hash)` (same DDL as `_near_duplicates`, `CREATE TABLE IF NOT EXISTS`); READY and already archived postings are never touched
  - `order_pending(conn, config, pending: list[int], *, context) -> list[int]`: like `_target_first` (15 closest then the 5 oldest) with closeness = maximum cosine of the ad's vector to the hypotheses' reference vectors; ads without a vector are ordered after the closest by age
- `after_collect` dispatch: when `settings['dedupe'] == 'semantic'` call `semantic_duplicates` instead of `_near_duplicates`; when `settings['ordering'] == 'hypotheses'` call `order_pending` instead of `_target_first`; the context is built once by a shared `discovery.context_for(conn, config)` (embedding-only; returns `None` and logs a code when hypotheses or the route are unavailable, in which case the legacy function runs for this call). The `semantic`/`hypotheses` paths never call `openrouter_extras.embed/vectors/rank_by_target/same_vacancy`.

- [ ] **Step 1: Write the failing tests** in `tests/occupations/test_dedupe.py` (postings inserted with `db.connect(tmp_path/'d.db')`, one `sightings` row per source, identical or near-identical ad texts through the hash transport):

```python
def test_same_vacancy_on_two_sources_archives_the_newer_copy():
    a = add(1, source='seek', company='Acme Pty Ltd', ...); b = add(2, source='jobspy_src', company='ACME', ...)   # same text
    assert semantic_duplicates(conn, cfg, context=ctx) == 1 and stage_of(2) == 'archived' and reason_of(2) == 'duplicate_of:1' and stage_of(1) == 'ingested'

def test_same_template_for_another_city_is_not_a_duplicate(): ...        # city differs
def test_same_source_distinct_requisitions_are_not_merged(): ...          # sightings share 'ats_workday'
def test_recruiter_reposting_another_company_ad_is_not_merged(): ...      # company names disjoint
def test_blank_company_is_never_merged(): ...
def test_title_mismatch_is_not_a_duplicate(): ...                         # Jaccard < 0.6
def test_ready_job_is_never_archived_as_a_duplicate(): ...
def test_checked_ads_are_not_compared_again(): ...                        # second call: no embedding calls, no work
def test_embedding_budget_bounds_the_backlog(): ...                       # limit=3 embeds 3 ads; the rest next call
def test_semantic_modes_never_use_the_legacy_embedding_path(world, monkeypatch):
    for name in ('embed', 'vectors', 'rank_by_target', 'same_vacancy'): monkeypatch.setattr(service, name, boom)   # names imported into service
    after_collect(...)              # dedupe='semantic', ordering='hypotheses' -> no AssertionError
def test_legacy_modes_are_unchanged_by_default(world, monkeypatch): ...   # spies show _near_duplicates and _target_first were called
def test_ordering_puts_ads_closest_to_the_hypotheses_first_and_keeps_five_oldest(): ...
```
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `tests/occupations/test_dedupe.py tests/test_dedupe.py tests/test_openrouter_extras.py tests/test_agentic_service.py` → PASS.
- [ ] **Step 5: Commit** `feat: cross-source semantic duplicates and hypothesis-based ordering on the approved embedding route`.

### Task 9: Read-only discovery API

**Files:**
- Create: `pipeline/agentic/discovery_api.py`, `tests/test_discovery_api.py`
- Modify: `pipeline/agentic/api.py` (mount the router next to `profile_api.mount`; add `discovery` to `capabilities`)

**Interfaces:**
- Produces `discovery_api.mount(app, require, get_config)` following `profile_api.mount` (person only from the bearer token; handlers run under `users.use(person)`; scope `read`; no write methods):
  - `GET /api/agent/discovery/fields` → `{'status': 'ready' | 'not_computed', 'profile_version': int | None, 'hypotheses': [FieldHypothesis json], 'note': 'Related occupations are search hypotheses, not qualification proof.'}` (from `cached_hypotheses`; never calls a model)
  - `GET /api/agent/discovery/plan` → `{'status', 'plan': SearchPlan json | None, 'flags': {'search_plan', 'relevance', 'dedupe', 'ordering'}}`
  - `GET /api/agent/discovery/postings/{posting_id}/relevance` → `latest_judgment_row` (the `RelevanceJudgment` JSON plus `mode` and `created_at`); 404 `{'error': 'not_found'}` when none
- `capabilities` gains `discovery=dict(read_only=True, flags=…)`.

- [ ] **Step 1: Write the failing tests** (harness as `tests/test_profile_api.py`: `create_api` with `Principal` tokens ≥ 32 characters, two people):

```python
def test_fields_are_not_computed_before_a_refresh(env): assert env.get(F, headers=h(RUN)).json()['status'] == 'not_computed'
def test_fields_are_the_cached_hypotheses_with_the_not_proof_note(env): ...      # status 'ready'; every item has is_qualification_proof False; note present
def test_plan_endpoint_reports_the_plan_and_flags(env): ...
def test_relevance_endpoint_returns_the_stored_judgment_or_404(env): ...
def test_other_person_sees_only_their_own_state(env): ...                        # B's token: fields not_computed; A's posting id -> 404
def test_endpoints_are_read_only(env): assert env.post(F, headers=h(RUN)).status_code == 405
def test_read_scope_is_required(env): ...                                         # a token without 'read' -> 403
def test_capabilities_advertise_discovery(env): ...
```
- [ ] **Step 2: Run** `tests/test_discovery_api.py` → FAIL. **Step 3: Implement.** **Step 4: Run** it plus `tests/test_profile_api.py tests/test_deepagents_runtime.py tests/test_auth.py` → PASS.
- [ ] **Step 5: Commit** `feat: read-only native API for discovered fields, search plan and relevance judgments`.

### Task 10: Documentation, full suite, example

**Files:**
- Modify: `README.md` (discovery workflow, flags, how to refresh and undo), `pipeline/agentic/CHAT.md` (discovery table and flags; limitation: only the first plan location is searched on Seek/Jora/JobSpy), `pipeline/agentic/MATCHING.md` (a short "Field and job discovery" paragraph: what is measured nowhere yet; thresholds uncalibrated; no accuracy claim; do not change the recorded pass count unless you ran the suite), `config/jobwatch.yaml` (commented `pipeline.agentic` keys `search_plan`, `relevance`, `dedupe`, `ordering` and a `pipeline.discovery` tuning block, all at the default values), `INTENT.md` (a short subsection recording the owner's semantic-filtering words verbatim and that keywords only widen recall), the ADR (status line; link to the example), `docs/superpowers/plans/EXECUTING.md` is not changed
- Create: `docs/examples/field-discovery.md`

- [ ] **Step 1: Run the full suite**: `<venv>/bin/python -m pytest -q -p no:cacheprovider` (add `--ignore` for the ten `tests/apply/` files that need the `browser` extra if it is not installed; about 20 minutes; one suite at a time). Record the exact pass/fail/skip counts; each failure must be fixed or shown to fail identically on `origin/main` (run that test file there and keep the output).
- [ ] **Step 2: Write `docs/examples/field-discovery.md`** in the style of `docs/examples/profile-intake.md`: a synthetic person, the real responses captured from the Task 9 test client for `fields`, `plan` and `relevance`, the `python -m jobwatch.occupations.datasets status` and `python -m pipeline.agentic.discovery refresh|status|restore` commands with their output on the synthetic fixtures, a table of the four flags with defaults and the recommended order (`relevance: shadow` for at least a week and compare against what the person actually opens, then `on`; `search_plan`, `dedupe`, `ordering` independently), and a statement of what is not shown (no accuracy figure, no live data, no hosted model).
- [ ] **Step 3: Update the docs** listed above; every claim in them must match the code (flag names, defaults, reasons `not_relevant` / `excluded_by_rule`, the three new tables, the folders `discovery/` and `<data>/reference/`).
- [ ] **Step 4: Commit** `docs: field and job discovery workflow, flags and limitations`; push; open the PR with: summary, the full-suite line, the checks run, the Rulings from the ledger, Owner decisions (below), limitations (thresholds uncalibrated; embeddings only, no lexical hybrid; first plan location only; reference-dataset downloads that were blocked, if any; nothing deployed and no accuracy claim), what is unverified (real-model behaviour of the relevance step and of Qwen cosine ranges; real dataset files if downloads were blocked), and undo instructions (Rollback).

---

## Owner decisions

None blocks the executor; each has the default used meanwhile.

1. **Turn the flags on.** `search_plan`, `dedupe` and `ordering` default to today's behaviour; `relevance` defaults to `shadow` (records verdicts, archives nothing) but does nothing until the owner runs `python -m pipeline.agentic.discovery refresh --user NAME`, which is the first paid step. Recommended: review `python -m pipeline.agentic.discovery status` after a week of `shadow`, then set `pipeline.agentic.relevance: on`. Exclusion rules additionally need `pipeline.agentic.decision_policy: profile` (Plan 2). Default now: `shadow`, no `refresh`.
2. **Reference-dataset licences and attribution** (O\*NET CC BY 4.0, ABS, ESCO, any Jobs and Skills Australia source). Default: a dataset whose licence the investigation could not confirm is `enabled=False`; the bundled reference alone is used.
3. **The first reference-index build is a paid embedding run** (about 0.5M tokens of Qwen for the bundled occupations, more per added dataset; shared by every person; counts toward the day's token ceiling). Default: the executor never makes a paid call; the build happens on the first timer run after a flag is turned on, or when the owner runs `python -m pipeline.agentic.discovery refresh --user NAME`.
4. **Thresholds** `similar_at = 0.60` and `duplicate_cosine = 0.95`. Default: as written, documented as uncalibrated. Calibrate from the similarity distribution in `status` and owner labels (Plan 6b) before relying on `relevance: on`.
5. **A cheaper relevance model** (`pipeline.discovery.relevance_model`). Default: the person's evaluator model.
6. **Primary Australian scheme.** Default: ANZSCO 2022 (bundled) stays primary; OSCA, where the investigation found it usable, is loaded and attached through correspondences.
7. **Blocked downloads.** If the executor's network blocked a dataset, the owner runs the fetch command on a machine with access and commits the printed hashes; default: that dataset stays `unverified`/disabled.

## Rollback

Revert the merge commit. Then, optionally:

- Config: remove the `pipeline.discovery` block and the `search_plan`, `relevance`, `dedupe` and `ordering` keys under `pipeline.agentic` (all back to defaults; set `relevance: off` to stop shadow judging). Postings archived as `not_relevant` or `excluded_by_rule` stay archived until restored: run `python -m pipeline.agentic.discovery restore --user NAME` (moves them back to `ingested`) before turning `relevance` off if you want them re-read; postings archived as `duplicate_of:<id>` by `semantic` dedupe keep that reason (the same as the legacy path).
- Database (each person's job DB): the new migration's tables `text_embeddings`, `posting_relevance`, `discovery_spend` are unused after the revert and harmless; older code accepts the higher `PRAGMA user_version`. To remove them: back up the DB, `DROP TABLE posting_relevance; DROP TABLE text_embeddings; DROP TABLE discovery_spend;` and `PRAGMA user_version` one lower.
- Files: delete `<person>/discovery/` (hypotheses, search plan) and the shared public folder `<data>/reference/` (downloaded datasets and vectors); both are rebuilt on demand. Nothing under `profile/`, `profile-versions/`, `intake/` or `ledger/` is written.
- No service or timer is changed by this plan, so none needs stopping or restarting.

## Self-review

- **Spec coverage:** semantic retrieval of evidence against occupational tasks and skills (Tasks 4-5); reuse of the approved retrieval route (Task 4, constraint list); versioned reference datasets and mappings and the investigation of Australian classifications and O\*NET/ESCO correspondences (Tasks 2-3, ADR); related occupations as hypotheses (Task 5 constant field, API note); the owner's semantic filtering (Task 7, with title keywords demoted in Task 6); strategy and exclusion rules (Tasks 5, 7); automatic deduplication on description similarity (Task 8); within confirmed limits (Tasks 4, 7: `discovery_spend` counted in `_spent_today`); isolation, budgets, private data (constraints, Tasks 4-5, 9); no accuracy claim (ADR, Task 10); rollback (above).
- **Step scan:** every code step names its signature and file; test steps name their assertions; bodies are left to the implementer except the two algorithms the signatures do not determine (field scoring and the duplicate rule), which are specified in Tasks 5 and 8.
- **Type consistency:** `FieldHypothesis`, `SearchPlan`, `RelevanceJudgment` carry the contract's fields plus additive defaults; `ScreenContext.reference` keys are `FieldHypothesis.id`; `cached_doc_keys` (Task 5) feeds `ScreenContext` (Task 7); `settings` keys (Task 6) are the ones Tasks 7-9 read.
- **Proportion:** the plan states interfaces, tests and decisions, not function bodies.

## Contract reconciliation

Reconciled decisions of the [cross-plan contract](2026-10-21-cross-plan-contract.md) that apply to this plan; all are applied above.

- **3 Flag for the profile policy:** the exclusion pre-filter (`enforce_exclusions`) acts only with `pipeline.agentic.decision_policy: profile` (Task 7).
- **6 Exclusion facts to rules:** the pre-filter consumes Plan 2's `ExclusionRule`s through `exclusion_hit`; `MINIMUM_EXCLUDED_CODES` is parametrised by Plan 2, so `family` rules still cannot be matched against O\*NET/ESCO/OSCA records (only `title_term` rules can) and the gate keeps enforcing family rules on the extracted `role_family`.
- **7 Relevance is stored:** table `posting_relevance` (Task 4 migration), `RelevanceJudgment` with `method`, `ad_hash`, `plan_hash`, `discovery.latest_judgment(conn, posting_id) -> RelevanceJudgment | None`, `discovery.enforce_exclusions(conn, config, *, person=None)` (Task 7); Plans 4 and 6b read the judgment.
- **8 Flags:** `pipeline.agentic.relevance: off | shadow | on` (default `shadow`, free until `refresh`), `dedupe: legacy | semantic`, `ordering: legacy | hypotheses` (defaults `legacy`), plus `search_plan` (bool, default false); tuning numbers in `pipeline.discovery.*` (Tasks 4, 6, 7).
- **9 Reference data location:** `users.base_dir()/reference/<dataset>/<version>/`, shared, public, outside Git; tiny invented fixture files stay in the repository (Tasks 2-3).
- **14 Signature additions:** `SearchPlan.queries` is keyed by `searches.yaml` section (`seek`, `jora`, `jobspy`), not by collector module name (`jobspy_src`) (Task 6).
- **15 Migrations:** the next free `MIGRATIONS` index at execution (Task 4).
- **16 `location_fit`:** this plan never reads `location_fit`.

Additive fields: `FieldHypothesis.related`; `RelevanceJudgment.method`, `ad_hash`, `plan_hash`; `field_hypotheses` and `judge_relevance` gain keyword-only parameters (`llm`, `config`, `policy` / `context`). Semantic dedupe and `_target_first` are available behind `dedupe: semantic` / `ordering: hypotheses`; the legacy code is removed in a later cleanup once the owner has switched.
