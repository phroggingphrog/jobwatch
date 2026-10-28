"""TechnologyOne Recruitment "RaaS" job list behind a council's own careers page (registry provider: techone).

Bendigo's careers page (bendigo.vic.gov.au/about-us/working-city) fills its vacancy list in the browser from an
anonymous JSON call, the same one any visitor makes:
  GET {api_url} -> {"DataSet": [{"JOBID","TITLE","ORGANISATIONUNIT","EMPLOYEETYPECODECODE","EMPLOYEECLASS",
                                 "PUBLISHDATE","EXPIRYDATE","RESOLVEDAPPLYURL"}], "TotalRecordCount": n}
The t1cloud portal pages themselves are NOT read (robots.txt on *.t1cloud.com disallows everything).
Registry fields: api_url (copy it from the council page's script), careers_url, state. The ION API host
serves no robots.txt (400), and this is a data endpoint, not a page. RESOLVEDAPPLYURL carries a token, so the
posting id is JOBID.
"""
from __future__ import annotations

from ..models import Posting, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_techone"


def parse_dataset(data: dict, employer: dict) -> list[Posting]:
    out = []
    for job in data.get("DataSet") or []:
        if not job.get("JOBID") or not job.get("TITLE"):
            continue
        posted = iso(job.get("PUBLISHDATE"))
        url = job.get("RESOLVEDAPPLYURL") or employer.get("careers_url") or ""
        out.append(Posting(
            source=NAME, source_id=f"{employer.get('name')}:{job['JOBID']}", url=url, title=job["TITLE"],
            company=employer.get("name", ""), location=employer.get("location") or "", state=employer.get("state") or None,
            work_type=work_type_of(job.get("EMPLOYEETYPECODECODE"), job.get("EMPLOYEECLASS")),
            posted_at=posted, posted_at_source="provider" if posted else "observed",
            description=" | ".join(str(job.get(k)) for k in ("ORGANISATIONUNIT", "EMPLOYEETYPECODECODE", "EMPLOYEECLASS")
                                   if job.get(k)),
            raw={k: job.get(k) for k in ("JOBID", "TITLE", "ORGANISATIONUNIT", "EMPLOYEETYPECODECODE", "EMPLOYEECLASS",
                                         "MINIMUMGRADECODE", "PUBLISHDATE", "EXPIRYDATE")},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    data = cfg.http.get_json(employer["api_url"])
    cfg.count_raw(len(data.get("DataSet") or []))
    return parse_dataset(data, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "techone", fetch_one)
