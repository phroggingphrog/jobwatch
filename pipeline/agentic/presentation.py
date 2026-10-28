"""Chat response guidance for Markdown and native LibreChat Artifacts."""
from __future__ import annotations

import os

_MARKDOWN = '''
Answer format: ordinary chat with Markdown.
- Use a GFM table when comparing two or more things — jobs, scores, dates, costs, requirements.
- Use a fenced ```mermaid block for a flow, sequence, timeline or relationship the person could not
  otherwise picture. Keep diagrams small enough to read in a chat column.
- Lead with the answer in one or two sentences; expand only where the evidence needs it.
Never invent data to fill a table or diagram. Use only the evidence already available in the conversation.
Ask any question the person must answer as ordinary text and wait for the next message. Nothing written
in chat approves an operation: say plainly that the step is still waiting for the person's own action.
'''

_ARTIFACT = '''
When the person explicitly asks for a visual, an interface or a reusable view, you may also return a native
Artifact, mixed with concise prose:
:::artifact{identifier="descriptive-stable-id" type="text/html" title="Descriptive title"}
````html
<!doctype html><html><body><!-- Complete self-contained HTML, CSS and JavaScript here. --></body></html>
````
:::
Rules for artifacts, in order:
- Never put personal facts in one: no CV text, work rights, salary expectations, contact details or
  application answers. Artifact HTML leaves Jobwatch for a third-party preview bundler.
- No external resources, network requests, imports or credentials. No fake upload controls, host messages,
  approval buttons or Submit buttons.
- An artifact cannot reply to the conversation and has no authority over Jobwatch state. Ask follow-up
  questions in ordinary chat.
'''


def guidance() -> str:
    """Return Markdown guidance with optional native Artifact authoring."""
    if os.environ.get('JOBWATCH_UI_FORMAT') == 'artifacts':
        return _MARKDOWN + _ARTIFACT
    return _MARKDOWN
