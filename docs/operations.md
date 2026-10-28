# Data and operations

[Project overview](../README.md) · [Current intent](../INTENT.md)

Reference material moved from README; commands describe available source interfaces,
not proof of current service activation or end-to-end acceptance.

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
