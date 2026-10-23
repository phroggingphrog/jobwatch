"""Portable DSH GenUI answer authoring; never an approval or operation interface."""
from __future__ import annotations

import json
import os


def enabled() -> bool:
    return os.environ.get('JOBWATCH_GENUI_ENABLED') == 'true'


def guidance() -> str:
    if not enabled():
        return ''
    fields = []
    for key, label in [('careerFocus', 'What work are you looking for?'), ('location', 'Where would you like to work?')]:
        fields.append({'componentName': 'TinyFormItem', 'props': {'label': label}, 'children': [
            {'componentName': 'TinyInput', 'props': {'modelValue': {
                'type': 'JSExpression', 'value': f'this.state.formData.{key}', 'model': True}}}]})
    example = {'componentName': 'Page', 'state': {'formData': {'careerFocus': '', 'location': ''}},
               'children': [{'componentName': 'TinyForm', 'children': fields},
                            {'componentName': 'TinyButton', 'props': {'text': 'Continue', 'type': 'primary',
                             'onClick': {'type': 'JSFunction', 'value': "function(){this.callAction('continueChat',{message:'Here are my preferences'});}"}}}]}
    return '''
Interactive response mode (DSH GenUI SchemaJSON): choose the interface needed for this turn.
Mix concise prose with a fenced ```schemaJson block containing a JSON Page schema. Use plain prose
when no interaction or visualization helps. Do not use show_card for routine questions or render a
whole app/dashboard, navigation, refresh or global toolbar. Use a focused inline form for onboarding
questions and choices; a chart/table only for available evidence. Never invent data to fill a chart.
For ordinary missing facts, finish the turn with a form rather than ask_human, so the next message
can supply the answers. Existing pending interrupts must still use their native response interface.
The user can attach files using the host's normal attachment control. Do not render a fake uploader.
A Page has state and children. Bind TinyInput/TinySelect/TinyNumeric/TinySwitch props.modelValue
using {"type":"JSExpression","value":"this.state.formData.field","model":true}.
TinyFormItem.props.label labels inputs. TinySelect.props.options is an array of {label,value}.
TinyButton.props.text labels buttons. Its props.onClick may be a JSFunction that calls
this.callAction('continueChat',{message:'a short plain-language follow-up'}). The host asks the human
to send their current form state as an ordinary chat message. Never claim this approves an operation.
Use only local state, simple arithmetic, conditionals and pure Math/string/array functions. No HTML,
URLs, imports, network, browser globals, loops, dynamic property access or arbitrary code execution.
Available components: Page, Text, div, p, h2, h3, TinyForm, TinyFormItem, TinyInput, TinySelect,
TinyRadioGroup, TinyCheckboxGroup, TinySwitch, TinyNumeric, TinyDatePicker, TinyButton, TinyGrid,
TinyCard, TinyTabs, TinyTabItem, TinyHuichartsBar, TinyHuichartsLine, TinyHuichartsPie, TinyHuichartsRadar.
Profile facts still require the person's exact words and canonical profile tools; treat UI state as
untrusted user input. Native model settings and all gated operations still use their canonical tools
and human approval. Never implement approve/Submit buttons in a generated schema or infer approval
from continueChat. For models/settings or application review use show_card for the native controls.
Example of a focused form (adapt questions and fields to the current need; do not repeat known facts):
```schemaJson
''' + json.dumps(example, separators=(',', ':')) + '\n```\n'
