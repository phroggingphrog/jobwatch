# User Discovery Categories

## Purpose

Provide user-specific discovery vocabulary and configurable screening categories without embedded personal assumptions.

## ADDED Requirements

### Requirement: Advisory assessment and explicit authority
The system SHALL distinguish goals, preferences, explicit confirmed constraints, factual work rights, unknowns and processing errors in a shared decision contract. A goal, preference, low fit score or occupational mismatch SHALL NOT authorize exclusion.

#### Scenario: Partial assessment
- **WHEN** a useful assessment has incomplete citations, short ad text or unavailable audit artifacts
- **THEN** the system preserves the assessment with explicit uncertainty instead of imposing a universal proof-completeness gate

#### Scenario: Explicit constraint conflict
- **WHEN** verified job facts conflict with an explicitly confirmed restriction or factual work-rights limit
- **THEN** the system records the conflict separately from fit, without a category-based legal-hours bypass

### Requirement: Nonblocking product audit
The system SHALL retain useful assessment and provenance records without requiring perfect audit citations, hashes, schemas or report artifacts before an assessment can exist. Authentication, per-user isolation, credential protection, bounded spending and submission approval remain mandatory.

#### Scenario: Advisory failure and runtime failure
- **WHEN** citation completeness is missing but useful assessment content exists
- **THEN** the system returns a partial assessment and clarification items, separate from technical failure

### Requirement: Reconsideration and spatial preservation
The system SHALL reconsider stale goal-only and category-only routing decisions in bounded idempotent operations, preserve history, and retain approved location templates when expanding research queries.

#### Scenario: Changed category or obsolete relevance archive
- **WHEN** a category changes or an old job was archived solely for occupational relevance
- **THEN** the system can return an open job for assessment without a new paid judgment and without restoring closed or explicitly excluded jobs


### Requirement: Configurable categories
The system SHALL use each user's validated category IDs, labels, ordering, phrases and explicit action and promotion policies without branching on category names.

#### Scenario: Category changes
- **WHEN** a user adds, renames, reorders or removes a category in configuration
- **THEN** classification, triage choices, routing and promotion follow that configuration without code changes

### Requirement: Research from goals
The system SHALL research relevant websites from user-defined goals and produce per-user category suggestions, synonyms and source-specific discovery query terms without requiring manual keyword maintenance.

#### Scenario: Goal changes
- **WHEN** a user changes their goals
- **THEN** research refreshes suggestions for the new goal version while retaining explicit user corrections

### Requirement: Provenance and rollback
The system SHALL distinguish user constraints from research suggestions and store source URLs, retrieval dates and goal/input versions for each researched suggestion, with versioned rollback.

#### Scenario: Correction and rollback
- **WHEN** a user corrects a suggestion or restores an earlier configuration
- **THEN** the selected version and explicit corrections govern that user's discovery and screening

### Requirement: No inferred personal exclusions
Research SHALL NOT create qualifications, work-rights, hours limits or hard personal exclusions; suggestions can broaden discovery but cannot authorize inferred negative filters.

#### Scenario: Suggestion contains an exclusion
- **WHEN** researched material suggests a restriction not explicitly approved by the user
- **THEN** the system does not apply it as a personal eligibility restriction

### Requirement: Neutral absent configuration
The system SHALL not inject hardcoded category vocabulary or silently reject a job solely because category configuration is missing.

#### Scenario: No categories exist
- **WHEN** a user has no category settings
- **THEN** classification remains unassigned and no hidden category vocabulary or category rejection is applied

### Requirement: Isolation and source boundary
The system SHALL isolate goals, suggestions and policies by user and SHALL NOT enable new collectors merely because a website was researched.

#### Scenario: Users have different goals
- **WHEN** two users configure different goals and category policies for the same title
- **THEN** each receives the result from their own configuration only

### Requirement: Preserve existing decisions on migration
Migration SHALL represent current configured vocabulary, category actions, promotion and existing eligibility protections as explicit user data and preserve current decisions until changed by the user.

#### Scenario: Existing owner configuration
- **WHEN** the current owner configuration is migrated
- **THEN** regression fixtures show equivalent classification, routing, promotion and hours-policy decisions, with reversible configuration versions
