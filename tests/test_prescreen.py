"""Prescreen: one generic engine driven by database rows. Synthetic people and postings only; no model, no network."""
import json
import sqlite3

import pytest

from conftest import make_config
from jobwatch import adtext, db
from jobwatch.candidate import policy as policy_mod
from jobwatch.filters import Rules
from jobwatch.models import Posting
from jobwatch.prescreen import lifecycle, store, sync
from jobwatch.prescreen.engine import Engine, PostingFields
from tests.candidate.policy_fixtures import fact, policy_of


def accountant():
    """A graduate accountant: entry/junior roles in Victoria, no citizenship, a 48 hour fortnight, programs may be full time."""
    return policy_of(
        fact('location', 'Melbourne VIC'), fact('preference', {'seniority': ['entry', 'junior']}),
        fact('exclusion', {'kind': 'family', 'value': 'hospitality'}, fid='x1'),
        fact('exclusion', {'kind': 'family', 'value': 'customer_service'}, fid='x2'),
        fact('work_rights', {'citizen_or_pr': False, 'hours_limit_per_fortnight': 48, 'full_time_programs_ok': True}))


def nurse():
    """A mid-level nurse: mid-level roles in New South Wales, a citizen, no casual work, not accounting or IT."""
    return policy_of(
        fact('location', 'Sydney NSW'), fact('preference', {'seniority': ['mid-level']}),
        fact('exclusion', {'kind': 'family', 'value': 'accounting'}, fid='x1'),
        fact('exclusion', {'kind': 'family', 'value': 'it'}, fid='x2'),
        fact('exclusion', {'kind': 'work_type', 'value': 'casual'}, fid='x3'),
        fact('work_rights', {'citizen_or_pr': True}))


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / 'p.db')
    yield c
    c.close()


def engine(conn, pol):
    return Engine.load(conn, pol)


def run(eng, title, location='', ad='', hours='', remote=False):
    return eng.evaluate(PostingFields(title=title, location=location, ad_text=ad, hours=hours, remote=remote))


