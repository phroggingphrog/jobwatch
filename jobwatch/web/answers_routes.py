"""Owner-only /answers page: fill the form-field answers in answers.yaml, keeping its comments and layout."""
import os
import re
import tempfile
from fastapi import Request
from fastapi.responses import RedirectResponse
from jobwatch.apply import paths

LINE = re.compile(r'^(\s*(?:- )?)([a-z_]+): "((?:[^"\\]|\\.)*)"(\s*(?:#\s*(.*))?)$')


PLAIN = {'australian_citizen_or_pr': 'Are you an Australian citizen or permanent resident?',
         'wwcc_number': 'Working with Children Check number', 'ndis_worker_screening': 'NDIS worker screening',
         'working_with_children_check': 'Working with Children Check', 'expected_annual_aud': 'Expected yearly pay (AUD)',
         'expected_hourly_aud': 'Expected hourly pay (AUD)', 'linkedin_on_forms': 'Include your LinkedIn on forms?',
         'related_to_employee_or_conflict': 'Related to an employee, or any conflict of interest?',
         'willing_to_relocate_in_victoria': 'Willing to relocate within your state?', 'drivers_licence': "Driver's licence"}


def _path():
    return paths.profile_dir() / 'answers.yaml'


def parse(text):
    """Return [(field_id, section, label, hint, value)] and the matching line numbers."""
    fields, lines_at = [], []
    section, ref = '', 0
    for n, line in enumerate(text.splitlines()):
        top = re.match(r'^([a-z_]+):\s*(#.*)?$', line)
        if top:
            section, ref = top.group(1), 0
            continue
        m = LINE.match(line)
        if not m:
            continue
        if section == 'referees' and m.group(1).strip() == '-':
            ref += 1
        key = m.group(2)
        fid = f'{section}.{ref}.{key}' if section == 'referees' else f'{section}.{key}'
        label = PLAIN.get(key) or key.replace('_', ' ').capitalize()
        if section == 'referees':
            label = f'Referee {ref}: {key}'
        fields.append({'id': fid, 'section': section.replace('_', ' ').capitalize(), 'label': label,
                       'hint': (m.group(5) or '').strip(), 'value': m.group(3).replace('\\"', '"')})
        lines_at.append(n)
    return fields, lines_at


def save(text, form):
    fields, lines_at = parse(text)
    lines = text.splitlines()
    for f, n in zip(fields, lines_at):
        if f['id'] not in form:
            continue
        value = ' '.join(str(form[f['id']]).split())[:300].replace('\\', '').replace('"', "'")
        m = LINE.match(lines[n])
        rest = m.group(4)
        lines[n] = f'{m.group(1)}{m.group(2)}: "{value}"' + (f'  {rest.strip()}' if rest.strip() else '')
    return '\n'.join(lines) + '\n'


def register(app, config, conn_factory, render):
    @app.get('/answers')
    def answers(request: Request):
        try:
            fields, _ = parse(_path().read_text())
        except OSError:               # no answers file yet: show the empty state, not a server error
            fields = []
        filled = sum(1 for f in fields if f['value'])
        conn = conn_factory()
        try:
            return render(request, 'answers.html', conn, fields=fields, filled=filled,
                          saved=request.query_params.get('saved'))
        finally:
            conn.close()

    @app.post('/answers')
    async def save_answers(request: Request):
        form = dict((await request.form()).items())
        p = _path()
        new = save(p.read_text(), form)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix='.answers-')
        with os.fdopen(fd, 'w') as fh:
            fh.write(new)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        return RedirectResponse('/answers?saved=1', status_code=303)
