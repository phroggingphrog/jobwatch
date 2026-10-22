# Explained shortlist — synthetic API example

**Status:** Source implementation is available on this branch. Full-suite verification and review/PR are pending. This example contains invented records; it is not a captured runtime response and makes no claim about recommendation quality.

The shortlist uses the current stored evaluation only after rechecking it through the canonical gate with the person's confirmed profile. In this example, all three invented postings receive current `draft/eligible` decisions, so each may enter the candidate pool. A `hold/insufficient_evidence` decision can enter only as `needs_clarification`; a hard gate, confirmed exclusion, closed posting, stale run, or enforced current relevance failure excludes a posting.

The profile is confirmed at version 4 and has employment-first strategy. There is no valid preference fit, so ordering is provisional. The example uses no model call, invents no candidate facts, records no owner choice, and does not use the holistic score to set labels or order.

## Read the list

Planned request (scope `read`):

```http
GET /api/agent/shortlist?limit=20&offset=0
```

This is an abbreviated view of the source response shape. Identifiers and timestamps are invented; shortlist/entry IDs use the source's 32-character form, while content hashes use 64 hexadecimal characters. The actual entry objects contain the full `ShortlistEntry` fields, including exact citation objects and all requirement rows.

```json
{
  "status": "ok",
  "shortlist_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "built_at": "2026-10-22T12:00:00+00:00",
  "content_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "profile_version": 4,
  "ordering": "provisional",
  "rules_version": "ranking-rules-v1",
  "score_policy": "advisory",
  "total": 3,
  "labels": {
    "stronger_match": 1,
    "stretch": 1,
    "needs_clarification": 1
  },
  "excluded": {},
  "open_questions": [],
  "meaning": "Labels and order describe evidence fit and, when personalised, learned preference among alternatives; they are not hiring probability or approval to apply.",
  "ordering_basis": {
    "preference": {
      "origin": "owner",
      "status": "no_data",
      "n_sets": 0,
      "n_choices": 0,
      "n_train": 0,
      "n_holdout": 0,
      "historical_choices": 0,
      "stale_choices": 0,
      "minimum_train": 20,
      "minimum_holdout": 5
    },
    "response_time": {
      "status": "insufficient_history",
      "responses": 0,
      "censored": 0,
      "minimum_responses": 30,
      "model": "none",
      "selection_bias": "Applications are chosen by the owner; this describes applied jobs only.",
      "reason": "insufficient_history"
    }
  },
  "entries": [
    {
      "entry_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "posting_id": 101,
      "label": "stronger_match",
      "rank": 1,
      "ordering": "provisional",
      "rank_reason": "stronger_match; evidence coverage 1.00–1.00; provisional: evidence coverage and current relevance within evidence tiers. Ties use posting id.",
      "uncertainty": "0 of 25 answered comparisons; provisional evidence ordering. Personalisation requires a valid genuine fit with complete utilities.",
      "objective_fit": "employment-first; evidence coverage 1.00–1.00 (stronger_match).",
      "holistic_score": 2.7,
      "utility": null,
      "coverage": {
        "weighted": 1.0,
        "demonstrated": 2,
        "partial": 0,
        "unknown": 0,
        "contradicted": 0,
        "mandatory_unmet": [],
        "missing_documentation": [],
        "real_gaps": [],
        "conflicts": [],
        "weighted_upper": 1.0,
        "unresolved_share": 0.0,
        "weight_total": 5,
        "without_judgment": 0,
        "mandatory_unknown": [],
        "mandatory_partial": [],
        "mandatory_conflicts": []
      },
      "posting": {
        "title": "Operations Coordinator",
        "company": "Example North Services",
        "location": "Melbourne VIC",
        "url": "https://example.invalid/jobs/101",
        "work_type": "full_time",
        "salary_text": null
      }
    },
    {
      "entry_id": "cccccccccccccccccccccccccccccccc",
      "posting_id": 102,
      "label": "stretch",
      "rank": 2,
      "ordering": "provisional",
      "rank_reason": "stretch; evidence coverage 0.79–0.79; provisional: evidence coverage and current relevance within evidence tiers. Ties use posting id.",
      "uncertainty": "0 of 25 answered comparisons; provisional evidence ordering. Personalisation requires a valid genuine fit with complete utilities.",
      "objective_fit": "employment-first; evidence coverage 0.79–0.79 (stretch).",
      "holistic_score": 4.6,
      "utility": null,
      "coverage": {
        "weighted": 0.7857142857142857,
        "demonstrated": 1,
        "partial": 1,
        "unknown": 0,
        "contradicted": 0,
        "mandatory_unmet": ["r2"],
        "missing_documentation": [],
        "real_gaps": ["r2"],
        "conflicts": [],
        "weighted_upper": 0.7857142857142857,
        "unresolved_share": 0.0,
        "weight_total": 7,
        "without_judgment": 0,
        "mandatory_unknown": [],
        "mandatory_partial": ["r2"],
        "mandatory_conflicts": []
      },
      "posting": {
        "title": "Service Planning Officer",
        "company": "Example Civic Group",
        "location": "Geelong VIC",
        "url": "https://example.invalid/jobs/102",
        "work_type": "full_time",
        "salary_text": null
      }
    },
    {
      "entry_id": "dddddddddddddddddddddddddddddddd",
      "posting_id": 103,
      "label": "needs_clarification",
      "rank": 3,
      "ordering": "provisional",
      "rank_reason": "needs_clarification; evidence coverage 0.60–1.00; provisional: evidence coverage and current relevance within evidence tiers. Ties use posting id.",
      "uncertainty": "0 of 25 answered comparisons; provisional evidence ordering. Personalisation requires a valid genuine fit with complete utilities.",
      "objective_fit": "employment-first; evidence coverage 0.60–1.00 (needs_clarification).",
      "holistic_score": 4.9,
      "utility": null,
      "coverage": {
        "weighted": 0.6,
        "demonstrated": 1,
        "partial": 0,
        "unknown": 1,
        "contradicted": 0,
        "mandatory_unmet": [],
        "missing_documentation": ["r2"],
        "real_gaps": [],
        "conflicts": [],
        "weighted_upper": 1.0,
        "unresolved_share": 0.4,
        "weight_total": 5,
        "without_judgment": 0,
        "mandatory_unknown": [],
        "mandatory_partial": [],
        "mandatory_conflicts": []
      },
      "posting": {
        "title": "Reporting Assistant",
        "company": "Example River Works",
        "location": "Ballarat VIC",
        "url": "https://example.invalid/jobs/103",
        "work_type": "full_time",
        "salary_text": null
      }
    }
  ]
}
```

