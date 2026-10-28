# Application and reader workflows

[Project overview](../README.md) · [Current intent](../INTENT.md)

Reference material moved from README; commands describe available source interfaces,
not proof of current service activation or end-to-end acceptance.

## Apply layer (B): outcome sync, callback stats

Design: `PLAN-apply.md` (D8, D9, D10). Shared application-state API:
`jobwatch/commands/state.py` and `apply_api.py`, with `jobwatch/outcomes/`.
Business CLI modules also live under `jobwatch/commands/` and register through the
`jobwatch` entry point; they are dispatch adapters, not another state store. The owner drives applications from the web board (save, hide,
draft, applied, status, approve, reject). The Matrix command handler (`draft`, `applied`, `list` ...)
was removed on 2026-10-06; `jobwatch draft <match_id>` still works from the shell.

### Outcome sync (`jobwatch outcomes [--dry-run [--show]]`)

- **Applications:** only those in `applied`/`assessment`/`interview`/`offer` with an `applied_at`.
- **Mail search:** through the local Phrog-Assistant MCP (`http://127.0.0.1:8913/mcp`).
  - Only `inbox_search`, `inbox_read_message` (never marks mail seen) and `inbox_list_mailboxes`
    can be called. Any other tool raises before a request is sent.
  - Mailboxes: gmail `[Gmail]/All Mail`, icloud `Inbox` and `Archive`.
  - Queries cover mail since `applied_at` minus 2 days from the company (full name, distinctive
    word, careers domain), plus common ATS senders.
- **Matching:** a message must name exactly one application's employer, domain or job title.
- **Classification:**
  - Rules come first (rejected > offer > interview > assessment > applied receipt).
  - Ambiguous mail goes to `jobwatch.llm` (`claude/haiku`, at most 10 calls a run). It gets the
    subject plus the first 1,500 chars only.
  - `hired` is never produced: it becomes `offer` with an `offer_review` flag. The DB also has a
    CHECK against it.
- **Stored per proposal:** subject (≤200 chars), sender domain only, message-id, and an evidence
  snippet (≤200 chars). Dedup is by message-id. Messages that are not outcomes are remembered in
  `state` (`outcomes:seen`).
- **Approval:**
  - Proposals wait in `outcome_proposals` (status `proposed`) for the web Inbox. Nothing changes until the owner approves.
  - Approve only moves an application forward. `rejected` always applies.
  - Proposals expire after 7 days.
- **Dry run:** `--dry-run` writes nothing, makes no LLM calls and posts nothing. It prints counts
  only; `--show` also prints the proposals, which contain mail subjects.
- **Overrides:** optional `outcomes:` keys in `jobwatch.yaml`: `mcp_url`, `mailboxes`,
  `ats_senders`, `expire_days`, `use_llm`, `llm_model`, `max_llm_calls`, `slack_days`.

### Callback stats (weekly digest)

- **Model:** Beta-Binomial per arm with prior Beta(1, 15).
- **Counts:** a success is an application that ever reached assessment, interview or offer;
  a trial is an application that was applied.
- **Output:** the digest shows the posterior mean and the 95% HDI. The HDI uses scipy when it is
  installed; otherwise it uses 200k numpy draws with a fixed seed. `n` is shown, and n < 10 is
  marked "small n".

Undo (B): `rm -rf jobwatch/outcomes tests/outcomes` and drop the two `callback` lines from `digest.py`.

## Apply layer (A): profile, ledger, draft chain (PLAN-apply.md)

```bash
.venv/bin/python scripts/seed_profile.py --src /path/to/approved-profile   # COPY to private runtime profile (700/600) + evidence.yaml
jobwatch profile-check                     # perms + evidence verbatim check (prints counts only)
jobwatch draft <match_id> [--actor-event SRC]   # run the chain; prints metrics + file paths, never profile text
jobwatch reindex [--dry-run]               # rebuild apply tables from the ledger
```

Extra dependencies (in `pyproject.toml` and the venv): `weasyprint`, `markdown`
(system Pango and poppler-utils `pdftotext`/`pdfinfo` are already on the host).

**Data contract.** `profile/` is the user layer: only `seed_profile.py` writes it; every other
write goes through `jobwatch.apply.paths.safe_write_*`, which raises `ProfileWriteError` under
`profile/` (symlinks and `..` resolved). `ledger/*.jsonl` (applications, drafts, outcomes,
commands) is append-only, flock + fsync, `"v": 1` on every line. `jobwatch.ledger.upsert(conn,
kind, table, values)` writes a DB row and logs the full row; `append(kind, record)` is a free log
line. `reindex` replays row records (last write wins per key) and refuses, changing nothing, if
the DB holds an apply-table row the ledger lacks.

