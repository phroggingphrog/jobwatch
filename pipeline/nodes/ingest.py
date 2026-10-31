"""Node 1: ingestion and deduplication. Plain code, no model.

Collectors (jobwatch.run.run) keep scraping and normalising postings into `postings`. This node admits every
posting still listed, in the person's own state / remote-Australia (filters.location_rule), with the WHOLE ad text
(fetched here when the source allows it). No title word lists: what the job is gets judged by meaning in node 2-3.
Same ad text as a job already in the pipeline -> archived as a duplicate (sha256 of the normalised text).
Paid placements (sponsored ads) are archived. Ads whose full text cannot be had yet are not admitted (asked again
next run, within the fetch log's limits).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import timedelta

from jobwatch.util import adtext as adtext
from jobwatch.filters import Rules
from jobwatch.models import Posting, fold, now_utc
from jobwatch.reader import is_sponsored

from .. import store
from ..schemas import JobAd, Stage

log = logging.getLogger(__name__)
SEEN_WITHIN_DAYS = 3
# One site may use at most this many of a run's fetches (2026-10-12: SmartRecruiters and Workday, being older rows,
# took the whole budget every run, so Seek and LinkedIn ads never got their text and never reached the AI).
PER_HOST_FETCHES = 8


def content_hash(company: str, text: str) -> str:
    norm = re.sub(r"\s+", " ", fold(f"{company}\n{text}")).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def posting_of(r) -> Posting:
    return Posting(source=r["source"], source_id=r["source_id"], url=r["url"], title=r["title"],
                   company=r["company"] or "", location=r["location"] or "", state=r["state"],
                   remote=bool(r["remote"]), description=r["description"] or "", origin=r["origin"] or "")


UNREADABLE_TRIES = 2


def candidates(conn, posting_ids: list[int] | None = None):
    if posting_ids:                             # named jobs (maintainer / shadow runs), still through every check below
        ids = [int(i) for i in posting_ids]
        return conn.execute("SELECT p.* FROM postings p LEFT JOIN pipeline_state s ON s.posting_id = p.id "
                            f"WHERE s.posting_id IS NULL AND p.id IN ({','.join('?' * len(ids))}) ORDER BY p.id", ids).fetchall()
    since = (now_utc() - timedelta(days=SEEN_WITHIN_DAYS)).isoformat(timespec="seconds")
    sql = ("SELECT p.* FROM postings p LEFT JOIN pipeline_state s ON s.posting_id = p.id "
           "WHERE s.posting_id IS NULL AND p.last_seen_at >= ? ORDER BY p.id")   # oldest first: a repost dedupes onto the original
    return conn.execute(sql, (since,)).fetchall()


def run(conn, config, *, limit: int = 200, fetch_budget: int = 25, fetcher=None,
        posting_ids: list[int] | None = None, deadline: float | None = None) -> dict:
    """Admit up to `limit` new jobs. Returns counts. Deterministic: same DB + same pages = same result."""
    store.ensure(conn)
    rules = Rules(config.rules, config.employers, conn=conn)
    stats = {"seen": 0, "admitted": 0, "duplicate": 0, "sponsored": 0, "out_of_area": 0, "waiting_text": 0,
             "fetched": 0}
    blocked: set[str] = set()
    per_host: dict[str, int] = {}
    from jobwatch.execution_mode import effective_mode
    from pipeline import tracks
    screened_mode = isinstance(getattr(config, "settings", None), dict) and effective_mode(config) == "screened"
    track_cfg = tracks.settings(config) if screened_mode else {}
    rows = candidates(conn, posting_ids)
    if screened_mode:                              # best title match first, like career-ops; stable, so oldest first within a track
        rank = {"undergraduate": 0, "primary": 1, None: 2}
        rows = sorted(rows, key=lambda r: rank.get(tracks.classify(r["title"] or "", track_cfg), 3))
    for r in rows:
        if deadline is not None and time.time() >= deadline:
            stats['deferred'] = 'batch_deadline'
            break
        if stats["admitted"] >= limit:
            break
        stats["seen"] += 1
        # Canonical prescreen records location decisions and applies posting overrides.
        loc = 'profile_prescreen' if getattr(rules, 'prescreen', None) is not None else rules.location_rule(posting_of(r))
        if not loc:
            stats["out_of_area"] += 1
            continue
        pre = _prescreen(conn, rules, r, r["description"] or "", "metadata")
        if pre is not None and pre.skip:           # a clear mismatch from the listing alone: no ad fetch, no model
            stats["prescreened"] = stats.get("prescreened", 0) + 1
            conn.commit()
            continue
        track = None
        if screened_mode:                          # title track before any fetch (pipeline/tracks.py)
            track = tracks.classify(r["title"] or "", track_cfg)
            if track in ("drop", "secondary"):
                stage, why = (Stage.ARCHIVED, "title_not_target") if track == "drop" else (Stage.SIDE, None)
                store.admit(conn, r["id"], f"{track}:{r['id']}", {"track": track}, stage, why)
                stats[track] = stats.get(track, 0) + 1
                conn.commit()
                continue
        host = adtext.fetch_host(r["source"])
        can_fetch = bool(fetcher) or (host and fetch_budget > 0 and host not in blocked
                                      and per_host.get(host, 0) < PER_HOST_FETCHES and adtext.wants_fetch(conn, r))
        try:
            adtext._note(None)                  # 'gone' below must come from this posting's fetch, not an earlier one
            text, kind = adtext.ensure_text(conn, r, fetcher, allow_fetch=bool(can_fetch), deadline=deadline)
        except adtext.Blocked as exc:           # the site said stop: no more requests to it this run
            blocked.add(host)
            log.info("ingest: %s blocked: %s", host, exc)
            text, kind = adtext.ensure_text(conn, r, allow_fetch=False)
        except Exception as exc:                # noqa: BLE001 - a slow or broken page (the fetch log has it): asked again later
            log.info("ingest: posting %s fetch failed: %s: %s", r["id"], type(exc).__name__, str(exc)[:120])
            stats["fetch_errors"] = stats.get("fetch_errors", 0) + 1
            text, kind = adtext.ensure_text(conn, r, allow_fetch=False)
        if kind != "full" and can_fetch and not fetcher and r["source"] in BROWSER_FALLBACK:
            # Seek's plain page download often fails while the safe browser reader opens the ad (2026-10-12:
            # "Graduate Accountant - 2027" and "Finance and Accounting Intern" waited forever for text).
            text, kind = _browser_text(conn, r, text, kind, deadline=deadline)
        if can_fetch and not fetcher:
            fetch_budget -= 1
            per_host[host] = per_host.get(host, 0) + 1
            stats["fetched"] += 1
            if deadline is None:
                adtext.pace()
            elif deadline > time.time():
                adtext.pace(min(2.5, deadline-time.time()))
        if kind != "full" and can_fetch and adtext.last_status() == "gone":     # the ad is closed: no model, never asked again
            store.admit(conn, r["id"], f"closed:{r['id']}", {}, Stage.ARCHIVED, "posting_closed")
            stats["closed"] = stats.get("closed", 0) + 1
            conn.commit()
            continue
        if kind != "full":
            tried = adtext.fetch_state(conn, r["id"])
            if screened_mode and not can_fetch and tried is not None and (tried["tries"] or 0) >= UNREADABLE_TRIES:
                # two failed reads: archive instead of re-checking it every run (1,030 waited on 2026-11-01)
                store.admit(conn, r["id"], f"unreadable:{r['id']}", {"track": track}, Stage.ARCHIVED, "ad_unreadable")
                stats["unreadable"] = stats.get("unreadable", 0) + 1
                conn.commit()
                continue
            stats["waiting_text"] += 1
            continue
        h = content_hash(r["company"] or "", text)
        ad = JobAd(posting_id=r["id"], source=r["source"], title=r["title"], company=r["company"] or "",
                   location=r["location"] or "", url=r["url"] or "", location_rule=loc, text_kind="full",
                   content_hash=h)
        full = _prescreen(conn, rules, r, text, "full", content_hash=h, ad=ad)
        if full is not None and full.skip:         # the full ad shows a clear mismatch (years, work rights, level): no model
            stats["prescreened"] = stats.get("prescreened", 0) + 1
            conn.commit()
            continue
        extra = {"prescreen": full.summary()} if full is not None else {}
        dup = conn.execute("SELECT posting_id FROM pipeline_state WHERE content_hash=? LIMIT 1", (h,)).fetchone()
        # Description hashes do not distinguish stores, cities or requisitions.
        # Semantic mode applies its company/title/location/source guards later.
        from pipeline.agentic.discovery import settings as discovery_settings
        if discovery_settings(config)['dedupe'] == 'semantic':
            dup = None
        if dup:
            store.admit(conn, r["id"], h, {"ingest": ad.model_dump(), "track": track, **extra}, Stage.ARCHIVED, f"duplicate_of:{dup[0]}")
            stats["duplicate"] += 1
        elif is_sponsored(r["raw_json"]):
            store.admit(conn, r["id"], h, {"ingest": ad.model_dump(), "track": track, **extra}, Stage.ARCHIVED, "sponsored_ad")
            stats["sponsored"] += 1
        else:
            store.admit(conn, r["id"], h, {"ingest": ad.model_dump(), "track": track, **extra})
            stats["admitted"] += 1
        conn.commit()
    return stats


def _prescreen(conn, rules, r, text: str, stage: str, *, content_hash: str | None = None, ad=None):
    """Run the prescreen engine for one row. A clear mismatch is archived (reason 'prescreened', reversible: see
    jobwatch.prescreen.reconsider). Returns the outcome, or None when prescreen is off (no confirmed profile)."""
    engine = rules.prescreen
    if engine is None:
        return None
    from jobwatch.prescreen.engine import fields_of_row
    out = engine.screen(conn, r["id"], fields_of_row(r, text), stage=stage)
    if out.skip:
        data = {"prescreen": out.summary()}
        if ad is not None:
            data["ingest"] = ad.model_dump()
        store.admit(conn, r["id"], content_hash or f"prescreen:{r['id']}", data, Stage.ARCHIVED, "prescreened")
    return out


BROWSER_FALLBACK = {"seek", "jobspy_src"}


def _browser_text(conn, r, text: str, kind: str, *, deadline: float | None = None) -> tuple[str, str]:
    import time
    from jobwatch.interview.browser import browser_ad
    try:
        remaining = 45 if deadline is None else min(45, deadline-time.time())
        if remaining <= 0:
            return text, kind
        ad = browser_ad(r["url"] or "", deadline=time.monotonic() + remaining)
    except Exception as exc:                    # noqa: BLE001 - unreadable now; asked again on a later run
        log.info("ingest: posting %s browser read failed: %s", r["id"], type(exc).__name__)
        return text, kind
    if len(ad.text) < max(200, len(text) + 1):
        return text, kind
    adtext.save_text(conn, r["id"], ad.text[:adtext.MAX_TEXT], "browser")
    return ad.text[:adtext.MAX_TEXT], "full"


def ad_text(conn, posting_id: int) -> str:
    """The stored full text (node 1 only admits jobs that have it)."""
    r = conn.execute("SELECT * FROM postings WHERE id=?", (posting_id,)).fetchone()
    text, kind = adtext.ensure_text(conn, r, allow_fetch=False)
    if kind != "full":
        raise RuntimeError(f"posting {posting_id}: full ad text is no longer available")
    return text
