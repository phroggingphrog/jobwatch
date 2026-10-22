# Jobwatch

A self-hosted job-application assistant. It collects job postings from many sources, filters them against what you
are looking for, has an AI model read each ad against your own profile, and drafts a tailored CV and cover letter
for the jobs you choose. It never applies on its own: you review the filled form and either press Submit yourself
or confirm that exact form and let Jobwatch press it.

The current delivery focus is the native agent API and backend. Read
[INTENT.md](INTENT.md) for the agreed goal and [AGENTS.md](AGENTS.md) for contributor
and agent guidance.

The [profile-preference audit](docs/audits/2026-10-22-profile-preferences.md)
records the source repairs made after its original findings and the evidence
limits that remain. It does not establish live recommendation quality or deployment.

## Features

- Native agent API: persistent conversations/runs, progress streaming, scoped human approvals and protected documents; see [backend setup](pipeline/agentic/CHAT.md).
- Collectors for job boards, company career pages (many ATS systems), RSS and Reddit; duplicates removed; SQLite storage.
- Web board (FastAPI + HTMX): Board, Table, Job, Applications, Inbox (mail outcomes), Sources, Insights.
- Profile built from your CV; evidence-backed drafts with a fresh-context reviewer and a code verifier.
- Several people per install, each with their own folder, profile, answers and logins.
- Optional Google (Gmail/Drive) connection for follow-up drafts and outcome tracking. Nothing is ever sent for you.
- Optional push of urgent messages to a personal assistant over ssh.

All data stays on your machine. The only outside calls are the job sources and the model gateway you configure.

## Install

```bash
git clone <this repo> ~/apps/jobwatch && cd ~/apps/jobwatch
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
mkdir -p ~/.config/jobwatch && cp .env.example ~/.config/jobwatch/settings.env   # then edit it
.venv/bin/jobwatch init-db
.venv/bin/jobwatch web                      # http://127.0.0.1:8960
```

Systemd user units (fast/slow collection, outcomes, digest, web) are in `systemd/`; copy them to
`~/.config/systemd/user/` and enable the timers. See `SETUP.md` for first sign-in and connecting accounts.

## Settings (`~/.config/jobwatch/settings.env`)

`KEY=value` lines; a real environment variable of the same name wins. Use another file with `JOBWATCH_SETTINGS`.

| Key | Meaning | Default |
|---|---|---|
| `JOBWATCH_DATA_DIR` | Profiles, ledger, drafts (one folder per person) | `~/.local/share/jobwatch` |
| `JOBWATCH_DB` | SQLite file | `<jobwatch.yaml db_path>` = `~/.local/share/jobwatch/jobwatch.db` |
| `JOBWATCH_PROFILE_DIR` | Profile folder override | `<data dir>/profile` |
| `JOBWATCH_CAREER_DIR` | Career record folder | `<data dir>/career` |
| `JOBWATCH_LLM_BASE_URL` | OpenAI-compatible gateway URL | `https://api.openai.com/v1` |
| `JOBWATCH_LLM_API_KEY` | Gateway API key | none |
| `JOBWATCH_LLM_KEYS_FILE` | Optional `KEY=value` file holding more keys | `~/.config/jobwatch/keys.env` |
| `JOBWATCH_LLM_KEY_NAMES` | Names (comma list) to read from that file | `JOBWATCH_LLM_API_KEY` |
| `JOBWATCH_LLM_MODEL` | Default model id for every role (each person can pick their own on the Models page) | `gpt-4o` |
| `JOBWATCH_PUBLIC_HOST`, `JOBWATCH_BOARD_URL` | Address you open the board at | localhost:8960 |
| `JOBWATCH_NOTIFY_CMD` | Command run to notify you | none |
| `JOBWATCH_HERMES_SSH`, `JOBWATCH_HERMES_FILE` | `user@host` and remote file to append urgent messages to; unset = no push | none |
| `JOBWATCH_SESSION_SECRET`, `JOBWATCH_INVITE_CODE`, `JOBWATCH_OWNER_PASSWORD` | Sign-in | sign-in off |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Your own Google OAuth client | Google off |

Bring your own keys: create an API key with any OpenAI-compatible provider, and (for Google) your own OAuth client in
Google Cloud Console (Gmail API + Drive API, Web application; redirect URI = `GOOGLE_REDIRECT_URI`). Your CV and answers
are sent to the model gateway you choose, so pick a provider you trust.

## Credits

