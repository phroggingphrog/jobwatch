## Purpose

Provide reproducible, private evidence that native job assessment completes correctly and efficiently before automatic assessment is activated.

## ADDED Requirements

### Requirement: Canonical provider acceptance
Acceptance SHALL require a real-provider evaluation with complete frozen-requirement coverage, valid primary-source citations, explicit evidence judgments and a canonical eligibility result. A failed invocation, plausible score or synthetic completion MUST NOT be reported as provider acceptance.

#### Scenario: Valid assessment with unresolved eligibility
- **WHEN** the provider produces a canonical evaluation whose gate holds for a supported unresolved condition
- **THEN** the report records valid assessment separately from the held eligibility result
- **AND** it does not describe the posting as qualified, application-ready or submitted

#### Scenario: Provider stops before canonical completion
- **WHEN** the run ends with a tool, schema, citation or provider failure
- **THEN** quality acceptance fails and the report identifies the last durable stage and error
- **AND** no source test result is substituted for provider acceptance

### Requirement: Complete efficiency accounting
Reports SHALL include every per-job model call, including public classifiers, orchestration and child calls, against the 3–6-call target. Embedding operations SHALL appear separately and in total paid operations. Reports MUST distinguish measured tokens, conservative charges, unknown usage, elapsed time and cold versus reused candidate-digest costs.

#### Scenario: Warm digest evaluation
- **WHEN** an evaluation reuses a current candidate digest
- **THEN** the report records zero new digest calls, the actual evaluation and classifier calls, embedding operations and their total paid operations
- **AND** it labels historical cold-digest cost separately rather than adding it to this invocation or hiding it

#### Scenario: Valid result misses the call target
- **WHEN** canonical evaluation succeeds but per-job model calls exceed six
- **THEN** quality acceptance and efficiency failure are recorded separately
- **AND** exceeding the target alone does not reject a valid assessment or stop legitimate evidence work; production activation still requires separate authorization and release evidence

### Requirement: Bounded source-access correction
A recoverable request for candidate information through a skill-only reader SHALL return precise guidance to canonical evidence access without opening the requested file. Corrections SHALL retain completed work and remain bounded across resume. Canonical citations, person isolation and source-access checks MUST remain enforced.

#### Scenario: Candidate filename supplied to the skill reader
- **WHEN** the agent requests a candidate filename through the skill-only reader
- **THEN** no candidate or arbitrary host file is opened
- **AND** one bounded correction identifies the permitted skill scope and canonical evidence operation
- **AND** a valid corrected request can continue to canonical completion

#### Scenario: Repeated invalid source access
- **WHEN** the same persisted correction boundary is exhausted
- **THEN** the run stops with an informative retained failure rather than resetting the allowance or weakening source checks

### Requirement: Recovery retains primary evidence
Unchanged-input recovery SHALL preserve successful paid responses, reasoning-bearing tool transcripts and exact primary evidence needed for judgments. Completed reuse SHALL make zero additional paid operations. Changed person, profile, evidence, ad, policy, model or implementation bindings MUST invalidate affected reuse.

#### Scenario: Graph checkpoints lost after a successful evidence read
- **WHEN** durable paid-response and action journals survive but graph checkpoints do not
- **THEN** recovery restores source payloads into the model transcript without repurchasing journaled responses
- **AND** historical access alone cannot authorize a judgment without restored primary records

#### Scenario: Completed unchanged assessment is read again
- **WHEN** a completed assessment is requested with unchanged bound inputs
- **THEN** canonical validation and current gate checks reuse the result with zero additional model, classifier or embedding operations

### Requirement: Controlled acceptance readiness
A controlled warm-digest acceptance SHALL require verified person identity, a current read-only digest, current posting inputs and the approved DeepSeek native-tool route. It MUST NOT silently buy a cold digest, release unrelated paused incidents or change owner limits. Failure SHALL retain checkpoints and accounting without starting an automatic paid retry loop.

#### Scenario: Digest is missing or stale at preflight
- **WHEN** the read-only readiness check cannot establish a current digest
- **THEN** the acceptance does not dispatch a model call
- **AND** it reports the binding that requires a separate candidate-understanding refresh

#### Scenario: Controlled provider attempt fails
- **WHEN** the single prepared provider attempt fails
- **THEN** the run and charges remain recorded, automatic assessment stays paused and no further paid attempt starts automatically

### Requirement: Runtime release proof
Automatic activation SHALL require quality acceptance, zero-paid completed reuse, reconciled accounting, required release checks, a verified native-runtime reader outcome and separate authorization. Reports MUST identify the deployed revision, protocol and actual cost against the efficiency target. Rollback MUST preserve profile approvals, usage, incidents and new records; deterministic collection SHALL remain available where possible.

