# Native candidate-understanding lifecycle

Implements [candidate-understanding tasks 2.1–2.3](../../openspec/changes/candidate-digest-native-assessment/tasks.md).
This describes source behavior and synthetic verification, not a deployed result.

`pipeline.agentic.candidate_digest.ensure_digest` runs a dedicated Deep Agents
native-tool graph over approved primary evidence. Its tools read structural
occupational analysis, preference readiness, callback posterior/readiness,
response-time readiness, retrieval availability and scoped Jev route status.
Every capability must be accessed before completion; unavailable capabilities
remain explicit. The agent must read every extracted evidence item on a cold
binding. Strengths and target paths require exact primary citations; uncited gaps
mean absent proof, not an asserted inability. Target families remain bounded by
the canonical target policy. Model interpretations are advisory, and job-dependent
predictions await posting inputs. No tool fits models, writes labels or policy,
contacts employers, changes approval or submits an application. Candidate-bearing
Jev capabilities remain unavailable because no approved route exists.

The digest's screening projection is code-owned: exact current `DecisionPolicy`
JSON, its profile version and policy hash, the approved profile hash and the
server-bound person. Agent suggestions have a separate advisory field and never
become exclusions. In particular, seniority does not imply an invented maximum
number of required years. Citation checking establishes source provenance; the
canonical factual and eligibility gates remain authoritative for individual jobs.

## Binding and recovery

The manifest binds person, the complete approved profile, evidence and career
framing, target and decision policy, structural/reference/mapping versions,
canonical runtime configuration and selected gateway/model, preference-model
source versions and fit/history table hashes, stage implementation, schema and
skill. Outcome history includes canonical submitted/resolved/censored cases;
unsubmitted drafts and unrelated new matches cannot invalidate understanding.

Completed typed digests live in the person's existing job database. Native replies,
private LangGraph checkpoints, tool access and bounded correction counts live in
`candidate-understanding.sqlite` inside that person's private runtime directory.
It uses the same private SQLite opener and native model transport as job evaluation.
A person-scoped file lock prevents concurrent cold dispatch. Replies and conservative
charge attribution are journaled atomically before tool dispatch. A later graph or
final-store failure reuses the successful reply or terminal result. One correction
per tool boundary returns fixed codes and field paths; repeated failure holds the
work without weakening citation or access checks.

`current_digest(conn, *, bundle, policy, cfg, structural, ...)` returns a typed
current digest or `None`. `current_policy_digest(conn, policy)` is the collector
entry point: it loads canonical configuration, evidence and structural inputs,
rechecks the full manifest, and never creates tables or calls a provider. Missing
or stale understanding defers the collector's personal filters while retaining
postings. The reader prepares understanding before ingestion, exclusion and
personal screening. Direct assessment synchronizes approved rule rows before
forming its run key, then prepares understanding before evaluating those rules.
The native job evaluator receives `candidate_digest` JSON as a separate context;
the structural `AnalysisResult` and `candidate_hash` remain deterministic. The
run's configuration hash also binds digest inputs, preventing reuse of an older
saved job evaluation after a relevant digest input changes. Cached READY public
rechecks retain the existing credential-free recovery path.

History-only changes can seed the new graph with previously validated primary
findings and evidence access. The graph must read current model outputs again;
it need not cold-read unchanged evidence. Profile/evidence/policy/reference,
skill, source or model changes prevent that stable-evidence reuse.

## Costs and verification

Digest charges use the caller's existing budget. Reader preparation uses the
existing `discovery_spend` ledger with purpose `candidate_digest`; its invocation
and daily allowance are shared with later discovery and job work, and the daily
balance is refreshed after cold preparation. Direct assessment uses its fenced
`JobBudget`. Owner Unlimited settings are read, not modified. Collect-only
operations never call digest preparation.

Native numeric counts preserve actual known tokens, cache/reasoning details,
unknown-usage operations, conservative charged tokens, calls and elapsed time.
Private `candidate_digest_counts` artifacts distinguish a job's attributable
cold preparation from zero-call reuse. Attribution is retained across checkpoint
recovery and excluded from job evaluation totals. `digest_costs(conn, digest)`
returns cold counts, distinct screened run count and charged tokens divided by
that count; without consumers, amortized cost is unknown. These are token charges,
not a dollar-price estimate. No live cost or efficiency target is claimed.

Focused synthetic coverage is in [test_candidate_digest.py](../../tests/test_candidate_digest.py)
and [test_native_assessment_service.py](../../tests/test_native_assessment_service.py).
It includes a real authenticated discovery endpoint and native graph using a
synthetic HTTP transport, zero-call cache reuse, changed bindings, history refresh,
persistence interruption, source/target rejection, direct/reader ordering and
collect-only refusal to dispatch. Run from this checkout with `PYTHONPATH="$PWD"`
and the native environment's `python -m pytest`; its `pytest` executable can resolve
the live editable checkout instead.

The checked local Career Ops source (`projects/references/career-ops/modes/triage.md`
and `scan.mjs`) separates compact reusable context from zero-model collection.
Its donor thresholds and interactive promotion rules are not Jobwatch policy.
