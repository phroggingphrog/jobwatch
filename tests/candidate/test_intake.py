"""Private uploads and sourced profile proposals (synthetic documents only)."""
import json
import stat

import pytest

from jobwatch.util import model_choice as model_choice
from jobwatch import users
from jobwatch.candidate import intake
from jobwatch.util.llm import LLM

SYNTHETIC_CV = """Alex Example
Accounts Assistant

Experience
Ledger Co, Accounts Assistant, 2021 - 2023
Reconciled supplier ledgers weekly
Prepared month-end journals

Education
Diploma of Accounting, Example College, 2020
"""
class FakeLLM:
    """LLM over a fake transport; .reply() sets the next JSON answer, .bodies keeps what was sent."""
    def __init__(self):
        self.next, self.bodies = {'facts': [], 'questions': []}, []
        def transport(url, headers, body, timeout):
            self.bodies.append(body)
            return 200, {'choices': [{'message': {'content': json.dumps(self.next)}}], 'usage': {}}
        self.llm = LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)
        self.base_url = self.llm.base_url

    def reply(self, data):
        self.next = data

    def chat(self, *a, **kw):
        return self.llm.chat(*a, **kw)


@pytest.fixture(autouse=True)
def local_gateway(monkeypatch):
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')      # the approved route: local gateway + paid model


@pytest.fixture
def person():
    users.create_user_dirs('sam')
    model_choice.set_models({'reader': 'claude/sonnet'}, 'sam')
    with users.use('sam'):
        yield 'sam'
    intake._inflight.clear()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def upload_id(person):
    return intake.save_upload(person, 'cv.txt', SYNTHETIC_CV.encode(), 'cv')['upload_id']


def fact(section, value, basis, sources=()):
    return {'section': section, 'value': value, 'basis': basis, 'sources': list(sources)}


def test_upload_is_private_and_outside_profile(person):
    info = intake.save_upload(person, 'cv.txt', SYNTHETIC_CV.encode(), 'cv')
    base = users.user_dir(person) / 'intake'
    path = base / 'uploads' / (info['sha256'] + '.txt')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and not (users.user_dir(person) / 'profile' / 'profile.yaml').exists()
    assert stat.S_IMODE(base.stat().st_mode) == 0o700 and stat.S_IMODE((base / 'uploads').stat().st_mode) == 0o700
    for f in (base / 'uploads.json', base / 'text' / (info['sha256'] + '.txt')):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert info['bytes'] == len(SYNTHETIC_CV.encode()) and info['kind'] == 'cv'


@pytest.mark.parametrize('name,data,code', [('cv.exe', b'x', 'unsupported_type'), ('cv', b'x', 'unsupported_type'),
                                            ('cv.txt', b'x' * (10 * 1024 * 1024 + 1), 'too_large')])
def test_upload_limits(person, name, data, code):
    with pytest.raises(intake.IntakeError, match=code):
        intake.save_upload(person, name, data, 'cv')


def test_unreferenced_kind_is_refused(person):
    with pytest.raises(intake.IntakeError, match='unsupported_type'):
        intake.save_upload(person, 'cv.txt', b'x', 'resume')


def test_verbatim_evidence_keeps_its_source(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('experience', 'Accounts Assistant, Ledger Co', 'evidence',
                                   [{'line': 6, 'quote': 'reconciled  SUPPLIER ledgers weekly'}])], 'questions': []})
    proposal = intake.propose(person, [upload_id], fake_llm)
    f = proposal.facts[0]
    assert f.basis == 'evidence' and f.actor == 'parser' and f.sources[0].line == 6
    assert f.sources[0].upload_sha256 == proposal.uploads[0]
    assert proposal.revision == 1 and proposal.status == 'draft' and proposal.base_version is None
    assert intake.load_proposal(person, proposal.id) == proposal
    path = users.user_dir(person) / 'intake' / 'proposals' / (proposal.id + '.json')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (users.user_dir(person) / 'profile' / 'profile.yaml').exists()


def test_quote_not_in_upload_is_downgraded_to_inference(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [{'section': 'skill', 'value': 'Kubernetes', 'basis': 'evidence',
                               'sources': [{'line': 3, 'quote': 'Ran Kubernetes clusters'}]}], 'questions': []})
    proposal = intake.propose(person, [upload_id], fake_llm)
    fact_ = proposal.facts[0]
    assert fact_.basis == 'inference' and fact_.sources == ()


def test_quote_far_from_cited_line_is_downgraded(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('education', 'Diploma of Accounting', 'evidence',
                                   [{'line': 1, 'quote': 'Diploma of Accounting, Example College, 2020'}])]})
    assert intake.propose(person, [upload_id], fake_llm).facts[0].basis == 'inference'


def test_cv_gap_never_becomes_unemployed(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [{'section': 'employment_status', 'value': 'unemployed', 'basis': 'inference', 'sources': []}],
                    'questions': []})
    proposal = intake.propose(person, [upload_id], fake_llm)
    status = next(f for f in proposal.facts if f.section == 'employment_status')
    assert status.basis == 'unknown' and status.value == '' and any(q.section == 'employment_status' for q in proposal.questions)
    assert len([f for f in proposal.facts if f.section == 'employment_status']) == 1


def test_employment_evidence_needs_a_quote_that_states_it(person, fake_llm):
    uid = intake.save_upload(person, 'cv.txt', b'Alex\nCurrently employed at Ledger Co\nSkills: ledgers\n', 'cv')['upload_id']
    fake_llm.reply({'facts': [fact('employment_status', 'employed', 'evidence', [{'line': 2, 'quote': 'Currently employed at Ledger Co'}]),
                              ]})
    status = next(f for f in intake.propose(person, [uid], fake_llm).facts if f.section == 'employment_status')
    assert status.basis == 'evidence' and status.value == 'employed'
    fake_llm.reply({'facts': [fact('employment_status', 'employed', 'evidence', [{'line': 3, 'quote': 'Skills: ledgers'}])]})
    status = next(f for f in intake.propose(person, [uid], fake_llm).facts if f.section == 'employment_status')
    assert status.basis == 'unknown'


STATUS_CV = b'Alex\nCurrently employed at Ledger Co\nLedger Co, Accounts Assistant, 2021 - Present\nBetween roles since June\nStudying full-time at Example College\nSeeking work as a bookkeeper\nNot currently employed\nSkills: ledgers\n'


def _status(person, fake_llm, line, value, basis='evidence'):
    uid = intake.save_upload(person, 'status.txt', STATUS_CV, 'cv')['upload_id']
    quote = STATUS_CV.decode().splitlines()[line - 1]
    fake_llm.reply({'facts': [fact('employment_status', value, basis, [{'line': line, 'quote': quote}])]})
    return next(f for f in intake.propose(person, [uid], fake_llm).facts if f.section == 'employment_status')


@pytest.mark.parametrize('line,value', [(2, 'employed'), (4, 'between roles'), (5, 'studying full-time'), (6, 'seeking work'),
                                         (7, 'unemployed')])
def test_employment_status_is_evidence_only_when_the_quote_states_it_and_the_value_agrees(person, fake_llm, line, value):
    status = _status(person, fake_llm, line, value)
    assert status.basis == 'evidence' and status.value == value and status.sources


