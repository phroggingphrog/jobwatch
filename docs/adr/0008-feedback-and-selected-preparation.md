# ADR 0008: Human feedback and selected preparation

**Status:** Implemented, locally verified and independently reviewed (2026-10-23).
Release evidence is in [the Phase 6 audit](../audits/2026-10-23-feedback-selection.md);
merge is tracked in PR #24.

## Context

The native agent API needs to record a person's response to a shortlist, allow a
rejection to be restored, collect confirmed policy amendments, and prepare jobs
the person selects. These actions must retain their human origin and exact input
context. They do not change canonical eligibility, turn model text into approval,
or authorize application submission.

The decision is implemented in the shared feedback, rules, prompt and selection
operations. The synthetic walkthrough is in the [feedback and selection
example](../examples/feedback-selection.md). This ADR records the current source
contract; parent verification is still required before release claims.

## Decision

1. **Human origin.** Domain writes require `actor='person'`. The native API takes
   identity from its authenticated principal and assigns the actor server-side.
   Chat tools call the same domain operations behind exact-payload human approval
   interrupts. Question answers must match words supplied by the person. Feedback
   and prompt writes use the `interact` scope; rule proposals use `interact`,
   rule confirmation and selected preparation use `approve`. Clients provide
   idempotency keys and exact expected entry/run identifiers where needed.
2. **Append-only feedback.** Feedback events are per person, carry source and
   provenance, and cannot be updated or deleted. A rejection refers to the
   current shortlist entry. A later restore appends a new event naming the exact
   active rejection. Restore releases that posting dismissal only; it does not
   revive an old snapshot or bypass eligibility. Identical retries replay the
   original event, while a reused request key with changed input conflicts.
3. **Confirmed policy amendments.** Supported exclusion kinds are `family`,
   `employer`, `title_term`, `location` and `work_type`. Proposing an add or
   withdrawal creates a per-person, digest-bound proposal tied to the current
   approved profile hash and version. Approval must confirm that digest while the
   base profile is still current. Confirmation creates a new immutable approved
   profile version; existing assessments become stale until reprocessed. Active
   approved exclusion facts are carried through full profile confirmation.
   Repeating a prior successful confirmation does not project its older files
   over a later profile version.
4. **Prompt limits and comparison.** `POST /api/agent/prompts/next` issues a
   bounded system prompt under `read` scope. `GET` on the same path only reads
   the outstanding prompt; `GET /api/agent/prompts` reads history. At most one
   prompt of either type can be open for a person. The default issuance cap is
   three prompts in a rolling
   seven-day window; configuration may lower it or disable prompts. The default
   repeated-question cooldown is 30 days; configuration may lengthen it. A
   comparison contains three eligible unseen jobs plus a “none” option, drawn
   from at most nine unseen candidates. A current, validated preference posterior
   may choose the triple by expected information gain. Otherwise deterministic
   cold start chooses a triple by observed feature disagreement. A response is
   bound to the displayed subject and current profile/policy/context manifest;
   stale prompts cannot record a choice. A free-text answer is preserved as
   feedback and never automatically becomes a profile fact.
5. **Selected preparation.** HTTP acceptance of a person's selection is unpaid.
   The authenticated worker later prepares packages through existing approved
   paid routes and execution budgets. A person may select one to ten currently
   eligible shortlist entries. The request binds each posting to its exact shortlist entry
   and run key, plus a manifest of the current profile, configuration and job
   inputs. Dispatch rechecks eligibility and that manifest before enqueue. A
   per-person request key and selection identity make retries idempotent across
   the job database and API run store. `pending_dispatch` may have no run ID;
   dispatch either queues the run, leaves it pending when the queue is full, or
   marks stale inputs failed. The manifest expires after 24 hours.
   `GET /api/agent/selections/{selection_id}` returns status and the public run
   when queued; existing artifact routes provide saved package files.
   `POST /api/agent/selections/{selection_id}/cancel` cancels through the existing
   run cancellation path. Chat's gated `prepare_application` and `select_jobs`
   operations create the same durable selection, and `selection_status` reads
   it. The request authorizes preparation only and never Submit.
6. **Privacy and evaluation boundary.** Feedback history and selection state are
   scoped to the authenticated person. This Phase 6 source does not deliver
   Phase 7 evaluation reports, holdout evaluation or report exports. No report
   artifact is part of this decision.

## Consequences

Feedback is a durable account of what the person said and which displayed inputs
they saw. Rejection and restoration remain separate events, so the history is
reversible without erasing the earlier choice. Confirmed rules change the
approved profile version, and dependent assessments must be reprocessed before
they can be treated as current.

Selection is a recoverable preparation request. It may cross two stores, so its
durable request record is committed before dispatch and the API run is keyed by
the stable selection ID. A retry can recover the queued run instead of creating a
second run. Preparation remains separate from final submission.

## Release and undo

The example is synthetic and documents source shapes only. Parent integration,
local release checks and independent review passed; merge is tracked in PR #24. No live
profile amendment, fit, migration, service activation, timer or deployment follows
from this ADR.

Undo the release by reverting its source changes while retaining immutable
feedback events, approved profile versions and selection history. There is no
destructive data migration to reverse. Reversion restores prior source behavior;
it does not delete historical choices or prepare/submit an application.

## References

- [Jobwatch intent](../../INTENT.md)
- [Feedback and selection example](../examples/feedback-selection.md)
- `pipeline/agentic/feedback.py`
- `pipeline/agentic/feedback_prompts.py`
- `pipeline/agentic/feedback_api.py`
- `pipeline/agentic/selection.py`
- `pipeline/agentic/feedback_chat.py`
- `jobwatch/candidate/rules.py`
