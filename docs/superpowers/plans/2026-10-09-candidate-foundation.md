# Candidate Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore callable, version-bound candidate/evidence analysis in isolation without changing legacy execution or enabling live work.

**Architecture:** Add `jobwatch/candidate/` as read-only tools. Current primary evidence extraction feeds strict snapshots; supplied DWA mappings are validated against a pinned reference; adapted archived structural math derives evidence-supported proposals under current target policy. Nothing writes canonical data, calls providers, admits drafts or changes graph stages.

**Tech Stack:** Existing Python 3.12, Pydantic 2, PyYAML and pytest; stdlib hashing/dataclasses/math/pathlib. No added dependencies.

**Spec:** [Approved candidate-foundation design](</home/phroggingphrog/workspace/builder/jobwatch-agentic/docs/superpowers/specs/2026-10-09-candidate-foundation-design.md>). Read [canonical intent](</home/phroggingphrog/apps/jobwatch/INTENT.md>) FIRST. BUI-258; broader research BUI-248. Root BUI-196 is not modified or resolved.

## Global Constraints

- No model inference in this slice.
- No DB/ledger migration, browser operation, timer, runtime feature enablement or provider-state persistence.
- No archived profiles, secrets, answers or personal data copied.
- Current enrolment is not mastery.
- Current owner targets govern recommendations; exclusions cannot be weakened by learned/model/reference metadata.
- No heavy dependency or new service.
- Live cutover requires separate owner approval.
- Existing legacy APIs and baseline remain unchanged. New functions require explicit input roots; no implicit real profile default.

## Working context and file boundaries

Existing linked worktree `/home/phroggingphrog/workspace/builder/jobwatch-agentic`, branch `phase/01-agentic-career-ops`. Main `7bfbc35` was merged non-destructively at `78be468`; approved spec commit `61fc495`. Do not touch the pre-existing untracked plan-review document or discard concurrent changes.

New implementation files: `jobwatch/candidate/{__init__,contracts,evidence,reference,mapping,analysis,policy}.py`. New tests: `tests/candidate/{test_contracts,test_evidence,test_reference,test_mapping,test_analysis}.py` and reusable synthetic builders in `tests/candidate/fixtures.py` (not named conftest; imports must work independently). Provenance: `docs/candidate-foundation/PROVENANCE.md`. All sources are read before adaptation. No legacy module modification is required for this slice.

Test prefix, run in worktree (no real provider keys loaded by tests):

```bash
scratch=$(mktemp -d /tmp/jobwatch-candidate-test.XXXXXX)
JOBWATCH_DATA_DIR="$scratch/data" JOBWATCH_PROFILE_DIR="$scratch/profile" JOBWATCH_DB="$scratch/test.db" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" /home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q -p no:cacheprovider tests/candidate
```

For full suite use isolated `JOBWATCH_DATA_DIR`, `JOBWATCH_PROFILE_DIR`, `JOBWATCH_DB` under a fresh temporary directory, with `PYTHONPATH=$PWD` and no cache provider. Do not run current collector/pipeline CLI, archived services or old scripts. No repository-wide formatter.

## Shared serialized contract (exact field vocabulary)

Use frozen, strict Pydantic models, extra forbidden. Public errors are fixed codes through `CandidateError(ValueError)`; do not interpolate quotes, paths or source contents. Private EvidenceBundle stores spans for later agent matching, but its repr must suppress quote/content fields. AnalysisResult contains no raw evidence/quotes. All public functions catch Pydantic/JSON/YAML/Unicode validation exceptions and return fixed CandidateError codes without interpolated input, cause or retained context (`exc.__cause__` and `exc.__context__` both None); raise a fresh safe error outside the except block, not merely `from None` while retaining private context. Direct model validation uses ConfigDict(hide_input_in_errors=True); tests inspect str/repr/cause/context for a unique private marker. Contact protection is drop-only with visible count, never rewrite a stored quote. No logging of exception objects/input.

`digest(value)` = SHA-256 of UTF-8 JSON, `sort_keys=True`, `separators=(',', ':')`, `ensure_ascii=False`, `allow_nan=False`; `content_hash(bytes)` = SHA-256 of bytes. Hashes lower-case 64 hex characters.