**Evidence** (`profile/evidence.yaml`, deterministic, no LLM): items `{id, kind
(role|education|skill|achievement|cert), text, source_file, line, group?}`; `text` is a verbatim
span of `master_resume.md` (`cv.L<line>`), `profile.yaml` (`pf.<path>`) or
`transferable_skills_taxonomy.yaml` (`tx.<id>`). Contact details are never evidence.

**Models.** `jobwatch/llm.py` only talks to `http://127.0.0.1:20128/v1` and only accepts
`^(openai|claude|google)/` (openrouter, command-code, cmd/, cc/, antigravity, *-pxy, anything
"free" raise `ModelNotAllowed` before a request). Key: `keys.env` `OMNIROUTE_API_KEY`, then the
Pi `omni` key when the first is refused for a combo (the keys.env key is not allowed on
`openai/sol`). Requirements, drafter, reviser: `openai/sol`. Reviewer: `claude/claude-sonnet-5-5`.

**Chain** (`jobwatch.apply.chain.start_draft(conn, match_id, actor_event) -> application_id`):
1. Gate: match exists, posting seen in the last 30 days, application not skipped/withdrawn/
   rejected or already drafting. The command is recorded as the owner's proceed (event `command`).
2. Requirements (once per posting): `jd_quoted` quotes are checked verbatim (case/whitespace
   normalised), `structural` against the structured fields; failures become `inferred` (weight
   <= 0.3, never a blocker).
3. Drafter -> code verifier -> fresh-context reviewer (only the claim-tagged drafts + the posting
   + cited evidence) -> reviser -> verifier again. Claims are `stated` (key span in evidence and in
   the claim), `derived` (years_between/count, recomputed by code) or `framing` (letter only, no
   numbers, names from the posting/evidence). Numbers, years, months and names must come from
   evidence; failures are removed and listed. Role/education headings are printed from evidence.
4. Render: markdown -> HTML -> PDF with WeasyPrint (offline, deterministic, one renderer for CV
   and letter; ligatures off; font steps 10.5 -> 9 pt to fit). rendercv was not used: no PDF
   engine in its base install and no cover letter.
5. verify_pdf: CV <= 2 pages, letter <= 1, no ligature/cid/U+FFFD/control garbage, every claim key
   span and heading present in the `pdftotext` layer. Keyword coverage vs `jd_quoted` is advisory.
6. Files: `drafts/<application_id>/v<n>/{cv,letter}.{md,pdf}, claims.json, verify.json,
   review.json, requirements.json, summary.md, summary.json`.

`draft_status(conn, application_id)` returns `{status (draft: ready|failed|drafting|none),
application_status, version, summary (summary.md text), error, dir, files {cv_pdf, letter_pdf,
summary_md}, metrics}`. Undo: see PLAN-apply.md.

## AI ad reader (`jobwatch review`)

The keyword rules only give a first list. A model then **reads the whole ad** and decides (`reader.py`):

1. `adtext.py` gets the full ad text: the stored description if it is long, else one polite request to the ad's page
   (Seek, SmartRecruiters, LinkedIn, Jora, Careers.Vic, Oracle, JSON-LD pages). One request per ad, 3 s apart, stops on 403/429.
2. The model (`reader.model`, default `google/gemini-flash`, allowlisted routes only) returns: real vacancy or not, whether
   it needs Australian citizenship / PR (with the exact words), seniority, years asked, a 0-100 fit against
   `config/reader_profile.md` (plain English: edit it to change what you want) and the reason.
3. Plain code makes the decision (`reader.decide`): hide sponsored ads, talent pools, anything that needs citizenship / PR / a
   clearance (a claim only counts if its quote is really in the ad; a regex backstop catches plain statements; the title
   `APS4` counts), roles asking for 4+ years or senior, and fit under `min_fit_show`. An ad whose body could not be read is
   **held** (`review`), not shown.
4. Results go to `ad_reviews` (+ `ad_text`). Nothing in `postings`/`matches` changes, so every decision can be seen and undone.

`jobwatch review` reads ads not yet read; `review stats` counts verdicts; `review rederive` re-applies the hiding rules to the
stored model answers without a model call; `review recall` is **AI recall**: a cheap model judges the Melbourne postings the
keywords missed by meaning and adds plausible ones to `matches` (arm `ai_semantic`). The pipeline does both after each
collection when `reader.enabled: true` in `config/jobwatch.yaml`. Same ad + same prompt + same model = no new call.
