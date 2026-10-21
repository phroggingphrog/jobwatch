"""Private uploads and sourced profile proposals (synthetic documents only)."""
import json
import stat

import pytest

from jobwatch import model_choice, users
from jobwatch.candidate import intake
from jobwatch.llm import LLM

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

    def reply(self, data):
        self.next = data

    def chat(self, *a, **kw):
        return self.llm.chat(*a, **kw)


@pytest.fixture
def person():
    users.create_user_dirs('sam')
    with users.use('sam'):
        yield 'sam'


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