- `EducationStatusEvidence`: `source_file: Literal['profile.yaml']`, `source_hash: str`, `line: int >=1`, `quote: Literal['completed','current']`, `education_index: int >=0`; private repr. Used only for the corresponding primary education group, never attached to unrelated work skills.
- `EvidenceItem`: `id: str`, `kind: Literal['role','education','skill','achievement','cert']`, `source_file: Literal['master_resume.md','cv.md','profile.yaml']`, `source_hash: str`, `line: int >=1`, `end_line: int >= line`, `quote: str nonempty`, `education_status: Literal['completed','current','unknown','not_applicable']='not_applicable'`, `status_evidence: EducationStatusEvidence|None=None`. Education/cert defaults unknown when loaded; do not infer completion from date/degree words. Completed/current status requires valid status_evidence; not_applicable is for ordinary work/skill evidence only. Status current never becomes mastery. Bind every item to exactly one source snapshot.
- `EvidenceBundle`: `schema_version: Literal[1]`, `sources: dict[str,str]` filename→raw-content hash (includes present annotation file hashes for invalidation), `items: tuple[EvidenceItem,...]`, `bundle_hash: str`, `contents: dict[str,bytes]` private immutable-acquisition bytes (`repr=False`, exclude from JSON/public serialization). At every analysis entry recompute byte hashes and verify exact quotes/status against those same snapshots; reject any mutated or missing contents even if a caller recomputed an item-only bundle hash. Contents never serialize/persist to disk or logs in this slice; persistence is a separate owner-approved extension. A reconstructed persisted bundle would require explicit source snapshot revalidation, not blind `model_validate` of public metadata. Hash canonical sources+items; duplicate IDs or source mismatch reject. Raw filenames are fixed names, not paths. Supported annotation files use strict envelope `{'schema_version':1,'items':[EvidenceItem serialized fields]}`; `evidence.yaml` and `transferable_skills_taxonomy.yaml` are read only when present, and legacy taxonomy-only files without this envelope return `annotation_invalid` rather than being treated as proof. Existing legacy loader is unchanged. Optional primary `profile.yaml` may yield quoted descriptive education; status is never inferred from dates/degree names. An explicit primary `education.<index>.status` of `completed` or `current` binds to that education group; absent/other status is unknown. Store status-source filename/hash/line/quote in a private `EducationStatusEvidence` field to validate it, rather than accepting the annotation's claim of completion. All education/cert items remain diagnostic only for structural capability recommendations even when completed: a completed award is not mastery of every DWA, and curricular learning outcomes cannot supply work-achievement claims. Ordinary independently quoted skill/work evidence remains usable. Official curriculum ingestion is outside the first slice.
- `Dwa`: `id: str`, `title: str`, `gwa_id: str`.
- `Occupation`: `code: str six digits`, `title: str`, `family: str canonicalized by casefold + collapse whitespace/hyphen/underscore runs to '_' + strip('_')`, `excluded: bool=False`, `dwa_weights: dict[str,float finite >0]`, `gwa_ratings: dict[str,float finite 0..5]`. Family is taxonomy metadata, not authority to change policy. ReferenceBundle declares closed `families: tuple[str,...]` canonical taxonomy (unknown occupation family becomes taxonomy_conflict diagnostic, never implicit alias). Reference-declared excluded or policy-bound excluded occupation code wins even if family is relabelled. Do not evaluate title words as a proxy for family; no invented title blocker vocabulary. TargetPolicy carries `excluded_codes: tuple[str,...]` containing immutable owner-exclusion code set from reviewed reference authority; minimal fixture/default includes 431111 (Barista) and 541211 (Customer Service Officer), verified in archived synthetic tests; wider exclusion authority uses reference-declared excluded flags plus hard family exclusion. This minimal code list is not claimed a complete production occupation taxonomy. Code namespace is ANZSCO 2022; do not extend code lists from title guesses. Current whole-ad gates remain authority for real job recommendations beyond these structural proposal codes. A tampered reference cannot remove excluded codes from policy.
- `Crosswalk`: `soc: str`, `anzsco_codes: tuple[str,...]`; never select one code when multiple are recorded.
- `ReferenceBundle`: `schema_version: Literal[1]`, `version: str`, `sources: dict[str,str]` source-name→version, `licenses: dict[str,str]` source-name→nonempty licence/attribution identifier, `families: tuple[str,...]` closed canonical taxonomy, `dwas: tuple[Dwa,...]`, `occupations: tuple[Occupation,...]`, `crosswalks: tuple[Crosswalk,...]`, `reference_hash: str` SHA-256 of file bytes. Validate uniqueness, known DWA/GWA/code references and complete source/licence metadata; disallow duplicate JSON keys.
- `Mapping`: `evidence_id`, `source_hash`, `reference_hash`, `dwa_id`, `method` (nonempty bounded string), `state: Literal['suggested','confirmed']`. No raw rationale field.
- `TargetPolicy`: `version: str`, `allowed_families: tuple[str,...]` canonicalized as above, `excluded_codes: tuple[str,...]=('431111','541211')`; constructors require this immutable minimum and permit additive exclusions only. Built-in immutable `EXCLUDED_FAMILIES=('customer_service','hospitality','retail','shop_floor')`; callers cannot remove it, or add excluded family to allowed list. Default allowed canonical families derive from current contract: `('accounting','finance_clerical','back_office_admin','data_analyst','business_analyst','finance_analyst','business_program','finance_program','operations_program','analytics_program')`. Job-specific work rights/hours/location/program gates are not replaced by family projection.
- `OccupationFit`: `code`, `family`, `dwa_coverage: float`, `gwa_similarity: float`, `proximity: float`, `evidence_ids: tuple[str,...]`, `gap_dwa_ids: tuple[str,...]`, `mapping_states: tuple[Literal['suggested','confirmed'],...]`, `recommendation_status: Literal['candidate_path','suggested_path','excluded','not_target','unsupported','education_unverified','taxonomy_conflict']`. Candidate_path requires at least one confirmed, non-education/non-cert evidence→DWA mapping contributing to this occupation's DWA coverage; suggestion-only or GWA-only proximity remains diagnostic. No title in safe metadata if it may carry personal data; reference title is available to a private tool separately.
- `ArchetypeProposal`: `codes: tuple[str,...]`, `evidence_ids: tuple[str,...]`, `shared_gwa_ids: tuple[str,...]`, `policy_status: Literal['candidate_path','diagnostic']`. Cluster per identical code[:3], shared characteristic GWA (rating>=3.5) intersect candidate supported GWA vector, positive proximity; at most 30 seeds sorted proximity/code. Never combine recommendation and diagnostic members. Derive shared IDs deterministically; singleton permitted.
- `AnalysisResult`: `archetypes: tuple[ArchetypeProposal,...]`, `schema_version: Literal[1]`, `run_key: str`, `evidence_hash: str`, `reference_hash: str|None`, `policy_hash`, `mapping_hash`, `status: Literal['available','reference_unavailable','unmapped']`, `recommendations: tuple[OccupationFit,...]`, `diagnostics: tuple[OccupationFit,...]`, `unmapped_evidence_ids: tuple[str,...]`. Stable input/output identity (including deterministic archetype proposals), no timestamps/random IDs.

