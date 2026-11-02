# Tasks

## 1. Establish clean baseline and map regressions

- [x] 1.1 Run mapped tests at base `152fc29224b9bd098ccf2731f991d2b29689c9a7` in `/tmp/jobwatch-clean-main`; record each outcome in `/tmp/profile-split-baseline-*.log` without changing the checkout.
- [x] 1.2 Compare the base outcomes with branch results and label each known failure as baseline or regression in `docs/profile-split.md`; verify the failure list against `/tmp/jobwatch-profile-split-pytest.log`.

## 2. Keep person inputs separate from generated projections

- [x] 2.1 Define source and projection file roles for adoption, confirmation, and later versions; add or update focused tests for unchanged live input, projection paths, original resume preservation, and crash recovery; run `tests/candidate/test_intake.py` and `tests/candidate/test_projection.py`.
- [x] 2.2 Preserve evidence annotations and policy, including `Policy: part-time only.`; add focused evidence and reader tests that check policy retention and invalid annotation handling; run the affected candidate evidence and projection tests.
- [x] 2.3 Make adoption followed by confirmation preserve the source identity and valid discovery scope; test `test_adopt_then_confirm_opens_discovery`, `test_adopting_again_records_the_next_version`, `test_a_hand_edit_reports_itself_rather_than_looking_unconfirmed`, and `test_confirm_never_rewrites_the_resume_or_drops_evidence`. Evidence: `/tmp/profile-split-confirm-intake-round3.log`, 135 passed across confirmation, intake, projection, and rules.

## 3. Make amendment publication and recovery idempotent

- [x] 3.1 Store the exact amendment identity in the staged approval before atomic publication; inject a crash after directory rename; verify `tests/candidate/test_rules.py::test_confirmation_recovers_projection_without_minting_another_version` and all of `tests/candidate/test_rules.py`. Result: 1 focused test passed; rules suite passed 8 tests; commit `a8eef4c`.
- [x] 3.2 Verify active rule carry-forward and retry after each publication boundary; test `test_active_rules_survive_later_full_profile_confirmation`, the recovery test, and the complete rules suite. Do not write to live profile input.

## 4. Route readers and gates through the approved version

- [x] 4.1 Bind profile, evidence, policy, digest, shortlist, and rendering readers to the server-bound person's approved version; run the affected reader, ranking, occupation workflow, and policy tests, including all reader-fence and canonical quote tests.
- [x] 4.2 Map every intake and profile-gate refusal to its specific public reason; verify `tests/test_profile_api.py::test_every_intake_code_has_a_mapping` and `tests/test_fetch_loop.py::test_pipeline_gate_skips_every_tier_without_a_confirmed_profile` without weakening refusal behavior.

## 5. Resolve remaining profile regressions

- [x] 5.1 Fix parse-slot cleanup while preserving person answers after parser failure; verify `tests/candidate/test_intake.py::test_parse_failure_keeps_answers` and neighboring inflight tests. Evidence: complete intake module passed in `/tmp/profile-split-confirm-intake-round3.log`. The original isolated failure was not reproduced on clean base.
- [x] 5.2 Fix `tests/occupations/test_discovery_workflow.py::test_confirm_refresh_and_read_native_fields_and_plan` and all profile-related focused failures that the clean baseline marks as branch regressions; record the command and results in `docs/profile-split.md`.
- [x] 5.3 Do not change unrelated external-fetch tests unless clean-baseline comparison proves this branch caused them; record baseline outcomes for the 403, 429, 502, and fetch-loop pacing failures.

## 6. Integration verification

- [x] 6.1 Run focused profile, reader, gate, and workflow batches with bounded commands; retain logs and exact pass/fail summaries in `docs/profile-split.md`.
- [x] 6.2 After focused regression groups pass, run the complete suite in bounded batches and record every batch result. Do not report unrun tests as passing. Release verification attempted all 27 batches. Batches 12 and 13 reached 240-second limits. Remaining batches have recorded summaries. TASK-408 and docs/profile-split.md separate repaired fixture failures, current-main failures, and incomplete coverage.

## Integrated verification

Integrated `origin/main` at `575683f` in merge `00e6658`. Final focused batch: 1232 passed in 121.70s, `/tmp/profile-integrated-all-focused-final.log`. It covers all candidate tests, profile confirmation, reader, reader-rules, ranking, occupation workflow, profile API and strict pipeline gate. The latest rule-publication edit has separate evidence: 20 rules/boundary passed and 8 rules passed after import cleanup. Reader/ranking rerun: 744 passed. Preserved original group: 135 passed. Clean current main: 36 failed, 1182 passed, `/tmp/profile-current-main-baseline.log`. This implementation checkpoint had no full-suite result. The later release verification below supersedes this checkpoint.

## Independent release verification

Release integration preserves current main `486d8f2` and implementation `ac113b2`. Runtime safety fixes are at `8b2db12`. The integrated focused suite passed 1,239 tests. Stable web/gate/reader tests passed 147. Final approved web fixture tests passed 29. Drift checks passed 3. Discovery settings and limits passed 27.

The initial full-suite collection contained 4,496 tests. All 27 bounded batches ran. Completed summaries reported 4,162 passed, 23 failed, and 2 skipped before repairs. Batches 12 and 13 reached time limits without complete node coverage. The 23 failures comprise 4 unchanged current-main fetch failures and 19 synthetic fixture failures. Focused reruns passed the repaired fixtures. A later collection contained 4,508 tests. No complete final-source suite pass is claimed.

See TASK-408 and docs/profile-split.md for every batch result, baseline logs, residual checks, and deployment limitations.