@pytest.mark.parametrize('value', ['employed', 'currently employed', 'working at Ledger Co'])
def test_a_date_range_ending_present_does_not_state_employment(person, fake_llm, value):
    for basis in ('evidence', 'inference'):
        status = _status(person, fake_llm, 3, value, basis)           # 'Ledger Co, Accounts Assistant, 2021 - Present'
        assert status.basis == 'unknown' and status.value == '' and status.sources == ()


@pytest.mark.parametrize('line,value', [(2, 'unemployed'), (2, 'studying'), (7, 'employed'), (5, 'seeking work'), (8, 'employed')])
def test_an_employment_status_that_disagrees_with_its_quote_is_not_evidence(person, fake_llm, line, value):
    assert _status(person, fake_llm, line, value).basis == 'unknown'


def test_missing_decision_sections_become_unknown_with_a_question(person, fake_llm, upload_id):
    proposal = intake.propose(person, [upload_id], fake_llm)
    for section in ('availability', 'work_rights', 'constraint', 'exclusion', 'employment_status'):
        assert any(f.section == section and f.basis == 'unknown' for f in proposal.facts), section
        assert sum(q.section == section for q in proposal.questions) == 1, section
    assert len({f.id for f in proposal.facts}) == len(proposal.facts) and len({q.id for q in proposal.questions}) == len(proposal.questions)


def test_model_question_is_kept_and_not_duplicated(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [], 'questions': [{'section': 'work_rights', 'text': 'Can you work here?', 'why': 'Roles need it'},
                                              {'section': 'nonsense', 'text': 'x', 'why': 'y'}]})
    proposal = intake.propose(person, [upload_id], fake_llm)
    assert [q.text for q in proposal.questions if q.section == 'work_rights'] == ['Can you work here?']
    assert not any(q.section == 'nonsense' for q in proposal.questions)


def test_unknown_section_and_bad_basis_are_handled(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('hobby', 'chess', 'evidence'), fact('skill', 'Ledgers', 'guess'), 'junk']})
    proposal = intake.propose(person, [upload_id], fake_llm)
    skills = [f for f in proposal.facts if f.section == 'skill']
    assert len(skills) == 1 and skills[0].basis == 'inference' and not any(f.section == 'hobby' for f in proposal.facts)


def test_prompt_rules_and_numbered_lines(person, fake_llm, upload_id):
    intake.propose(person, [upload_id], fake_llm)
    system, user = (m['content'] for m in fake_llm.bodies[0]['messages'])
    for needle in ('evidence', 'inference', 'unknown', 'verbatim', 'line number', 'gap', 'materially'):
        assert needle in system
    assert 'L6: Reconciled supplier ledgers weekly' in user


def _pdf_with_text(lines):
    """A minimal valid one-page PDF whose content stream draws each line (so pypdf can extract it)."""
    stream = "BT /F1 12 Tf 14 TL 20 180 Td " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(stream)}>>stream\n{stream}\nendstream", "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj{o}endobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()


def _docx(lines):
    import io, docx
    d = docx.Document()
    for l in lines:
        d.add_paragraph(l)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_scanned_pdf_has_no_text(person, fake_llm):
    upload = intake.save_upload(person, 'scan.pdf', _pdf_with_text([]), 'cv')        # parses fine, holds no text
    with pytest.raises(intake.IntakeError, match='no_extractable_text'):
        intake.propose(person, [upload['upload_id']], fake_llm)
    assert fake_llm.bodies == []                      # nothing was sent to the model


def test_text_pdf_is_extracted_and_reaches_the_model(person, fake_llm):
    up = intake.save_upload(person, 'cv.pdf', _pdf_with_text(['Alex Example', 'Reconciled supplier ledgers weekly']), 'cv')
    fake_llm.reply({'facts': [fact('experience', 'Ledgers', 'evidence', [{'line': 2, 'quote': 'Reconciled supplier ledgers weekly'}])]})
    proposal = intake.propose(person, [up['upload_id']], fake_llm)
    assert 'L2: Reconciled supplier ledgers weekly' in fake_llm.bodies[0]['messages'][1]['content']
    assert proposal.facts[0].basis == 'evidence'


def test_docx_is_extracted_and_reaches_the_model(person, fake_llm):
    up = intake.save_upload(person, 'cv.docx', _docx(['Alex Example', 'Prepared month-end journals']), 'cv')
    intake.propose(person, [up['upload_id']], fake_llm)
    assert 'L2: Prepared month-end journals' in fake_llm.bodies[0]['messages'][1]['content']


@pytest.mark.parametrize('name', ['cv.pdf', 'cv.docx'])
def test_corrupt_document_is_unreadable_not_empty(person, name):
    with pytest.raises(intake.IntakeError, match='unreadable_document'):
        intake.save_upload(person, name, b'this is not a document', 'cv')
    assert not (users.user_dir(person) / 'intake' / 'uploads.json').exists()      # nothing was kept


@pytest.mark.parametrize('name,module', [('cv.pdf', 'pypdf'), ('cv.docx', 'docx')])
def test_missing_extractor_is_reported_distinctly(person, monkeypatch, name, module):
    import sys
    monkeypatch.setitem(sys.modules, module, None)          # makes `import <module>` raise ImportError
    with pytest.raises(intake.IntakeError, match='extractor_unavailable'):
        intake.save_upload(person, name, b'%PDF-1.4 anything', 'cv')
    with pytest.raises(ValueError):                         # the legacy page still gets a readable message
        intake.extract_text(name, b'x')


def test_unknown_upload_and_proposal_ids(person, fake_llm):
    with pytest.raises(intake.IntakeError, match='upload_not_found'):
        intake.propose(person, ['0' * 16], fake_llm)
    with pytest.raises(intake.IntakeError, match='upload_not_found'):
        intake.propose(person, ['../../x'], fake_llm)
    for bad in ('0' * 16, '../uploads', ''):
        with pytest.raises(intake.IntakeError, match='proposal_not_found'):
            intake.load_proposal(person, bad)


def test_uploads_are_per_person(person, fake_llm, upload_id):
    users.create_user_dirs('kim')
    with pytest.raises(intake.IntakeError, match='upload_not_found'):
        intake.propose('kim', [upload_id], fake_llm)


def test_non_object_model_output_is_parse_failed(person, fake_llm, upload_id):
    fake_llm.reply(['not', 'an', 'object'])
    with pytest.raises(intake.IntakeError, match='parse_failed'):
        intake.propose(person, [upload_id], fake_llm)


def test_models_are_frozen_and_strict():
    f = intake.ProfileFact(id='f1', section='skill', value='x', basis=intake.Basis.INFERENCE)
    with pytest.raises(Exception):
        f.value = 'y'
    with pytest.raises(Exception):
        intake.ProfileFact(id=1, section='skill', value='x', basis='inference')


def test_extract_text_is_shared_with_the_web_route():
    from jobwatch.web import onboarding_routes
    assert onboarding_routes.extract_text is intake.extract_text
    assert intake.extract_text('a.md', b'hello') == 'hello'


# ----------------------------------------------------------------------------- corrections and answers
@pytest.fixture
def draft(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('skill', 'Bookkeeping', 'inference')], 'questions': []})
    return intake.propose(person, [upload_id], fake_llm)


def test_edit_with_stale_revision_is_refused(person, draft):
    after = intake.edit(person, draft.id, expected_revision=1, edits=[{'op': 'set', 'fact_id': 'f1', 'value': 'Payroll', 'basis': 'evidence'}])
    assert after.revision == 2
    with pytest.raises(intake.IntakeError) as err:
        intake.edit(person, draft.id, expected_revision=1, edits=[{'op': 'remove', 'fact_id': 'f1'}])
    assert err.value.code == 'proposal_changed'
    assert intake.load_proposal(person, draft.id) == after


