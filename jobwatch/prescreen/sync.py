"""Write the confirmed profile into prescreen_rules (rows with source='profile'), so the engine reads rules, not the profile.

Runs when a policy differs from the one last written (profile version + policy hash). The mapping below is translation of
profile facts into rule parameters; it names no occupation, place or person. Returns the number of rules written.
"""
from __future__ import annotations

import json

from . import store

LADDER = ("entry", "junior", "mid", "senior", "executive")
PROJECTION_VERSION = 2
SYNC_KEY = "prescreen_profile_sync"
_WORK_TYPES = {"casual": "casual", "part_time": "part_time", "full_time": "full_time"}


def _rules_for(policy) -> list[tuple[str, dict, str]]:
    out: list[tuple[str, dict, str]] = []
    approved = [x for x in policy.seniority if x in LADDER]
    if approved:
        if "senior" in approved:
            approved.append("executive")
        out.append(("level_not_approved", {
            "ladder": list(LADDER), "approved": approved, "tolerance_below": 1,
            "tolerance_above": 1 if max(LADDER.index(x) for x in approved) == 0 else 0,   # "junior" is not far from "entry"
            "legacy_reason": "seniority",
            "reason": "Title says \"{matched}\" ({value} level); your approved levels are: {approved}."}, "skip"))
        # Approved levels do not establish a maximum required experience duration.
        # Numeric years_over rules remain available for an explicitly confirmed strategy.
    if policy.regions:
        out.append(("region_outside", {
            "regions": [*policy.regions, "AU"],      # "AU": a country-level mention ("Australia-wide") is inside every Australian region
            "region_labels": ", ".join(policy.regions), "remote_ok": policy.remote_ok, "remote_exempt_tags": ["au_state"], "legacy_reason": "location",
            "reason": "Location \"{matched}\" is outside your regions ({region_labels})."}, "skip"))
    if policy.home and policy.max_commute_km is not None:
        out.append(("term_hit", {"measurement": "distance", "category": "location_outside",
            "home": policy.home['place'], "limit": policy.max_commute_km, "remote_ok": policy.remote_ok,
            "legacy_reason": "location", "reason": "Location \"{matched}\" is {km} straight-line km from your approved home, beyond {limit} km."}, "skip"))
    families = sorted({r.value for r in policy.exclusions if r.kind == "family"})
    if families:
        out.append(("term_hit", {
            "category": "off_target_occupation", "values": families, "match": "all", "legacy_reason": "off_target",
            "reason": "Title \"{matched}\" is {value} work, which you excluded."}, "skip"))
    blocked_types = sorted({_WORK_TYPES[r.value] for r in policy.exclusions if r.kind == "work_type" and r.value in _WORK_TYPES})
    wr = policy.work_rights or {}
    limit = wr.get("hours_limit_per_fortnight")
    if isinstance(limit, (int, float)) and limit > 0 and "full_time" not in blocked_types:
        rule = {"category": "employment_type", "values": ["full_time"], "match": "all", "legacy_reason": "employment_type",
                "reason": "The posting is {value} only; your confirmed work rights allow up to {limit} hours a fortnight.",
                "limit": limit}
        if wr.get("full_time_programs_ok") is True:
            rule["program_exception"] = True
        out.append(("term_hit", rule, "flag"))
        out.append(("term_hit", {"measurement": "hours", "category": "employment_type",
            "limit": limit, "program_exception": wr.get("full_time_programs_ok") is True,
            "legacy_reason": "employment_type",
            "reason": "The ad states {hours} hours per fortnight (\"{matched}\"), exceeding your approved limit of {limit}."}, "skip"))
    if blocked_types:
        out.append(("term_hit", {
            "category": "employment_type", "values": blocked_types, "match": "all", "legacy_reason": "employment_type",
            "reason": "The posting is {value}, which you excluded."}, "skip"))
    blocked_rights = []
    if wr.get("citizen_or_pr") is False:
        blocked_rights += ["citizen_or_pr", "citizen_only"]
    elif wr.get("citizen") is False:
        blocked_rights += ["citizen_only"]
    if wr.get("requires_sponsorship") is True:
        blocked_rights.append("no_sponsorship")
    if wr.get("unrestricted_work_rights") is False:
        blocked_rights.append("unrestricted_work_rights")
    if blocked_rights:
        out.append(("term_hit", {
            "category": "work_rights", "values": sorted(set(blocked_rights)), "match": "any", "legacy_reason": "work_rights",
            "reason": "The ad requires {value} (\"{matched}\"), which your confirmed work rights do not meet."}, "skip"))
    return out


def sync_profile(conn, policy) -> int:
    key = None if policy is None else [policy.profile_version, policy.policy_hash, PROJECTION_VERSION]
    row = conn.execute("SELECT value FROM state WHERE key=?", (SYNC_KEY,)).fetchone()
    if row and json.loads(row[0]) == key:
        return 0
    conn.execute("DELETE FROM prescreen_rules WHERE source='profile'")
    n = 0
    if policy is not None:
        for kind, params, effect in _rules_for(policy):
            conn.execute("INSERT INTO prescreen_rules(kind,params_json,effect,enabled,scope,derived_from_profile_version,source,created_at) "
                         "VALUES(?,?,?,1,'person',?,'profile',?)",
                         (kind, json.dumps(params, sort_keys=True), effect, policy.profile_version, store._now()))
            n += 1
    conn.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (SYNC_KEY, json.dumps(key)))
    conn.commit()
    return n