# -- schema and seeds -------------------------------------------------------------------
def test_migration_from_empty_creates_tables_and_seeds(tmp_path):
    c = db.connect(tmp_path / 'new.db')
    assert c.execute('PRAGMA user_version').fetchone()[0] == len(db.MIGRATIONS)
    assert {'prescreen_terms', 'prescreen_rules', 'prescreen_overrides', 'prescreen_decisions'} <= {
        r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cats = {r[0] for r in c.execute('SELECT DISTINCT category FROM prescreen_terms')}
    assert cats == set(store.CATEGORIES)


def test_migration_from_the_previous_version_keeps_data_and_is_repeatable(tmp_path):
    c = sqlite3.connect(tmp_path / 'old.db')
    c.row_factory = sqlite3.Row
    for index, script in enumerate(db.MIGRATIONS[:-1], start=1):
        for statement in db._statements(script):
            c.execute(statement)
        c.execute(f'PRAGMA user_version={index}')
    c.commit()
    c.execute("INSERT INTO postings(source,source_id,url,url_hash,dedupe_key,title,first_seen_at,last_seen_at) "
              "VALUES('s','1','https://example.invalid/1','h','k','Old role','2026-01-01','2026-01-01')")
    c.commit()
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert store.ensure_seeds(c) > 0
    n = c.execute('SELECT COUNT(*) FROM prescreen_terms').fetchone()[0]
    assert db.migrate(c) == len(db.MIGRATIONS) and store.ensure_seeds(c) == 0
    assert c.execute('SELECT COUNT(*) FROM prescreen_terms').fetchone()[0] == n
    assert c.execute('SELECT title FROM postings').fetchone()[0] == 'Old role'


def test_every_seed_term_compiles_and_a_bad_regex_is_rejected(conn):
    for r in conn.execute('SELECT term, match_type FROM prescreen_terms'):
        store.compile_term(r['term'], r['match_type'])
    with pytest.raises(ValueError, match='bad regex'):
        store.add_term(conn, category='seniority_level', term='(unclosed', match_type='regex')
    with pytest.raises(ValueError):
        store.add_term(conn, category='nonsense', term='x')


def test_reseeding_does_not_undo_a_person_edit(conn):
    tid = conn.execute("SELECT id FROM prescreen_terms WHERE term='\\bsenior\\b'").fetchone()[0]
    store.set_term_enabled(conn, tid, False)
    conn.execute("DELETE FROM state WHERE key=?", (store.SEED_STATE_KEY,))
    store.ensure_seeds(conn)
    assert conn.execute('SELECT enabled FROM prescreen_terms WHERE id=?', (tid,)).fetchone()[0] == 0


# -- each stage, for two different people ---------------------------------------------------
@pytest.mark.parametrize('who,title,skips', [
    (accountant, 'Senior Accountant', True), (accountant, 'Principal Engineer, Payments', True),
    (accountant, 'Senior Product Marketing Manager', True), (accountant, 'National Learning Manager, Audit', True),
    (accountant, 'Graduate Accountant', False), (accountant, 'Junior Accounts Officer', False),
    (accountant, 'Accounts Officer', False), (accountant, 'Head Office Accountant', False),
    (accountant, 'Executive Accountant', False),                       # 'executive' alone is weak: flag, never a skip
    (nurse, 'Nurse Manager', True), (nurse, 'Senior Registered Nurse', True), (nurse, 'Graduate Nurse', True),
    (nurse, 'Registered Nurse', False), (nurse, 'Mid-level Registered Nurse', False),
])
def test_level_stage(conn, who, title, skips):
    out = run(engine(conn, who()), title)
    assert out.skip is skips
    if skips:
        assert out.category == 'seniority_level' and out.matched_text and 'approved levels' in out.reason


def test_no_level_in_the_profile_means_no_level_screen(conn):
    p = policy_of(fact('location', 'Melbourne VIC'))
    assert not run(engine(conn, p), 'Principal Engineer').skip


def test_years_stage(conn):
    acc, nur = engine(conn, accountant()), engine(conn, nurse())
    ask5 = '5+ years of experience in accounts payable is required.'
    assert run(acc, 'Accounts Officer', ad=ask5).skip and run(acc, 'Accounts Officer', ad=ask5).category == 'experience'
    assert not run(acc, 'Accounts Officer', ad='1-2 years experience preferred').skip
    assert not run(acc, 'Accounts Officer', ad='We have 25 years of experience serving clients.').skip
    assert not run(nur, 'Registered Nurse', ad=ask5).skip                          # a mid-level nurse tolerates 5
    assert run(nur, 'Registered Nurse', ad='Minimum of 10 years experience in acute care.').skip
    # senior approved: no years cap at all
    assert not run(engine(conn, policy_of(fact('preference', {'seniority': ['senior']}))), 'Analyst', ad=ask5 + ' 15 years experience').skip


def test_employment_stage(conn):
    acc, nur = engine(conn, accountant()), engine(conn, nurse())
    assert run(acc, 'Accountant - Full Time').skip
    assert not run(acc, 'Graduate Accountant - Full Time').skip                    # programs may be full time
    assert not run(acc, 'Accountant - Part Time').skip
    flagged = run(acc, 'Accounts Officer', hours='FT')
    assert not flagged.skip                                                        # the source's FT field is weak evidence
    assert run(nur, 'Casual Registered Nurse').skip and run(nur, 'Casual Registered Nurse').category == 'employment_type'
    assert not run(nur, 'Registered Nurse (part time or casual)').skip             # one unblocked type is enough


def test_work_rights_stage(conn):
    acc, nur = engine(conn, accountant()), engine(conn, nurse())
    assert run(acc, 'Accounts Officer', ad='Applicants must be an Australian citizen.').skip
    assert run(acc, 'Analyst', ad='Baseline security clearance is required.').skip
    assert run(acc, 'Analyst', ad='Must hold NV1 clearance.').category == 'work_rights'
    assert not run(acc, 'Analyst', ad='Applicants must be Australian citizens or hold a valid visa.').skip
    assert not run(acc, 'Analyst', ad='We employ regardless of citizenship status.').skip
    out = run(nur, 'Registered Nurse', ad='Australian citizens only.')
    assert out.outcome == 'flag' and out.flags                                     # a citizen is not blocked, the ad is flagged
    sponsored = policy_of(fact('work_rights', {'requires_sponsorship': True}))
    assert run(engine(conn, sponsored), 'Analyst', ad='No visa sponsorship is available.').skip
    assert not run(engine(conn, policy_of(fact('experience', 'x'))), 'Analyst', ad='Must be an Australian citizen.').skip   # no stated status


def test_location_stage(conn):
    acc, nur = engine(conn, accountant()), engine(conn, nurse())
    assert run(acc, 'Senior Accountant — Western Australia').skip                  # (also a level mismatch)
    assert run(acc, 'Accounts Officer - WA').category == 'location_outside'
    assert run(acc, 'Accounts Officer', 'Perth WA').skip
    assert not run(acc, 'Accounts Officer', 'Melbourne VIC').skip
    assert not run(acc, 'Accounts Officer', '').skip and not run(acc, 'Accounts Officer', 'Australia').skip   # unknown stays assessable
    assert not run(acc, 'Accounts Officer', 'Melbourne VIC; Sydney NSW').skip      # an alternative inside the profile region
    assert not run(acc, 'Accounts Officer - Sydney', 'Melbourne VIC').skip        # the location field decides when it names a region
    assert run(nur, 'Registered Nurse', 'Melbourne VIC').skip and not run(nur, 'Registered Nurse', 'Sydney NSW').skip
    assert run(acc, 'Accounts Officer', 'Remote - United States', remote=True).skip   # a remote ad abroad
    assert not run(acc, 'Accounts Officer', 'Sydney NSW', remote=True).skip           # remote inside Australia (remote_ok not refused)
    no_remote = policy_of(fact('location', 'Melbourne VIC'), fact('preference', {'remote_ok': False}))
    assert run(engine(conn, no_remote), 'Accounts Officer', 'Sydney NSW', remote=True).skip


def test_off_target_follows_the_profile_exclusions_only(conn):
    acc, nur = engine(conn, accountant()), engine(conn, nurse())
    assert run(acc, 'Barista').skip and run(acc, 'Call Centre Consultant').skip
    assert not run(acc, 'Registered Nurse').skip                                   # health is not excluded by this person
    assert run(nur, 'Senior Accountant').category in ('seniority_level', 'off_target_occupation')
    assert run(nur, 'Accountant').skip and run(nur, 'Software Developer').skip
    assert not run(nur, 'Barista').skip                                            # hospitality is not excluded by the nurse
    assert not run(acc, 'Retail Accounts Assistant').skip                          # hospitality excluded but retail is not: stays
    nothing = engine(conn, policy_of(fact('location', 'Melbourne VIC')))
    assert not run(nothing, 'Barista').skip                                        # no exclusions in the profile: no occupation screen


def test_only_obvious_terms_skip(conn):
    eng_p = accountant()
    store.add_term(conn, category='off_target_occupation', term='baker', applies_to='title', value='hospitality', strength='weak')
    assert not run(engine(conn, eng_p), 'Baker').skip and run(engine(conn, eng_p), 'Baker').outcome == 'flag'
    store.add_term(conn, category='off_target_occupation', term='pastry chef', applies_to='title', value='hospitality', strength='obvious')
    assert run(engine(conn, eng_p), 'Pastry Chef').skip


def test_a_new_field_needs_only_rows(conn):
    """A profession the seed does not know is added with rows; the engine code does not change."""
    store.add_term(conn, category='seniority_level', term='charge nurse', match_type='phrase', value='senior', strength='obvious')
    assert run(engine(conn, nurse()), 'Charge Nurse').skip
    assert not run(engine(conn, nurse()), 'Registered Nurse').skip


# -- profile -> rules rows ------------------------------------------------------------------
def test_profile_is_written_as_rows_and_rewritten_when_it_changes(conn):
    engine(conn, accountant())
    kinds = {r['kind'] for r in conn.execute("SELECT kind FROM prescreen_rules WHERE source='profile'")}
    assert {'level_not_approved', 'years_over', 'region_outside', 'term_hit'} <= kinds
    assert {r[0] for r in conn.execute("SELECT derived_from_profile_version FROM prescreen_rules WHERE source='profile'")} == {2}
    n = conn.execute('SELECT COUNT(*) FROM prescreen_rules').fetchone()[0]
    engine(conn, accountant())
    assert conn.execute('SELECT COUNT(*) FROM prescreen_rules').fetchone()[0] == n          # idempotent
    engine(conn, nurse())
    regions = [json.loads(r[0])['regions'] for r in conn.execute("SELECT params_json FROM prescreen_rules WHERE kind='region_outside'")]
    assert regions == [['NSW', 'AU']]
    Engine.load(conn, None)
    assert conn.execute("SELECT COUNT(*) FROM prescreen_rules WHERE source='profile'").fetchone()[0] == 0


# -- overrides, decisions, re-admission --------------------------------------------------------
def _posting(conn, ident, title, location='Melbourne VIC', text='Reconcile ledgers.'):
    conn.execute('INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,location,description,first_seen_at,last_seen_at) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (ident, 'synthetic', str(ident), f'https://example.invalid/{ident}', f'u{ident}',
                                                   f'd{ident}', title, 'Example Co', location, text, db.ts(), db.ts()))
    adtext.save_text(conn, ident, text, 'synthetic-full')
    conn.commit()