def test_edit_set_remove_add(person, draft):
    p = intake.edit(person, draft.id, expected_revision=1, edits=[
        {'op': 'set', 'fact_id': 'f1', 'value': 'Payroll', 'basis': 'evidence'},
        {'op': 'add', 'section': 'location', 'value': 'Perth'},
        {'op': 'remove', 'fact_id': 'f2'}])
    by_id = {f.id: f for f in p.facts}
    assert by_id['f1'].value == 'Payroll' and by_id['f1'].actor == 'person' and by_id['f1'].sources == ()
    assert by_id['f1'].basis == 'evidence' and by_id['f1'].note == 'stated by person'
    added = [f for f in p.facts if f.section == 'location']
    assert len(added) == 1 and added[0].actor == 'person' and added[0].id not in {'f1', 'f2'}
    assert 'f2' not in by_id and len({f.id for f in p.facts}) == len(p.facts)


@pytest.mark.parametrize('bad', [
    {'op': 'set', 'fact_id': 'nope', 'value': 'x', 'basis': 'evidence'},
    {'op': 'remove', 'fact_id': 'nope'}])
def test_edit_unknown_fact_is_refused_and_nothing_changes(person, draft, bad):
    with pytest.raises(intake.IntakeError) as err:
        intake.edit(person, draft.id, expected_revision=1, edits=[{'op': 'add', 'section': 'location', 'value': 'Perth'}, bad])
    assert err.value.code == 'fact_not_found'
    assert intake.load_proposal(person, draft.id) == draft


@pytest.mark.parametrize('bad', [
    {'op': 'add', 'section': 'nonsense', 'value': 'x'}, {'op': 'add', 'section': 'location', 'value': ''},
    {'op': 'set', 'fact_id': 'f1', 'value': 'x', 'basis': 'inference'}, {'op': 'explode'}, 'not a dict'])
def test_invalid_edits_are_refused(person, draft, bad):
    with pytest.raises(intake.IntakeError) as err:
        intake.edit(person, draft.id, expected_revision=1, edits=[bad])
    assert err.value.code == 'invalid_edit'
    with pytest.raises(intake.IntakeError):
        intake.edit(person, draft.id, expected_revision=1, edits=[])


def test_answer_records_a_person_fact(person, draft):
    qid = next(q.id for q in draft.questions if q.section == 'work_rights')
    p = intake.answer(person, draft.id, expected_revision=1, question_id=qid, text='Citizen')
    assert p.revision == 2 and qid not in {q.id for q in p.questions}
    mine = [f for f in p.facts if f.section == 'work_rights']
    assert len(mine) == 1 and mine[0].value == 'Citizen' and mine[0].actor == 'person'
    assert mine[0].basis == 'evidence' and mine[0].sources == () and mine[0].note == 'stated by person'
    assert len({f.id for f in p.facts}) == len(p.facts)
    assert intake.load_proposal(person, draft.id) == p
    with pytest.raises(intake.IntakeError) as err:
        intake.answer(person, draft.id, expected_revision=2, question_id=qid, text='again')
    assert err.value.code == 'question_not_found'
    with pytest.raises(intake.IntakeError) as err:
        intake.answer(person, draft.id, expected_revision=2, question_id='q99', text=' ')
    assert err.value.code in ('question_not_found', 'invalid_edit')


def test_person_facts_are_never_marked_parser(person, draft):
    assert all(f.actor == 'parser' for f in draft.facts)
    p = intake.edit(person, draft.id, expected_revision=1, edits=[
        {'op': 'add', 'section': 'location', 'value': 'Perth'},
        {'op': 'set', 'fact_id': 'f1', 'value': 'Payroll', 'basis': 'evidence'}])
    assert {f.id: f.actor for f in p.facts if f.section in ('location', 'skill')} == {'f1': 'person', **{f.id: 'person' for f in p.facts if f.section == 'location'}}
    assert all(f.actor == 'parser' for f in p.facts if f.section not in ('location', 'skill'))


def test_confirmed_proposal_is_not_editable(person, draft):
    intake.save_proposal(person, draft.model_copy(update={'status': 'confirmed'}))
    with pytest.raises(intake.IntakeError) as err:
        intake.edit(person, draft.id, expected_revision=1, edits=[{'op': 'remove', 'fact_id': 'f1'}])
    assert err.value.code == 'proposal_not_draft'
    with pytest.raises(intake.IntakeError) as err:
        intake.answer(person, draft.id, expected_revision=1, question_id=draft.questions[0].id, text='x')
    assert err.value.code == 'proposal_not_draft'
    assert intake.load_proposal(person, draft.id).status == 'confirmed'


def test_concurrent_edits_do_not_lose_updates(person, draft):
    import threading
    results = []
    def go(n):
        with users.use(person):
            try:
                results.append(intake.edit(person, draft.id, expected_revision=1, edits=[{'op': 'add', 'section': 'location', 'value': f'City{n}'}]))
            except intake.IntakeError as exc:
                results.append(exc.code)
    threads = [threading.Thread(target=go, args=(n,)) for n in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sum(isinstance(r, intake.Proposal) for r in results) == 1 and results.count('proposal_changed') == 5
    final = intake.load_proposal(person, draft.id)
    assert final.revision == 2 and sum(f.section == 'location' for f in final.facts) == 1


def test_digest_is_deterministic_and_tracks_every_input(person, draft):
    assert intake.digest(draft) == intake.digest(Proposal_copy(draft)) and len(intake.digest(draft)) == 64
    base = intake.digest(draft)
    fact0 = draft.facts[0]
    changed = [
        draft.model_copy(update={'revision': 2}), draft.model_copy(update={'base_version': 3}),
        draft.model_copy(update={'uploads': draft.uploads + ('0' * 64,)}),
        draft.model_copy(update={'facts': (fact0.model_copy(update={'value': 'other'}),) + draft.facts[1:]}),
        draft.model_copy(update={'facts': draft.facts[1:]})]
    assert len({base, *map(intake.digest, changed)}) == len(changed) + 1
    assert intake.digest(draft.model_copy(update={'status': 'confirmed'})) == base      # status is not part of the digest


def Proposal_copy(p):
    return intake.Proposal.model_validate_json(p.model_dump_json())


# ----------------------------------------------------------------------------- confirmation and versions
import hashlib  # noqa: E402
import threading  # noqa: E402

from jobwatch.apply import paths as apaths  # noqa: E402
from jobwatch.candidate.evidence import snapshot_evidence  # noqa: E402

CONFIG = {'pipeline': {'agentic': {'batch_token_ceiling': 1234}}}
Q = lambda line, quote: {'line': line, 'quote': quote}  # noqa: E731


@pytest.fixture
def full(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [
        fact('experience', 'Accounts Assistant, Ledger Co', 'evidence', [Q(5, 'Ledger Co, Accounts Assistant, 2021 - 2023')]),
        fact('experience', 'Prepared journals', 'evidence', [Q(7, 'Prepared month-end journals')]),
        fact('education', 'Diploma of Accounting', 'evidence', [Q(10, 'Diploma of Accounting, Example College, 2020')]),
        fact('skill', 'Bookkeeping', 'inference'),
        fact('career_focus', 'Accounts officer', 'inference')], 'questions': []})
    return intake.propose(person, [upload_id], fake_llm)


