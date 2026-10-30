# Profile split design

## Goal

The live `profile/` directory is person input only. The system must not write derived files into it. Every verifier, assessment, confirmation, and shortlist reader must use the appropriate immutable version directory.

## Person input files

- Person CV files in `profile/` remain person-owned input.
- `profile/profile.yaml` remains person-owned input.
- `profile/evidence.yaml` remains person-owned input. Its annotations carry policy, including `Policy: part-time only.`
- The system reads these files but does not write, restore, or delete them.

## Derived files and locations

- All projections currently written into `profile/` move to the corresponding immutable profile version directory.
- The version directory is the sole location for derived profile projections and their verification metadata.
- The approved snapshot and its evidence annotations must be read from that same version directory by verification, assessment, confirmation, and shortlist code.
- No derived file is written to the live `profile/` directory.

Exact derived paths in each version are `profile-versions/<n>/profile.yaml` and `profile-versions/<n>/interests_and_criteria.yaml`. Keep the complete person evidence snapshot in `profile-versions/<n>/evidence/`, including `evidence.yaml` and the original person documents. `profile-versions/<n>/approved.json` remains version metadata. Do not project into or alter `profile/`.

## Structural change

Create one structural boundary between person input and derived profile versions. A projection is built from read-only person input into a version directory. Verification and all downstream gates consume that version, including its annotations and policy. They must not mix live inputs with derived output.

Keep versions isolated per person. Preserve existing approval and exact-input invalidation rules. Do not weaken annotation validation or drop policy from prompts.

## Failure reasons

Each gate reports its specific failure cause rather than collapsing failures into `no_confirmed_profile`. A `busy` failure names the lock owner.

## Current verification (supersedes historical next steps)

Task record: TASK-408. HEAD remains `a8eef4c`; the source changes below are uncommitted.

The preservation regression came from mixing source identity with projection names. Confirmation removed `master_resume.md` from adopted hashes. Scope validation compared `cv.md` with `master_resume.md`, although both synthetic sources existed with different contents. Preserve adopted hashes and compare each exact snapshot filename. Confirmation must also verify adopted `profile.yaml` edits. Re-adoption accepts repaired adopted inputs, but refuses unchanged adoption or adoption after an upload-generated version.

- Reproduction: `/tmp/profile-split-confirm-repro.log`, 2 failures (preservation and hand-edit detection).
- Final focused command: `timeout 180 env PYTHONPATH=. /home/phroggingphrog/apps/jobwatch-native/.venv/bin/python -m pytest tests/test_profile_confirm.py tests/candidate/test_intake.py tests/candidate/test_projection.py tests/candidate/test_rules.py -q`. Result: 135 passed in 53.95 seconds, `/tmp/profile-split-confirm-intake-round3.log`.
- Reader/gate command: same Python and environment, `timeout 180`, modules `tests/test_reader.py tests/test_reader_rules.py tests/test_ranking.py tests/occupations/test_discovery_workflow.py tests/test_profile_api.py`, plus `tests/test_fetch_loop.py::test_pipeline_gate_skips_every_tier_without_a_confirmed_profile`. Result: 767 passed, 3 failed in 54.84 seconds, `/tmp/profile-split-readers-gates-current.log`.
- No full-suite rerun, paid call, live profile change, push, merge, or deployment occurred. Three focused correction rounds are exhausted. Remaining source needs review before a verified milestone commit.

### Same-base classification

Comparison base: `152fc29224b9bd098ccf2731f991d2b29689c9a7`, unchanged checkout `/tmp/jobwatch-clean-main`. Baseline logs: `/tmp/profile-split-baseline-*.log`. Compare with historical `/tmp/jobwatch-profile-split-pytest.log`; historical branch results are not final verification.

| Historical failure group | Clean-base evidence | Current branch evidence |
| --- | --- | --- |
| 4 profile-confirm failures | 12 passed; confirmed regressions | All 12 now pass; original repeated-adoption CLI assertion restored |
| 3 projection failures | Same 3 failed, 4 passed | Complete projection module passes |
| 2 rules failures | 8 passed; recovery regression repaired in `a8eef4c` | Complete rules module passes |
| Parse failure preserves answers | Passed in isolation | Complete intake module passes; original broad-run failure not reproduced |
| Crash recovery | 4 baseline parameter failures; old hook differs from current hook | Complete intake module passes; boundary coverage still needs review |
| 7 reader/ranking failures | Same exact 7 failures, 737 passed | Reader, reader-rules and ranking modules now pass in combined batch |
| Occupation workflow | Failed on base | Still fails: confirmation copies a nonexistent live profile directory |
| Profile API code mapping | Failed on base | Still fails: public status mapping lacks intake codes |
| Pipeline profile gate | Failed on base | Still fails: stale assertion expects generic reason instead of `no_profile_version`, and omits `text_only` |
| HTTP 403/429/502 and pacing | Same 4 failed on base | Not rerun or modified |

Remaining action: review the missing-directory confirmation path and public mappings, without weakening exact-input or specific-reason checks. Verify snapshot policy and reader failure behavior explicitly. Do not claim the entire change is ready from these focused results.

## Historical progress

- Milestone 1: Design recorded before implementation. Source review found that `confirm()` writes projections to `profile/` and can omit stale annotations from the version snapshot. Candidate readers also load the live directory. `jobwatch` remains unavailable for task tracking (`command not found`).
- Milestone 2: Confirmation now writes projections at the version root and stores evidence inputs separately. Focused tests exposed one shared cause across 3 corrections: source files, projections, and verification hashes were treated as one directory. The structural boundary now separates live input, immutable evidence, version projections, and live-input integrity checks. The reader and location paths now use approved version data. The full suite ran and reported 25 failures, 4,461 passes, and 2 skips. Focused profile suites still need fixes and a clean rerun. Failures include test contracts that need updates and existing external-fetch failures. No commit, push, or PR exists yet.
- Shared cause after 3 further fixes: input paths, projected outputs, evidence snapshots, and adoption recovery use inconsistent file roles. This caused repeated regressions in profile verification and retry behavior. I separated those roles and restored retry checks. The focused intake suite passes most tests, but rule-amendment recovery still fails. The source-preservation test also needs review. File-role tests verify input, evidence, and version projections separately.
- Recovery milestone: the original test patched `_write_profile`, but `rules.confirm()` publishes a staged version through `intake._write_private` and `os.rename`. The retry returned version 3 after version 2 was published. I moved crash injection to `os.rename`, after atomic publication. The recovery test passed, and `tests/candidate/test_rules.py` passed 8 tests. Commit `a8eef4c` records this milestone. The amendment digest and publication state are in staged `approved.json` before rename. Retry reuses the published version. I did not restore live profile writes.
- OpenSpec change: `openspec/changes/profile-input-isolation/`. Its artifacts specify source isolation, evidence and policy retention, idempotent recovery, adoption scope, approved-version readers, and specific gate reasons.
- The full-suite log reports 25 failures, 4,461 passes, and 2 skips. It does not establish which failures are baseline. A profile-focused batch after the recovery commit still failed `test_confirm_never_rewrites_the_resume_or_drops_evidence`. Later attempts did not fix it.
- Next: run the listed tests in clean checkout base `152fc29224b9bd098ccf2731f991d2b29689c9a7`. Classify failures as baseline or regressions. Then fix the smallest profile isolation failure and verify its focused tests.
- Next: fix the remaining profile-related regressions in focused batches. Compare failures with the same base commit in a clean worktree. Keep baseline failures separate. Do not run a full suite until the focused regression groups pass.
