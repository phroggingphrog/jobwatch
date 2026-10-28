# jobwatch web: personal job board (2026-10-06)

> **Status 2026-10-06:** built and live (W3, BUI-91): `jobs.phroggingphrog.com` behind Access. Drift: D2 says "no new tables" but the DB now has `web_views` and `saved_searches`. Current status and backlog: `TRACK.md`.
> **Matrix removed 2026-10-06:** D5 is moot. The board is the only surface; there is no push and no Matrix link.

Owner direction (2026-10-06): "Matrix just makes it complicated. Make a full-on dashboard with multiple pages and a nice UI/UX where I can see all the jobs, as if I had my own Seek-like job board, plus lists/tables and another page that filters. Check career-ops TUI or GitHub for this kind of project."

## Decisions (defaults; the owner can override)
- **D1 Stack:** FastAPI + Jinja2 templates + HTMX, served by uvicorn. No JS build step and no SPA framework. It lives in `jobwatch/web/`, started with `jobwatch web`.
  - Static assets are vendored in `jobwatch/web/static/`: htmx, plus a tiny chart lib if needed.
  - Fonts: IBM Plex from Google Fonts, the same as dash.phroggingphrog.com.
  - Design tokens on `:root` with light and dark themes, the same palette family as the PhrogVPS dashboard.
- **D2 Data:**
  - Read from `~/brain/data/jobwatch/jobwatch.db` (WAL), opening a connection per request.
  - Writes go only through the existing APIs:
    - application status via `ledger.upsert`;
    - drafting via `jobwatch.apply.chain.start_draft`;
    - outcome approve/reject via `jobwatch.outcomes.decide`.
  - No new tables. Save, hide and notes use `applications` (status `interested`/`skipped`, `notes`).
- **D3 Pages:**
  1. **Board** (`/`): Seek-like layout.
     - Search bar: keywords and location.
     - Left filter rail: job type (arm), core/fallback, source, sector, posted within, remote, entry-level, work type, has salary, flags (work rights, full-time-only, experience).
     - Card list: title, company, location, salary, posted-ago, badges (NEW, remote, entry-level, warning flags).
     - Split-view detail pane opened with HTMX. Toggle between "matches" (default) and "all jobs".
     - Sort: newest, salary, relevance.
     - Keyboard navigation: j/k to move, s to save, h to hide, d to draft.
  2. **Table** (`/table`): dense sortable table of all postings or matches with the same filters, column chooser, CSV export, pagination.
  3. **Job** (`/job/<posting_id>`): full description, all sightings (other sources), flags with reasons, rules matched.
     - Actions: Save, Hide, Mark applied, Draft CV + letter (runs in the background; status polls; PDFs download when ready), Notes.
  4. **Applications** (`/applications`): kanban by status (interested → drafted → applied → assessment → interview → offer / rejected / withdrawn). Cards have a quick status change, draft PDF links and timeline events.
  5. **Inbox** (`/inbox`): outcome proposals from mail, with Approve/Reject (replaces the Matrix approve command).
  6. **Sources** (`/sources`): employer registry (enabled, provider, last count, sector) and per-collector health (last ok, errors), so it's easy to see what is watched.
  7. **Insights** (`/insights`): new matches per day, matches by job type, by source and by sector, top hiring employers, Reddit chatter themes, and callback rate per arm (the Beta-Binomial stats from the digest).
- **D4 Access:**
  - Bind 127.0.0.1:8960.
  - Public at `jobs.phroggingphrog.com` through tunnel PHROG_LOCAL, behind a Cloudflare Access app with the owner-email policy (same as dash).
  - POST/PUT need a same-origin check (`origin_guard`: Origin/Host must be the public host or loopback).
  - Runs as the systemd user service `jobwatch-web` (always on).
- **D5 Matrix:**
  - Alerts stay as a short push, and each line links to `https://jobs.phroggingphrog.com/job/<id>`.
  - Commands keep working but aren't needed; everything can be done on the web.
- **D6 Privacy:** profile text and draft contents are never rendered except the owner's own PDFs on download. No candidate data is in page source beyond that.

## Verify
- Tests: route smoke tests with a temp DB fixture; filters; actions write through the ledger; origin guard rejects a foreign Origin.
- Headless Chromium screenshots of every page in light and dark, desktop and 390 px phone width.
- Then the service runs, the public host is checked behind Access, and the Matrix links point to it.

## Undo
- `systemctl --user disable --now jobwatch-web`, then delete the unit.
- `rm -r jobwatch/web`, and remove `web` from `cli.py` (backup `cli.py.pre-web`).
- Delete the Access app, DNS record and ingress rule for `jobs`.
