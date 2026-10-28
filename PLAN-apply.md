# jobwatch apply layer: plan (Paperclip BUI-81, 2026-10-06)

> **Status 2026-10-06:** built and live (W2). Commands and outcomes timers installed. Current status and backlog: `TRACK.md`.
> **Matrix removed 2026-10-06:** D1 (Matrix commands) and the Matrix approval batch no longer exist. The owner drives drafting, status and approvals from the web board (PLAN-web.md); `jobwatch draft <id>` still works from the shell.

Owner direction (2026-10-06): "do it?" on the R&D list (reviewer chain + verify_pdf; permissive sources; safe routes; mail outcome sync with approval batch; data contract + origin guard; provenance tiers).

## Status of the 5 R&D items
| # | Item | Where |
|---|---|---|
| 1 | ai-job-search reviewer chain, honest gaps, PDF text-layer check | Agent A: `jobwatch/apply/` |
| 2 | Permissive sources (ATS/RSS/JSON-LD) | **Done** in jobwatch wave 1–2. JobSpy and Seek are kept because the owner chose them. |
| 3 | Profile data on safe routes only | Agent A: a model allowlist enforced in code. Only `openai/`, `claude/` and `google/` OmniRoute combos are allowed. Free OpenRouter and CommandCode routes are refused. |
| 4 | Mail outcome sync, approval batch | Agent B: `jobwatch/outcomes/` |
| 5 | Data contract + origin guard + provenance tiers | Data contract: shared (below). Origin guard: Agent B (Matrix owner-only + room check; no HTTP server exists). Provenance tiers: Agent A. |

## Decisions (defaults; the owner can override)
- **D1 Trigger:** commands in the Matrix room "Job alerts", from `@acha:matrix.phroggingphrog.com` only.
  - `draft <id>`: start the chain. The command is the recorded "proceed" (fit-stop gate).
  - `applied <id>`, `skip <id>`, `status <id> <state>`.
  - `approve <n…>` / `reject <n…>`: decide outcome proposals.
  - `list`: open applications.
  - `help`.
  - Every alert line carries a short id `#<match_id>`.
  - Polled by `jobwatch-commands.timer` every 2 min via Matrix `/sync`, with the since-token kept in the `kv` table.
- **D2 Data contract (career-ops style):**
  - **User layer:** `~/brain/data/jobwatch/profile/` (cv.md, profile.yaml, evidence.yaml), mode 700. Code never writes there.
  - **System layer:** `~/brain/data/jobwatch/ledger/*.jsonl` (append-only, canonical) and `drafts/<application_id>/v<n>/`.
  - **SQLite:** a derived index. `jobwatch reindex` rebuilds it from the ledger.
- **D3 Profile:** seeded once from the archived `agent/candidate-profile/` (master_resume.md, profile.yaml, career_ops_profile.md, transferable_skills_taxonomy.yaml) into the user layer. Not printed or logged.
- **D4 Models:**
  - Drafter `openai/sol`. Reviewer `claude/claude-sonnet-*` (a different family, with fresh context). Reviser `openai/sol`.
  - All calls go through local OmniRoute (http://127.0.0.1:20128/v1). The key comes from `~/.config/llm-gateway/keys.env` and is never logged.
  - Allowlist `^(openai|claude|google)/`; anything else raises.
- **D5 Provenance tiers:**
  - **Candidate claims:** every claim in a draft cites an evidence id and a tier (`stated` = verbatim in profile/cv, `derived` = computed from stated facts, e.g. tenure). `inferred` claims are rejected by code. The verifier checks that each cited quote appears in the profile.
  - **Posting requirements:** `jd_quoted` (the verbatim quote is checked), `structural` or `inferred`. `inferred` is weight-capped and can never be a blocker (DB CHECK constraint + code).
- **D6 verify_pdf:**
  - pdftotext text layer → ≤2 pages (CV), garbage/ligature check, fact claims still present.
  - Keyword coverage table is advisory only: never stuffed, missing keywords listed as gaps.
  - On failure, the draft fails with reasons and nothing is posted.
- **D7 Delivery:** CV + cover letter PDFs uploaded to the "Job alerts" room (local homeserver), plus a summary: fit, honest gaps, reviewer edits, verify results. **jobwatch never sends anything to an employer.** The owner applies.
- **D8 Outcome sync:**
  - Every 2 h (07:00–22:00), search the owner's mailboxes **read-only** via Phrog-Assistant MCP (http://127.0.0.1:8913/mcp). Only messages from companies/ATS domains of applications in applied+ states, plus generic ATS senders, since the application date.
  - Classify: rules first, then a paid LLM for ambiguous mail, getting only subject + first 1,500 chars.
  - Post one approval batch to Matrix. Never infer `hired`; an offer becomes `offer` + flag. Idempotent by message-id. Nothing changes until `approve`.
- **D9 Callback stats:** approved outcomes feed a Beta-Binomial callback rate per arm (prior Beta(1,15)), shown in the weekly digest with a 95% HDI. This is the model the audit called sound.
- **D10 Origin guard:**
  - Commands: accept only the owner sender in the Job alerts room; others are logged `rejected_sender`.
  - No HTTP listener. If one is ever added, bind 127.0.0.1 and reject non-loopback Origin/Host (helper + test shipped now).

## Shared contracts (already in place, built by Claude)
- DB migration v2: `applications`, `application_events`, `drafts`, `requirements` (CHECK: inferred ≠ blocker), `commands`, `outcome_proposals` (CHECK: never 'hired').
- CLI hook: a module `jobwatch.apply.cli_ext` / `jobwatch.outcomes.cli_ext` / `jobwatch.commands_ext` exposing `register(subparsers)` and `handle(args) -> int|None` is picked up automatically.

## Ownership (parallel wave)
- **Agent A:** `jobwatch/apply/**`, `jobwatch/llm.py` (OmniRoute client + allowlist), `jobwatch/ledger.py`, `jobwatch/origin_guard.py`, the profile seeding script, tests under `tests/apply/`.
- **Agent B:** `jobwatch/commands_ext.py` (+ `jobwatch/commands/**`), `jobwatch/outcomes/**`, the alert-line `#id` change in `notify_matrix.py`, the digest callback section in `digest.py`, systemd `jobwatch-commands.*` and `jobwatch-outcomes.*` (written, not installed), tests under `tests/commands/` and `tests/outcomes/`.
  - B calls A's API: `jobwatch.apply.chain.start_draft(conn, match_id, actor_event) -> application_id` and `jobwatch.ledger.append(kind, record)`.
  - Until A lands, B uses a stub with that exact signature.

## Verify
- Full test suite green.
- One real end-to-end `draft` on a live match.
- An outcome dry-run over the owner's mail showing proposals without writing.
- Commands from a non-owner rejected.
- A free-route model refused.

## Undo
`git`-less. Remove `jobwatch/apply`, `jobwatch/outcomes`, `jobwatch/commands*`, `jobwatch/llm.py`, `jobwatch/ledger.py` and `jobwatch/origin_guard.py`. Restore `db.py`/`cli.py` from the scratchpad backups (`*.pre-apply`). Then `rm -rf ~/brain/data/jobwatch/{profile,ledger,drafts}` and disable the new timers.