def ok(person, p, **kw):
    c = intake.confirmation(person, p.id, CONFIG)
    return intake.confirm(person, p.id, proposal_digest=kw.get('pd', c['proposal_digest']),
                          scope_digest=kw.get('sd', c['scope_digest']), actor=kw.get('actor', 'person'), config=CONFIG)


def vdir(person, n):
    return users.user_dir(person) / 'profile-versions' / str(n)


def test_confirmation_shows_scope_and_limits(person, full):
    c = intake.confirmation(person, full.id, CONFIG)
    assert c['proposal_digest'] == intake.digest(full)
    s = c['scope']
    assert s.daily_assessments == 40 and s.daily_token_ceiling == 1234
    assert s.basis == ('Accounts Assistant, Ledger Co', 'Prepared journals')       # employment-first, evidence only
    assert c['authorises'] == ['discovery', 'assessment']
    assert c['does_not_authorise'] == ['document_preparation', 'employer_messages', 'submission']
    assert c['scope_digest'] == hashlib.sha256(s.model_dump_json().encode()).hexdigest()


def test_confirm_with_stale_digest_writes_nothing(person, full):
    c = intake.confirmation(person, full.id, CONFIG)
    intake.edit(person, full.id, expected_revision=1, edits=[{'op': 'add', 'section': 'location', 'value': 'Perth'}])
    with pytest.raises(intake.IntakeError) as err:
        intake.confirm(person, full.id, proposal_digest=c['proposal_digest'], scope_digest=c['scope_digest'], actor='person', config=CONFIG)
    assert err.value.code == 'proposal_changed'
    assert not (users.user_dir(person) / 'profile-versions').exists() and not list(apaths.profile_dir().iterdir())
    assert intake.load_proposal(person, full.id).status == 'draft' and intake.current_version(person) is None


def test_confirm_with_stale_scope_writes_nothing(person, full):
    with pytest.raises(intake.IntakeError) as err:
        ok(person, full, sd='0' * 64)
    assert err.value.code == 'scope_changed' and not (users.user_dir(person) / 'profile-versions').exists()


def test_only_the_person_confirms(person, full):
    with pytest.raises(intake.IntakeError):
        ok(person, full, actor='agent')
    assert intake.current_version(person) is None


def test_confirm_writes_immutable_version_and_snapshot(person, full):
    n = ok(person, full)
    assert n == 1 and intake.load_proposal(person, full.id).status == 'confirmed'
    d = vdir(person, n)
    approved = json.loads((d / 'approved.json').read_text())
    assert approved['version'] == 1 and approved['uploads'] == list(full.uploads) and approved['actor'] == 'person'
    assert approved['scope']['daily_token_ceiling'] == 1234 and approved['proposal_digest'] == intake.digest(full)
    assert approved['evidence_bundle_hash'] == snapshot_evidence(d / 'evidence').bundle_hash
    for name in ('profile.yaml', 'interests_and_criteria.yaml', 'master_resume.md'):
        assert (d / name).is_file()
    assert any((d / 'evidence' / name).is_file() for name in ('cv.md', 'master_resume.md'))
    assert snapshot_evidence(d / 'evidence').bundle_hash == approved['evidence_bundle_hash']
    assert stat.S_IMODE((d / 'approved.json').stat().st_mode) == 0o600 and stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stat.S_IMODE(next((d / 'evidence' / name).stat().st_mode for name in ('cv.md', 'master_resume.md') if (d / 'evidence' / name).exists())) == 0o600
    assert intake.current_version(person)['version'] == 1 and [v['version'] for v in intake.versions(person)] == [1]


def test_projection_does_not_invalidate_person_annotations(person, full, fake_llm, upload_id):
    before = hand_made({**HAND, 'evidence.yaml': 'items: []\n'})
    before_hash = snapshot_evidence(apaths.profile_dir()).bundle_hash
    intake.adopt_existing(person, actor='person')
    proposal = intake.propose(person, [upload_id], fake_llm, base_version=1)
    assert ok(person, proposal) == 2
    assert snapshot_evidence(vdir(person, 2) / 'evidence').bundle_hash == before_hash
    assert (apaths.profile_dir() / 'evidence.yaml').read_bytes() == before['evidence.yaml']
    assert (vdir(person, 2) / 'profile.yaml').is_file()

def test_projection_feeds_existing_readers(person, full, monkeypatch):
    intake.edit(person, full.id, expected_revision=1, edits=[{'op': 'add', 'section': 'work_rights', 'value': {'visa': 'Citizen', 'hours_limit_per_fortnight': 48}}])
    p = intake.load_proposal(person, full.id)
    ok(person, p)
    from jobwatch.candidate import person as cp
    assert cp.work_rights()['visa'] == 'Citizen' and cp.hours_limit_per_fortnight() == 48.0
    quotes = [str(f['value']) for f in intake.current_version(person)['facts'] if f['basis'] == 'evidence']
    assert any('Accounts Assistant, Ledger Co' in q for q in quotes) and any('Diploma of Accounting' in q for q in quotes)
    assert 'Bookkeeping' not in ' '.join(quotes)


def test_inferred_facts_only_enter_after_confirmation(person, full):
    assert not list(apaths.profile_dir().iterdir())
    ok(person, full)
    approved = intake.current_version(person)
    inferred = [f for f in approved['facts'] if f['basis'] == 'inference']
    assert {f['value'] for f in inferred} == {'Bookkeeping', 'Accounts officer'}
    projection_text = ''.join((vdir(person, 1) / name).read_text() for name in ('profile.yaml', 'interests_and_criteria.yaml'))
    assert 'Bookkeeping' not in projection_text and 'Accounts officer' not in projection_text


def test_person_fact_replaces_parser_unknown_and_unanswered_stay_unknown(person, full):
    p = intake.answer(person, full.id, expected_revision=1, question_id=next(q.id for q in full.questions if q.section == 'availability'), text='Immediately, 38 hours')
    ok(person, p)
    facts = intake.current_version(person)['facts']
    avail = [f for f in facts if f['section'] == 'availability']
    assert len(avail) == 1 and avail[0]['actor'] == 'person'
    assert [f['basis'] for f in facts if f['section'] == 'work_rights'] == ['unknown']
    assert {q['section'] for q in intake.current_version(person)['open_questions']} >= {'work_rights'}
    assert 'availability' not in {q['section'] for q in intake.current_version(person)['open_questions']}


def test_second_confirm_supersedes_drafts_and_numbers_versions(person, full, fake_llm, upload_id):
    other = intake.propose(person, [upload_id], fake_llm)
    assert ok(person, full) == 1
    assert intake.load_proposal(person, other.id).status == 'superseded'
    again = intake.propose(person, [upload_id], fake_llm, base_version=1)
    assert ok(person, again) == 2 and intake.current_version(person)['version'] == 2
    assert (vdir(person, 1) / 'approved.json').exists() and len(intake.versions(person)) == 2
    with pytest.raises(intake.IntakeError) as err:
        ok(person, full)
    assert err.value.code == 'proposal_not_draft'


def test_stale_base_version_is_refused(person, full, fake_llm, upload_id):
    ok(person, full)
    stale = intake.propose(person, [upload_id], fake_llm, base_version=7)
    with pytest.raises(intake.IntakeError) as err:
        ok(person, stale)
    assert err.value.code == 'proposal_changed'


