"""Writing form from the current person's confirmed preferences, never another owner's voice.

Style is framing only. Factual evidence, independent review and PDF verification remain mandatory.
Missing style choices use neutral factual prose and the standard supported renderer.
"""
from __future__ import annotations

from jobwatch import users

_CV_TEMPLATES = {'cv_consult_default', 'cv_compact_1page', 'cv_graduate_2page'}
_LETTER_TEMPLATES = {'cl_consult_default', 'cl_short_direct', 'cl_graduate_academic'}


def approved_writing_profile() -> dict:
    """Only the authenticated/context-bound person's confirmed version supplies style choices."""
    from jobwatch.candidate.intake import current_version
    return current_version(users.current()) or {}


def writing_preferences(approved: dict | None = None) -> dict:
    """Explicit writing preference facts; inferred and unknown facts are never controls.

    A preference can use {kind: writing, value: {tone, cv_template, ...}} or a
    single {kind: writing_style/cv_template/letter_template, value: ...} choice.
    Other preference strings remain personal framing; they cannot select a template.
    """
    approved = approved_writing_profile() if approved is None else approved
    out: dict = {}
    for fact in approved.get('facts', ()):
        if not isinstance(fact, dict) or fact.get('section') != 'preference' or fact.get('basis') != 'evidence':
            continue
        value = fact.get('value')
        if not isinstance(value, dict):
            continue
        kind = value.get('kind')
        if kind == 'writing' and isinstance(value.get('value'), dict):
            options = value['value']
        elif kind in ('writing_style', 'cv_template', 'letter_template'):
            options = {'tone' if kind == 'writing_style' else kind: value.get('value')}
        else:
            continue
        for key in ('tone', 'letter_approach', 'cv_instructions'):
            if isinstance(options.get(key), str) and options[key].strip():
                out[key] = options[key].strip()[:4000]
        for key in ('omit_grades', 'omit_unit_codes', 'use_style_examples', 'avoid_stock_phrases', 'avoid_em_dashes', 'avoid_repetition', 'short_closing', 'vary_openings'):
            if isinstance(options.get(key), bool):
                out[key] = options[key]
        for key, allowed in (('cv_template', _CV_TEMPLATES), ('letter_template', _LETTER_TEMPLATES)):
            if isinstance(options.get(key), str) and options[key] in allowed:
                out[key] = options[key]
        for key in ('responsibilities_per_role', 'max_sentence_words'):
            count = options.get(key)
            if type(count) is int and 1 <= count <= (20 if key == 'responsibilities_per_role' else 200):
                out[key] = count
    return out


def templates_for(approved: dict | None = None) -> tuple[str, str]:
    """A title is not consent to a graduate or compact template."""
    options = writing_preferences(approved)
    return options.get('cv_template', 'cv_consult_default'), options.get('letter_template', 'cl_consult_default')


def writing_guide(cl_template: str, title: str, archetype: str, cv_template_id: str = '',
                  *, approved: dict | None = None) -> dict:
    approved = approved_writing_profile() if approved is None else approved
    options = writing_preferences(approved)
    guide = {
        'stated_preferences': [f['value'] for f in approved.get('facts', ())
                               if isinstance(f, dict) and f.get('section') == 'preference'
                               and f.get('basis') == 'evidence' and isinstance(f.get('value'), str)],
        'preferences': options,
        'how_to_use': 'Style choices affect form and voice only; never override factual evidence or verification.',
        'letter_approach': (
            'Use the confirmed writing preferences and relevant stated_preferences below as personal style framing, never factual evidence. When no tone is stated, use neutral factual prose. '
            'Connect verified ad duties or cited employer facts to supported experience and expressed interests. '
            'Do not invent personal motivations, enthusiasm, beliefs or company facts. Choose a clear structure '
            'suited to the supported content; no fixed bullet quota or academic emphasis is implied. '
            'Mention gaps and practical restrictions when relevant without claiming missing qualifications.'),
        'cv_guide': (
            'Use readable standard section headings and selectable text. Include only supported claims. '
            'Select relevant evidence and order it clearly; do not fill pages or invent content to meet a quota. '
            'Reword evidence in the role vocabulary only when its meaning and scope remain unchanged. '
            'Use the confirmed template choice and respect its PDF page limit.'),
    }
    if options.get('use_style_examples'):
        # No global career directory or another person's original letters are consulted.
        from jobwatch.onboarding import style_examples
        examples = {f'example_{i}': text for i, text in enumerate(style_examples(), 1)}
        if examples:
            guide['human_examples'] = {'how_to_use': 'Voice and rhythm only; never copy facts or sentences.', **examples}
    return guide