Status trigger priority: excluded = reference.excluded or immutable excluded code or excluded canonical family; taxonomy_conflict = undeclared family; not_target = declared non-allowed family; unsupported = no contributing mapped evidence/positive proximity; education_unverified = positive proximity supported solely by education/cert; suggested_path = no confirmed non-education DWA coverage (including only GWA overlap); candidate_path = positive confirmed non-education DWA coverage within allowed policy. Every non-candidate_path goes to diagnostics; no trigger is inferred from title text.

### Task 1: Strict contracts and provenance

**Files:** Create `jobwatch/candidate/__init__.py`, `jobwatch/candidate/contracts.py`, `tests/candidate/__init__.py`, `tests/candidate/test_contracts.py`, `tests/candidate/fixtures.py`, `docs/candidate-foundation/PROVENANCE.md`.

**Consumes:** Approved spec, archive/current source identity.
**Produces:** All types above; `digest(value: object)->str`, `content_hash(value: bytes)->str`, `CandidateError`, `EXCLUDED_FAMILIES` and immutable allowed-family vocabulary. Fixture builders `fictional_reference(tmp_path)->Path` writes an explicit reference JSON and returns its path; `fictional_profile(tmp_path)->Path` writes a primary CV under `<tmp_path>/profile` and returns that root. CV is `# Fictional\n\n## Skills\n- Reconciled ledgers\n`. Reference includes `test.accounts` DWA → `test.gwa` and accounting occupation `221111` with that DWA weight 1.0 / GWA rating 4.0; a second excluded hospitality occupation `431111` shares that GWA to exercise policy. Metadata uses `sources={'fictional':'fixture-v1'}`, `licenses={'fictional':'test-only'}`, `families=('accounting','hospitality')`, version `fixture-v1`, no real reference data. Excluded 431111 has excluded=true and remains excluded if maliciously relabelled finance_clerical; code policy independently blocks it. Tests also normalize Hospitality/hospitality_/customer-service aliases and reject policy attempts to remove excluded codes. Builders write only under pytest temporary paths.

