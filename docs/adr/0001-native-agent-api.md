# ADR 0001: Native Jobwatch agent API

Date: 2026-10-21

Status: Accepted owner direction; deployment has its own acceptance criteria.

## Context

The owner chose: "native API is my plan" and requested the LangChain ecosystem
inside a working Jobwatch backend before website integration. Earlier discussion
considered a chat host using MCP; the native API is the primary delivery choice.

## Decision

Expose an authenticated Jobwatch HTTP agent API. Jobwatch runs the orchestration
through LangChain, LangGraph and Deep Agents, reusing existing canonical domain
operations. MCP remains an optional adapter. A client presents structured progress,
outcomes, questions, approvals and authorized document references.

## Consequences

- Authentication owns person identity, and durable interactions own human decisions.
- Domain services retain evidence, eligibility, leases, factual review and package
  persistence; a model cannot certify its own READY result.
- HTTP clients can reconnect to conversations and progress without requiring a
  particular website, external chat host or DSH integration.
- Published source, passing checks and a merged PR each remain distinct from a
  configured deployment or a verified real-candidate application workflow.

See [INTENT.md](../../INTENT.md) and [the backend contract](../../pipeline/agentic/CHAT.md).
