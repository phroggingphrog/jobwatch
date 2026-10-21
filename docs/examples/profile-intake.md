# Profile intake: curl walk-through

A worked example of the native profile API (`/api/agent/profile`, contract in
[CHAT.md](../../pipeline/agentic/CHAT.md), decision in
[ADR 0002](../adr/0002-profile-intake-and-approval.md)). Every request and response below was
captured by running the real API with FastAPI's `TestClient` over a short invented CV and a
fake model transport. Nothing here is a real person's record, and no hosted model was called.

Conventions:

- Hex ids and digests are shortened to eight characters and an ellipsis (`6453d466…`) in
  responses. In the commands they are shell variables holding the full value from the earlier
  response (`$UPLOAD`, `$PID`, `$QID`, `$PROPOSAL_DIGEST`, `$SCOPE_DIGEST`). Send the full value.
- `$RUN_TOKEN` is a bearer token with the `run` and `read` scopes. `$APPROVE_TOKEN` also has
  `interact` and `approve`. The person always comes from the token; no request names one.
- Long lists are shortened where a line says `... N more ... omitted here`. Fields not marked so are verbatim.

The invented CV (`alex-cv.txt`):

```text
Alex Example
Accounts Assistant

Experience
Ledger Co, Accounts Assistant, 2021 - 2023
Reconciled supplier statements and prepared month-end journals.

Education
Diploma of Accounting, 2020
```

## 1. Upload a document

Kinds are `cv`, `letter` and `evidence`; types `.pdf .docx .txt .md`, up to 10 MiB. The file is
stored privately and does not touch the approved profile.

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/uploads \
  -H "Authorization: Bearer $RUN_TOKEN" \
  -F kind=cv -F file=@alex-cv.txt
```

HTTP 201:

```json
{
  "upload_id": "6453d466…",
  "sha256": "56e9af35…",
  "kind": "cv",
  "bytes": 190
}
```

## 2. Start a proposal (202, parsing)

The call returns at once with the standing questions listed and every section `unknown`. The
documents are read in the background (one paid parse per person at a time). A gap in a CV does
not establish unemployment, so employment status stays a question.

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/proposals \
  -H "Authorization: Bearer $RUN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"upload_ids": ["'"$UPLOAD"'"], "base_version": null}'
```

HTTP 202:

```json
{
  "id": "9c323854…",
  "revision": 1,
  "base_version": null,
  "uploads": [
    "56e9af35…"
  ],
  "facts": [
    {
      "id": "f1",
      "section": "employment_status",
      "value": "",
      "basis": "unknown",
      "sources": [],
      "note": "The documents do not state this.",
      "actor": "parser"
    },
    "... 6 more unknown-basis facts omitted here"
  ],
  "questions": [
    {
      "id": "q1",
      "section": "employment_status",
      "text": "Are you currently employed, studying, or between roles?",
      "why": "The documents do not state it, and a gap in a CV does not tell us."
    },
    {
      "id": "q2",
      "section": "availability",
      "text": "When can you start, and how many hours can you work?",
      "why": "Availability and notice period change which roles are realistic."
    },
    {
      "id": "q3",
      "section": "work_rights",
      "text": "What are your work rights in the places you want to work?",
      "why": "Roles that require specific work rights must be matched against this."
    },
    {
      "id": "q4",
      "section": "constraint",
      "text": "Are there limits on location, travel, hours or pay that a role must respect?",
      "why": "Hard limits decide whether a role is worth showing."
    },
    {
      "id": "q5",
      "section": "exclusion",
      "text": "Are there employers, industries or kinds of work you never want to see?",
      "why": "Exclusions remove roles before they are assessed."
    },
    {
      "id": "q6",
      "section": "career_focus",
      "text": "What kind of work do you want to be found for?",
      "why": "Your career focus decides what discovery looks for."
    },
    {
      "id": "q7",
      "section": "location",
      "text": "Where would you like to work (cities, regions, remote)?",
      "why": "Location limits which openings are shown."
    }
  ],
  "status": "parsing",
  "parse_error": ""
}
```

Seven standing questions are listed (all of them, verbatim); this is revision 1. Keep `id` and `revision`: they are needed for the next call.

