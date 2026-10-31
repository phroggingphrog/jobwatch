# Spec Delta

## Purpose

Defines how the system separates person-owned profile input from approved generated versions. It protects evidence, policy, retries, discovery scope, and reader integrity.

## ADDED Requirements

### Requirement: Generated writes preserve person input
The system SHALL NOT modify, replace, restore, or delete person-owned files in the live profile directory during projection, confirmation, adoption, recovery, or rule amendment.

#### Scenario: Confirmation creates generated output
- **WHEN** a person confirms a valid profile proposal
- **THEN** the system stores generated projections in that person's approved version and leaves every live input file unchanged

#### Scenario: Recovery runs after publication
- **WHEN** a retry resumes a published version
- **THEN** the system completes work from that version and does not write to the live profile directory

### Requirement: Approved versions retain evidence and policy
The system SHALL retain the approved evidence snapshot and its valid annotations with the approved version. It SHALL preserve policy constraints, including `Policy: part-time only.`, in every downstream decision that uses the snapshot.

#### Scenario: Annotation matches source evidence
- **WHEN** the system publishes an approved version with valid evidence annotations
- **THEN** the version contains the source evidence and annotations, and downstream readers can apply their policy

#### Scenario: Annotation is invalid
- **WHEN** evidence annotations do not match their source documents
- **THEN** the system preserves source input, records a specific invalid-annotation reason, and does not apply unverified annotation claims

### Requirement: Published-version recovery is idempotent
The system SHALL use an atomically published approved version as the commit record. A retry for the same proposal or amendment SHALL reuse that version and SHALL NOT mint a duplicate version.

#### Scenario: Rule amendment publication completes before a crash
- **WHEN** a process stops after the approved version directory is published
- **THEN** retry finds the same amendment identity, completes any remaining version-local work, and returns the published version number

#### Scenario: Crash occurs before publication
- **WHEN** a process stops before the approved version directory is published
- **THEN** retry does not treat an incomplete staging directory as an approved version and may publish one complete version

### Requirement: Adoption and amendments preserve valid discovery scope
The system SHALL preserve the confirmed scope and its integrity checks across adoption and rule amendments. A changed or unreadable person input SHALL close discovery with a specific reason.

#### Scenario: Adoption is followed by confirmation
- **WHEN** an adopted profile contains a valid person input snapshot and a person confirms a valid proposal
- **THEN** the approved version retains the input identity and discovery opens only when all scope checks pass

#### Scenario: Rule amendment is retried
- **WHEN** the person retries an already published rule amendment
- **THEN** the system returns the original version and preserves the valid discovery scope

#### Scenario: Confirmed input changes
- **WHEN** a person input differs from its approved integrity record
- **THEN** discovery remains closed and the system reports the specific integrity failure

### Requirement: Readers use the approved version
The system SHALL bind every assessment, policy, digest, shortlist, and rendering read to the server-bound person's approved version. A reader SHALL NOT combine generated files from a different version or person-owned live input with an approved snapshot.

#### Scenario: Reader loads an approved profile
- **WHEN** a downstream reader requests candidate evidence or generated profile data
- **THEN** it reads only the server-bound person's approved version and its associated evidence snapshot

#### Scenario: Approved version is absent or invalid
- **WHEN** the reader cannot verify the approved version
- **THEN** it returns a specific failure reason and does not fall back to unverified live data

### Requirement: Gates report specific failure reasons
Each profile or discovery gate SHALL report the specific cause when it refuses access. It SHALL NOT replace distinct failures with one generic missing-profile result.

#### Scenario: Gate rejects a damaged or unconfirmed profile
- **WHEN** a profile gate refuses a request
- **THEN** it returns the specific reason, such as no approved version, no confirmed scope, changed input, invalid annotation, unreadable file, or an out-of-scope path
