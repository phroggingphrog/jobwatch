# Host guidance (for contributors)

Jobwatch's MCP server teaches its host how to run the workflow, so the host neither improvises nor relies on a widget.
Everything a host reads is generated from two sources of truth. Do not write tool names, counts or workflow rules
anywhere else.

| Source | What it holds |
|---|---|
| `src/tools.ts` (the registry) | one `defineTool({...})` per tool: `summary`, `whenToUse`, `whenNotToUse`, `next`, `widget` policy, `annotations`, schemas, handler |
| `guidance/*.md` | editable text: `instructions.md`, `topics/*.md`, `widgets-*.md`, `skills.json`. Tool names are written `{{tool:name}}` and checked against the registry |

Generated from them: the server `instructions`, each tool's description, the tool-selection table, the tool count, the
`jobwatch_guide` topics, `skill://` resources and the README tool reference. `npm run docs` writes
`src/generated/guidance-bundle.ts` (the markdown, bundled at build time) and the README tool reference;
`npm run docs:check` fails if they are stale, and so does `test/conformance.test.ts`.

## Add a tool
1. Add `name: defineTool({...})` to `T` in `src/tools.ts`. Fill every field:
   - `whenToUse` completes "Use when ..." and appears in the instructions table, so keep it short.
   - `next` must name another registered tool. The full description must stay within 600 characters.
   - `widget`: `none` unless the tool exists to open a view. Only `open_dashboard` (`on_request`) and `review_submission` (`review`, the Submit boundary) open views. Data tools return text and structure only, through `reply(summary, data, next_actions)`.
   - `access: "app"` is for view-only buttons the model must never call.
2. If a view calls the tool, add a typed export in `index.ts` (`export const x = ref("tool_name")`).
3. Mention it in `guidance/instructions.md` or a topic with `{{tool:name}}` where the workflow needs it.
4. `npm run docs`, then `npm run typecheck && npm run build && npm test`.

## Edit guidance
Edit the markdown in `guidance/`, run `npm run docs`. Keep it field-agnostic: no occupation, person, host or machine
names. The conformance test enforces this. Repo skill files (`pipeline/agentic/skills/*/SKILL.md`) are read at runtime
as optional enrichment for `jobwatch_guide` and the `skill://` resources; `JOBWATCH_SKILLS_DIR` overrides the location
and a bundled one-line description is used when a file is missing.

## Widget policy
`JOBWATCH_MCP_WIDGETS` is `on_request` (default) or `off`. Text is always the primary answer. The client's declared
UI capability is only read to word a hint; nothing depends on it.

## How a host should consume this
- Read `instructions` from the initialize result and follow it every turn.
- Answer from each result's text summary; follow `next_actions`.
- Call `jobwatch_guide(topic)` when unsure; read `skill://jobwatch/<name>/SKILL.md` if resources are supported.
- If the tool list is smaller than the count the instructions state, the host's tool catalog is stale: start a new session.