## 3. Answer while the documents are being read

The person's own answer is accepted during the parse (`interact` scope, `expected_revision` from
the last read). It is recorded with `actor: person`, closes question `q3`, and bumps the revision to 2.

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/proposals/$PID/answers \
  -H "Authorization: Bearer $APPROVE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"expected_revision": 1, "question_id": "'"$QID"'", "text": "Australian citizen"}'
```

HTTP 200:

```json
{
  "id": "9c323854…",
  "revision": 2,
  "base_version": null,
  "uploads": [
    "56e9af35…"
  ],
  "facts": [
    {
      "id": "f1",
      "section": "employment_status",
      "value": "",
      "basis": "unknown",
      "sources": [],
      "note": "The documents do not state this.",
      "actor": "parser"
    },
    {
      "id": "f8",
      "section": "work_rights",
      "value": "Australian citizen",
      "basis": "evidence",
      "sources": [],
      "note": "stated by person",
      "actor": "person"
    },
    "... 5 more unknown-basis facts omitted here"
  ],
  "questions": [
    {
      "id": "q1",
      "section": "employment_status",
      "text": "Are you currently employed, studying, or between roles?",
      "why": "The documents do not state it, and a gap in a CV does not tell us."
    },
    {
      "id": "q2",
      "section": "availability",
      "text": "When can you start, and how many hours can you work?",
      "why": "Availability and notice period change which roles are realistic."
    },
    {
      "id": "q4",
      "section": "constraint",
      "text": "Are there limits on location, travel, hours or pay that a role must respect?",
      "why": "Hard limits decide whether a role is worth showing."
    },
    {
      "id": "q5",
      "section": "exclusion",
      "text": "Are there employers, industries or kinds of work you never want to see?",
      "why": "Exclusions remove roles before they are assessed."
    },
    {
      "id": "q6",
      "section": "career_focus",
      "text": "What kind of work do you want to be found for?",
      "why": "Your career focus decides what discovery looks for."
    },
    {
      "id": "q7",
      "section": "location",
      "text": "Where would you like to work (cities, regions, remote)?",
      "why": "Location limits which openings are shown."
    }
  ],
  "status": "parsing",
  "parse_error": ""
}
```

## 4. Read the merged draft

When the parse ends it merges into the draft: evidence-based facts carry the verbatim quote, line
and upload hash; the inferred career focus is labelled `inference`; the person's work-rights
answer is untouched and its question stays closed. Revision 3, `status` `draft`.

```bash
curl -s https://jobwatch.example.invalid/api/agent/profile/proposals/$PID \
  -H "Authorization: Bearer $RUN_TOKEN"
```

HTTP 200:

```json
{
  "id": "9c323854…",
  "revision": 3,
  "base_version": null,
  "uploads": [
    "56e9af35…"
  ],
  "facts": [
    {
      "id": "f1",
      "section": "employment_status",
      "value": "",
      "basis": "unknown",
      "sources": [],
      "note": "The documents do not state this.",
      "actor": "parser"
    },
    {
      "id": "f8",
      "section": "work_rights",
      "value": "Australian citizen",
      "basis": "evidence",
      "sources": [],
      "note": "stated by person",
      "actor": "person"
    },
    {
      "id": "f9",
      "section": "experience",
      "value": "Accounts Assistant, Ledger Co (2021-2023)",
      "basis": "evidence",
      "sources": [
        {
          "upload_sha256": "56e9af35…",
          "line": 5,
          "quote": "Ledger Co, Accounts Assistant, 2021 - 2023"
        }
      ],
      "note": "",
      "actor": "parser"
    },
    {
      "id": "f10",
      "section": "education",
      "value": "Diploma of Accounting (2020)",
      "basis": "evidence",
      "sources": [
        {
          "upload_sha256": "56e9af35…",
          "line": 9,
          "quote": "Diploma of Accounting, 2020"
        }
      ],
      "note": "",
      "actor": "parser"
    },
    {
      "id": "f11",
      "section": "career_focus",
      "value": "Accounts payable or bookkeeping roles",
      "basis": "inference",
      "sources": [
        {
          "upload_sha256": "56e9af35…",
          "line": 6,
          "quote": "Reconciled supplier statements and prepared month-end journals."
        }
      ],
      "note": "",
      "actor": "parser"
    },
    "... 4 more unknown-basis facts omitted here"
  ],
  "questions": [
    {
      "id": "q1",
      "section": "employment_status",
      "text": "Are you currently employed, studying, or between roles?",
      "why": "The documents do not state it, and a gap in a CV does not tell us."
    },
    {
      "id": "q2",
      "section": "availability",
      "text": "When can you start, and how many hours can you work?",
      "why": "Availability and notice period change which roles are realistic."
    },
    {
      "id": "q4",
      "section": "constraint",
      "text": "Are there limits on location, travel, hours or pay that a role must respect?",
      "why": "Hard limits decide whether a role is worth showing."
    },
    {
      "id": "q5",
      "section": "exclusion",
      "text": "Are there employers, industries or kinds of work you never want to see?",
      "why": "Exclusions remove roles before they are assessed."
    },
    {
      "id": "q7",
      "section": "location",
      "text": "Where would you like to work (cities, regions, remote)?",
      "why": "Location limits which openings are shown."
    }
  ],
  "status": "draft",
  "parse_error": ""
}
```

## 5. See exactly what confirming would do

The confirmation names the search scope and daily limits that discovery would run within, and
what it does not authorise. The two digests bind a later confirm to exactly this draft and scope.

```bash
curl -s https://jobwatch.example.invalid/api/agent/profile/proposals/$PID/confirmation \
  -H "Authorization: Bearer $RUN_TOKEN"