def test_existing_profile_without_a_version_must_be_adopted(person, full):
    pdir = apaths.profile_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / 'profile.yaml').write_text('candidate:\n  name: Hand Made\n')
    with pytest.raises(intake.IntakeError) as err:
        ok(person, full)
    assert err.value.code == 'adopt_first'
    assert (pdir / 'profile.yaml').read_text() == 'candidate:\n  name: Hand Made\n'
    assert not (users.user_dir(person) / 'profile-versions').exists() and intake.load_proposal(person, full.id).status == 'draft'


def test_confirm_races_with_edit(person, full):
    c = intake.confirmation(person, full.id, CONFIG)
    results = []
    def conf():
        try:
            results.append(intake.confirm(person, full.id, proposal_digest=c['proposal_digest'], scope_digest=c['scope_digest'], actor='person', config=CONFIG))
        except intake.IntakeError as e:
            results.append(e.code)
    def ed():
        with users.use(person):
            try:
                intake.edit(person, full.id, expected_revision=1, edits=[{'op': 'add', 'section': 'location', 'value': 'Perth'}])
                results.append('edited')
            except intake.IntakeError as e:
                results.append(e.code)
    ts = [threading.Thread(target=f) for f in (conf, ed)]
    [t.start() for t in ts]; [t.join() for t in ts]
    # exactly one wins; a confirmed version never contains an edit made after its digest was shown
    assert sorted(map(str, results)) in (['1', 'proposal_not_draft'], ['edited', 'proposal_changed'])


def test_hand_made_interests_file_must_be_adopted(person, full):
    pdir = apaths.profile_dir()
    (pdir / 'interests_and_criteria.yaml').write_text('target_roles:\n  titles: [Hand]\n')
    with pytest.raises(intake.IntakeError) as err:
        ok(person, full)
    assert err.value.code == 'adopt_first' and 'Hand' in (pdir / 'interests_and_criteria.yaml').read_text()
    assert not (users.user_dir(person) / 'profile-versions').exists()


def test_draft_without_base_is_refused_when_versions_exist(person, full, fake_llm, upload_id):
    other = intake.propose(person, [upload_id], fake_llm)             # a second concurrent draft, no base_version
    ok(person, full)
    assert intake.load_proposal(person, other.id).status == 'superseded'
    fresh = intake.propose(person, [upload_id], fake_llm)           # no base_version although v1 exists
    with pytest.raises(intake.IntakeError) as err:
        ok(person, fresh)
    assert err.value.code == 'proposal_changed' and [v['version'] for v in intake.versions(person)] == [1]


@pytest.mark.parametrize('crash', ['version_projection', 'proposal_save'])
@pytest.mark.parametrize('based', [False, True])
def test_confirm_resumes_after_a_crash(person, full, fake_llm, upload_id, monkeypatch, crash, based):
    target = full
    if based:
        assert ok(person, full) == 1
        target = intake.propose(person, [upload_id], fake_llm, base_version=1)
    first = 2 if based else 1
    real = intake._write_private if crash == 'version_projection' else intake.save_proposal
    state = {'boom': True}
    def flaky(*a, **kw):
        if state['boom'] and (crash == 'version_projection' or a[1].status == 'confirmed'):
            state['boom'] = False
            raise OSError('simulated crash')
        return real(*a, **kw)
    monkeypatch.setattr(intake, '_write_private' if crash == 'version_projection' else 'save_proposal', flaky)
    with pytest.raises(OSError):
        ok(person, target)
    assert intake.load_proposal(person, target.id).status == 'draft'
    current = intake.current_version(person)
    expected_current = (1 if based else None) if crash == 'version_projection' else first
    assert (current['version'] if current else None) == expected_current
    assert ok(person, target) == first                                     # retry finishes; no duplicate version
    assert [v['version'] for v in intake.versions(person)] == list(range(1, first + 1))
    assert intake.load_proposal(person, target.id).status == 'confirmed'
    d = vdir(person, first)
    for name in ('profile.yaml', 'interests_and_criteria.yaml'):
        assert (d / name).is_file()
    assert any((d / 'evidence' / source).is_file() for source in ('cv.md', 'master_resume.md'))


# ----------------------------------------------------------------------------- amendments and owner adoption
HAND = {'profile.yaml': 'candidate:\n  name: Hand Made\n',
        'master_resume.md': '# Hand Made\n\nLedger Co, Accounts Assistant, 2021 - 2023\n'}


def hand_made(files=HAND):
    pdir = apaths.profile_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (pdir / name).write_text(text)
    return {n: (pdir / n).read_bytes() for n in files}


def test_owner_profile_is_not_overwritten_without_adoption(person, full):
    before = hand_made()
    with pytest.raises(intake.IntakeError) as err:
        ok(person, full)
    assert err.value.code == 'adopt_first'
    assert intake.adopt_existing(person, actor='person') == 1
    assert {n: (apaths.profile_dir() / n).read_bytes() for n in before} == before      # adoption rewrites nothing
    d = vdir(person, 1)
    approved = json.loads((d / 'approved.json').read_text())
    assert approved['adopted_from_files'] is True and approved['actor'] == 'person' and approved['version'] == 1
    assert approved['evidence_bundle_hash'] == snapshot_evidence(d / 'evidence').bundle_hash
    for name, raw in before.items():
        if name in ('master_resume.md', 'evidence.yaml', 'profile.yaml'):
            assert (d / 'evidence' / name).read_bytes() == raw
    assert not (d / 'profile.yaml').exists()
    assert stat.S_IMODE((d / 'approved.json').stat().st_mode) == 0o600 and stat.S_IMODE(d.stat().st_mode) == 0o700
    assert intake.current_version(person)['version'] == 1
    assert intake.load_proposal(person, full.id).status == 'draft'


def test_adoption_then_amendment_projects_normally(person, full, fake_llm, upload_id):
    hand_made()
    intake.adopt_existing(person, actor='person')
    nxt = intake.propose(person, [upload_id], fake_llm, base_version=1)
    assert ok(person, nxt) == 2
    assert (apaths.profile_dir() / 'profile.yaml').read_text() == HAND['profile.yaml']
    assert (vdir(person, 2) / 'profile.yaml').is_file()


def test_an_adopted_owner_onboards_by_a_proposal_on_the_current_version(person, fake_llm, upload_id):
    hand_made()
    intake.adopt_existing(person, actor='person')
    assert intake.discovery_scope(person) is None                                      # adoption authorises nothing
    fake_llm.reply({'facts': [fact('experience', 'Accounts Assistant, Ledger Co', 'evidence', [Q(5, 'Ledger Co, Accounts Assistant, 2021 - 2023')])],
                    'questions': []})
    nxt = intake.propose(person, [upload_id], fake_llm, base_version=intake.current_version(person)['version'])
    shown = intake.confirmation(person, nxt.id, CONFIG)
    assert shown['scope'].basis and intake.discovery_scope(person) is None             # shown, not yet on
    assert intake.confirm(person, nxt.id, proposal_digest=shown['proposal_digest'], scope_digest=shown['scope_digest'],
                          actor='person', config=CONFIG) == 2
    assert intake.discovery_scope(person) == shown['scope']


def test_adoption_with_extra_hand_made_file_still_allows_next_version(person, full, fake_llm, upload_id):
    hand_made({**HAND, 'evidence.yaml': 'items: []\n'})
    intake.adopt_existing(person, actor='person')
    nxt = intake.propose(person, [upload_id], fake_llm, base_version=1)
    assert ok(person, nxt) == 2


