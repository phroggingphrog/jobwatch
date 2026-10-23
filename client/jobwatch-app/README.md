# Jobwatch MCP App

Build with `npm ci && npm run build` in this directory. The generated, self-contained
HTML is packaged in `pipeline/agentic/jobwatch-app.html`; deployments need no Node
runtime or CDN. SDK 1.7.5 deliberately matches the installed LibreChat 0.8.8 host.
The current upstream SDK is 2.x; upgrading it is a separate host compatibility check.

The panel reads authenticated native state through MCP resources. Its action tool
is app-only and separately enforces human approval scope. LibreChat shows the exact
action arguments in its own confirmation dialog. Uploads use a short-lived,
single-use capability bound to person, filename, kind, byte count and SHA-256;
document bytes never enter model tool arguments. Native intake still extracts,
parses, cites and confirms evidence. Model settings use canonical per-person picks
and the existing approved paid-route checks.
