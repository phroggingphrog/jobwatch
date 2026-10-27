## Purpose

Provide reusable candidate understanding grounded in approved evidence and canonical models before personal job filtering begins.

## ADDED Requirements

### Requirement: Model-aware candidate digest
The system SHALL produce a cited candidate digest from the approved profile, primary evidence and every applicable model's actual outputs or explicit readiness/unavailability status before personal job filtering.

#### Scenario: Candidate understanding is prepared
- **WHEN** an approved person has no current digest
- **THEN** the system reads their approved evidence, accesses structural, preference and outcome model capabilities, and persists strengths, gaps, target paths, constraints, uncertainties and model provenance
- **AND** job-dependent predictions await posting inputs and unavailable models do not receive fabricated outputs

### Requirement: Reusable isolated understanding
The system SHALL reuse a digest across jobs only while its person, approved profile, evidence, policy and relevant model/reference/history versions remain current.

#### Scenario: Multiple jobs share current understanding
- **WHEN** several jobs are screened against unchanged bound inputs
- **THEN** completed candidate understanding incurs no additional model calls

#### Scenario: Relevant inputs change
- **WHEN** a bound profile, evidence, policy or model snapshot changes
- **THEN** affected understanding is marked stale and refreshed before use without reusing another person's digest

### Requirement: Facts and policy remain authoritative
The digest SHALL distinguish approved facts and preferences from model advice. It MUST NOT invent personal constraints, qualifications, readiness or consent, silently activate new exclusions, retrain statistical models or disclose candidate data through unapproved routes.

#### Scenario: Suggested screening policy exceeds approval
- **WHEN** interpretation proposes an exclusion not supported by existing approved policy
- **THEN** the exclusion remains advisory pending confirmation and does not automatically reject jobs