def test_adoption_refusals(person):
    with pytest.raises(intake.IntakeError) as err:
        intake.adopt_existing(person, actor='person')
    assert err.value.code == 'nothing_to_adopt' and not (users.user_dir(person) / 'profile-versions').exists()
    hand_made()
    with pytest.raises(intake.IntakeError) as err:
        intake.adopt_existing(person, actor='agent')
    assert err.value.code == 'person_required' and intake.current_version(person) is None
    assert intake.adopt_existing(person, actor='person') == 1
    with pytest.raises(intake.IntakeError) as err:
        intake.adopt_existing(person, actor='person')
    assert err.value.code == 'already_adopted' and [v['version'] for v in intake.versions(person)] == [1]


def test_adoption_is_refused_once_any_version_exists(person, full):
    ok(person, full)
    with pytest.raises(intake.IntakeError) as err:
        intake.adopt_existing(person, actor='person')
    assert err.value.code == 'already_adopted'


def test_amendment_does_not_change_approved_facts_until_confirmed(person, full, fake_llm, upload_id):
    intake.answer(person, full.id, expected_revision=1, question_id=next(q.id for q in full.questions if q.section == 'availability'), text='Immediately')
    ok(person, intake.load_proposal(person, full.id))
    v1 = intake.current_version(person)
    old = next(f for f in v1['facts'] if f['section'] == 'availability')
    profile_before = {p.name: p.read_bytes() for p in apaths.profile_dir().iterdir()}
    version_before = (vdir(person, 1) / 'approved.json').read_bytes()
    fake_llm.reply({'facts': [fact('experience', 'Accounts Assistant, Ledger Co', 'evidence', [Q(5, 'Ledger Co, Accounts Assistant, 2021 - 2023')]),
                              fact('availability', 'From March, 20 hours', 'inference'), fact('skill', 'Payroll', 'inference'),
                              fact('availability', 'Immediately', 'inference')], 'questions': []})
    amend = intake.propose(person, [upload_id], fake_llm, base_version=1)
    notes = {f.value: f.note for f in amend.facts if f.section in ('availability', 'skill') and f.basis != 'unknown'}
    assert notes['From March, 20 hours'] == f'replaces {old["id"]}'
    assert notes['Payroll'] == '' and notes['Immediately'] == ''                       # new, or unchanged: no replacement
    assert amend.status == 'draft' and amend.base_version == 1
    assert intake.current_version(person) == v1 and (vdir(person, 1) / 'approved.json').read_bytes() == version_before
    assert {p.name: p.read_bytes() for p in apaths.profile_dir().iterdir()} == profile_before
    assert ok(person, amend) == 2
    assert intake.current_version(person)['version'] == 2 and (vdir(person, 1) / 'approved.json').read_bytes() == version_before


def test_hand_edit_after_adoption_is_refused_not_overwritten(person, full, fake_llm, upload_id):
    hand_made()
    intake.adopt_existing(person, actor='person')
    (apaths.profile_dir() / 'profile.yaml').write_text('candidate:\n  name: Edited Later\n')
    nxt = intake.propose(person, [upload_id], fake_llm, base_version=1)
    with pytest.raises(intake.IntakeError) as err:
        ok(person, nxt)
    assert err.value.code == 'profile_edited_by_hand'
    assert (apaths.profile_dir() / 'profile.yaml').read_text() == 'candidate:\n  name: Edited Later\n'
    assert [v['version'] for v in intake.versions(person)] == [1] and intake.load_proposal(person, nxt.id).status == 'draft'


def test_hand_edit_after_a_confirmed_version_is_refused(person, full, fake_llm, upload_id):
    hand_made()
    intake.adopt_existing(person, actor='person')
    (apaths.profile_dir() / 'master_resume.md').write_text('hand edit\n')
    with pytest.raises(intake.IntakeError) as err:
        ok(person, intake.propose(person, [upload_id], fake_llm, base_version=1))
    assert err.value.code == 'profile_edited_by_hand' and (apaths.profile_dir() / 'master_resume.md').read_text() == 'hand edit\n'


def test_a_hand_edit_after_confirmation_turns_discovery_off_until_the_files_match_again(person, full, fake_llm, upload_id):
    from jobwatch import discovery_gate
    ok(person, full)
    assert intake.discovery_scope(person) is not None and discovery_gate.allowed('run')
    path = vdir(person, 1) / 'profile.yaml'
    confirmed = path.read_bytes()
    path.write_text(confirmed.decode() + '# unreviewed derived edit\n')
    assert intake.discovery_scope(person) is not None and discovery_gate.allowed('run')
    path.write_bytes(confirmed)


def test_a_removed_file_or_an_added_file_does_not_turn_discovery_off(person, full):
    ok(person, full)
    recorded = intake.current_version(person)['file_sha256']
    assert 'master_resume.md' in recorded
    (apaths.profile_dir() / 'zzz-notes.txt').write_text('not a profile file\n')
    assert intake.discovery_scope(person) is not None


def test_discovery_scope_is_checked_as_the_person_not_the_ambient_user(person, full):
    ok(person, full)
    (apaths.profile_dir() / 'master_resume.md').write_text('edited source\n')
    users.create_user_dirs('other')
    with users.use('other'):
        assert intake.discovery_scope('sam') is None


def test_adopted_extras_are_carried_into_the_next_evidence_snapshot(person, full, fake_llm, upload_id):
    hand_made({**HAND, 'evidence.yaml': 'items: []\n'})
    intake.adopt_existing(person, actor='person')
    assert ok(person, intake.propose(person, [upload_id], fake_llm, base_version=1)) == 2
    d = vdir(person, 2)
    assert (d / 'evidence' / 'evidence.yaml').read_text() == 'items: []\n' and not (d / 'evidence.yaml').exists()
    approved = json.loads((d / 'approved.json').read_text())
    assert approved['evidence_bundle_hash'] == snapshot_evidence(d / 'evidence').bundle_hash
    assert set(approved['file_sha256']) == {'master_resume.md', 'evidence.yaml'}
    assert (apaths.profile_dir() / 'evidence.yaml').read_text() == 'items: []\n'


def test_new_hand_made_file_after_adoption_still_needs_adoption(person, full, fake_llm, upload_id):
    hand_made()
    intake.adopt_existing(person, actor='person')
    (apaths.profile_dir() / 'evidence.yaml').write_text('items: []\n')            # not in adopted_files
    with pytest.raises(intake.IntakeError) as err:
        ok(person, intake.propose(person, [upload_id], fake_llm, base_version=1))
    assert err.value.code == 'adopt_first' and [v['version'] for v in intake.versions(person)] == [1]


def test_adopted_version_is_listed_and_symlinks_are_not_adopted(person):
    pdir = apaths.profile_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    (users.user_dir(person) / 'elsewhere.yaml').write_text('x: 1\n')
    (pdir / 'profile.yaml').symlink_to(users.user_dir(person) / 'elsewhere.yaml')
    with pytest.raises(intake.IntakeError) as err:
        intake.adopt_existing(person, actor='person')
    assert err.value.code == 'unreadable_document' and intake.current_version(person) is None
    (pdir / 'profile.yaml').unlink()
    hand_made()
    intake.adopt_existing(person, actor='person')
    assert intake.versions(person)[0]['version'] == 1 and intake.current_version(person)['adopted_from_files'] is True