Jobwatch borrows ideas from [career-ops](https://github.com/santifer/career-ops) by santifer (MIT); the copied
anti-slop file and the career-ops templates keep that project's license notice. Resume-Matcher, Reactive Resume and
jobsync were inspirations.

## CLI

```bash
jobwatch run --tier fast|slow|all [--dry-run] [--only <collector>] [--limit N]
jobwatch digest [--dry-run]         # weekly Reddit chatter themes + posting/match stats
jobwatch health                     # last status, count, failures and latency per collector
jobwatch init-db                    # create or migrate the DB (idempotent)
jobwatch --user <name> baseline freeze [--limit N] [--posting-id ID]   # freeze stored inputs and outputs (no model call, no DB write)
jobwatch --user <name> baseline list                                    # this person's frozen baselines
jobwatch --user <name> baseline show <baseline_id> [--cases]            # record, label counts, gate state
jobwatch --user <name> baseline label <baseline_id> <case_id> ...       # the owner's label, at a terminal only
```

- `--dry-run` still writes postings and matches, but leaves new matches `queued` (nothing is published), so the next live run publishes them as `board`. For tests, point `JOBWATCH_DB` at a scratch file.
- `--limit N` caps the postings per collector and stops making requests once N are collected.
- `--only` names one collector: `jobspy_src seek ats_greenhouse ats_lever ats_ashby ats_workable
  ats_smartrecruiters ats_workday ats_pageup ats_employmenthero ats_scouttalent ats_oracle
  ats_successfactors ats_phenom ats_atlassian careers_vic jsonld_pages rss reddit`.
- Exit code: 1 when **every** collector in the run errored (systemd marks the unit failed);
  partial failures exit 0 and show up in `jobwatch health` and the Sources page. There is no failure push.
- Environment overrides: `JOBWATCH_DB`, `JOBWATCH_CONFIG_DIR`, `JOBWATCH_EMPLOYERS`.

## Profile workflow

Discovery runs only for a person whose current profile is confirmed, with a confirmed search scope.

1. **Onboard.** Either let the chat agent guide you (it asks for your files and your questions while it reads them in the background) or use the API under `/api/agent/profile`: upload a CV, letter or evidence file, start a proposal, answer the open questions, correct facts. Facts are marked evidence, inference or unknown; a CV gap alone does not establish unemployment.
2. **Confirm.** Review the confirmation (facts, search scope, daily limits). Confirming needs the approve scope, or in chat your own approval of those exact digests, and writes an immutable version under `profile-versions/`.
3. **Discover.** Collection and assessment then run within the confirmed scope and limits.

Existing installs: discovery stays off until a confirmed profile exists. `jobwatch --user <name> profile adopt` turns your current `profile/` files into version 1, which protects them from being overwritten and keeps them in the history; it authorises no discovery. To turn discovery on, onboard on top of that version: let the chat agent guide you (it can read your existing files through `profile_start` with `use_existing_files`) or start a proposal with `base_version` set to the current version, then confirm the scope shown. A scope with nothing to search for is refused (`profile_incomplete`).

Confirmation does not authorise document preparation, employer messages or submission; those keep their own approvals, and Submit stays on the owner-confirmed path. Walk-through with real requests and responses: [docs/examples/profile-intake.md](docs/examples/profile-intake.md).

### Field and job discovery

Field discovery compares approved profile facts with versioned occupation
references and saves related occupations as search hypotheses, never as proof
of qualification. The public bundled reference is always available; optional
public datasets are hash-verified under `<data>/reference/<dataset>/<version>/`
(`data` is `users.base_dir()`). Per-person hypotheses and the search plan are
stored under `<person>/discovery/`. Embeddings use the approved paid Qwen route
through OmniRoute and count against the confirmed scope's token budget.

Discovery settings live under `pipeline.agentic`. The confirmed profile is the
canonical source for regional admission, eligibility and personal exclusions;
missing or unresolved facts remain unknown. Search plans rotate supported
query/location pairs within each collector's request caps. Relevance can run in
`shadow` mode, which stores judgments without archiving postings, or `on`, which
archives a current `no` judgment; `uncertain` continues. These controls do not
replace canonical eligibility.

Inspect the configured flags and current state with
`python -m pipeline.agentic.discovery status --user <name>`; status is
read-only. After confirming the current profile and scope, explicitly compute
and cache fields and a search plan with
`python -m pipeline.agentic.discovery refresh --user <name>`. The first refresh
can build the shared reference index through the approved embedding route.
`python -m jobwatch.occupations.datasets status` reports reference dataset
availability without network access. The authenticated API also exposes
read-only `GET /api/agent/discovery/fields`, `/plan` and
`/postings/{posting_id}/relevance` routes under the server-bound person.

The thresholds `similar_at: 0.60` and `duplicate_cosine: 0.95` are uncalibrated;
there is no matching-accuracy claim. Relevance uses embeddings and, below the
similarity threshold, a bounded model extraction; there is no lexical hybrid.
Collector scope is bounded by request caps. Nothing here establishes deployment
or live model behaviour.

Undo by removing the discovery keys under `pipeline.agentic` and the
`pipeline.discovery` tuning block (or set `relevance: off` to stop shadow
judging). To restore postings archived by relevance or the exclusion
pre-filter, first run `python -m pipeline.agentic.discovery restore --user <name>`;
this returns those postings to `ingested`. To remove generated state,
delete that person's `<person>/discovery/` directory and the shared
`<data>/reference/` folder; both are rebuilt on demand. The migration tables
`text_embeddings`, `posting_relevance` and `discovery_spend` can remain unused.

### Frozen baseline

`jobwatch --user <name> baseline freeze` records the stored inputs and outputs of the newest evaluated run of each posting, the gate version, and the approved profile and profile files as they stand at freeze time (`summary.evidence_mismatch` counts runs made on other evidence), so a later matcher or gate can be compared on identical inputs. The recommended point to freeze is before Plan 2 (the revised decision policy) is deployed. A freeze never calls a model, writes no database row and opens the database read-only. Its files live under `<user_dir>/baselines/<baseline_id>/`, private to that person. Duplicate adverts and related employers share a `group_id`, so a comparison can keep them on one side of a split. `list` and `show` print the record and counts, never candidate text; `show` reports `gate_state` (`pre_revision` or `revised`) and whether the gate has changed since the freeze. `label` records the owner's own judgment and works only at a terminal; an agent running shell commands is refused. No numbers in MATCHING.md changed.

Undo: `rm -rf <user_dir>/baselines/<baseline_id>` removes one baseline (`rm -rf <user_dir>/baselines` removes all). Nothing else reads them and nothing else was changed.

Not verified or not available yet:

- The freeze has never been run on a real person's data.
- The database uses WAL journal mode (`jobwatch/db.py`) and the freeze opens it read-only (`mode=ro`). That has not been tested against a live WAL database; the owner's first real freeze must confirm that it opens.
- Labels are absent until the owner adds them.
- Tags are heuristics, not judgments.
- `explicit_exclusion` is limited to the family rules until Plans 2 and 5.
- Replays of the old gate need the baseline's `pinned_profile`.

Walk-through with real output (invented data, no model called): [docs/examples/frozen-baseline.md](docs/examples/frozen-baseline.md).

### Decision policy

The canonical gate reads the person's confirmed profile. A historical `legacy`
setting is treated as `profile`; no fixed personal-policy fallback is active.
The flag is not part of a run key, so policy changes do not trigger paid model
work. Current source keeps holistic scores as advisory comparison data; they do
not exclude a job. Stored evaluations are re-decided through canonical policy
before downstream use.

With `profile`, the gate reads only the approved facts of the confirmed version:

- **Strategy.** A stated career focus gives `career_focus`. Unemployed with no contrary status gives `employment_first`. Anything else is `balanced`. Strategy guides explanations and ranking; it does not turn missing information into a personal preference.
- **Exclusions are rules only when structured.** An exclusion becomes a rule only as a `{kind, value}` fact, with kind `family`, `employer`, `title_term`, `location` or `work_type`. Free text is never a rule. It stays prompt text and is listed as the open question `exclusion:<fact_id>` until the person gives it a kind.
- **Work rights, hours, level and commute** are read from the approved facts by a documented deterministic grammar. The grammar asks only about missing sections and about locations and exclusions it cannot read. A work-rights, hours, level or commute statement it cannot read is ignored without a question and appears only in the policy JSON. A commute limit with no recognised home is not applied.
- **Missing facts** that change a decision are open questions (for example `location`). An ad whose location cannot be resolved holds rather than archives.

To see the policy and its open questions: `GET /api/agent/profile/policy` (scope `read`) returns `policy`, `mode`, `enabled`, `open_questions` (each `{code, question, why}`) and `reason` when there is no policy. The chat agent's read-only `profile_policy` tool returns the same. Neither writes anything.

Limits: distance uses place data for Victoria only. Other states resolve by state name, state code or capital city, and an unresolved location holds. The product remains Australia-only. Confirmed policy and canonical eligibility are shared across the active and retained assessment paths.

Undo source behavior by reverting the relevant source change; do not treat the historical `legacy` alias as a rollback switch. Profile decisions and records remain per person. Walk-through with invented output (no model called): [docs/examples/decision-policy.md](docs/examples/decision-policy.md).

### Ranking and explained shortlist

Phase 5 implements importance-weighted evidence coverage,
three explanation labels, deterministic provisional ordering, and optional
within-label personalised ordering from valid owner-choice fits. Unknown facts
remain questions; transferable evidence requires a frozen evidence-matched fact,
not word overlap alone. Priors are neutral, and historical choices move only
through an explicit migration that preserves originals and split assignments.
The design is recorded in [ADR 0007](docs/adr/0007-ranking-and-explained-shortlist.md)
and [ranking rules](docs/ranking-rules.md). Phases 1–5 are merged. The historical
[Phase 5 verification](docs/audits/2026-10-22-shortlist-release.md) retains its
browser failure; the subsequent [browser repair](docs/audits/2026-10-23-browser-popup.md)
records the merged fix and passing release suite. Deployment remains separate.

Phase 6 (merged in PR #24) adds reversible posting feedback, confirmed exclusion amendments,
bounded genuine-choice prompts and durable selected-job preparation. Native API
and chat use the same domain services and exact human approvals. See the
[worked example](docs/examples/feedback-selection.md),
[backend contract](pipeline/agentic/CHAT.md#feedback-and-selected-preparation-phase-6)
and [remaining-roadmap plan](docs/superpowers/plans/2026-10-23-finish-backend-roadmap.md).

Phase 7 provides private frozen replay, write-once grouped holdout splits, human
labels, missing-label-aware metrics and bounded development monitoring through
`jobwatch evaluate`. Default replay makes zero model calls and uses provisional
ordering. Paid evaluation and local fitting require explicit flags and remain
separate from activation. See [the command example](docs/examples/evaluation-monitoring.md)
and [backend contract](pipeline/agentic/CHAT.md#frozen-evaluation-and-bounded-monitoring-phase-7).
The [Phase 7 verification](docs/audits/2026-10-23-evaluation-monitoring.md) records
3804 passed, 11 skipped, resolved independent review, real synthetic sampler checks
and the installed-database access incident. Source delivery is PR #25; no real
blind-quality study or deployment is claimed.

## Config files (`config/`)

| File | What it holds |
|---|---|
| `jobwatch.yaml` | DB path, timezone, HTTP timeout/delay, `alerts.max_age_hours`, retention, tier membership |
| `rules.yaml` | Arms (keywords per ANZSCO arm, per-arm excludes), location rules, seniority/off-target excludes, flag patterns |
| `searches.yaml` | Seek keywords (`where`, `date_range`, pages, rotation) and JobSpy searches (sites, `hours_old`, `results_wanted`) |
| `feeds.yaml` | Generic RSS/Atom job feeds, and Reddit feeds, hiring/chatter keywords, digest themes |
| `employers.yaml` | Employer registry, maintained separately. If it is missing, `employers.example.yaml` is used |

### `employers.yaml` schema

```yaml
employers:
  - name: Telstra              # required; also used for "VIC employer" matching
    sector: telecommunications # free text
    arms: [call_centre, retail_sales]   # rules.yaml arm ids it is likely to hire for
    state: VIC                 # VIC lets unknown-location postings from it match
    provider: workday          # greenhouse | lever | ashby | workable | smartrecruiters |
                               # workday | pageup | employmenthero | scouttalent | jsonld |
                               # oracle-hcm | successfactors | phenom | atlassian | careers_vic
    tenant: telstra            # board slug / PageUp client no. / Workday tenant / Scout subdomain
    site: Telstra_Careers      # workday only
    host: telstra.wd3.myworkdayjobs.com   # workday only
    search_text: ""            # workday only, optional (string or list)
    applied_facets: {}         # workday only, optional CXS facet filter
    feed_url: https://careers.pageuppeople.com/527/cw/en/rss   # pageup
    careers_url: https://example.vic.gov.au/careers            # jsonld (string or list)
    link_pattern: '/jobs/\d+'  # jsonld, optional regex for job-detail links
    allowed_hosts: []          # jsonld, optional extra hosts for detail links
    follow_links: true         # jsonld, optional (false = read the listing page only)
    url_pattern: '…/job/\d+/[a-z0-9-]+'  # jsonld, optional: pair url-less JobPostings with page links by title slug
    host: …  site: CX_1        # oracle-hcm (api_url optional; offset paging is added by the collector)
    feed_url: https://…/googlefeed.xml   # successfactors (slow tier)
    careers_url: https://…/au/en/search-results   # phenom
    detail_cap: 10             # optional; workday/smartrecruiters default 10, jsonld max 30
    region: eu                 # lever only, when the board lives on api.eu.lever.co
    enabled: true
    notes: how it was verified
    verified_at: 2026-10-06
```

## Collectors

| Collector | Tier | Source |
|---|---|---|
| `ats_greenhouse` | fast | `boards-api.greenhouse.io/v1/boards/{tenant}/jobs?content=true` |
| `ats_lever` | fast | `api.lever.co/v0/postings/{tenant}?mode=json` |
| `ats_ashby` | fast | `api.ashbyhq.com/posting-api/job-board/{tenant}` |
| `ats_workable` | fast | `apply.workable.com/api/v1/widget/accounts/{tenant}?details=true` |
| `ats_smartrecruiters` | fast | `api.smartrecruiters.com/v1/companies/{tenant}/postings?country=au` (+ detail for target titles) |
| `ats_workday` | fast | `POST {host}/wday/cxs/{tenant}/{site}/jobs` (+ detail for target titles whose location is unclear) |
| `ats_pageup` | fast | PageUp RSS (`job:` namespace) |
| `ats_employmenthero` | fast | `services.employmenthero.com/ats/api/v1/career_page/organisations/{tenant}/jobs` |
| `ats_scouttalent` | fast | `{tenant}.applynow.net.au/` index (`div.jobblock` data attributes), robots.txt respected |
| `rss` | fast | `feeds.yaml` feeds (generic, or `format: pageup`) |
| `reddit` | fast | `reddit.com/r/<sub>/new/.rss` and `/search.rss`, descriptive UA, rate-limit headers honoured |
| `jobspy_src` | slow | python-jobspy: LinkedIn, Indeed (Australia), Google; "Melbourne, VIC" |
| `seek` | slow | `seek.com.au/api/jobsearch/v5/search` (AU-Main, All Melbourne VIC, at most 2 pages) |
| `ats_oracle` | fast | Oracle Recruiting Cloud `recruitingCEJobRequisitions` finder (public, newest first); pages until a seen id, 2 pages fast / 4 slow |
| `careers_vic` | fast + slow | careers.vic.gov.au `/jobs?page=N` HTML (15/page, newest first, robots.txt respected); pages 1-2 on fast runs, up to 10 on slow, stops at a seen id; VPS grade -> `classification` |
| `ats_successfactors` | slow | SuccessFactors `googlefeed.xml` RSS (1-3 MB each); location from the title suffix or `g:location`; conditional GET when the server sends ETag/Last-Modified |
| `ats_phenom` | slow | Phenom search page (`phApp.ddo` / `eagerLoadRefineSearch`) + the page's own `/widgets` paging (100/page, max 10); robots.txt respected |
| `ats_atlassian` | slow | `atlassian.com/endpoint/careers/listings` JSON (AU locations only) |
| `jsonld_pages` | slow | employer careers pages: schema.org `JobPosting` JSON-LD (incl. capitalised `Title`), robots.txt respected |

Politeness rules: requests time out after 20 s or less, and there is a 1.5 s gap (allowed range
1 to 2 s) between requests to the same host (at least 3 s for Reddit). The User-Agent is a normal
browser string; Reddit gets a descriptive one. There are no proxies and no stealth. A 403, 429 or
5xx marks the host as backed off for the rest of the run and is recorded as an error. Every
collector gates on Australia (a structured country of AU, or Australian place names); the filter
decides about Melbourne, Victoria and remote.

## Matching, flags, alerts

- **Match:** the title matches an arm keyword, the location is Melbourne/Victoria or remote in
  Australia (or the location is unknown and the employer has `state: VIC`), there is no
  seniority or off-target word, and the ad does not ask for 5 or more years. Each match stores
  its arm, all matching arms and the rules that fired (`matches.rules_json`).
- **Flags (warnings, not filters):** `work_rights_required`, `full_time_only`,
  `experience_years>=2`, `entry_level`, plus source tags such as `via_linkedin` or `reddit`.
- **Alerts:** there is no push. A fresh match gets an `alerts` row with status `board` (visible as NEW on
  the web board). Old or seed postings are `stale`. `--dry-run` leaves them `queued`. The board decides NEW itself (unviewed), not from this table.
- **Classification:** collectors that know a pay grade (Careers.Vic "Grade") set `classification`.
  `seniority.exclude_classification` excludes VPS 5+/SES/executive grades;
  `flags.entry_classification` flags VPS 1-3 as `entry_level`. VPS 4 matches with no flag.
- **Arm names:** `rules.yaml` `registry_arm_map` maps the registry's brief arm names (admin,
  retail, ...) to rule arm ids (`Rules.rule_arms_for`). Reporting only; matching is by title.
- **No floods:** a provider-dated posting older than 72 h is stored as `stale` and not alerted.
  The first time an employer or feed is read, observed-date postings are stored without alerts
  (seeding).
- **Health:** consecutive failures per collector are counted in `source_health` and shown by
  `jobwatch health` and the Sources page. Nothing is pushed.

## Data (`~/.local/share/jobwatch/jobwatch.db`)

| Table | Holds |
|---|---|
| `postings` | Every posting (first source wins), the raw payload and a description snippet of up to 2000 chars |
| `sightings` | One row per posting × source, with first/last seen and a count |
| `matches` | One row per matched posting |
| `alerts` | Bookkeeping per match (`queued`, `board`, `stale`; older rows `sent` from the Matrix era) |
| `source_health` | Per-collector health |
| `reddit_posts` | Reddit hiring and chatter posts (no usernames) |
| `runs` | Run stats |
| `state` | Rotation cursors and seed lists |

Dedup works by canonical-URL hash first, then by a normalised (company, title, city) key within
30 days. Non-matching postings unseen for 90 days are deleted at the end of each run.

## Timers

Unit files are in `systemd/`:

```bash
cp systemd/jobwatch-* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jobwatch-fast.timer jobwatch-slow.timer jobwatch-outcomes.timer jobwatch-digest.timer
```

- `jobwatch-fast.timer`: every 20 min (+ up to 60 s jitter) runs `jobwatch --user all run --tier fast`.
- `jobwatch-slow.timer`: every 2 h at :10 (+ up to 15 min jitter) runs `jobwatch --user all run --tier slow`.
- Discovery is off for a person until their current profile is confirmed with its search scope shown, and while the live `profile/` files differ from that confirmed version (a hand edit after confirming pauses it until the files match again; `jobwatch profile adopt` alone does not turn it on, and a scope with nothing to search for is refused as `profile_incomplete`; onboard with a proposal built on the current version and confirm it). Unconfirmed people are skipped; `--user all` splits the unit's time over those who run.
- `jobwatch-outcomes.timer`: 07:00, 09:00 … 21:00 Melbourne runs `jobwatch outcomes`.
- `jobwatch-digest.timer`: Monday 08:00 Melbourne runs `jobwatch digest` (the text goes to the journal).

## Apply layer (B): outcome sync, callback stats

Design: `PLAN-apply.md` (D8, D9, D10). Code: `jobwatch/commands/` (shared state API: `state.py`,
`apply_api.py`) and `jobwatch/outcomes/`. The owner drives applications from the web board (save, hide,
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

## Web board (`jobwatch web`, systemd `jobwatch-web.service`)

A personal job board on `127.0.0.1:8960` (put it behind your own reverse proxy or tunnel with login to expose it). FastAPI + Jinja2 + HTMX, no JS build. Pages: Board (`/`), Table (`/table`, CSV export),
Job (`/job/<id>`), Applications (kanban), Inbox (mail outcome proposals: approve or reject), Sources (collector
health and the employer registry), Insights. Keys on the board: `j`/`k` move, `s` save, `h` hide, `d` draft, `/` search.
Reads: `jobwatch/web/queries.py`. Writes: `jobwatch/web/actions.py` (ledger and state APIs only).
Template contexts: `jobwatch/web/CONTRACT.md`. Guards: Host allow-list, Origin/Referer required on every POST,
cross-site sub-requests refused, CSP `script-src 'self'`, only http(s) links, draft files served only by exact name
inside the drafts folder. jobwatch never applies on its own: Submit is your click, or your confirmation of that exact filled form.

## Undo

```bash
systemctl --user disable --now jobwatch-fast.timer jobwatch-slow.timer jobwatch-outcomes.timer jobwatch-digest.timer jobwatch-web.service
rm ~/.config/systemd/user/jobwatch-*; systemctl --user daemon-reload
rm -rf ~/apps/jobwatch ~/.local/share/jobwatch     # archive first if the data matters
```

