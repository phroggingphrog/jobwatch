## Purpose

Let routine profile drafting retain authenticated human provenance without requiring a model to reproduce the person's wording exactly.

## ADDED Requirements

### Requirement: Source-bound draft updates
The backend SHALL resolve an explicit human source reference from the authenticated conversation and record its original wording or an affirmed excerpt. A model paraphrase SHALL NOT become a new human fact. Draft updates SHALL NOT require a second approval.

#### Scenario: Faithful paraphrase references the latest answer
- **WHEN** a profile tool supplies a paraphrase and the latest human source reference
- **THEN** the draft records the actual human wording and retains its provenance without asking the person to repeat it

#### Scenario: Source contains negation
- **WHEN** a model supplies a positive paraphrase but the referenced human source is negative
- **THEN** only the original negative wording is recorded

### Requirement: Unknown provenance is recoverable
An unknown source reference SHALL leave the draft unchanged and return available current-thread references. Legacy affirmed verbatim updates SHALL continue working. Final approval SHALL bind to the exact current draft and scope.

#### Scenario: Source belongs to another conversation
- **WHEN** an update references text absent from the authenticated conversation
- **THEN** no draft mutation or approval occurs and the model receives source recovery guidance