# ----------------------------------------------------------------------------- turning discovery on without a new proposal
def test_confirm_refuses_a_proposal_with_an_empty_basis(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('education', 'Diploma of Accounting', 'evidence', [Q(10, 'Diploma of Accounting, Example College, 2020')])],
                    'questions': []})
    with pytest.raises(intake.IntakeError) as err:
        ok(person, intake.propose(person, [upload_id], fake_llm))
    assert err.value.code == 'profile_incomplete' and intake.current_version(person) is None


def test_stored_scope_with_empty_basis_authorises_nothing(person, full):
    ok(person, full)
    path = vdir(person, 1) / 'approved.json'
    approved = json.loads(path.read_text())
    approved['scope']['basis'] = []
    approved['scope_digest'] = intake._scope_digest(intake.SearchScope.model_validate(approved['scope'], strict=False))
    path.write_text(json.dumps(approved))
    assert intake.discovery_scope(person) is None


# ----------------------------------------------------------------------------- background parse (guided onboarding)
import threading
import time


class BlockingLLM:
    """Holds the parse open until .release is set (never forever: waits are bounded)."""
    def __init__(self, inner, fail=None):
        self.inner, self.fail, self.base_url = inner, fail, inner.base_url
        self.started, self.release = threading.Event(), threading.Event()

    def chat(self, *a, **kw):
        self.started.set()
        assert self.release.wait(10), 'test never released the parse'
        if self.fail:
            raise self.fail
        return self.inner.chat(*a, **kw)


def settle(person, pid, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = intake.load_proposal(person, pid)
        if got.status != 'parsing':
            return got
        time.sleep(0.01)
    raise AssertionError('parse did not finish')


@pytest.fixture
def held(fake_llm):
    llm = BlockingLLM(fake_llm)
    yield llm
    llm.release.set()                       # never leave a parse thread waiting
    deadline = time.monotonic() + 10
    while intake._inflight and time.monotonic() < deadline:
        time.sleep(0.01)


def test_questions_available_before_parse_finishes(person, held, upload_id):
    p = intake.start_proposal(person, [upload_id], held)
    assert p.status == 'parsing' and p.revision == 1 and p.parse_error == ''
    assert held.started.wait(10)
    sections = {q.section for q in p.questions}
    assert set(intake.ASK_WHEN_ABSENT) | {'career_focus', 'location'} <= sections
    assert all(f.basis == 'unknown' for f in p.facts)
    assert intake.load_proposal(person, p.id) == p
    held.release.set()
    done = settle(person, p.id)
    assert done.status == 'draft' and done.revision == 2


def test_answer_during_parse_survives_merge(person, held, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('career_focus', 'Data analysis', 'inference'),
                              fact('experience', 'Accounts Assistant, Ledger Co', 'evidence',
                                   [{'line': 5, 'quote': 'Ledger Co, Accounts Assistant, 2021 - 2023'}])],
                    'questions': [{'section': 'preference', 'text': 'Remote or office?', 'why': 'Fit.'}]})
    p = intake.start_proposal(person, [upload_id], held)
    qid = next(q.id for q in p.questions if q.section == 'career_focus')
    mid = intake.answer(person, p.id, expected_revision=1, question_id=qid, text='Bookkeeping')
    assert mid.revision == 2 and mid.status == 'parsing'
    held.release.set()
    done = settle(person, p.id)
    focus = [f for f in done.facts if f.section == 'career_focus']
    assert [(f.value, f.actor) for f in focus] == [('Bookkeeping', 'person')]       # the parsed inference lost
    assert any(f.section == 'experience' and f.basis == 'evidence' for f in done.facts)
    assert done.revision == 3 and done.status == 'draft' and done.parse_error == ''
    assert qid not in [q.id for q in done.questions]                                 # answered stays closed
    assert 'Remote or office?' in [q.text for q in done.questions]
    assert len({f.id for f in done.facts}) == len(done.facts) and len({q.id for q in done.questions}) == len(done.questions)
    with pytest.raises(intake.IntakeError, match='proposal_changed'):                # a client holding revision 2 must re-read
        intake.edit(person, p.id, expected_revision=2, edits=[{'op': 'add', 'section': 'skill', 'value': 'Excel'}])


def test_confirm_refused_while_parsing(person, held, upload_id):
    p = intake.start_proposal(person, [upload_id], held)
    with pytest.raises(intake.IntakeError, match='proposal_parsing'):
        intake.confirm(person, p.id, proposal_digest=intake.digest(p), scope_digest='x', actor='person', config={})
    with pytest.raises(intake.IntakeError, match='proposal_parsing'):
        intake.confirmation(person, p.id, {})


def test_one_parse_per_person_and_slot_released(person, held, fake_llm, upload_id):
    p = intake.start_proposal(person, [upload_id], held)
    with pytest.raises(intake.IntakeError, match='proposal_in_progress'):
        intake.start_proposal(person, [upload_id], held)
    with pytest.raises(intake.IntakeError, match='proposal_in_progress'):
        intake.propose(person, [upload_id], fake_llm)                                 # the sync entry shares the slot
    held.release.set()
    settle(person, p.id)
    end = time.monotonic() + 10
    while intake._inflight and time.monotonic() < end:
        time.sleep(0.01)
    assert intake.propose(person, [upload_id], fake_llm).status == 'draft'


def test_start_proposal_unknown_upload_creates_nothing(person, held):
    with pytest.raises(intake.IntakeError, match='upload_not_found'):
        intake.start_proposal(person, ['0' * 16], held)
    assert not (users.user_dir(person) / 'intake' / 'proposals').exists() and not intake._inflight


def test_parse_failure_keeps_answers(person, fake_llm, upload_id):
    held = BlockingLLM(fake_llm, fail=intake.IntakeError('parse_failed'))
    p = intake.start_proposal(person, [upload_id], held)
    qid = next(q.id for q in p.questions if q.section == 'work_rights')
    intake.answer(person, p.id, expected_revision=1, question_id=qid, text='Citizen')
    held.release.set()
    done = settle(person, p.id)
    assert done.status == 'draft' and done.parse_error == 'parse_failed'
    assert any(f.section == 'work_rights' and f.value == 'Citizen' and f.actor == 'person' for f in done.facts)
    assert qid not in [q.id for q in done.questions]
    other = BlockingLLM(fake_llm, fail=RuntimeError('boom'))                          # an unexpected error is a fixed code too
    p2 = intake.start_proposal(person, [upload_id], other)
    other.release.set()
    assert settle(person, p2.id).parse_error == 'parse_failed'


def test_add_uploads_merges_incrementally(person, fake_llm, upload_id):
    fake_llm.reply({'facts': [fact('skill', 'Excel', 'inference')], 'questions': []})
    p = intake.start_proposal(person, [upload_id], fake_llm)
    first = settle(person, p.id)
    mine = intake.edit(person, p.id, expected_revision=first.revision,
                       edits=[{'op': 'add', 'section': 'availability', 'value': 'From March'}])
    letter = intake.save_upload(person, 'letter.txt', b'Dear team\nI led the audit at Ledger Co\n', 'letter')
    fake_llm.reply({'facts': [fact('skill', 'Excel', 'inference'), fact('experience', 'Audit lead', 'evidence',
                                                                      [{'line': 2, 'quote': 'I led the audit at Ledger Co'}]),
                              fact('availability', 'Immediately', 'inference')], 'questions': []})
    added = intake.add_uploads(person, p.id, [letter['upload_id']], fake_llm)
    assert added.status == 'parsing' and added.revision == mine.revision + 1
    done = settle(person, p.id)
    assert done.status == 'draft' and done.revision == added.revision + 1
    assert [f.value for f in done.facts if f.section == 'availability' and f.basis != 'unknown'] == ['From March']   # person's untouched
    assert [f.value for f in done.facts if f.section == 'skill'] == ['Excel']                                      # no duplicate
    audit = next(f for f in done.facts if f.section == 'experience')
    assert audit.sources[0].upload_sha256 == letter['sha256'] and len(done.uploads) == 2
    assert [f for f in done.facts if f.actor == 'person'] == [f for f in mine.facts if f.actor == 'person']


