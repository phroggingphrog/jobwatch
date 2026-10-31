# Spec Delta

## Purpose

Defines the `screened` execution mode: deterministic screening and one structured read before any agentic evaluation.

## ADDED Requirements

### Requirement: Screening runs before any model call
The system SHALL apply the metadata prescreen before fetching an ad, and SHALL NOT fetch or call a model for a posting the prescreen skips.

#### Scenario: Title is an obvious skip
- **WHEN** a posting's title matches an active skip rule with an obvious hit
- **THEN** the posting is archived with the prescreen reason, no ad fetch is attempted and no model call is made

#### Scenario: Title is unclear
- **WHEN** no skip rule has an obvious hit
- **THEN** the posting continues to fetch and read

### Requirement: Closed ads are not evaluated
The system SHALL archive a posting with reason `posting_closed` when the ad fetch reports it gone, and SHALL NOT call a model for it.

#### Scenario: Ad returns 404
- **WHEN** the ad URL returns 400, 404 or 410
- **THEN** the posting is archived with reason `posting_closed`

### Requirement: Every screened posting reaches a terminal or retryable state
The system SHALL move each screened posting to exactly one of SHORTLISTED, ARCHIVED or DLQ, and SHALL NOT leave it held without a stage.

#### Scenario: Gate passes
- **WHEN** the canonical gate returns eligible
- **THEN** the posting moves to SHORTLISTED with its score

#### Scenario: Model output is invalid three times
- **WHEN** a structured call fails validation three times
- **THEN** the posting moves to DLQ with the validation error text

### Requirement: Agentic evaluation is limited to promoted postings
The system SHALL call agentic evaluation only for SHORTLISTED postings with score >= `min_score`, at most `promote_per_run` per run and `promote_per_day` per 24 h, highest score first.

#### Scenario: Five shortlisted, limit three
- **WHEN** five postings are SHORTLISTED with scores 4.5, 4.2, 4.0, 3.5, 2.9 and `promote_per_run` is 3
- **THEN** only the first three are passed to agentic evaluation and the others stay SHORTLISTED

### Requirement: Search queries are title-shaped
The system SHALL send a focus item to a job board only when it has 1-6 words and matches the title pattern; other items SHALL be dropped and counted.

#### Scenario: Sentence focus item
- **WHEN** a focus item is a sentence with punctuation or more than six words
- **THEN** it is not sent as a query and `dropped_focus` is incremented

### Requirement: Transport failures retry once
The system SHALL re-queue an unresolved dead letter whose error is a transport failure, older than 6 h and with fewer than 4 attempts, at most 50 per run.

#### Scenario: Provider outage
- **WHEN** a dead letter's error contains `Connection refused` and it is 7 h old with 3 attempts
- **THEN** the next screened run puts it back in its stage

### Requirement: Dropped postings are visible
The system SHALL list postings skipped by the metadata prescreen in the last N days (default 7) through the CLI and the board.

#### Scenario: Owner checks drops
- **WHEN** the owner runs `jobwatch pipeline dropped`
- **THEN** each skipped posting shows title, company, rule reason and decision time
