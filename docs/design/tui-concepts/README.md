# TUI design concepts (2026-10-25)

Mockups with made-up data, for redesigning `pipeline/agentic/tui.py`. Not UI-audited.

| File | Concept |
|---|---|
| `c0-current.*` | The real TUI today (rendered in a test with a fake model) |
| `c1.*` | Conversation first: transcript with plan and folded tool blocks |
| `c2.*` | Mission control: job queue left, conversation right (recommended main screen) |
| `c3.*` | Review before Submit (recommended approval screen) |
| `c4.*` | Minimal cards for narrow windows |
| `c5-dcode-*` | Deep Agents Code spike talking to Jobwatch's graph |

Re-render C1 to C4 after editing `concepts.py` (plain Textual):

```
.venv/bin/python docs/design/tui-concepts/concepts.py docs/design/tui-concepts
.venv/bin/python docs/design/tui-concepts/svg_to_png.py docs/design/tui-concepts/c2.svg docs/design/tui-concepts/c2.png
```

Libraries: Textual https://github.com/Textualize/textual · Rich https://github.com/Textualize/rich ·
Deep Agents https://github.com/langchain-ai/deepagents · Toad https://github.com/batrachianai/toad ·
ACP https://agentclientprotocol.com
