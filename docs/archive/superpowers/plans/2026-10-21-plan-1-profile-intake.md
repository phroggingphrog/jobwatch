# Plan 1: Profile intake and approval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn uploaded documents into a private draft profile that the person reviews, corrects and confirms through the native API; only confirmed contents become the authoritative, versioned profile, and confirmation starts evaluate-only discovery within a shown scope and budget.

**Architecture:** A new domain module `jobwatch/candidate/intake.py` owns uploads, proposals, confirmation and approved versions under `<person>/intake/` and `<person>/profile-versions/` (0700/0600). Confirming writes an immutable version, persists its evidence snapshot bytes, and projects it into the existing `profile/` files in the schema `person.py`, `apply/evidence.py` and `snapshot_evidence` already read. A FastAPI router `pipeline/agentic/profile_api.py` exposes it on the native API with the existing bearer scopes. Collection switches to `operation='evaluate'` so discovery never drafts.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2 (strict models like `pipeline/agentic/contracts.py`), SQLite, pytest, existing `jobwatch.llm.LLM` with fake transports in tests.

**Spec:** the owner's agreed backend brief (2026-10-21, sections 1, 2, 4 "never record agent-generated answers", 5 "deliver profile approval/versioning") and [the roadmap](2026-10-21-backend-roadmap.md).

## Global Constraints

- "Keep uploaded documents and parsed proposals private and separate from the approved candidate profile."
- "Distinguish direct evidence, inference and unknown information. A CV gap alone does not establish unemployment."
- "Only confirmed contents become authoritative profile facts. Preserve source references and versioned evidence snapshots. Later inferred amendments require confirmation before replacing approved facts."
- "Profile confirmation starts ongoing discovery and assessment within the search scope and budget shown during confirmation. It does not authorise document preparation, employer messages or submission."
- "Never record agent-generated answers as user choices or approval."
- Private files 0600, directories 0700, no symlinks followed (reuse `candidate/_private_io.read_regular_file`, `apply/paths.ensure_dir`).
- Upload limit 10 MiB per file, types `.pdf .docx .txt .md`; JSON bodies keep the existing 64 KiB cap.
- Never use live candidate records as test fixtures (AGENTS.md).

## Review Focus

1. A scanned PDF with no extractable text → upload accepted, proposal creation fails with `no_extractable_text`; nothing written to `profile/`. (Task 3 test.)
2. A CV with an 18-month gap and no stated status → `employment_status` fact has basis `unknown`, never `unemployed`. (Task 3 test.)
3. The model returns a "direct evidence" fact whose quote is not in the upload → the fact is downgraded to `inference` with no source, never kept as evidence. (Task 3 test.)
4. Confirm with a digest from before the latest correction → 409 `proposal_changed`, no version written. (Task 5 test.)
5. Person B's token cannot read, edit or confirm person A's uploads or proposals → 404. (Task 7 test.)
6. The owner's existing hand-made `profile/` is never overwritten until they explicitly adopt or confirm. (Task 6 test.)

---

### Task 1: Collection evaluates only; onboarding writes structured work rights

**Files:**
- Modify: `pipeline/agentic/service.py` (`after_collect`, the `agentic_batch_run(...)` call near line 688)
- Modify: `jobwatch/onboarding.py` (`build_profile`)
- Modify: `jobwatch/candidate/person.py:28-35` (`work_rights` tolerates a legacy string)
- Test: `tests/test_agentic_service.py`, `tests/test_onboarding_wrangle.py`

**Interfaces:**
- Produces: `after_collect(...)` passes `operation='evaluate'` to `agentic_batch_run`; `person.work_rights() -> dict` always returns a dict.

- [ ] **Step 1: Write the failing tests**