The labels follow the rules. Entry 101 has demonstrated high (weight 3) and meaningful (weight 2) requirements, giving coverage 1.00. Entry 102 has a demonstrated critical requirement (weight 4) and a partial mandatory high requirement (weight 3), giving `(4 + 3×0.5)/7 = 0.7857`; the mandatory partial makes it a stretch despite coverage above two thirds. Entry 103 has demonstrated high weight 3 and unknown meaningful weight 2, giving coverage 0.60, upper bound 1.00 and unresolved share 0.40; the unknown share exceeds one third, so it needs clarification.

The visible `score_policy: advisory` field is summary metadata emitted by the current source. It is not a configurable switch. Holistic scores are carried for comparison and are not inputs to labels or ordering. The lower-scoring stronger match remains first; higher scores do not move the stretch or clarification entry above it.

## Inspect an entry

Planned detail request (scope `read`):

```http
GET /api/agent/shortlist/102
```

The endpoint returns the full `ShortlistEntry`; below is its requirement-detail excerpt. Each requirement row contains the serialized requirement fields and a nested `match` object. Citation hashes and IDs are synthetic.

```json
{
  "posting_id": 102,
  "label": "stretch",
  "requirements": [
    {
      "id": "r1",
      "text": "Coordinate service schedules",
      "tier": "stated",
      "importance": "critical",
      "jd_signal": {
        "source_id": "ad-102",
        "content_hash": "1111111111111111111111111111111111111111111111111111111111111111",
        "quote": "Coordinate service schedules for the regional team."
      },
      "blocker": false,
      "match": {
        "requirement_id": "r1",
        "match": "strong",
        "evidence": [
          {
            "source_id": "ev-31",
            "content_hash": "2222222222222222222222222222222222222222222222222222222222222222",
            "quote": "Coordinated weekly schedules for a team of twelve."
          }
        ],
        "risk": "",
        "mitigation": "",
        "judgment": {
          "status": "demonstrated",
          "rationale": "The approved record directly supports schedule coordination.",
          "reviewed_evidence_ids": ["ev-31"],
          "contradiction_evidence": [],
          "open_question": ""
        }
      }
    },
    {
      "id": "r2",
      "text": "Hold a current project management certification",
      "tier": "stated",
      "importance": "high",
      "jd_signal": {
        "source_id": "ad-102",
        "content_hash": "1111111111111111111111111111111111111111111111111111111111111111",
        "quote": "A current project management certification is required."
      },
      "blocker": true,
      "match": {
        "requirement_id": "r2",
        "match": "partial",
        "evidence": [
          {
            "source_id": "ev-08",
            "content_hash": "3333333333333333333333333333333333333333333333333333333333333333",
            "quote": "Completed three units toward the project management certificate."
          }
        ],
        "risk": "The approved record shows study in progress, not a current award.",
        "mitigation": "Ask whether the candidate has since completed the certification.",
        "judgment": {
          "status": "partial",
          "rationale": "Study is documented, but completion is not.",
          "reviewed_evidence_ids": ["ev-08"],
          "contradiction_evidence": [],
          "open_question": "Complete project management certification is not evidenced."
        }
      }
    }
  ]
}
```

The credential in progress is not represented as complete. Because the requirement is mandatory and partial, the label is `stretch`; a mandatory contradiction would instead exclude the posting.

## Refresh and limits

The implemented source includes a run-scoped, database-only refresh. It reuses a result younger than 60 seconds only when the complete snapshot is unchanged. It makes no model call, triggers no paid work, and does not create feedback or fit records. The response includes the current list header and a `rebuilt` boolean. Full-suite verification and independent review remain pending.

All names, IDs, hashes, timestamps, employers, locations, ads, profile facts, quotations, scores and response content above are invented. The example illustrates source schema and rule arithmetic only. It does not establish real-world eligibility accuracy, recommendation quality, model behavior, or deployment.
