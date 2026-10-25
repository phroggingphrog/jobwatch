# Feedback and selected preparation — synthetic API example

**Status:** Source implementation, local checks and independent review are complete;
merge is tracked in PR #24. This walkthrough uses invented
IDs and values. It is not a captured response and makes no quality or deployment
claim. Prompt reads and HTTP selection acceptance do not call a model. After
acceptance, the authenticated worker prepares packages through existing approved
paid routes and execution budgets; the example does not run that worker.

The authenticated native API derives the person from the bearer principal. The
client does not supply a person ID. Human feedback uses `interact`; profile-rule
confirmation and selection use `approve`. Each write includes an idempotency key.

## Reject and restore a shortlist entry

The person rejects the current entry for synthetic posting `42`:

```http
POST /api/agent/shortlist/42/feedback
Authorization: Bearer <person-token>
Idempotency-Key: demo-reject-001
Content-Type: application/json
```

```json
{
  "expected_entry_id": "entry-demo-42",
  "reason_code": "not_this_employer",
  "reason_text": ""
}
```

The API checks that the entry is still current, then appends a person-authored
event and returns the rebuilt shortlist. The event retains its reason, source,
entry, run and profile provenance. An identical retry returns the same event; a
changed payload under the same key conflicts.

Restoration is a separate append-only action. It must name the exact active
rejection event:

```http
POST /api/agent/shortlist/42/restore
Authorization: Bearer <person-token>
Idempotency-Key: demo-restore-001
Content-Type: application/json
```

```json
{
  "expected_rejection_id": 123
}
```

Restore lifts the dismissal for that posting. The next shortlist still uses
current inputs and canonical eligibility; restoration does not revive a stale
entry or bypass an eligibility decision.

## Propose and confirm an exclusion

The person can propose a rule amendment. Supported kinds are `family`,
`employer`, `title_term`, `location` and `work_type`.

```http
POST /api/agent/profile/rules
Authorization: Bearer <person-token>
Idempotency-Key: demo-rule-001
Content-Type: application/json
```

```json
{
  "op": "add",
  "kind": "employer",
  "value": "Example North Services"
}
```

The response contains a proposal ID and digest tied to the current approved
profile version and hash. The person confirms those exact proposal bytes:

```http
POST /api/agent/profile/rules/<proposal-id>/confirm
Authorization: Bearer <person-token>
Content-Type: application/json
```

```json
{
  "rule_digest": "<digest-returned-by-the-proposal>"
}
```

The confirmation creates a new approved profile version. Its response reports
that assessments are stale until reprocessed. A profile change between proposal
and confirmation invalidates the proposal. This flow creates no fit and performs
no model call.

## Answer a prompt

At most one prompt of either type may be open. The default cap is three prompt
issuances in a rolling seven days; configuration can lower it or disable all
prompts. A repeated question has a 30-day default cooldown, which configuration
may lengthen.

```http
POST /api/agent/prompts/next
Authorization: Bearer <person-token>
```

This issues the next bounded system prompt when one is due. Read the current
outstanding prompt without issuing another with `GET /api/agent/prompts/next`;
`GET /api/agent/prompts` returns prompt history.

When a comparison is available, it presents three eligible, unseen jobs and a
“none” option. Selection considers at most nine unseen candidates. A current
valid preference posterior with canonical validation selects a comparison by
expected information gain. Without that posterior, deterministic cold start uses
feature disagreement. The displayed set is pinned to the profile, policy and
input manifest; if these change, the prompt becomes stale.

The person may choose one of the displayed posting IDs or `null` for “none”:

```http
POST /api/agent/prompts/<prompt-id>/pick
Authorization: Bearer <person-token>
Idempotency-Key: demo-pick-001
Content-Type: application/json
```

```json
{
  "selected": null
}
```

A free-text question is answered separately. The answer remains verbatim
feedback; it does not automatically become a profile fact.

```http
POST /api/agent/prompts/<prompt-id>/answer
Authorization: Bearer <person-token>
Idempotency-Key: demo-answer-001
Content-Type: application/json
```

```json
{
  "text": "I can consider this condition for now."
}
```

Prompt responses are bound to the displayed subject and the current manifest.
Identical retries preserve the original response; reusing the request key with
different input conflicts.

## Select jobs for preparation

Selection requires one to ten currently eligible entries and binds each one to
its current shortlist entry ID and run key:

```http
POST /api/agent/selections
Authorization: Bearer <person-token>
Idempotency-Key: demo-selection-001
Content-Type: application/json
```

```json
{
  "posting_ids": [42, 43],
  "expected_entry_ids": {
    "42": "entry-demo-42",
    "43": "entry-demo-43"
  },
  "expected_run_keys": {
    "42": "run-key-demo-42",
    "43": "run-key-demo-43"
  }
}
```

Before accepting the request, the service checks current eligibility, entry IDs,
run keys and a pinned preparation manifest. The response starts in
`pending_dispatch`; `run_id` may be null. The durable selection record is
committed with person-authored selection events before a worker dispatches it.
Dispatch rechecks the manifest and eligibility. A full queue leaves the request
pending; changed inputs fail it. The approval expires after 24 hours.

The API run store uses the stable selection ID as its idempotency key, so recovery
after a cross-store interruption can find the existing run rather than create a
duplicate. `GET /api/agent/selections/<selection-id>` shows the request state and,
once queued, the public run with saved artifact references. The owner can cancel
through `POST /api/agent/selections/<selection-id>/cancel`; chat uses its gated
`cancel_selection` tool.

In chat, `prepare_application` for one posting uses this same durable selection
path; `select_jobs` covers a group, and `selection_status` reads it. These writes
are gated by an exact-payload human interrupt. Question text must match words
supplied by the person. The model cannot invent an answer or approve changed
inputs. HTTP acceptance and dispatch do not call a model; package preparation
later runs in the authenticated worker using existing paid routes and execution
budgets. Selection authorizes preparation only. Submit is a separate step: the owner clicks it, or
confirms the exact reviewed form (board button or chat) so Jobwatch presses it.

Feedback history and selection status are scoped to the authenticated person.
This Phase 6 example does not expose evaluation reports or holdout results;
private Phase 7 reports remain outside this implementation scope.

The [release audit](../audits/2026-10-23-feedback-selection.md) records actual
native API/chat package checks, independent review and the complete local suite:
**3758 passed, 11 skipped**. Synthetic checks establish workflow behavior, not
real recommendation quality.