```python
def test_collection_never_drafts_documents(world, monkeypatch):
    # world: existing fixture; a READY-eligible posting
    ops = []
    monkeypatch.setattr(service, 'run_agentic_job', lambda pid, cfg, conn, **kw: ops.append(kw.get('operation')) or Stage.READY)
    service.after_collect(conn, config, max_seconds=60)
    assert ops and set(ops) == {'evaluate'}

def test_legacy_string_work_rights_reads_as_unknown(tmp_path, monkeypatch):
    # profile.yaml candidate.work_rights: "Australian citizen"
    assert person.work_rights() == {'statement': 'Australian citizen'}
    assert person.hours_limit_per_fortnight() is None
```

- [ ] **Step 2: Run them to verify they fail** — `python -m pytest -q -p no:cacheprovider tests/test_agentic_service.py -k never_drafts tests/test_onboarding_wrangle.py -k legacy_string` → FAIL (`prepare` in ops; AttributeError on `str.get`).
- [ ] **Step 3: Implement** — pass `operation='evaluate'` from `after_collect`; `work_rights()` returns `{'statement': value}` for a string; `build_profile` writes `work_rights: {'statement': ...}`.
- [ ] **Step 4: Run** the two test files and `tests/test_agentic_*.py` → PASS.
- [ ] **Step 5: Commit** `fix: collection evaluates only; structured work rights from onboarding`.

### Task 2: ADR and glossary for profile approval

**Files:**
- Create: `docs/adr/0002-profile-intake-and-approval.md`
- Modify: `GLOSSARY.md` (Proposal, Approved profile, Profile version, Fact basis, Search scope)

- [ ] **Step 1:** Write the ADR (context: brief §1–2; decision: proposal → confirm → immutable version + projection; consequences: owner adoption, discovery gated on a confirmed version; status Accepted).
- [ ] **Step 2: Commit** `docs: ADR 0002 profile intake and approval`.

### Task 3: Private uploads and parsed proposals

**Files:**
- Create: `jobwatch/candidate/intake.py`
- Modify: `jobwatch/onboarding.py` (move `PROMPT` into an intake prompt that returns sourced facts; keep `wrangle` as a thin caller for the legacy `/welcome` page)
- Move: `extract_text` from `jobwatch/web/onboarding_routes.py` to `jobwatch/candidate/intake.py` (re-export for the web route)
- Test: `tests/candidate/test_intake.py`

**Interfaces:**
- Produces:
  - `class Basis(StrEnum): EVIDENCE='evidence'; INFERENCE='inference'; UNKNOWN='unknown'`
  - `SECTIONS = ('experience','education','skill','transferable_skill','employment_status','availability','preference','constraint','exclusion','work_rights','location','career_focus')`
  - `class SourceRef(BaseModel): upload_sha256: str; line: int; quote: str`
  - `class ProfileFact(BaseModel): id: str; section: str; value: str | dict; basis: Basis; sources: tuple[SourceRef, ...] = (); note: str = ''; actor: Literal['parser','person'] = 'parser'`
  - `class Question(BaseModel): id: str; section: str; text: str; why: str`
  - `class Proposal(BaseModel): id: str; revision: int; base_version: int | None; uploads: tuple[str, ...]; facts: tuple[ProfileFact, ...]; questions: tuple[Question, ...]; status: Literal['draft','confirmed','superseded']`
  - `save_upload(person: str, filename: str, data: bytes, kind: Literal['cv','letter','evidence']) -> dict` → `{'upload_id','sha256','kind','bytes'}`; raises `IntakeError('unsupported_type'|'too_large')`
  - `propose(person: str, upload_ids: list[str], llm: LLM, *, base_version: int | None = None) -> Proposal`; raises `IntakeError('no_extractable_text')`
  - `load_proposal(person: str, proposal_id: str) -> Proposal`
  - `class IntakeError(ValueError)` with fixed codes only

- [ ] **Step 1: Write the failing tests** (synthetic CV text only)

