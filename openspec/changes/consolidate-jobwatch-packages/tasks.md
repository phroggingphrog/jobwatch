## Current execution boundary (2026-10-28)

The owner first approved the cleanup-first documentation deliverable, then
explicitly directed execution through completion of the cleanup plan. The current
scope includes the package moves, CLI consolidation, collection-module rename,
UI-removal reconciliation and local verification below. Deployment, paid candidate
experiments and employer actions remain excluded. Existing uncommitted UI removals
must be reconciled rather than overwritten; documenting them is not proof that
their tests passed. Focused checks belong to each implementation scope; run the
full reconciled suite once after the writers finish, not after every move.

- [x] Preserve the previous INTENT.md verbatim in a linked historical record and
  replace its supersession chain with a current normative product contract.
- [x] Trace and document collection dispatch, shared state, agentic/domain
  ownership, removed embedded UI and retained compatibility paths; distinguish
  static findings from runtime and acceptance gaps.

Evidence: `INTENT.md`, `docs/adr/0011-owner-direction-history.md`,
`docs/agents/architecture-inventory.md` and its link from `docs/agents/domain.md`.
## Source reconciliation (2026-11-08)

`main` at `0ea4fe0` already contains `jobwatch/interview/`, `jobwatch/followup/`,
`jobwatch/google/`, `jobwatch/util/`, `jobwatch/run.py`, business implementations
under `jobwatch/commands/`, dispatch from `jobwatch/cli.py`, and a linked README
topic split. Do not repeat these moves. The remaining unchecked tasks below are
verification gaps, not claims that these source changes are absent. Static file
and dispatch inspection does not establish complete compatibility, historical
commit scope, passing tests or runtime deployment. No application tests were run
for this documentation reconciliation.

## 1. Audit and remove superseded UI directions

- [x] 1.1 Establish the full-suite baseline and trace imports, routes, static assets, resource URIs and packaging references for GenUI/MCP App cards; verify findings against the latest INTENT.md direction and current LibreChat/native Artifacts call sites.
- [x] 1.2 Remove only superseded code and corresponding obsolete tests, retaining current-client dependencies; verify with focused tests and a review showing approval/submit-confirmation logic unchanged.
- [x] 1.3 Run the full test suite, investigate failures and commit only this step; verify the commit diff excludes unrelated working-tree edits.

## 2. Consolidate domain and utility packages

- [ ] 2.1 Verify the domain/utility package moves already present in main: check imports, dynamic references, scripts, tests and synthetic import smoke checks; repair only demonstrated gaps through a separately authorized implementation change.
- [ ] 2.2 Recover or record focused verification and rename-aware review evidence for the landed moves, including unchanged approval/submit-confirmation behavior. Do not require recreating historical commits or a full suite per move.

## 3. Resolve collection orchestrator naming

- [ ] 3.1 Verify the existing `jobwatch/run.py` collection orchestrator and updated dispatch; distinguish obsolete collection-module references from the retained top-level agentic `pipeline/` package, and record synthetic CLI/import checks.
- [ ] 3.2 Recover or record review evidence for the landed naming change, without repeating the rename or claiming a fresh full-suite result.

## 4. Unify business CLI entry points

- [ ] 4.1 Verify the existing `jobwatch/commands/` implementations and common dispatch against actual invocation contracts and deployment callers; check retained wrappers, help and argument semantics with synthetic fixtures rather than moving already consolidated code again.
- [ ] 4.2 Recover or record focused CLI compatibility and review evidence, including retained native API transport entry points and unchanged human approval/submission behavior.

## 5. Split README topics

- [ ] 5.1 Verify content preservation and working relative links for the existing README overview and `docs/` topic files, including links affected by module moves. Do not repeat the split.
- [ ] 5.2 Reconcile the final source and required local evidence. Documentation-only reconciliation needs no application suite; reserve a full reconciled suite for release. Historical five-commit ordering is not a prerequisite to recognizing landed source, and does not prove approval/submit-confirmation behavior or deployment.

## Workflow follow-up

- Report each commit and its test result, remaining verification gaps, no deployment, and rollback by reverting cleanup commits in reverse order.
