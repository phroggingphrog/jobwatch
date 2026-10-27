"""End to end on a realistic filled application (see tests/realapp.py): overview -> detail -> review -> Submit (digest +
shown_hash) queued -> second Submit refused -> the owner edits the live form -> review changes -> the old hash is refused.
Real fill, real browser page, real native review API, real digest. Nothing is ever pressed: the employer form is local and the
worker that presses a queued Submit is not running."""
import pytest

pytest.importorskip('playwright')
pytest.importorskip('weasyprint')

import sqlite3  # noqa: E402

import requests  # noqa: E402

from tests import realapp  # noqa: E402

H = {'Authorization': 'Bearer ' + realapp.CONNECTOR_TOKEN}


@pytest.fixture   # per test: tests/conftest.py resets JOBWATCH_* around each test, which would break a shared one
def app(tmp_path):
    with realapp.real_application(tmp_path) as running:
        yield running


def get(app, path):
    return requests.get(app.connector + path, headers=H, timeout=60)


def post(app, path, body):
    return requests.post(app.connector + path, headers=H, json=body, timeout=60)


def test_overview_and_detail_show_the_application(app):
    overview = get(app, '/connector/overview').json()
    assert [(j['posting_id'], j['employer'], j['state']) for j in overview['jobs']] == [(1, 'Acme Pty Ltd', 'draft ready')]
    detail = get(app, '/connector/jobs/1').json()['job']
    assert detail['employer'] == 'Acme Pty Ltd' and detail['can_submit'] is True and 'submit_digest' not in str(detail)


def test_the_fill_stored_the_original_file_names(app):
    from jobwatch import users
    from jobwatch.apply import prepare
    with users.use('owner'):
        prepared = prepare.latest_preparation(users.user_dir(), '1')
    assert prepared['document_names'] == {'cv': realapp.CV_NAME, 'letter': realapp.LETTER_NAME}
    assert app.form_value('motivation') == realapp.MOTIVATION


def test_review_submit_second_submit_edit_review_old_hash(app):
    first = get(app, '/connector/jobs/1/review').json()
    review, digest = first['review'], first['submit_digest']
    assert review['ready'] and digest and digest not in str(review)
    answers = {a['question']: a['answer'] for a in review['answers']}
    assert answers['Why are you suitable for this role?'] == realapp.MOTIVATION            # long, multi-paragraph, in full
    assert answers['Full name'] == 'Alex Example'
    assert [(d['label'], d['file']) for d in review['documents']] == [('CV', realapp.CV_NAME), ('Cover letter', realapp.LETTER_NAME)]

    # a wrong hash or digest queues nothing
    assert post(app, '/connector/jobs/1/submit', {'confirm_digest': digest, 'shown_hash': 'f' * 64}).status_code == 400
    assert post(app, '/connector/jobs/1/submit', {'confirm_digest': 'a' * 64, 'shown_hash': review['shown_hash']}).status_code == 400
    assert app.queued() == []

    # Submit with the digest and the hash of what was shown: queued (not pressed)
    ok = post(app, '/connector/jobs/1/submit', {'confirm_digest': digest, 'shown_hash': review['shown_hash']})
    assert ok.status_code == 200 and ok.json()['status'] == 'queued'
    assert [status for _, status in app.queued()] == ['pending']
    # the second Submit is refused and queues nothing more
    again = post(app, '/connector/jobs/1/submit', {'confirm_digest': digest, 'shown_hash': review['shown_hash']})
    assert again.status_code == 400 and len(app.queued()) == 1

    # the owner edits the live form; the review now shows the edit, with a new hash and digest
    edited_text = realapp.MOTIVATION.replace('three days a week', 'two days a week')
    app.edit('motivation', edited_text)
    second = get(app, '/connector/jobs/1/review').json()
    assert second['review']['state'] == 'awaiting browser press'                             # the queued press is shown as such
    assert second['review']['ready'] is True
    answers = {a['question']: a['answer'] for a in second['review']['answers']}
    assert answers['Why are you suitable for this role?'] == edited_text
    assert second['review']['shown_hash'] != review['shown_hash'] and second['submit_digest'] != digest
    # a Submit against the fresh review is still refused: a press is already queued, and the edit is not confirmed by it
    refused = post(app, '/connector/jobs/1/submit', {'confirm_digest': second['submit_digest'], 'shown_hash': second['review']['shown_hash']})
    assert refused.status_code == 400 and refused.json()['error'] == 'submit_already_queued'
    assert len(app.queued()) == 1
    # the old hash is refused, whatever the state
    assert post(app, '/connector/jobs/1/submit', {'confirm_digest': digest, 'shown_hash': review['shown_hash']}).status_code == 400
    assert len(app.queued()) == 1
    assert ('POST', '/submit') not in app.employer_requests()                                 # nothing reached the employer


def test_edit_before_submit_is_reviewed_confirmed_and_queued_against_the_fresh_hash(app):
    """The owner fixes an answer in the browser after the fill: the review shows the edit (no dead end), the old hash is
    refused, and Submit against the fresh review records the person's confirmation of the edited form and queues once."""
    before = get(app, '/connector/jobs/1/review').json()
    assert before['review']['ready']
    edited_text = realapp.MOTIVATION.replace('Melbourne', 'Melbourne, Victoria')
    app.edit('motivation', edited_text)
    fresh = get(app, '/connector/jobs/1/review').json()
    assert fresh['review']['ready'] and 'reason' not in fresh['review']
    answers = {a['question']: a['answer'] for a in fresh['review']['answers']}
    assert answers['Why are you suitable for this role?'] == edited_text
    assert fresh['submit_digest'] != before['submit_digest'] and fresh['review']['shown_hash'] != before['review']['shown_hash']
    # what the person saw before the edit is refused and nothing is queued
    assert post(app, '/connector/jobs/1/submit', {'confirm_digest': before['submit_digest'], 'shown_hash': before['review']['shown_hash']}).status_code == 400
    assert post(app, '/connector/jobs/1/submit', {'confirm_digest': fresh['submit_digest'], 'shown_hash': before['review']['shown_hash']}).status_code == 400
    assert app.queued() == []
    ok = post(app, '/connector/jobs/1/submit', {'confirm_digest': fresh['submit_digest'], 'shown_hash': fresh['review']['shown_hash']})
    assert ok.status_code == 200 and ok.json()['status'] == 'queued'
    row = sqlite3.connect(app.db).execute('SELECT digest FROM submit_requests').fetchone()
    assert row == (fresh['submit_digest'],)                       # the queued press is bound to the edited form's digest
    # after the rebind the same edited form needs no further confirmation: the review is stable and agrees
    again = get(app, '/connector/jobs/1/review').json()
    assert again['submit_digest'] == fresh['submit_digest']
    assert post(app, '/connector/jobs/1/submit', {'confirm_digest': fresh['submit_digest'], 'shown_hash': fresh['review']['shown_hash']}).status_code == 400
    assert len(app.queued()) == 1 and ('POST', '/submit') not in app.employer_requests()
