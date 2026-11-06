## ADDED Requirements

### Requirement: Enabled-channel delivery
Disabled notification channels SHALL NOT consume the dispatch batch allowance for enabled channels. Repeating an already delivered notification SHALL report delivered without resending it.

#### Scenario: Disabled rows precede enabled rows
- **WHEN** a dispatch batch contains pending disabled-channel rows before an enabled-channel notification
- **THEN** the enabled notification is dispatched within its allowance

#### Scenario: Duplicate delivered notification
- **WHEN** an already delivered deduplication key is requested again
- **THEN** delivery is reported successful without an additional send