- [ ] Write failing strict-contract tests, including unknown fields, malformed hashes, duplicate IDs, nonfinite weights, education status and unsupported sources. Core examples:

```python
import pytest
from jobwatch.candidate.contracts import EvidenceItem, CandidateError, digest

def test_stable_digest():
    assert digest({'b': 2, 'a': 1}) == digest({'a': 1, 'b': 2})

def test_unknown_claim_property_rejected():
    with pytest.raises(ValueError):
        EvidenceItem(id='cv.L3', kind='skill', source_file='cv.md', source_hash='a'*64,
                     line=3, end_line=3, quote='Ledger reconciliation', invented=True)

def test_error_is_safe():
    assert str(CandidateError('source_escape')) == 'source_escape'
```

- [ ] Run `tests/candidate/test_contracts.py`; first run must fail import because package does not exist. Record observed failure, not assumed red.
- [ ] Implement models with this base and hash primitives; no side effects:

```python
import hashlib, json
from pydantic import BaseModel, ConfigDict
class StrictFrozen(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, hide_input_in_errors=True)
def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()
def content_hash(value):
    return hashlib.sha256(value).hexdigest()
class CandidateError(ValueError):
    pass
```

Add explicit bounds/validators for every shared-contract invariant; validate nested container mutation defensively by hashing/copying serialized input at API boundaries rather than trusting `frozen=True` to make dicts deeply immutable. `repr=False` for quote and private source-bearing fields. Serialize tuple models with `model_dump(mode='json')`; load JSON with strict supported types, not lax coercion.

- [ ] Provenance names archive `candidate_analysis.py` (GWA/DWA coverage/cosine/clustering concepts), `occupation_reference.py` (crosswalk aggregation), `evidence_dwa_map.py` (validated IDs/hash binding), current `apply/evidence.py`. Record exact SHA-256, licence evidence/uncertainty and adaptation details; do not assert a broken archived worktree HEAD. Substantial upstream material carries actual required notice; if authorship/licence of a local fragment cannot be established, port the independently described mathematical method rather than copying source text. Source inventory is not blanket permission.
- [ ] Run task tests and commit only listed files: `git add jobwatch/candidate/__init__.py jobwatch/candidate/contracts.py tests/candidate/__init__.py tests/candidate/test_contracts.py tests/candidate/fixtures.py docs/candidate-foundation/PROVENANCE.md && git commit -m 'feat: define versioned candidate analysis contracts'`.

### Task 2: Confined primary evidence snapshots

**Files:** Create `jobwatch/candidate/evidence.py`, `tests/candidate/test_evidence.py`; extend synthetic fixture builders only.
**Consumes:** Task 1 models, existing `jobwatch.apply.evidence.extract_cv` and `extract_profile_yaml` (not default live loader).
**Produces:** `snapshot_evidence(root: Path)->EvidenceBundle`; `validate_annotation(item: EvidenceItem, sources: dict[str,str])->None` checks exact primary lines/hash with safe errors.

- [ ] Add red tests for fictional CV extraction and root escapes:

```python
from pathlib import Path
import pytest
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.candidate.contracts import CandidateError

def test_quote_is_bound_to_primary_bytes(tmp_path):
    (tmp_path/'master_resume.md').write_text('# Fictional\n\n## Skills\n- Reconciled ledgers\n')
    b = snapshot_evidence(tmp_path)
    assert b.items[0].quote == 'Reconciled ledgers'
    assert b.items[0].source_hash == b.sources['master_resume.md']
    assert 'Fictional' not in [i.quote for i in b.items]

def test_symlink_primary_refused(tmp_path):
    outer=tmp_path/'outside'; outer.write_text('secret')
    root=tmp_path/'profile';root.mkdir()
    (root/'master_resume.md').symlink_to(outer)
    with pytest.raises(CandidateError, match='source_escape'):
        snapshot_evidence(root)
```

