# Portable inline GenUI

Vendored DSH GenUI 0.3.1 (MIT) supplies its actual self-contained OpenTiny/Vue
renderer and authoring reference. `vendor/dsh-genui/PROVENANCE.json` records source
hashes. No DSH service or dashboard is required.

`pipeline.agentic.genui.guidance` teaches the native agent the same `schemaJson`
answer format. `JOBWATCH_GENUI_ENABLED=true` enables it at release. Plain Markdown
is the default for Q&A and onboarding: ask directly and wait for the next message.
Use generated interfaces for explicit interactive requests or useful evidence displays,
without opening an app merely to collect an answer. Canonical view requests
and pending human decisions still use the existing protected native interfaces.

A compatible frontend parses schemaJson fences into components, validates bounded
schema/logic and isolates the renderer from host credentials and network access.
`continueChat` returns local form state as an ordinary user message only after a
host-owned human Send action. It cannot approve, modify canonical state or submit an
application. The LibreChat adapter lives in its separate repository under
`client/src/components/GenUI`; other frontends can implement the same format.

Rollback: disable JOBWATCH_GENUI_ENABLED and restart the native API, restore the
previous LibreChat image, retaining all conversation/profile stores. Historical MCP
resources and schema text remain saved; disabling authoring does not delete them.
