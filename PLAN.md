# Job watch: plan (Paperclip BUI-73, 2026-10-06)

> **Status 2026-10-06:** built and live (W1). D1 ("no LLM, no drafting") applies to the watcher only; the apply layer is in `PLAN-apply.md`. D7 alerts now post as `@jobwatch`, not `@hermes`. Current status and backlog: `TRACK.md`.
> **Matrix removed 2026-10-06:** D7 (Matrix alerts, quiet hours, room) no longer exists. Fresh matches are published to the web board only.

Owner direction (2026-10-06): "sources: JobSpy, Seek, Indeed, ATS/RSS, try to find from employer sites; make a cron so if there's an opening we get earlier notifications; scrape Reddit job forums for a more realistic picture."

## 1. Decisions (Discuss phase; defaults taken, owner can override)

| # | Decision | Default taken | Why |
|---|---|---|---|
| D1 | Scope | A small **watcher**, not the old pipeline: collect, filter, dedupe, alert. No LLM scoring, no drafting, no prefill. | Fast alerts are the ask. Smallest change. The archived pipeline stays archived. |
| D2 | Sources | JobSpy (LinkedIn + Indeed AU + Google), Seek public search, ATS public job APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday CXS, PageUp RSS, Employment Hero, Scout Talent), employer career pages (schema.org JobPosting JSON-LD), government RSS/feeds (Careers.Vic, APSJobs), Reddit (subreddit RSS). | Owner list. |
| D3 | Terms of service | Owner accepts the ToS risk for Seek, Indeed and LinkedIn (personal use). Mitigation: low volume, no login, no proxies or stealth, polite delays, back off on 403/429. | R&D rated JobSpy's Indeed adapter a critical ToS risk; this is the owner's call (concept O4). |
| D4 | Cadence | ATS APIs, RSS and Reddit: every 20 min. Employer pages (JSON-LD): every 2 h. JobSpy and Seek: every 2 h, with jitter. | Early alerts where cheap and allowed; heavier sources less often. |
| D5 | Matching | Config rules: target title keywords (the 21 ANZSCO arms), Melbourne/Victoria/remote-AU location, entry-level signals, and seniority excludes. **Work rights = warning flag, not a filter.** | The concept and R&D say flag, don't block. The owner didn't decide, so this is the default. |
| D6 | Dedup | Canonical URL hash, then a normalised (company, title, city) key within 30 days. The first source seen wins, and later sources are recorded. | Alert once per job. |
| D7 | Alerts | A Matrix room **"Job alerts"** (`@hermes` posts, owner invited). One batched message per run with new matches. Max 15 per message, and the overflow goes to a link-only list. Quiet hours 22:00–07:00 Melbourne: matches are held and sent at 07:00. | Matrix is the owner's main channel. A separate room keeps Hermes chats clean. |
| D8 | Reddit | Subreddit RSS (no login, no API key). Two streams: (a) **hiring posts** that match the filters → alerts; (b) **market chatter** (job-search experiences, salary, callbacks) → stored, with a weekly digest of themes and counts. | "More realistic" picture of the market. RSS avoids the blocked `.json` path. |
| D9 | Storage | SQLite `~/brain/data/jobwatch/jobwatch.db` (open format). Raw payload kept per posting. 90-day retention for non-matches. | Data sovereignty; matches the brain layout. |
| D10 | Runtime | `~/apps/jobwatch` with a `uv` venv (python-jobspy, requests, feedparser, pyyaml). systemd **user** timers. No containers, no new ports. | Smallest runtime. Listed in WHAT-HAPPENED. |
| D11 | Privacy | No candidate profile and no LLM. Filters are plain config. Nothing leaves the server except fetch requests and the Matrix post (local homeserver). | Owner rule on candidate data. |

## 2. Architecture

```
systemd --user timers
  jobwatch-fast.timer (20 min)  → jobwatch run --tier fast   (ats, rss, reddit)
  jobwatch-slow.timer (2 h)     → jobwatch run --tier slow   (jobspy, seek, employer_pages)
  jobwatch-digest.timer (Mon 08:00) → jobwatch digest       (reddit chatter + weekly stats)

jobwatch run:
  collectors (plugin per source kind) → normalise to Posting
  → filter (rules.yaml) → dedupe (db) → store
  → alert (matrix) for NEW matches only, respecting quiet hours
  → per-source health row (ok/err/count/latency); 3 consecutive errors → one health alert
```

Files:
- `jobwatch/` package: `cli.py`, `models.py`, `db.py`, `filters.py`, `dedupe.py`, `notify_matrix.py`, `collectors/{jobspy_src,seek,ats_greenhouse,ats_lever,ats_ashby,ats_workable,ats_smartrecruiters,ats_workday,ats_pageup,ats_employmenthero,ats_scouttalent,jsonld_pages,rss,reddit}.py`
- `config/rules.yaml` (titles, locations, excludes, flags), `config/searches.yaml` (JobSpy/Seek queries), `config/employers.yaml` (registry: name, sector, provider, tenant/feed/url), `config/feeds.yaml` (RSS, Reddit)
- `tests/` with offline fixtures; `README.md`; `systemd/` unit files.

## 3. Waves

- **Wave 1 (parallel):**
  - **A: engine.** All collectors, the DB, filters, dedupe, the notifier (dry-run mode), the CLI, tests and fixtures.
  - **B: employer registry.** Melbourne/Victoria employers likely to hire for the target arms, with verified public ATS endpoints or feeds.
- **Wave 2 (Claude):** integrate, then run every collector live once in dry-run. Check counts, dedupe and filter precision on real output.
- **Wave 3 (Claude):** create the Matrix room and send a test alert, install the timers, watch 2 cycles, then log it and close BUI-73.

## 4. Verify (acceptance)

1. Every enabled collector returns ≥ 1 posting live or reports a clean, logged error. Nothing crashes the run.
2. Re-running immediately produces 0 new alerts (dedupe works).
3. Matches spot-checked by hand: ≥ 80% of the first 30 alerted items fit the target arms.
4. Quiet hours hold messages. A health alert fires after 3 consecutive failures of a source.
5. Timers are listed in WHAT-HAPPENED with undo steps.

## 5. Undo

`systemctl --user disable --now jobwatch-fast.timer jobwatch-slow.timer jobwatch-digest.timer`, delete the units, `rm -rf ~/apps/jobwatch ~/brain/data/jobwatch`, and leave the Matrix room.