- [ ] Run focused tests and confirm red before implementation.
- [ ] Read explicit root only. Reject root symlinks and file symlinks/nonregular files. Use descriptor-based read with `os.open(..., O_RDONLY|O_NOFOLLOW)`, `fstat`, bounded size (2 MiB per source), UTF-8 strict decode, no write/network. Treat missing both CV names as `source_missing`; if `cv.md` exists use it as preferred CV and do not silently pick the alternate on malformed content. Hash exact bytes read, call extraction on those same bytes, verify every quote against explicit start/end lines, reject duplicate IDs. For CV extracts end_line=line. For YAML scalars retain node.start_mark/end_mark bounds. Support plain, single/double-quoted and literal/folded block forms; the quoted analytic text is the decoded scalar value, with source span pointing to its exact YAML node. Decode that bounded node slice using YAML scalar semantics (remove quote/indicator delimiters and decode escapes), then compare whitespace-normalized candidate quote to the independently decoded node value at the declared source path, preserving raw bytes/hash. Do not match an arbitrary 30-line tail or equate raw quoted syntax with decoded text. Tags, anchors, aliases and multiple documents reject with safe code. Duplicate YAML keys reject. Status source line must match that education index's scalar node. Unsupported/malformed span rejects with safe code; do not silently omit a factual claim.

```python
from jobwatch.apply.evidence import extract_cv, extract_profile_yaml
raw_items = extract_cv(cv_text, source_file=cv_name)
if profile_text is not None:
    raw_items += extract_profile_yaml(profile_text)
# Construct EvidenceItem from fixed keys, bound to hashes of these exact snapshots.
```

Drop whole contact-bearing items (emails, phone-like sequences, URLs) conservatively from analytic evidence even in body sources; never rewrite stored quotes. EvidenceBundle adds `dropped_contact_count: int>=0`, included in bundle hash and safe counts, so omission is visible. Do not put source text in errors. Imported `evidence.yaml`/taxonomy annotations are optional: strict field schema, primary-source quote/hash verification, no proof from taxonomy itself. If present and malformed or containing unsupported claim, reject snapshot rather than silently discard findings; distinguish harmless framing from factual claims. Education/cert gets unknown unless explicit independently bound completion/current metadata validates against primary record; current stays descriptive only. Annotations cannot mark unknown qualification completed without cited primary completion evidence. This slice need not fetch/ingest curriculum pages.

- [ ] Add missing sources, duplicate annotation IDs, traversal/absolute source names, forged quote/hash, taxonomy-only fabricated metric/credential, current study, plain/single/double-quoted and literal/folded scalar/status forms, anchor/tag/alias/multidocument rejection, preferred-CV alias and source mutation tests. Validate safe error code and no raw private quote in `repr`/logs. Verify existing legacy evidence tests unchanged.
- [ ] Commit only task files with `feat: snapshot confined primary candidate evidence`.

### Task 3: Pinned reference loading and mapping validation

**Files:** Create `jobwatch/candidate/reference.py`, `jobwatch/candidate/mapping.py`, `tests/candidate/test_reference.py`, `tests/candidate/test_mapping.py`.
**Consumes:** Task 1 contracts, Task 2 evidence snapshot.
**Produces:** `load_reference(path: Path)->ReferenceBundle|None`, `validate_mappings(bundle: EvidenceBundle, reference: ReferenceBundle, mappings: tuple[Mapping,...])->tuple[Mapping,...]`, `crosswalk_codes(reference: ReferenceBundle, soc: str)->tuple[str,...]` returns all candidates or empty, never one arbitrary code.

- [ ] Write red tests with a fictional JSON export built from the exact contract (source/license metadata `fictional: test-only`; no production data download):

```python
import pytest
from jobwatch.candidate.reference import load_reference, crosswalk_codes
from jobwatch.candidate.contracts import CandidateError

def test_missing_reference_is_unavailable(tmp_path):
    assert load_reference(tmp_path/'absent.json') is None

def test_duplicate_json_keys_reject(tmp_path):
    p=tmp_path/'bad.json';p.write_text('{"version":"a","version":"b"}')
    with pytest.raises(CandidateError):
        load_reference(p)
```

