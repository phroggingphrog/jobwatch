# Bringing Jobwatch up as a running service

A staged first run for one server, with a gate at each step. The component reference is
in [README.md](../README.md) (install, settings, timers) and the account setup in
[SETUP.md](../SETUP.md); this document is the order to do them in, and what to check
before continuing.

Written against the source merged in `e5541d8`. The commands are the ones that exist in
that tree.

## What is and is not established before the first run

The local suite passes on the merged source: 3831 passed, 2 skipped (the two skips are
the R/JAGS sampler cases, which need R and `JOBWATCH_TEST_R=1`). The safety boundaries
hold under test: nothing submits outside `jobwatch/apply/submit_confirm.py`, people and
their data stay isolated, approvals bind to exact inputs, and candidate text stays out
of hosted tracing.

That is source correctness against invented fixtures and a synthetic gateway. It is not
evidence of a working deployment, and the backend releases stopped deliberately short of
one: no service or timer has been activated by them, and no real model call has gone
through this backend. Per [AGENTS.md](../AGENTS.md), a merge does not establish a
deployed backend. Recommendation quality is a separate claim again, and is still
unmeasured — see Stage 8.

Each stage below has a **Gate**. Do not start the next stage until it passes. Nothing is
enabled at boot until Stage 7.

## Stage 0 — back up, and record where the data is

```bash
systemctl --user stop 'jobwatch-*' 2>/dev/null; systemctl --user list-timers 'jobwatch-*'
cp -a ~/.local/share/jobwatch ~/jobwatch-backup-$(date +%F)     # or your JOBWATCH_DATA_DIR
sqlite3 ~/.local/share/jobwatch/jobwatch.db 'PRAGMA user_version; PRAGMA integrity_check;'
```

**Gate:** a backup exists outside the data directory, `integrity_check` reports `ok`, and
the `user_version` is written down. There are 16 migrations, so 16 means fully migrated.
A lower number means the next `db.connect` migrates, and v12 backfills
`postings.expires_at` for every row that has none — a data write, not only schema. Choose
that rather than discover it.

## Stage 1 — install the code where the units expect it

The units hard-code `%h/apps/jobwatch` and `%h/apps/jobwatch/.venv/bin/...`
(`deploy/jobwatch-agent.service`, `systemd/jobwatch-web.service`, the five timers), so
put the checkout there or edit every unit.

```bash
cd ~/apps/jobwatch && git fetch origin main && git checkout main
uv sync --frozen --extra browser          # add --extra mcp only if the MCP adapter is wanted
uv run --no-sync python -m playwright install --with-deps chromium
```

**Gate:** `uv run --no-sync jobwatch --help` works, and
`uv run --no-sync python -m pytest -q tests/test_agentic_service.py` passes on this
machine. Resolve missing system libraries here (weasyprint asks for HarfBuzz-Subset)
rather than during a later stage.

## Stage 2 — settings and credentials

`~/.config/jobwatch/settings.env`, from `.env.example`: `JOBWATCH_DATA_DIR`,
`JOBWATCH_SESSION_SECRET`, `JOBWATCH_OWNER_PASSWORD`, and the gateway
(`JOBWATCH_LLM_BASE_URL`, `JOBWATCH_LLM_API_KEY`, `JOBWATCH_LLM_MODEL`). The configured
gateway must be the approved paid route: generic external-provider fallbacks and
free/stealth helper selections fail closed, so a wrong base URL presents as a broken
agent rather than as a refusal.

`~/.config/jobwatch/agent.env`, mode 0600, read by `deploy/jobwatch-agent.service`:

```
JOBWATCH_AGENT_TOKEN=<32+ random characters>        # read/run scope
JOBWATCH_AGENT_APPROVAL_TOKEN=<a different 32+>     # read/interact/approve scope
JOBWATCH_AGENT_PERSON=<the Jobwatch person>
```

The two secrets must differ; equal values are refused. **The client a person types into
needs the approval token.** Recording a profile fact is a gated operation, so a client
holding only the run token fails onboarding with `approval_scope_required`. Keep the run
token where model tools run and the approval token only in the trusted client, as
[CHAT.md](../pipeline/agentic/CHAT.md) describes.

```bash
cd ~/apps/jobwatch
uv run --no-sync jobwatch check --code
uv run --no-sync jobwatch --user <person> init-db
```

`--user` is removed from the arguments before parsing (`jobwatch/cli.py:61`), so it comes
**before** the subcommand; `--user all` loops over every person, and omitting it acts as
the default person in a different data directory.

**Gate:** `check --code` is clean and `init-db` reports the schema without errors.

## Stage 3 — the agent API by hand, in the foreground

```bash
cd ~/apps/jobwatch
set -a && . ~/.config/jobwatch/agent.env && set +a
uv run --no-sync jobwatch-agent --host 127.0.0.1 --port 8914
```

From a second shell, with `$RUN` holding the run token:

```bash
curl -fsS localhost:8914/health
curl -fsS -H "Authorization: Bearer $RUN" localhost:8914/api/agent/capabilities
TID=$(curl -fsS -X POST -H "Authorization: Bearer $RUN" \
      localhost:8914/api/agent/threads | jq -r .thread_id)
curl -fsS -X POST -H "Authorization: Bearer $RUN" -H 'Idempotency-Key: first-1' \
     -H 'Content-Type: application/json' -d '{"message":"What can you do?"}' \
     localhost:8914/api/agent/threads/$TID/runs
```

Then poll `GET /api/agent/runs/{id}` and read `/api/agent/runs/{id}/events`.