```

HTTP 200:

```json
{
  "proposal_digest": "9ea41a34…",
  "scope": {
    "basis": [
      "Accounts Assistant, Ledger Co (2021-2023)"
    ],
    "locations": [],
    "daily_assessments": 40,
    "daily_token_ceiling": 2000000
  },
  "scope_digest": "f5fd5e3d…",
  "authorises": [
    "discovery",
    "assessment"
  ],
  "does_not_authorise": [
    "document_preparation",
    "employer_messages",
    "submission"
  ]
}
```

## 6. Confirm (approve scope required)

A token without the `approve` scope is refused; model text is never approval.

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/proposals/$PID/confirm \
  -H "Authorization: Bearer $RUN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"proposal_digest": "'"$PROPOSAL_DIGEST"'", "scope_digest": "'"$SCOPE_DIGEST"'"}'
```

HTTP 403:

```json
{
  "detail": "scope_required"
}
```

With the approve token and both digests exactly as shown (a changed draft answers
`409 {"error": "proposal_changed"}`, a changed scope `409 {"error": "scope_changed"}`):

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/proposals/$PID/confirm \
  -H "Authorization: Bearer $APPROVE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"proposal_digest": "'"$PROPOSAL_DIGEST"'", "scope_digest": "'"$SCOPE_DIGEST"'"}'
```

HTTP 201:

```json
{
  "version": 1
}
```

Confirmation writes immutable version 1 and starts discovery and assessment within that scope.
It does not authorise document preparation, employer messages or submission.

## 7. Current profile and versions

```bash
curl -s https://jobwatch.example.invalid/api/agent/profile/ \
  -H "Authorization: Bearer $RUN_TOKEN"