Add fictional `soc='S1'` with two actual synthetic occupation codes and assert returned tuple has both. Unknown IDs and missing licence/version reject.
- [ ] Run and confirm red.
- [ ] Implement explicit read-only reference loading: same symlink/regular-file controls, 32 MiB limit, duplicate-key rejecting `object_pairs_hook`, strict finite fields, no missing/empty required metadata, validate all foreign references. Hash raw file bytes, not filepath. Root schema excludes `reference_hash` in export (loader supplies digest); unknown field reject. Missing returns None, unreadable/malformed returns safe `reference_invalid`. Validate real O*NET hierarchy separately from fictional IDs: declared `gwa_id` must match the first five segments of a hierarchical real DWA; synthetic fixture IDs use explicit `test.*` namespace to avoid asserting fake official codes.

```python
from collections import Counter
# Mapping uniqueness is (evidence_id, dwa_id); every mapping binds exact source and reference hashes.
pairs = [(m.evidence_id, m.dwa_id) for m in mappings]
if len(set(pairs)) != len(pairs):
    raise CandidateError('mapping_duplicate')
```

Every Mapping must resolve to existing evidence/DWA and correct bound hashes; stale/unknown rejects entire request atomically. Maximum three DWA mappings per evidence, preserving archive validation ceiling; validate method/state, sorted stable result. Education current/unknown mapping may remain diagnostic but cannot support a mastered/credential-based recommendation. No model chooser/transport is added.
- [ ] Run tests covering mapping duplicate, forged/changed source, changed reference bytes, dangling occupation weights, nonfinite numbers, unordered serialization, ambiguous many-to-many crosswalk and absent reference; commit task files with `feat: validate pinned occupation references and evidence mappings`.

### Task 4: Structural analysis under immutable target policy

**Files:** Create `jobwatch/candidate/policy.py`, `jobwatch/candidate/analysis.py`, `tests/candidate/test_analysis.py`; extend provenance and fixtures.
**Consumes:** Evidence/reference/validated mappings.
**Produces:** `default_policy()->TargetPolicy`; `analyse_candidate(bundle: EvidenceBundle, reference: ReferenceBundle|None, mappings: tuple[Mapping,...], policy: TargetPolicy)->AnalysisResult`; `analysis_metadata(result: AnalysisResult)->dict` safe hash/count/status only, no source paths/text. Export callable APIs from package __init__.

- [ ] Red tests: two fictional candidates (ledger work versus hospitality work) differ, no excluded recommendation even high proximity, course-current only diagnostic, reference unavailable produces explicit empty result, stale mappings fail. Core exclusion contract:

```python
import pytest
from jobwatch.candidate.contracts import TargetPolicy

def test_policy_cannot_reenable_excluded_family():
    with pytest.raises(ValueError):
        TargetPolicy(version='owner-v1', allowed_families=('accounting','hospitality'))
```

Tests use fixtures with two occupations sharing a GWA plus a wanted finance role and excluded hospitality role; declared family/title conflict must be diagnostic. No title-word classifier becomes eligibility decision.
- [ ] Run and confirm red.
- [ ] Implement reference maths adapted from archived candidate analysis:

```python
import math

def cosine(a, b):
    denom=math.sqrt(sum(v*v for v in a.values())*sum(v*v for v in b.values()))
    return sum(v*b.get(k,0.0) for k,v in a.items())/denom if denom else 0.0

def structural_fit(candidate_dwas, candidate_gwas, occupation):
    total=sum(occupation.dwa_weights.values())
    coverage=(sum(w for d,w in occupation.dwa_weights.items() if d in candidate_dwas)/total) if total else 0.0
    similarity=cosine(candidate_gwas, occupation.gwa_ratings)
    return coverage, similarity, .6*coverage+.4*similarity
```

GWA vector counts distinct usable evidence IDs per GWA (not repeated mappings). Structural fit accepts all valid evidence for diagnostic; candidate_path requires confirmed non-education/non-cert DWA coverage and allowed canonical family, never a title classifier. Reference-declared excluded flags and immutable policy exclusions win over relabeling. Suggested mapping-only fits are diagnostic suggested_path. Evidence IDs and DWA gaps sorted; tie-break proximity descending then occupation code. Derive ArchetypeProposal by the frozen cluster rule above (same minor3, shared characteristic GWA, positive proximity, 30 seeds); no mixing diagnostic/recommendation members. Shared IDs are intersection of members' characteristic GWA sets with candidate supported vector. No raw profile text or guessed hire probability.

