# Jobwatch

A self-hosted career-operations backend. It collects job postings, evaluates ads
against each person's approved evidence and preferences, and prepares application
materials for selected jobs. It never applies on its own: you review the filled
employer form, then press Submit yourself or confirm that exact form for Jobwatch
to submit through its canonical confirmation path.

The current delivery priority is one reliable native Screening → Evaluation
slice. Available modules and command references are not claims of end-to-end
acceptance or deployment. Read [current intent](INTENT.md) for the product contract
and [contributor guidance](AGENTS.md) before making changes.

## Architecture

The authenticated native agent API owns durable conversations and orchestration.
Canonical Jobwatch services enforce evidence, eligibility, review, packages and
human authorization. Standard LibreChat, the separate website and optional MCP
adapters are clients, not alternative sources of authority.

See the [backend contract](pipeline/agentic/CHAT.md) for native operations and
client boundaries. Collection dispatch selects the assessment mode; the top-level
`pipeline/` package also contains shared state and agentic orchestration.
Candidate facts, preferences and credentials belong in isolated runtime files,
never in this repository. Job sources, approved model providers
and explicitly connected integrations may receive data as their operations require;
local storage does not mean all processing is offline.

## Documentation

- [Native backend contract and setup](pipeline/agentic/CHAT.md)
- [Installation and settings](docs/installation.md)
- [Commands and profile workflow](docs/commands.md)
- [Configuration and collectors](docs/configuration.md)
- [Data, timers, web board and rollback](docs/operations.md)
- [Application and reader workflows](docs/application-workflows.md)
- [Detailed setup](SETUP.md)
- [Glossary](GLOSSARY.md) and [architecture decisions](docs/adr/)
- [Profile-preference audit and evidence limits](docs/archive/audits/2026-10-22-profile-preferences.md)

No package move or source change activates services or authorizes a deployment.
Use synthetic fixtures for local checks and verify the owner's actual deployment
before claiming live behavior.