#### Scenario: Source is ready but runtime remains old
- **WHEN** source checks pass while the running native service still uses the previous revision
- **THEN** the report distinguishes implemented and tested from deployed and observed working
- **AND** the change is not marked delivered

#### Scenario: Release candidate has accepted evaluation evidence
- **WHEN** provider acceptance and release checks pass for the exact candidate
- **THEN** deployment verifies the native imported revision, DeepSeek assessment-only configuration and service health
- **AND** one controlled reader outcome and unchanged-input reuse are verified before automatic assessment is restored

### Requirement: Explicit bounded reader invocation
An authenticated discovery request SHALL accept an optional positive assessment-count limit for that invocation. Omitted limits SHALL preserve existing behavior. The limit MUST bind request identity and constrain assessed postings without changing saved owner limits, approved scope, collection or another person's work.

#### Scenario: Controlled one-posting reader check
- **WHEN** the authenticated owner requests a discovery run with an assessment-count limit of one
- **THEN** at most one posting enters per-job assessment and the remainder are deferred with an explicit reason
- **AND** saved daily and per-job limits, including Unlimited, remain unchanged

#### Scenario: Request identifier is reused with different controls
- **WHEN** a request identifier already bound to one assessment limit is reused with another
- **THEN** the request is rejected as conflicting rather than silently reusing or expanding the earlier run

#### Scenario: Invalid invocation limit
- **WHEN** the supplied limit is zero, negative, a boolean or outside the supported batch range
- **THEN** the request is rejected before model dispatch

### Requirement: Private acceptance evidence
Acceptance artifacts SHALL expose only counts, validation outcomes and non-sensitive provenance in shared reports. Candidate content, credentials and raw reasoning MUST remain in approved private stores and MUST NOT enter hosted tracing or public fixtures.

#### Scenario: Acceptance evidence is published to tracking
- **WHEN** results are recorded on the existing work card or architecture documentation
- **THEN** shared content contains counts, outcome codes and source references without private candidate text, credentials or raw reasoning

### Requirement: Scoped combo protocol instructions
The system SHALL support a person-bound Evaluation combo and verified protocol prompt while preserving existing runtime system instructions. The combo and prompt revision SHALL invalidate affected evaluation reuse without changing candidate understanding or unrelated model roles. Malformed known-tool arguments SHALL receive bounded correction without executing a guessed repair.

#### Scenario: Dedicated Evaluation combo is configured
- **WHEN** a person configures an approved assessment combo and matching protocol prompt hash
- **THEN** native Evaluation uses that combo with the protocol appended to its existing system context
- **AND** candidate understanding, other model roles and current digest reuse remain unchanged

#### Scenario: Prompt revision does not match packaged instructions
- **WHEN** the configured protocol hash differs from the actual packaged prompt bytes
- **THEN** the run refuses dispatch before any paid model operation

#### Scenario: Malformed arguments are corrected after interruption
- **WHEN** a known tool returns malformed JSON arguments and its error feedback was persisted
- **THEN** the malformed operation is not executed, the original tool arguments and reasoning remain preserved, and unchanged-input recovery reuses the feedback without consuming another correction allowance


### Requirement: Informed autonomous execution with stable domain authority
The native evaluator SHALL receive the current candidate context, model readiness,
approved policy and exact evidence inventory once before its first model turn.
It SHALL choose primary evidence reads and optional retrieval without a mandatory
split-extraction or all-requirements-search sequence. Canonical complete-ad,
coverage, citation, evidence-access and eligibility validation MUST remain gates.

#### Scenario: Primary evidence before ad registration
- **WHEN** the agent reads a known primary record before registering the ad
- **THEN** the exact approved record and its actual access are retained
- **AND** final completion still requires validated ad extraction and judgments

#### Scenario: Evaluation needs no dense search
- **WHEN** direct primary reads suffice for canonical evaluation
- **THEN** registering the ad and completing evaluation make no embedding calls
- **AND** unchanged completed reuse makes no additional paid operations

### Requirement: Shared read-only candidate understanding
Native clients and the existing candidate page SHALL project the same current
canonical digest. They MUST keep approved constraints separate from suggestions,
report model readiness and missing/stale/unconfirmed states, and MUST NOT prepare
understanding, refit models or substitute legacy per-job assessments on a read.

#### Scenario: Current understanding is unavailable
- **WHEN** the authenticated person has no currently bound candidate digest
- **THEN** the view reports its absence or staleness without a provider call
- **AND** another person's digest cannot be used as a fallback
