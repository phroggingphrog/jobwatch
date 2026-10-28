"""SAP SuccessFactors Career Site Builder feeds (registry provider: successfactors), slow tier.

Registry fields: feed_url (usually https://{host}/googlefeed.xml, RSS 2.0, every live job,
1-3 MB), name, optional company. The location sits at the end of each title
("Store Team Member (Chadstone, VIC, AU, 3148)"); rss.parse_successfactors splits it off and
drops non-AU rows (ANZ, Kmart and Chemist Warehouse feeds include NZ). The feeds carry no
posted date, so postings are observed-dated and the first read only seeds the DB.
Conditional GET (ETag / Last-Modified) is used when the server supports it.
"""
from __future__ import annotations

from ..models import Posting
from .base import CollectorContext, run_per_employer
from .rss import fetch_conditional, parse_successfactors

NAME = "ats_successfactors"


def fetch_one(cfg: CollectorContext, employer: dict):
    url = employer.get("feed_url") or f"https://{employer['host']}/googlefeed.xml"
    text = fetch_conditional(cfg, url)
    if text is None:                       # 304: unchanged since last poll
        return []
    cfg.count_raw(text.count("<item>") + text.count("<item "))
    return parse_successfactors(text, employer, source=NAME)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "successfactors", fetch_one)
