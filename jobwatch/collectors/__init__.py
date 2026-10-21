"""Collectors. Each module exposes NAME and `collect(cfg, since) -> list[Posting]`.

`cfg` is a CollectorContext (see base.py): it carries the HTTP fetcher, the config,
the employer registry, a per-run limit, an error list, and a title pre-check.
"""
from importlib import import_module

COLLECTORS = [
    "jobspy_src", "seek", "jora",
    "ats_greenhouse", "ats_lever", "ats_ashby", "ats_workable", "ats_smartrecruiters",
    "ats_workday", "ats_pageup", "ats_employmenthero", "ats_scouttalent",
    "ats_oracle", "ats_successfactors", "ats_phenom", "ats_atlassian", "careers_vic",
    "ats_pulse", "ats_recruitmenthub", "ats_jobs_search", "ats_elmo", "ats_techone",
    "jsonld_pages", "rss", "reddit",
]


def get(name: str):
    if name not in COLLECTORS:
        raise KeyError(f"unknown collector {name!r}; known: {', '.join(COLLECTORS)}")
    return import_module(f"{__name__}.{name}")
