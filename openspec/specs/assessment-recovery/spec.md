# assessment-recovery Specification

## Purpose
Keep useful assessment corrections available while preserving bounded, durable recovery and canonical validation across restarts.

## Requirements

### Requirement: Progress-aware bounded correction
Distinct corrections that resolve prior validation problems SHALL continue under configured budgets. Repeated or cycling failures without progress SHALL stop at a persisted boundary. No recovery SHALL weaken schema, citation or evidence validation.

#### Scenario: Three progressively improved submissions
- **WHEN** more than two rejected submissions resolve earlier missing fields before a valid completion
- **THEN** the valid completion remains reachable within the existing budget

#### Scenario: Repeated malformed output after restart
- **WHEN** the same malformed operation exhausts its no-progress allowance and is replayed
- **THEN** replay preserves refusal without purchasing more work or resetting the allowance
