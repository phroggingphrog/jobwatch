## 1. Reproduce
- [x] 1.1 Reproduce source-bound paraphrase refusal and premature improving-correction exhaustion using existing synthetic seams.
## 2. Human provenance
- [x] 2.1 Implement source-bound draft updates, bounded source recovery guidance and persisted origin without changing approved facts or final human approval.
## 3. Assessment recovery
- [x] 3.1 Implement and verify persisted progress-aware correction with repeated/churning failure bounds and unchanged budgets.
## 4. Integration
- [x] 4.1 Run affected provenance, approval, native recovery and completion checks; review the diff and record exact outcome/undo on TASK-424 while remaining offline.

## Verification

- Source-bound paraphrase reproduction: 2 failed before the repair. Third improving assessment correction also failed before the repair.
- Final source references/negation/earlier/resumed/cross-thread/attachment-only/same-turn recovery: 9 passed in 15.85s.
- Native recovery/completion/autonomous graph group: 57 passed in 38.53s. This includes the actual-native raw JSON unrelated-churn regression found in review (before repair: 5 requests; after: bounded at 3).
- Existing profile correction, final approval, changed-draft and human-question behavior: 18 passed in 68.05s.
- Broader intake/profile-confirm/recovery run: 184 passed, one test setup failed because a bare blank request is invalid. The test was corrected to use a valid attachment-only turn; the final 9-case source group includes it and passes. No application change was made to permit invalid blank requests.
- Strict OpenSpec validation, compileall and whitespace checks passed. Review found no remaining blocker in the scoped corrections.

These are synthetic local checks, not a release suite or live provider acceptance.
The prior 32 release failures are not claimed repaired. No dependency/framework
change, configuration edit, service/timer activation, paid call, real notification
or application submission was performed. The approved owner profile was untouched.

Undo by reverting this change's source commit. No runtime data/config rollback
is needed. Keep Jobwatch offline while broader release decisions remain held.
