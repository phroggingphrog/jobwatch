## Purpose

Expose the stored advertisement and the recorded follow-up cadence to an authenticated MCP client, per person, without a chat turn, a model call or an approval.

## ADDED Requirements

### Requirement: Advertisement read
`career_reader` SHALL return the posting identity, the stored advertisement text and the text kind for one posting, using the canonical capture that the internal `inspect_job` tool uses. A missing posting SHALL return `status: missing`.

#### Scenario: An advertisement exists
- **WHEN** a client reads a posting that has stored text
- **THEN** the response carries the identity fields, the text and the text kind
- **AND** no host path and no model output appear in the payload

#### Scenario: A posting is absent
- **WHEN** a client reads an unknown posting id
- **THEN** the response reports `status: missing`

### Requirement: Follow-up cadence read
`followup_history` SHALL return the recorded follow-up events, the cadence state, the due date and whether a draft is allowed, for one application. It MUST NOT send a message, draft text or change a status.

#### Scenario: Cadence is available
- **WHEN** a client reads an application with recorded events
- **THEN** the response carries the dates, the sent count, the state, the due date and `draft_allowed`
- **AND** no message is sent

#### Scenario: The application is unknown
- **WHEN** a client reads an application id with no record
- **THEN** the response reports `status: missing`
- **AND** it does not infer history from chat text

### Requirement: Read-only behaviour
Both tools MUST NOT write to the database, start a chat turn, call a model, or submit an application. Both SHALL carry the server's read-only annotation so a client can tell a read from work before it calls.

#### Scenario: A read spends nothing
- **WHEN** a client calls either tool
- **THEN** the database opens read-only and no model call, ledger charge or approval prompt occurs

#### Scenario: Annotations advertise the rule
- **WHEN** a client lists the tools
- **THEN** `career_reader` and `followup_history` report `readOnlyHint: true`
- **AND** the submit tool remains the only destructive one

### Requirement: Person isolation from the verified token
Each read tool SHALL resolve the person from the verified access token through `_person_from_request()`. A model-supplied argument MUST NOT select an account.

#### Scenario: The token is absent or invalid
- **WHEN** a request arrives without a valid bearer token
- **THEN** the server refuses the call
- **AND** it reads no row

#### Scenario: A read is scoped to its person
- **WHEN** a client reads a posting or application id
- **THEN** every query runs inside the token's person
- **AND** a row owned by another person is not returned