Run key hashes evidence hash, reference hash, canonical mapping list (including state/method), full policy and deterministic archetype proposals. No missing-data score promoted to positive: no mappings yields unmapped with empty recommendations; reference None with empty mappings yields reference_unavailable with empty recommendations/diagnostics/archetypes; reference None with non-empty mappings raises CandidateError('mapping_unresolved'). Confirm dict mutation after model creation cannot preserve stale acceptance: revalidate bound snapshots at analysis entry. All calls are pure/read-only after snapshot acquisition.
- [ ] Add deterministic ordering, changed bytes/hash/method/confirmation/policy invalidation, unsupported new IDs, source privacy, empty reference and cluster/exclusion tests. Compare adapted mathematical result to a tiny hand-computed case (coverage=1/2, cosine=1, proximity=.7) rather than executing archived runtime.
- [ ] Commit listed task files with `feat: derive evidence-backed candidate paths within owner targets`.

### Task 5: Callable acceptance, review and handoff

**Files:** Create `tests/candidate/test_acceptance.py`, `docs/candidate-foundation/README.md`; update scoped provenance and test builders if required; no other shared planning/contract files.
**Consumes:** All exported foundation APIs.
**Produces:** Documented explicit-root invocation and synthetic end-to-end evidence/reference/map→analysis tests. Private source input may be displayed only to paid role tools in later slices; safe metadata is distinct.

- [ ] Write a failing acceptance scenario that snapshots a fictional primary CV, loads fictional references, constructs source/hash-bound mappings, runs analysis and checks safe metadata. Include excluded diagnostic and education-unverified cases; assert temporary source hashes/mtime unchanged and no added files after callable analysis. Add exact fixture code using exported Task 1 builders, not a live profile path.
```python
import json
from jobwatch.candidate import snapshot_evidence, load_reference, analyse_candidate, default_policy, analysis_metadata
from jobwatch.candidate.contracts import Mapping
from candidate.fixtures import fictional_profile, fictional_reference

def test_callable_foundation_has_no_side_effects(tmp_path):
    root=fictional_profile(tmp_path)
    path=fictional_reference(tmp_path)
    before={p: (p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    evidence=snapshot_evidence(root)
    reference=load_reference(path)
    item=next(i for i in evidence.items if i.quote=='Reconciled ledgers')
    mapping=Mapping(evidence_id=item.id, source_hash=item.source_hash,
                    reference_hash=reference.reference_hash, dwa_id='test.accounts',
                    method='fixture', state='confirmed')
    result=analyse_candidate(evidence,reference,(mapping,),default_policy())
    assert [r.code for r in result.recommendations]==['221111']
    assert 'Reconciled ledgers' not in json.dumps(analysis_metadata(result))
    after={p: (p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    assert before==after
```

Ensure `tests/candidate/__init__.py` exists so pytest's test-root insertion allows `candidate.fixtures` imports, following the existing `tests/apply` package pattern; do not add a root tests package or change legacy conftest discovery.

- [ ] Run acceptance red, then fill only necessary integration/export wiring; no CLI timer/pipeline hook added.
- [ ] README shows explicit invocation, exact source/reference JSON format, diagnostic/suggested/confirmed meanings, versioning, education limits, missing-data/error behavior, provenance and pending role-runtime/product capabilities. Explain that foundations ≠ eligibility or full CAP-2 acceptance. Document undo as isolated scoped revert/leave unapplied, no data deletion.
- [ ] Review full diff, independent code review and intent/spec review on final candidate. Execute full synthetic suite with isolated roots; inspect exit code and failures. Any baseline failure stops build claims until diagnosed. No provider/inference or real form acceptance claimed.
- [ ] Commit only acceptance/docs with `test: verify candidate foundation acceptance and provenance`; record evidence/check SHA on BUI-258 child only after fresh card checks and in WHAT-HAPPENED with rollback. Broader BUI-196 stays incomplete and untouched.

## Self-review traceability

Evidence truth/confinement/privacy → tasks 1/2/5. Reference/licence/ambiguity → 1/3/5. Mapping/version/confirmation → 1/3/4. Candidate-derived paths/transferability/education → 2/4/5. Hard exclusions/target projection → 1/4/5. Stable invalidation → all API-bound snapshots plus task 4 tests. No runtime admissions/legacy change → task 5 full suite and diff. Real CAP-2/3/5 are not claimed; the foundation is a separate verified tool slice.

The first detailed plan receives fresh-context read-only review before task execution. Owner approval already selected the first slice; execute inline with checkpoints by default to avoid adding writer agents for these coupled contracts, use independent reviewers as scoped subagents. This is not Agent Teams and adds no long-running service.
