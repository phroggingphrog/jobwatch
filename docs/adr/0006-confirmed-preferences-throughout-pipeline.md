# ADR 0006: Confirmed preferences throughout the pipeline

Status: accepted by the owner on 2026-10-22 in GitHub #14.

The owner directs: “fix all of the issues then merged into main”. The audit found
that shared collector, eligibility, taste-model and writer defaults encoded an earlier
person's home, level, rights and style. A location prefilter alone could not repair it.

## Decision

Use the confirmed per-person DecisionPolicy for every active personal eligibility path.
The canonical `candidate.eligibility.evaluate_eligibility` operation distinguishes eligible,
held and excluded. Missing material facts remain questions, never negative facts. Explicit
None is a neutral frozen-input policy for comparison. The historical legacy setting cannot
reactivate donor rules. Ad classification stays separate from the person's ability to meet it.

Compare advertised numeric hours with confirmed limits. Do not turn requested junior level
into a maximum experience count; primary-evidence requirement matching establishes actual
qualification. Citizenship, residency, sponsorship and exact clearance are distinct facts.
Keep citation, evidence, identity, budget, review and Submit controls authoritative.
Holistic and career-direction scores remain advisory, with their historical baseline preserved.

Every confirmed discovery scope replaces inherited personal search terms/locations, even
without a paid semantic index. Search all supported approved locations with bounded rotation.
Explicit refresh remains required for paid occupational expansion. ATS/RSS source inventories
remain configured acquisition coverage; this change does not invent providers.

Structural defaults have no built-in excluded occupation codes. Confirmed family exclusions
alone determine personal scope. Neutral taste priors and canonical families have new feature,
model and structural identities. Historical choices and fits stay immutable and are reported
stale; collecting new choices and fitting remain explicit. No live automatic migration.

Writers use approved style/template preferences with neutral defaults. Factual source,
placeholder, review and PDF requirements remain unconditional. Legacy reader and deterministic
pipeline delegate eligibility to the same policy, without inherited score caps.

## Release and undo

Run synthetic contrasting-profile regressions, frozen historical gate comparisons and the
release suite. No recommendation-quality or deployment claim follows from synthetic tests.
Run/config/profile identities change so old packages/choices cannot pass as current inputs.
A source revert restores earlier code; retained immutable runtime artifacts need no destructive
migration. Reverting does not restore services or retrain models because this release does neither.