@pytest.fixture
def pinned(monkeypatch):
    def pin(pol):
        monkeypatch.setattr(policy_mod, 'policy_for', lambda person: pol)
    return pin


def test_a_skip_is_archived_with_a_visible_reason_and_ingest_never_fetches_it(conn, tmp_path, pinned, monkeypatch):
    from pipeline.nodes import ingest
    pinned(accountant())
    _posting(conn, 1, 'Principal Engineer, Payments')
    _posting(conn, 2, 'Graduate Accountant')
    monkeypatch.setattr(adtext, 'ensure_text', lambda c, r, f=None, **kw: ('Reconcile ledgers.', 'full') if r['id'] == 2 else pytest.fail('fetched'))
    cfg = make_config(tmp_path=tmp_path)
    stats = ingest.run(conn, cfg)
    assert stats['prescreened'] == 1 and stats['admitted'] == 1
    row = conn.execute('SELECT stage, reason, data_json FROM pipeline_state WHERE posting_id=1').fetchone()
    assert (row['stage'], row['reason']) == ('archived', 'prescreened')
    assert 'approved levels' in json.loads(row['data_json'])['prescreen']['reason']
    d = store.latest_decision(conn, 1)
    assert d['outcome'] == 'skip' and d['matched_text'].lower() == 'principal' and d['stage'] == 'metadata'
    assert store.latest_decision(conn, 2)['outcome'] == 'admit' and store.latest_decision(conn, 2)['stage'] == 'full'


