# assessment-completion Specification

## Purpose
Define what it means for a scheduled assessment to be complete: promotion evaluates postings without preparing application documents, each started posting is charged once per daily window, and skipped work consumes no allowance. Completion is reported separately from whether documents were prepared.

## Requirements

### Requirement: Assessment-only scheduling
Scheduled promotion SHALL evaluate postings without preparing application documents and SHALL charge each started posting once per daily window. Skipped work SHALL NOT consume promotion allowance.

#### Scenario: One selected posting is skipped
- **WHEN** a promotion selects two postings but only one starts
- **THEN** one promotion is charged and neither posting is implicitly selected for document preparation

### Requirement: Durable evaluated result
A successful evaluation SHALL persist a distinct evaluated outcome backed by valid candidate and evaluation artifacts. Unchanged-input reuse SHALL validate artifact bindings and perform zero additional model work.

#### Scenario: Saved artifact is absent or invalid
- **WHEN** a saved completion lacks a valid expected artifact
- **THEN** it is not accepted as a reusable successful evaluation

### Requirement: Independent document readiness
Evaluation SHALL remain available without document identity fields. Preparation SHALL hold before paid work when required approved identity is missing, without fabricating facts or human confirmation.

#### Scenario: Approved profile has a generic header
- **WHEN** assessment is requested for a profile whose document name is missing
- **THEN** assessment can complete while preparation reports its identity blocker
