# Decision policy: workflow example

This walk-through uses invented data. The person is `example-a`, the adverts are invented, and no model or network call was made. The output is from running the policy endpoint and the gate on those inputs through the test client. It shows how the code behaves. It makes no claim about matching quality.

The flag defaults to `legacy`, which keeps the fixed gate and changes nothing. The examples show both modes side by side. Set `pipeline.agentic.decision_policy: profile` in `config/jobwatch.yaml` to use the policy.

## 1. The confirmed profile

The approved version (version 1) holds three facts relevant to the policy, and no location:

| Fact | Basis | Value |
|---|---|---|
| Employment status | evidence | "Currently unemployed and looking for work" |
| Exclusion | evidence | `{"kind": "family", "value": "accounting"}` |
| Exclusion | evidence | "no night shifts" (free text) |

## 2. The policy endpoint

`GET /api/agent/profile/policy`, with a read-scoped token, returns the policy the gate would use and the open questions:

```json
{
  "policy": {
    "profile_version": 1,
    "strategy": "employment_first",
    "focus": [],
    "exclusions": [
      {"rule_id": "f10:family", "kind": "family", "value": "accounting",
       "source_fact_id": "f10", "actor": "person"}
    ],
    "home": null,
    "max_commute_km": null,
    "remote_ok": null,
    "work_rights": {},
    "seniority": [],
    "open_questions": ["work_rights", "location", "exclusion:f11"],
    "policy_hash": "f83e7147…",
    "regions": []
  },
  "mode": "legacy",
  "enabled": false,
  "open_questions": [
    {"code": "work_rights", "question": "What are your work rights in the places you want to work?",
     "why": "Roles that require specific work rights must be matched against this."},
    {"code": "location", "question": "Where would you like to work (cities, regions, remote)?",
     "why": "Location limits which openings are shown."},
    {"code": "exclusion:f11",
     "question": "Is 'no night shifts' an employer, a kind of work, a place, a job family or a title word? Until you say, it is not applied as a rule.",
     "why": "Only an exclusion given with its kind is applied as a rule."}
  ]
}
```

The policy hash is shortened to its first eight characters. Points to note:

- **Strategy `employment_first`** comes from the unemployment statement with no employment status to the contrary.
- **The structured exclusion** is the one rule. The free-text exclusion is not a rule. It stays an open question until the person gives it a kind.
- **`work_rights` is also open.** No work-rights fact was given, so the endpoint asks for one.
- **`mode` and `enabled` reflect the flag.** With the flag unset they read `legacy` and `false`. With `profile` they read `profile` and `true`. Nothing else in the response changes.

## 3. Three adverts through the gate

The adverts are invented:

- **Advert 1:** "Junior Office Coordinator", Melbourne VIC, family `back_office_admin`.
- **Advert 2:** "Graduate Accounting Analyst", Melbourne VIC, family `accounting`. This names the excluded family.
- **Advert 3:** "Junior Office Coordinator", location "Level 3, 1 Example St", with no resolvable location.

Results for `example-a`, who has no location:

| Advert | Mode | Route | Reason | Policy excluded it |
|---|---|---|---|---|
| 1 | legacy | draft | eligible | no |
| 1 | profile | draft | eligible | no |
| 2 | legacy | draft | eligible | no |
| 2 | profile | archive | policy_excluded | yes (rule `f10:family`) |
| 3 | legacy | hold | insufficient_evidence | no |
| 3 | profile | draft | eligible | no |

Results for `example-b`, the same person with the location "Melbourne, VIC" added:

| Advert | Mode | Route | Reason | Policy excluded it |
|---|---|---|---|---|
| 1 | legacy | draft | eligible | no |
| 1 | profile | draft | eligible | no |
| 2 | legacy | draft | eligible | no |
| 2 | profile | archive | policy_excluded | yes (rule `f10:family`) |
| 3 | legacy | hold | insufficient_evidence | no |
| 3 | profile | hold | insufficient_evidence | no |

What the tables show:

- **Advert 2 is excluded only in `profile` mode.** The `legacy` gate drafts it. The legacy path does not carry this person's structured family exclusion into its own checks (see Limits).
- **Advert 3 holds in profile mode only when the person has a location.** Without a location fact, the location check does not run, so an unresolvable location is not a reason to hold. The location question remains open. With a location fact, an unresolvable location holds instead of archiving.

## Limits

- Distance uses place data for Victoria only. Other states resolve by state name, state code or capital city, and an unresolved location holds.
- The product remains Australia-only.
- Only the structured `{kind, value}` exclusion becomes a rule. Free text is never enforced until the person classifies it.
- **Legacy gap:** the legacy projection (`jobwatch/candidate/projection.py`) builds `excluded_families` from the text of each exclusion fact. For a structured fact that text is `"family, accounting"`, which matches no known family, so the family is dropped. Under `legacy` a structured family exclusion is therefore not applied (a bare family name typed as text still is). This is a known limitation of Plan 1 code, not changed in this phase.
- Collection pre-filters, `_target_first`, near-duplicate embeddings, the `north_star < 3` score gate and the preference-model families are unchanged.
- Nothing here was measured on real postings. No matching-quality claim is made.

## Undo

Set `pipeline.agentic.decision_policy: legacy` to restore the current gate immediately. To remove the table written in `profile` mode, run `DROP TABLE IF EXISTS gate_decisions` on the person's database.