```python
def test_upload_is_private_and_outside_profile(tmp_path, person):
    info = intake.save_upload(person, 'cv.txt', SYNTHETIC_CV.encode(), 'cv')
    path = users.user_dir(person) / 'intake' / 'uploads' / (info['sha256'] + '.txt')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and not (users.user_dir(person) / 'profile' / 'profile.yaml').exists()

def test_quote_not_in_upload_is_downgraded_to_inference(person, fake_llm):
    fake_llm.reply({'facts': [{'section': 'skill', 'value': 'Kubernetes', 'basis': 'evidence',
                               'sources': [{'line': 3, 'quote': 'Ran Kubernetes clusters'}]}], 'questions': []})
    proposal = intake.propose(person, [upload_id], fake_llm)
    fact = proposal.facts[0]
    assert fact.basis == 'inference' and fact.sources == ()

def test_cv_gap_never_becomes_unemployed(person, fake_llm):
    fake_llm.reply({'facts': [{'section': 'employment_status', 'value': 'unemployed', 'basis': 'inference', 'sources': []}],
                    'questions': []})
    proposal = intake.propose(person, [upload_id], fake_llm)
    status = next(f for f in proposal.facts if f.section == 'employment_status')
    assert status.basis == 'unknown' and any(q.section == 'employment_status' for q in proposal.questions)

def test_scanned_pdf_has_no_text(person, fake_llm):
    upload = intake.save_upload(person, 'scan.pdf', BLANK_PDF, 'cv')
    with pytest.raises(intake.IntakeError, match='no_extractable_text'):
        intake.propose(person, [upload['upload_id']], fake_llm)
```

- [ ] **Step 2: Run** `python -m pytest -q -p no:cacheprovider tests/candidate/test_intake.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `intake.py`. Store originals at `intake/uploads/<sha256><ext>` and an index `intake/uploads.json`; extracted text at `intake/text/<sha256>.txt`; proposals at `intake/proposals/<id>.json`. Validation rules in `propose`: a fact with basis `evidence` keeps only sources whose `quote` is verbatim (normalised with `apply.evidence.norm`) on the cited line ±2 of the stored text, else it becomes `inference` with no sources; `employment_status` may be `evidence` only with a quote stating the status, otherwise it becomes `unknown` and a question is added; unknown sections listed in the prompt (availability, constraints, exclusions, work rights when absent) become `unknown` facts plus a question when material.
- [ ] **Step 4: Run** the test file → PASS.
- [ ] **Step 5: Commit** `feat: private uploads and sourced profile proposals`.

### Task 4: Corrections and answers

**Files:**
- Modify: `jobwatch/candidate/intake.py`
- Test: `tests/candidate/test_intake.py`

**Interfaces:**
- Produces:
  - `edit(person: str, proposal_id: str, *, expected_revision: int, edits: list[dict]) -> Proposal` — edit ops `{'op':'set','fact_id','value','basis'}`, `{'op':'remove','fact_id'}`, `{'op':'add','section','value'}`; person edits get `actor='person'` and basis `evidence` only when the person states it (`basis='evidence'` with no source means "stated by the person", recorded as `sources=()` and `note='stated by person'`).
  - `answer(person: str, proposal_id: str, *, expected_revision: int, question_id: str, text: str) -> Proposal` — adds or replaces the fact for that question with `actor='person'`.
  - Every change increments `revision`; a stale `expected_revision` raises `IntakeError('proposal_changed')`.
  - `digest(proposal: Proposal) -> str` — sha256 of the canonical JSON of `facts`, `uploads`, `base_version`, `revision`.

- [ ] **Step 1: Failing tests:** `test_edit_with_stale_revision_is_refused`, `test_answer_records_a_person_fact`, `test_person_facts_are_never_marked_parser` (asserts `actor == 'person'` and that `propose` output never contains `actor='person'`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: proposal corrections and answers with revisions`.

### Task 5: Confirmation, approved versions and evidence snapshots