```

HTTP 200:

```json
{
  "actor": "person",
  "base_version": null,
  "confirmed_at": "2026-10-21T09:56:17+00:00",
  "evidence_bundle_hash": "e8961aa9…",
  "facts": [
    {
      "actor": "parser",
      "basis": "unknown",
      "id": "f1",
      "note": "The documents do not state this.",
      "section": "employment_status",
      "sources": [],
      "value": ""
    },
    {
      "actor": "person",
      "basis": "evidence",
      "id": "f8",
      "note": "stated by person",
      "section": "work_rights",
      "sources": [],
      "value": "Australian citizen"
    },
    {
      "actor": "parser",
      "basis": "evidence",
      "id": "f9",
      "note": "",
      "section": "experience",
      "sources": [
        {
          "line": 5,
          "quote": "Ledger Co, Accounts Assistant, 2021 - 2023",
          "upload_sha256": "56e9af35…"
        }
      ],
      "value": "Accounts Assistant, Ledger Co (2021-2023)"
    },
    {
      "actor": "parser",
      "basis": "evidence",
      "id": "f10",
      "note": "",
      "section": "education",
      "sources": [
        {
          "line": 9,
          "quote": "Diploma of Accounting, 2020",
          "upload_sha256": "56e9af35…"
        }
      ],
      "value": "Diploma of Accounting (2020)"
    },
    {
      "actor": "parser",
      "basis": "inference",
      "id": "f11",
      "note": "",
      "section": "career_focus",
      "sources": [
        {
          "line": 6,
          "quote": "Reconciled supplier statements and prepared month-end journals.",
          "upload_sha256": "56e9af35…"
        }
      ],
      "value": "Accounts payable or bookkeeping roles"
    },
    "... 4 more unknown-basis facts omitted here"
  ],
  "file_sha256": {
    "interests_and_criteria.yaml": "b9cf6b82…",
    "master_resume.md": "35f83776…",
    "profile.yaml": "9ceb4844…"
  },
  "open_questions": [
    {
      "id": "q1",
      "section": "employment_status",
      "text": "Are you currently employed, studying, or between roles?",
      "why": "The documents do not state it, and a gap in a CV does not tell us."
    },
    {
      "id": "q2",
      "section": "availability",
      "text": "When can you start, and how many hours can you work?",
      "why": "Availability and notice period change which roles are realistic."
    },
    {
      "id": "q4",
      "section": "constraint",
      "text": "Are there limits on location, travel, hours or pay that a role must respect?",
      "why": "Hard limits decide whether a role is worth showing."
    },
    {
      "id": "q5",
      "section": "exclusion",
      "text": "Are there employers, industries or kinds of work you never want to see?",
      "why": "Exclusions remove roles before they are assessed."
    },
    {
      "id": "q7",
      "section": "location",
      "text": "Where would you like to work (cities, regions, remote)?",
      "why": "Location limits which openings are shown."
    }
  ],
  "proposal_digest": "9ea41a34…",
  "proposal_id": "9c323854…",
  "revision": 3,
  "schema": 1,
  "scope": {
    "basis": [
      "Accounts Assistant, Ledger Co (2021-2023)"
    ],
    "daily_assessments": 40,
    "daily_token_ceiling": 2000000,
    "locations": []
  },
  "scope_digest": "f5fd5e3d…",
  "uploads": [
    "56e9af35…"
  ],
  "version": 1
}
```

```bash
curl -s https://jobwatch.example.invalid/api/agent/profile/versions \
  -H "Authorization: Bearer $RUN_TOKEN"
```

HTTP 200:

```json
{
  "versions": [
    {
      "version": 1,
      "confirmed_at": "2026-10-21T09:56:17+00:00",
      "proposal_id": "9c323854…",
      "proposal_digest": "9ea41a34…",
      "evidence_bundle_hash": "e8961aa9…",
      "scope": {
        "basis": [
          "Accounts Assistant, Ledger Co (2021-2023)"
        ],
        "daily_assessments": 40,
        "daily_token_ceiling": 2000000,
        "locations": []
      },
      "uploads": [
        "56e9af35…"
      ]
    }
  ]
}
```

## 8. Onboarding an adopted profile

A hand-made `profile/` is adopted once with `jobwatch --user <name> profile adopt`. That makes
version 1 and protects the files from being overwritten, but it holds no confirmed facts and no
scope, so it authorises nothing: discovery stays off. The owner turns it on by onboarding on top
of that version, which is the same flow as above with `base_version` set to the current version.
This section runs it for a second, invented person (`$SAM_TOKEN`, `$SAM_APPROVE_TOKEN`) whose
`profile/` holds only a `profile.yaml` and a `master_resume.md`.

```bash
curl -s https://jobwatch.example.invalid/api/agent/profile/ \
  -H "Authorization: Bearer $SAM_TOKEN"
