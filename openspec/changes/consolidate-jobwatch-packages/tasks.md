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
The original implementation tasks below remain open; no full-suite or release
claim is implied by this documentation-only reconciliation.

## 1. Audit and remove superseded UI directions

- [x] 1.1 Establish the full-suite baseline and trace imports, routes, static assets, resource URIs and packaging references for GenUI/MCP App cards; verify findings against the latest INTENT.md direction and current LibreChat/native Artifacts call sites.
- [x] 1.2 Remove only superseded code and corresponding obsolete tests, retaining current-client dependencies; verify with focused tests and a review showing approval/submit-confirmation logic unchanged.
- [x] 1.3 Run the full test suite, investigate failures and commit only this step; verify the commit diff excludes unrelated working-tree edits.

## 2. Consolidate domain and utility packages

- [ ] 2.1 Move interview, follow-up, Google integration and utility modules into their domain packages; update imports, dynamic references, scripts and tests; verify old-path searches and import smoke tests.
- [ ] 2.2 Run the full test suite and commit this step separately; verify rename-aware diffs preserve behavior and leave approval/submit-confirmation logic untouched.

## 3. Resolve collection orchestrator naming

- [ ] 3.1 Rename jobwatch/pipeline.py to jobwatch/run.py and update all importers and references; verify no old collection-module references remain and collection CLI smoke tests pass.
- [ ] 3.2 Run the full test suite and commit this step separately; verify only orchestrator naming changes are staged.

## 4. Unify business CLI entry points

- [ ] 4.1 Trace existing CLI invocation contracts and deployment callers, then move implementations under jobwatch/commands/ with common dispatch; retain documented thin wrappers only where required; verify help, argument parsing and deployment command compatibility with synthetic fixtures.
- [ ] 4.2 Run the full test suite and commit this step separately; verify native API transport entry points and human approval/submission behavior remain unchanged.

## 5. Split README topics

- [ ] 5.1 Move existing README topic content into docs/ and leave a short linked overview; verify content preservation and relative links, including links affected by module moves.
- [ ] 5.2 Run the full test suite and commit this step separately; verify the five ordered cleanup commits, clean cleanup-owned paths, and unchanged approval/submit-confirmation logic.

## Workflow follow-up

- Report each commit and its test result, remaining verification gaps, no deployment, and rollback by reverting cleanup commits in reverse order.
