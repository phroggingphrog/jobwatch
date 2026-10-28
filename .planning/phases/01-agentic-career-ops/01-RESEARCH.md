# Phase 01 implementation research

Base: 72fe424be63f241d913aad8508815ede716baea8. Design approved by Staff in BUI-209 (design only). No external model/network calls or live data reads/writes performed.

## Observed integration seams
- `jobwatch/llm.py`: paid-route allowlist, loopback-only endpoint and injectable transport already exist. `chat` returns parsed JSON and usage but malformed JSON loses usage; credential retries are internal and not exposed to a caller's attempt counter. Extend with optional bounded-call hooks without changing legacy behavior. Never log remote error bodies on agentic calls.
- `pipeline/graph.py`: owns stages and retries, but its `_retry` multiplies nested attempts. Its `posting_ids` currently restricts ingest, not resumed queue selection. Agentic execution must restrict actual work to the approved snapshot and share one budget across all nodes and retries.
- `pipeline/store.py`: `move` checks stage by SELECT then updates only by posting ID. This is not a lease or atomic compare-and-swap. Add fenced claims and conditional transactional commit; do not rely on the docstring's duplicate prevention claim.
- `pipeline/nodes/gate.py`: legacy arithmetic threshold is 3.8; rights quote checks exist, location is absent. Agentic admission needs a separate 4.0 holistic adapter and explicit location/hours/program/sponsorship checks. Legacy outputs remain unchanged.
- `jobwatch/apply/chain.py`: rendering, evidence verification and PDF checks can be reused. `start_draft` records an owner command even for pipeline calls, allocates a new version every call and its revised output is not freshly approved. Do not call it unchanged for agentic persistence.
- `jobwatch/ledger.py`: fsynced append before SQLite commit provides recovery material but not a transaction across ledger, filesystem and DB. Use stable operation IDs and a staged package manifest plus fenced finalization; replay existing canonical records instead of appending duplicate logical operations. Reconciliation must be scoped to the operation, not global reindex of unrelated jobs.
- `pipeline/nodes/form_map.py`: answers file is read-only; missing values already marked owner_to_answer. Current screening accepts a model assertion of evidence; agentic screening must validate exact evidence references and share budget.
- Web query/templates and private draft directories provide existing surfaces. Add explicit progress/held/review states, not a second board.
- Python >=3.12,<3.13; Pydantic, requests, pytest, WeasyPrint already installed dependencies. This worktree has no .venv; existing interpreter is `/home/phroggingphrog/apps/jobwatch/.venv/bin/python`. Run it from this worktree with `PYTHONPATH=$PWD`, never against production DB/profile. No dependency additions planned.

## Research capability decision
Repository inspection found no employer search client/configuration (only collector search and inbox search, which is not suitable). Connection-discovery tools and work-memory tools are not exposed in this run. Therefore installed external search access is **unverified**, not claimed ready. Do not inspect secrets or invent a search endpoint. Implement an injected search protocol with explicit unavailable result by default; support bounded public-page retrieval using existing requests/stdlib with DNS pinning and redirect checks. Before enabling any actual search provider, Release must discover an installed connection through the connection tools; absence is reported as research unavailable and does not block otherwise supported evaluation. No subscription or serious outside library comparison is needed: approved architecture reuses local code and dependencies. Feynman delegation not needed for this internal seam audit.

## Locked safety mechanisms
JD-only phase has no candidate-reading capability. Accept immutable requirement importance before introducing evidence. Public research calls accept only enumerated intents and result IDs, never arbitrary model query/URL strings after candidate context is available. Construct queries from a separate public employer/title snapshot; candidate text cannot populate that snapshot. URLs come only from the captured posting or public search results. Reject credentials, non-http(s), private/non-global addresses (IPv4 and IPv6), mixed DNS results, unsafe redirects and DNS rebinding; pin validated resolution for connection while retaining TLS hostname validation. Treat page text as untrusted data, never capability grants.

All local candidate files are confined to the approved read-only profile root (resolve symlinks; reject traversal), and citations refer to content hashes plus exact quotes. Resume identity includes full ad, all consumed evidence bytes, answers content when used, rubric and relevant configuration versions. Never persist candidate content in git, comments, attachments or logs.

## Source coverage audit
- GOAL/CONTEXT evaluation, two-pass importance, owner targets, holistic scoring: 01 and 04.
- GOAL/CONTEXT paid routes, bounded genuine tool choice, budgets, safe research: 02 and 04.
- CONTEXT leased resume, CAS, ledger/file reconciliation: 03 and 06.
- GOAL/CONTEXT tailored CV+letter, independent review, verify_pdf, honest form map: 05 and 06.
- CONTEXT default-off graph integration, backlog re-evaluation, explicit snapshot restriction: 06.
- GOAL/CONTEXT visible progress, fit/gaps/provenance and unknown answers: 07.
- GOAL full suite, board walkthrough, >=20 real READY packages, TRACK/todo/WHAT-HAPPENED and undo: 08 plus QA/Release/live-acceptance issue chain in DELIVERY.md.
- RESEARCH design-review adversarial recommendations: 02 (exfiltration/SSRF), 03 (stale leases/crashes), 04 (gates/content hashes), 06 (resume), 08 (cross-layer tests).
- No REQUIREMENTS.md exists; contract + context + approved design are requirement sources. T19 form typing remains independently owned and unbuilt here; contract is unchanged, not represented as fully satisfied by this phase.