**Files:**
- Modify: `jobwatch/candidate/intake.py`
- Create: `jobwatch/candidate/projection.py`
- Test: `tests/candidate/test_intake.py`, `tests/candidate/test_projection.py`

**Interfaces:**
- Consumes: `snapshot_evidence(profile_dir)` (`jobwatch/candidate/evidence.py`), `apply.evidence.build_evidence/check_evidence`.
- Produces:
  - `class SearchScope(BaseModel): basis: tuple[str, ...]; locations: tuple[str, ...]; daily_assessments: int; daily_token_ceiling: int`
  - `scope_for(person: str, proposal: Proposal, config) -> SearchScope` — defaults `daily_assessments=40`, `daily_token_ceiling` = `pipeline.agentic.batch_token_ceiling` from config; basis = confirmed `career_focus` facts, else the experience/skill sections (employment-first); locations from `location` facts.
  - `confirmation(person, proposal_id, config) -> dict` → `{'proposal_digest', 'scope': SearchScope, 'scope_digest', 'authorises': ['discovery','assessment'], 'does_not_authorise': ['document_preparation','employer_messages','submission']}`
  - `confirm(person, proposal_id, *, proposal_digest: str, scope_digest: str, actor: Literal['person'], config) -> int` — writes `profile-versions/<n>/approved.json` (facts + scope + source upload hashes), copies the projected files and the evidence snapshot bytes into the version dir, projects into `profile/` atomically, marks the proposal `confirmed`, older drafts `superseded`; returns `n`. Raises `IntakeError('proposal_changed'|'scope_changed')`.
  - `current_version(person) -> dict | None`, `versions(person) -> list[dict]`
  - `projection.project(approved: dict) -> dict[str, str]` — file name → text for `profile.yaml` (candidate.work_rights as a dict, `hours_limit_per_fortnight` only from a person-stated or evidenced number), `master_resume.md` (sections built from confirmed experience/education/skills with verbatim quotes so `extract_cv` finds them), `interests_and_criteria.yaml` (target_roles from career_focus, `not_wanted`/`excluded_families` from exclusion facts).