**Gate:** a run reaches `completed` with a real answer. This is the first real model call
through this backend, so the gateway, the model id and the credential index are where to
expect a failure. Only a loopback bind is accepted: `--host 0.0.0.0` exits without
serving, by design.

## Stage 4 — onboarding, through the approval-scoped client

Drive onboarding from the client holding the **approval** token: `profile_start` with a
CV, then answer the questions the agent asks. Every recorded answer or correction raises
an approval interaction, answered through
`POST /api/agent/interactions/{id}/responses`, before `profile_confirm`.

**Gate:** `profile.yaml` and `approved.json` exist for that person, the recorded facts
are the person's own words, and `uv run --no-sync jobwatch --user <person> profile-check`
is clean (that subcommand lives in `jobwatch/apply/cli_ext.py` and reports counts only;
it never prints evidence).

Two behaviours to expect, both recent: an approval round trip per recorded fact, and
`not_person_words` when the agent quotes a fragment of a sentence instead of the clause —
quoting the whole clause records it. A span lifted out of a clause the person negated is
refused on purpose, so "a citizen" is never recorded from "I am not a citizen".

## Stage 5 — one manual collection and reader pass

```bash
cd ~/apps/jobwatch
uv run --no-sync jobwatch --user <person> run --tier fast
uv run --no-sync jobwatch --user <person> read
uv run --no-sync jobwatch health
```

Discovery runs only for a person whose current profile version is confirmed with its
search scope, so Stage 4 comes first; before that, these commands correctly do nothing.

**Gate:** postings arrive, the reader judges some, `health` lists the expected
collectors, and the shortlist entries carry reasons that hold up to reading. Keep the
first run small and watch the spend against `job_token_ceiling`.

## Stage 6 — one supervised assessment and one preparation

Assess a single posting, approve it, prepare materials for one job, and read the package:
open the CV and the letter.

**Gate:** the package is `READY` with citations traceable to that person's own approved
evidence, and nothing was submitted. Submission stays on the owner's confirmed-Submit
path: their own click on the employer's button, or their confirmation of that exact
reviewed fill, which expires after 15 minutes.

## Stage 7 — install the units, one at a time

```bash
mkdir -p ~/.config/systemd/user
cp deploy/jobwatch-agent.service systemd/jobwatch-*.service systemd/jobwatch-*.timer \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jobwatch-agent.service
```

Enable in this order, reading `journalctl --user -u <unit> -n 50` after each before
adding the next: `jobwatch-agent` → `jobwatch-web` → `jobwatch-reader.timer` (15 min) →
`jobwatch-fast.timer` (20 min) → `jobwatch-slow.timer` (2 h) → `jobwatch-outcomes.timer`
→ `jobwatch-digest.timer` (weekly). The timers run `--user all`, so every confirmed
person is collected for.

Both services bind loopback, and the agent API refuses anything else, so remote access
goes through the existing reverse proxy over HTTPS. There is no CORS configuration and no
interactive OAuth enrollment: the client stays a configured, trusted one.

**Gate:** two consecutive firings of each enabled timer with no failed units, no
unexpected spend, and new postings appearing on the board.

## Stage 8 — start measuring quality

Quality metrics need ten applicable owner labels per measure, and a new installation has
none, so every quality number correctly reports `missing_labels` until labelling starts.
Freeze a baseline and begin:

```bash
cd ~/apps/jobwatch
uv run --no-sync jobwatch --user <person> evaluate cases --limit 500
uv run --no-sync jobwatch --user <person> evaluate cases --list
uv run --no-sync jobwatch --user <person> evaluate split <baseline-id>
uv run --no-sync jobwatch --user <person> evaluate replay <baseline-id> --limit 500 --seconds 300
uv run --no-sync jobwatch --user <person> evaluate monitor <baseline-id> --limit 500 --seconds 300
uv run --no-sync jobwatch --user <person> evaluate report <baseline-id> <result-id>
```

`evaluate` also takes `label`, for recording a genuine terminal human judgment, and
`run`. Default replay makes no model calls and writes only private evaluation
artifacts. Monitoring is capped at 500 cases and 300 seconds and never reads the label
log. The blind comparison that would turn these diagnostics into a quality claim is
tracked in GitHub #6 and remains open.

## Stop conditions

Stop and report rather than working around any of these:

- The gateway refuses, or the credential index is wrong. A fallback would send candidate
  data to an unapproved route.
- `not_person_words` or `approval_inputs_changed` on something that was approved: either
  a guard is wrong or the draft moved underneath it. Diagnose it; do not retry in a loop.
- A package cites evidence that cannot be traced, or an eligibility verdict looks
  manufactured.
- A timer fails twice, or spend outruns `job_token_ceiling`.
- Anything at all reaches an employer.

## Rollback

`systemctl --user disable --now 'jobwatch-*'` makes the system inert again: the units are
the only thing that runs it unattended. A source rollback is a reviewed revert plus
`uv sync --frozen`; it does not undo data. Keep approved profile versions, feedback,
prompts, genuine choices, fits, selections, results, packages, baselines, human labels,
splits, audit logs and evaluation reports. Do not delete histories or downgrade schema
metadata by hand. Evaluation results and reports written under `METRICS_VERSION` v2 keep
their content-addressed ids and stay readable, but compare like-for-like only within v2.
There is no automatic data rollback, which is why Stage 0 is a backup.

## One boundary to be explicit about

If the optional MCP adapter is installed, the connected MCP host is the human-approval
boundary on that path: it has a single bearer token with no scope separation, and an
accepted elicitation becomes the person's approval, including for `submit_application`.
The native HTTP API is the path with a separate approve-scoped credential. See the MCP
section of [CHAT.md](../pipeline/agentic/CHAT.md).