def test_override_readmits_and_records_an_exception_for_this_person_only(conn, tmp_path, pinned):
    from pipeline.nodes import ingest
    pinned(accountant())
    _posting(conn, 1, 'Principal Accountant')
    ingest.run(conn, make_config(tmp_path=tmp_path))
    assert conn.execute('SELECT reason FROM pipeline_state WHERE posting_id=1').fetchone()[0] == 'prescreened'
    done = lifecycle.override_skip(conn, 1)
    assert done['readmitted'] and done['term_id']
    assert conn.execute('SELECT COUNT(*) FROM pipeline_state WHERE posting_id=1').fetchone()[0] == 0   # ingest reads it again
    assert not run(engine(conn, accountant()), 'Principal Accountant').skip                           # the term is off for her
    other = db.connect(tmp_path / 'someone-else.db')
    assert run(engine(other, accountant()), 'Principal Accountant').skip                              # another person's bank is untouched


def test_posting_only_override_keeps_the_term_active(conn):
    _posting(conn, 5, 'Principal Accountant')
    eng = engine(conn, accountant())
    eng.screen(conn, 5, PostingFields(title='Principal Accountant'), stage='metadata')
    lifecycle.override_skip(conn, 5, term_too=False)
    eng = engine(conn, accountant())
    assert eng.evaluate(PostingFields(title='Principal Accountant'), posting_id=5).overridden
    assert not eng.evaluate(PostingFields(title='Principal Accountant'), posting_id=5).skip
    assert eng.evaluate(PostingFields(title='Principal Accountant'), posting_id=6).skip


def test_a_profile_change_makes_old_skips_stale_and_reconsider_readmits(conn, tmp_path, pinned):
    from pipeline.nodes import ingest
    pinned(accountant())
    _posting(conn, 1, 'Senior Accountant')
    ingest.run(conn, make_config(tmp_path=tmp_path))
    assert lifecycle.reconsider(conn, accountant()) == 0            # nothing changed: stays skipped
    senior = policy_of(fact('location', 'Melbourne VIC'), fact('preference', {'seniority': ['senior']}), version=3)
    assert lifecycle.reconsider(conn, senior) == 1                  # the person now wants senior roles
    assert conn.execute('SELECT COUNT(*) FROM pipeline_state WHERE posting_id=1').fetchone()[0] == 0


def test_disabling_a_term_readmits_through_reconsider(conn, tmp_path, pinned):
    from pipeline.nodes import ingest
    pinned(accountant())
    _posting(conn, 1, 'Senior Accountant')
    ingest.run(conn, make_config(tmp_path=tmp_path))
    store.set_term_enabled(conn, store.latest_decision(conn, 1)['term_id'], False)
    assert lifecycle.reconsider(conn, accountant()) == 1