```

HTTP 200 (the adopted version: no facts, no scope):

```json
{
  "actor": "person",
  "adopted_files": ["master_resume.md", "profile.yaml"],
  "adopted_from_files": true,
  "confirmed_at": "2026-10-21T10:34:02+00:00",
  "evidence_bundle_hash": "38a0a81e…",
  "facts": [],
  "file_sha256": {
    "master_resume.md": "fca809f6…",
    "profile.yaml": "6ff85f9e…"
  },
  "open_questions": [],
  "proposal_id": null,
  "schema": 1,
  "uploads": [],
  "version": 1
}
```

The owner uploads a CV (step 1), or, in chat, offers the files already in `profile/`
(`profile_start` with `use_existing_files`), then starts a proposal on version 1:

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/proposals \
  -H "Authorization: Bearer $SAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"upload_ids": ["'"$UPLOAD"'"], "base_version": 1}'
```

HTTP 202: the pending draft, as in step 2, with `"base_version": 1`, the seven standing
questions and `"status": "parsing"`. Answer the questions while it is read (step 3). When the
parse ends, `GET /api/agent/profile/proposals/$PID` returns the merged draft (revision 2 here, no
answers given), `"status": "draft"` and `"base_version": 1`:

```json
{
  "id": "0b82bf28…",
  "revision": 2,
  "base_version": 1,
  "uploads": ["56e9af35…"],
  "facts": [
    "... f1 to f7: the seven unknown-basis facts, as in step 2, omitted here",
    {
      "id": "f8",
      "section": "experience",
      "value": "Accounts Assistant, Ledger Co (2021-2023)",
      "basis": "evidence",
      "sources": [
        {
          "upload_sha256": "56e9af35…",
          "line": 5,
          "quote": "Ledger Co, Accounts Assistant, 2021 - 2023"
        }
      ],
      "note": "",
      "actor": "parser"
    }
  ],
  "questions": ["... q1 to q7: the seven standing questions, still open, omitted here"],
  "status": "draft",
  "parse_error": ""
}
```

Until it is confirmed the adopted version still authorises nothing. The confirmation shows the
scope this draft would turn on (as in step 5):

```bash
curl -s https://jobwatch.example.invalid/api/agent/profile/proposals/$PID/confirmation \
  -H "Authorization: Bearer $SAM_TOKEN"
```

HTTP 200:

```json
{
  "proposal_digest": "36e42238…",
  "scope": {
    "basis": ["Accounts Assistant, Ledger Co (2021-2023)"],
    "locations": [],
    "daily_assessments": 40,
    "daily_token_ceiling": 2000000
  },
  "scope_digest": "f5fd5e3d…",
  "authorises": ["discovery", "assessment"],
  "does_not_authorise": ["document_preparation", "employer_messages", "submission"]
}
```

The owner confirms with the approve token and both digests exactly as shown:

```bash
curl -s -X POST https://jobwatch.example.invalid/api/agent/profile/proposals/$PID/confirm \
  -H "Authorization: Bearer $SAM_APPROVE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"proposal_digest": "'"$PROPOSAL_DIGEST"'", "scope_digest": "'"$SCOPE_DIGEST"'"}'
```

HTTP 201:

```json
{
  "version": 2
}
```

Version 2 records `"base_version": 1` and the scope shown; version 1 is unchanged. Discovery is
on only from this point. A proposal with nothing to search for (no evidence-backed experience, skill or career
focus) is refused when confirming with `409 {"error": "profile_incomplete"}`.

## Chat onboarding

The chat agent runs the same flow as a conversation. The person gives their documents (or offers
the files already in their `profile/`); the agent calls `profile_start`, which begins the background
parse, and meanwhile asks the open questions one at a time. `profile_answer` and `profile_correct`
record only the person's own words from their latest message; anything the agent made up is
refused with `not_person_words`. When the draft is ready the agent calls `profile_confirmation`
and shows the scope, daily limits and what is not authorised. `profile_confirm` is a gated tool:
the person's approval is bound to the exact `proposal_digest` and `scope_digest`, and a changed
draft fails with `approval_inputs_changed`. See "Guided onboarding in the chat agent" in CHAT.md.

## CLI for existing installs

```bash
jobwatch --user <name> profile adopt                 # existing profile/ files become version 1 (no scope; discovery stays off)
```

Discovery for that person stays off until a version carries a confirmed scope. Onboard with a
proposal built on the current version (section 8, or the chat agent), then confirm the scope shown.