def test_add_uploads_needs_a_draft_and_no_parse_in_flight(person, held, fake_llm, upload_id):
    p = intake.start_proposal(person, [upload_id], held)
    with pytest.raises(intake.IntakeError, match='proposal_parsing'):
        intake.add_uploads(person, p.id, [upload_id], fake_llm)
    held.release.set()
    settle(person, p.id)
    with pytest.raises(intake.IntakeError, match='upload_not_found'):
        intake.add_uploads(person, p.id, ['0' * 16], fake_llm)
    with pytest.raises(intake.IntakeError, match='proposal_not_found'):
        intake.add_uploads(person, '0' * 16, [upload_id], fake_llm)


def test_parse_runs_as_the_person_and_slot_is_per_person(person, held, fake_llm, upload_id):
    users.create_user_dirs('kim')
    kim_up = intake.save_upload('kim', 'cv.txt', SYNTHETIC_CV.encode(), 'cv')['upload_id']
    p = intake.start_proposal(person, [upload_id], held)
    q = intake.start_proposal('kim', [kim_up], fake_llm)                              # another person is not blocked
    assert settle('kim', q.id).status == 'draft'
    held.release.set()
    assert settle(person, p.id).status == 'draft'
    assert not (users.user_dir('kim') / 'intake' / 'proposals' / (p.id + '.json')).exists()


def _profile(person, **files):
    pdir = users.user_dir(person) / 'profile'
    pdir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (pdir / name.replace('_dot_', '.')).write_text(text)
    return pdir


def test_upload_profile_files_offers_the_persons_own_files(person, fake_llm):
    _profile(person, **{'master_resume_dot_md': SYNTHETIC_CV, 'profile_dot_yaml': 'name: x\n',
                        'notes_dot_md': 'not an allowed name'})
    ids = intake.upload_profile_files(person)
    assert len(ids) == 1                                                              # yaml is not an upload type; notes not allowed
    p = intake.start_proposal(person, ids, fake_llm)
    assert settle(person, p.id).uploads


def test_upload_profile_files_refuses_symlinks(person):
    pdir = _profile(person, **{'cv_dot_md': 'x'})
    (pdir / 'cv.md').unlink()
    outside = pdir.parent / 'secret.md'
    outside.write_text('private')
    (pdir / 'cv.md').symlink_to(outside)
    with pytest.raises(intake.IntakeError, match='unreadable_document'):
        intake.upload_profile_files(person)
    assert not (users.user_dir(person) / 'intake' / 'uploads.json').exists()


def test_upload_profile_files_with_nothing_to_offer(person):
    assert intake.upload_profile_files(person) == []


def _backdate(person, pid, seconds):
    import os
    path = users.user_dir(person) / 'intake' / 'proposals' / (pid + '.json')
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_a_parsing_draft_with_no_live_parse_is_recovered(person, fake_llm, upload_id, monkeypatch):
    real, dead = intake._spawn, {'on': True}
    monkeypatch.setattr(intake, '_spawn', lambda *a: None if dead['on'] else real(*a))   # no worker runs: the process "died"
    p = intake.start_proposal(person, [upload_id], fake_llm)
    qid = next(q.id for q in p.questions if q.section == 'career_focus')
    mine = intake.answer(person, p.id, expected_revision=1, question_id=qid, text='Bookkeeping')
    intake._release(person)                                            # and its slot is gone
    assert intake.load_proposal(person, p.id).status == 'parsing'      # too fresh: another process may still own it
    _backdate(person, p.id, 2 * intake.PARSE_SECONDS + 30)
    got = intake.load_proposal(person, p.id)
    assert got.status == 'draft' and got.parse_error == 'parse_interrupted' and got.revision == mine.revision + 1
    assert [f.value for f in got.facts if f.actor == 'person'] == ['Bookkeeping']
    assert intake.open_proposal(person).status == 'draft'
    dead['on'] = False
    assert intake.add_uploads(person, p.id, [upload_id], fake_llm).status == 'parsing'   # usable again
    settle(person, p.id)


def test_a_parsing_draft_with_a_live_slot_is_not_recovered(person, fake_llm, upload_id, monkeypatch):
    monkeypatch.setattr(intake, '_spawn', lambda *a: None)
    p = intake.start_proposal(person, [upload_id], fake_llm)           # the slot stays claimed
    _backdate(person, p.id, 2 * intake.PARSE_SECONDS + 30)
    assert intake.load_proposal(person, p.id).status == 'parsing'
    intake._release(person)


def test_start_proposal_that_cannot_spawn_finishes_as_parse_failed(person, fake_llm, upload_id, monkeypatch):
    def boom(*a):
        raise RuntimeError('cannot start thread')
    monkeypatch.setattr(intake, '_spawn', boom)
    with pytest.raises(RuntimeError):
        intake.start_proposal(person, [upload_id], fake_llm)
    saved = intake.open_proposal(person)
    assert saved.status == 'draft' and saved.parse_error == 'parse_failed' and not intake._inflight


# ----------------------------------------------------------------------------- paid route: every parse path checks it
def _bodies_after(fake_llm, run):
    before = len(fake_llm.bodies)
    with pytest.raises(intake.IntakeError) as exc:
        run()
    assert len(fake_llm.bodies) == before                       # the person's text never reached a model
    return exc.value.code


@pytest.mark.parametrize('model', ['openrouter/free-model', 'claude/opus-4', 'stealth-stack'])
def test_every_parse_path_refuses_a_model_that_is_not_an_approved_paid_route(person, fake_llm, upload_id, model):
    draft = intake.propose(person, [upload_id], fake_llm)                 # allowed while the reader model is paid
    model_choice.set_models({'reader': model}, person)
    refused = lambda run: _bodies_after(fake_llm, run)
    assert refused(lambda: intake.propose(person, [upload_id], fake_llm)) == 'model_not_allowed'
    assert refused(lambda: intake.start_proposal(person, [upload_id], fake_llm)) == 'model_not_allowed'
    assert refused(lambda: intake.add_uploads(person, draft.id, [upload_id], fake_llm)) == 'model_not_allowed'
    assert [p.id for p in [intake.load_proposal(person, draft.id)]] == [draft.id] and not intake._inflight
    assert intake.load_proposal(person, draft.id).revision == 1       # the refused add changed nothing


def test_every_parse_path_refuses_a_gateway_that_is_not_the_local_one(person, upload_id):
    other = FakeLLM()
    other.base_url = 'https://example.invalid/v1'
    code = lambda run: _bodies_after(other, run)
    assert code(lambda: intake.propose(person, [upload_id], other)) == 'gateway_not_allowed'
    assert code(lambda: intake.start_proposal(person, [upload_id], other)) == 'gateway_not_allowed'
    assert intake.open_proposal(person) is None and not intake._inflight      # no draft, no slot held
