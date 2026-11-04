# Design

## Context

Investigation source326e8d6 accepted exact human clauses but rejected equivalent model paraphrases. Native assessment allowed two tool corrections total, including distinct improving payloads. The current framework already supports crash/replay; canonical rules own these refusals.

## Goals / Non-Goals

Remove needless draft-answer friction and allow useful correction progress. Preserve original human wording, negations, current-thread identity, evidence integrity, unchanged-input replay, configured cost/time/call limits and exact-input final approval. Do not fix unrelated release failures, migrate frameworks, deploy or edit owner data.

## Decisions

Draft tools accept an optional server-owned source reference (`latest` or a stable digest exposed by profile status). The backend resolves it against authenticated human texts in the current conversation. A copied affirmed value remains compatible; a model paraphrase is replaced with the actual source wording rather than being promoted to a fact. Persist its source digest in the existing fact note. Unknown/stale sources do not mutate the draft and return usable references; no additional human approval is added to routine draft edits. Current complete draft/scope confirmation remains the only approval path.

Native correction accounting persists progress and repeated-failure state before responding. Improved missing-field/violation sets can continue without increasing configured budgets. Identical errors, cycling payloads and unrelated churn do not create progress. Existing response feedback must replay before accounting, and refusal persists across resume.

## Risks / Trade-offs

Raw source wording can be longer than a model summary, but retains negation and avoids semantic guessing. Structured paraphrases cannot become invented structured facts; source-bound fallback stores original human text. Source inventories are bounded and reference only current authenticated human history. Recovery must not reset on restart or treat arbitrary payload changes as improvement.

## Verification / Rollback

Reproduce third improving correction failure and source-bound paraphrase failure first. Verify current/earlier/resumed human sources, unknown references, negation, unapproved draft state, stale approval invalidation, same-error exhaustion and journal replay with synthetic inputs. Run affected integration checks; no release/full-suite claim from this repair. Revert this change's source commit to undo; no runtime database/config rollback is needed.