def test_screen_ingested_archives_a_queued_mismatch(conn):
    from pipeline import store as pstore
    pstore.ensure(conn)
    _posting(conn, 1, 'Accounts Officer', text='You need 8 years of experience.')
    _posting(conn, 2, 'Accounts Officer')
    for i in (1, 2):
        conn.execute("INSERT INTO pipeline_state(posting_id,stage,content_hash,data_json,updated_at) VALUES(?, 'ingested', ?, '{}', ?)", (i, f'h{i}', db.ts()))
    conn.commit()
    assert lifecycle.screen_ingested(conn, accountant()) == [1]
    assert lifecycle.screen_ingested(conn, accountant()) == []       # decisions are current: not re-run


def test_stats_count_hits_per_term(conn):
    eng = engine(conn, accountant())
    _posting(conn, 1, 'Senior Accountant'); _posting(conn, 2, 'Senior Analyst')
    eng.screen(conn, 1, PostingFields(title='Senior Accountant'), stage='metadata')
    eng.screen(conn, 2, PostingFields(title='Senior Analyst'), stage='metadata')
    top = store.stats(conn)[0]
    assert top['term'] == '\\bsenior\\b' and top['skips'] == 2


# -- the legacy filter ----------------------------------------------------------------------
def test_rules_evaluate_gives_the_reason_and_parsed_fields(conn, pinned):
    pinned(accountant())
    cfg = make_config()
    rules = Rules(cfg.rules, cfg.employers, conn=conn)
    p = Posting(source='s', source_id='1', url='https://example.invalid/1', title='Principal Engineer, Payments', location='Melbourne VIC')
    d = rules.evaluate(p)
    assert not d.matched and d.reason == 'seniority'
    assert d.rules['prescreen']['matched'].lower() == 'principal' and 'seniority_level' in d.rules['prescreen']['parsed']
    ok = rules.evaluate(Posting(source='s', source_id='2', url='https://example.invalid/2', title='Graduate Accountant', location='Melbourne VIC'))
    assert ok.matched and ok.rules['prescreen']['outcome'] == 'admit'
    assert rules.seniority_hit('Senior Accountant') and not rules.seniority_hit('Accountant')


def test_without_a_confirmed_profile_the_legacy_rules_are_unchanged():
    cfg = make_config()
    rules = Rules(cfg.rules, cfg.employers)
    assert rules.prescreen is None


def test_an_entry_only_profile_still_reads_junior_roles(conn):
    eng = engine(conn, policy_of(fact('preference', {'seniority': ['entry-level']})))
    assert not run(eng, 'Junior Analyst').skip and not run(eng, 'Graduate Analyst').skip
    assert run(eng, 'Senior Analyst').skip and run(eng, 'Mid-level Analyst').skip


def test_country_wide_and_nested_place_names(conn):
    eng = engine(conn, accountant())
    assert not run(eng, 'Content Creator', 'Australia & New Zealand').skip           # Australia is named: inside
    assert run(eng, 'Content Creator', 'Western Australia').skip                      # "Australia" inside "Western Australia" is not a country mention
    assert run(eng, 'Content Creator', 'New Zealand|Auckland').skip


def test_cli_words_rules_test_and_override(conn, capsys):
    from argparse import Namespace
    from jobwatch.prescreen import cli
    ns = lambda **k: Namespace(cmd='prescreen', **k)          # noqa: E731
    assert cli._run(conn, ns(prescreen_cmd='words', action='add', category='seniority_level', term='(oops', match='regex',
                             applies_to='title', value='senior', strength='obvious', polarity='exclude', field_tag=None)) == 2
    assert 'not added' in capsys.readouterr().out
    assert cli._run(conn, ns(prescreen_cmd='words', action='add', category='seniority_level', term='charge nurse', match='phrase',
                             applies_to='title', value='senior', strength='obvious', polarity='exclude', field_tag=None)) == 0
    cli._run(conn, ns(prescreen_cmd='test', title='Charge Nurse, Ward 3', location='Sydney NSW', hours='', remote=False, ad_text_file=None))
    out = capsys.readouterr().out
    assert 'seniority_level' in out and "'Charge Nurse'" in out and 'outcome:' in out
    cli._run(conn, ns(prescreen_cmd='words', action='list', category='work_rights', all=False))
    assert 'citizen' in capsys.readouterr().out
    cli._run(conn, ns(prescreen_cmd='rules', action='list'))
    assert 'term_hit' in capsys.readouterr().out
