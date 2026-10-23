# Standard chat clients own presentation

Accepted owner direction, 2026-10-24. Use vanilla LibreChat with native Artifacts;
Jobwatch owns bot orchestration, file intake and isolated identities. Standard
OpenAI-compatible file parts carry original bytes, and server-configured client
credentials plus an authenticated subject preserve account mapping without a
LibreChat fork. The subject is trusted only with the configured server credential;
this path receives read/run scope and never human approval scope.

Attachment receipt is distinct from readable profile evidence. Retain arbitrary
originals privately, parse supported formats through canonical intake, and report
unreadable content without failing the conversation. Generated HTML remains local,
illustrative UI and has no ability to approve or submit. A client without protected
human review cannot complete a gated operation. Preserve historical resources;
remove Jobwatch-specific cards from new vanilla conversations.