- [ ] **Step 1: Failing tests:** `test_confirm_with_stale_digest_writes_nothing`, `test_confirm_writes_immutable_version_and_snapshot` (version dir contains `approved.json` and the snapshot's `bundle_hash` equals `snapshot_evidence(profile_dir).bundle_hash` after projection), `test_projection_feeds_existing_readers` (after projection `person.work_rights()` is a dict, `snapshot_evidence` yields items citing the confirmed quotes), `test_inferred_facts_only_enter_after_confirmation` (an `inference` fact stays out of `profile/` until confirmed, then appears marked as inference in `approved.json`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: confirm profiles into immutable versions with evidence snapshots`.

### Task 6: Amendments and owner adoption

**Files:**
- Modify: `jobwatch/candidate/intake.py`, `jobwatch/cli.py` (new `jobwatch profile adopt`)
- Test: `tests/candidate/test_intake.py`, `tests/test_cli_profile.py`

**Interfaces:**
- Produces:
  - `propose(..., base_version=n)` diffs against version `n`; facts that would change an approved fact carry `note='replaces <fact_id>'` and only take effect through `confirm`.
  - `adopt_existing(person, *, actor: Literal['person']) -> int` — turns an existing hand-made `profile/` into version 1 without rewriting its files (projection skipped; `approved.json` records `adopted_from_files=True`).

- [ ] **Step 1: Failing tests:** `test_owner_profile_is_not_overwritten_without_adoption` (propose + confirm for the owner with an existing `profile.yaml` refuses with `adopt_first` until `adopt_existing` ran), `test_amendment_does_not_change_approved_facts_until_confirmed`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: profile amendments and explicit adoption of existing profiles`.

### Task 7: Native API endpoints

**Files:**
- Create: `pipeline/agentic/profile_api.py`
- Modify: `pipeline/agentic/api.py` (mount router; exempt the upload route from the 64 KiB JSON cap with its own 10 MiB cap; add `profile` to capabilities)
- Modify: `pipeline/agentic/CHAT.md` (profile section)
- Test: `tests/test_profile_api.py`

**Interfaces:**
- Consumes: Tasks 3–6; `require(scope)` from `create_api`.
- Produces (all under `/api/agent/profile`, person from the bearer token, never from the body):
  - `POST /uploads` (multipart `file`, form `kind`; scope `run`) → 201 `{'upload_id','sha256','kind','bytes'}`
  - `POST /proposals` `{'upload_ids': [...], 'base_version': int|null}` (scope `run`) → 201 Proposal
  - `GET /proposals/{id}` (scope `read`) → Proposal with each fact's basis and sources
  - `PATCH /proposals/{id}` `{'expected_revision': int, 'edits': [...]}` (scope `interact`)
  - `POST /proposals/{id}/answers` `{'expected_revision': int, 'question_id': str, 'text': str}` (scope `interact`)
  - `GET /proposals/{id}/confirmation` (scope `read`) → the `confirmation(...)` dict
  - `POST /proposals/{id}/confirm` `{'proposal_digest': str, 'scope_digest': str}` (scope `approve`) → 201 `{'version': n}`
  - `GET /` and `GET /versions` (scope `read`)
  - Errors map `IntakeError` codes to 409 (`proposal_changed`, `scope_changed`, `adopt_first`), 413 (`too_large`), 415 (`unsupported_type`), 422 (`no_extractable_text`).

- [ ] **Step 1: Failing tests:** `test_full_profile_flow_over_http` (upload synthetic CV → proposal → edit → answer → confirmation → confirm with approve token → version 1 readable), `test_confirm_needs_approve_scope` (run-scope token → 403), `test_other_person_cannot_see_proposal` (404), `test_upload_size_and_type_limits`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `tests/test_profile_api.py tests/test_deepagents_runtime.py` → PASS.
- [ ] **Step 5: Commit** `feat: native API for profile intake and approval`.

### Task 8: Discovery starts on confirmation, within the shown scope and budget

**Files:**
- Modify: `pipeline/agentic/service.py` (`after_collect`), `jobwatch/cli.py` (`read` and `run` honour per-person scope; `--user all` documented), `systemd/*.service` (pass `--user all`)
- Test: `tests/test_agentic_service.py`

**Interfaces:**
- Consumes: `intake.current_version(person)` → `scope`.
- Produces: `after_collect` returns `{'skipped': 'no_confirmed_profile'}` for a person with no approved version; otherwise evaluates at most `scope.daily_assessments` jobs per local day and stops when that day's charged tokens (from `agentic_activity` / `Execution` usage) reach `scope.daily_token_ceiling`, reporting `{'deferred': 'daily_budget'}`.

- [ ] **Step 1: Failing tests:** `test_no_discovery_without_confirmed_profile`, `test_daily_assessment_cap_from_scope`, `test_daily_token_ceiling_defers_the_rest`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the agentic test files → PASS.
- [ ] **Step 5: Commit** `feat: confirmation starts evaluate-only discovery within scope and budget`.

### Task 9: Release check and workflow example

**Files:**
- Create: `docs/examples/profile-intake.md` (curl walk-through with synthetic data and real responses captured from the test client)
- Modify: `README.md` (profile workflow), `INTENT.md` only if the owner's words need recording

- [ ] **Step 1:** Run the full suite: `python -m pytest -q -p no:cacheprovider` → expect all pass; record the count.
- [ ] **Step 2:** Write the example from the Task 7 test transcript.
- [ ] **Step 3: Commit** `docs: profile intake workflow example`; push; open the PR with checks, limitations and undo (revert the merge; intake/ and profile-versions/ folders can be deleted; projected profile/ files are restored from the previous version dir).
