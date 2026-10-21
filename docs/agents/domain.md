# Domain conventions

Jobwatch has one domain context: career operations for an authenticated person.
Collection, assessment, application preparation and follow-up work share that
context and its existing domain services.

Keep domain terms in the single root [GLOSSARY.md](../../GLOSSARY.md). Update that
file when a term changes; avoid competing module-specific definitions of a run,
approval, package or READY result.

Record consequential architecture decisions in [docs/adr/](../adr/) using numbered
Markdown files. Include context, status, decision, consequences and references to
the owner direction or issue. An accepted design is distinct from verified delivery.

Do not introduce separate bounded contexts or service boundaries merely because
an agent framework offers them. Explain any proposed split against
[INTENT.md](../../INTENT.md) and record the agreed decision before implementation.
