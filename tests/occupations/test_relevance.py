from types import SimpleNamespace
import json

import numpy as np
import pytest

from jobwatch import db, users
from jobwatch.candidate.policy import build_policy
from jobwatch.occupations.embeddings import VectorCache, discovery_budget, normalise
from pipeline import store
from pipeline.agentic import discovery
from pipeline.agentic.discovery import ScreenContext, judge_relevance, ad_passages
from pipeline.agentic.runtime import RuntimeErrorSafe
from pipeline.schemas import Stage


class Embedder:
    def __init__(self): self.calls = []
    def embed_documents(self, texts):
        self.calls.extend(texts)
        return [[1., 0.] if 'ledgers' in text else [0., 1.] for text in texts]


@pytest.fixture
def env(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / 'd.db'); store.ensure(conn)
    pol = build_policy({'version': 1, 'facts': []})
    hyps = (SimpleNamespace(title='Accountant', id='anzsco2022:221111'),)
    plan = SimpleNamespace(plan_hash='p', profile_version=1, policy_hash=pol.policy_hash)
    monkeypatch.setattr(discovery, '_current_plan', lambda person: (pol, plan))
    monkeypatch.setattr(discovery, '_fields', lambda: SimpleNamespace(cached_hypotheses=lambda person, **kw: hyps))
    with discovery_budget(conn, 'synthetic', token_ceiling=100_000) as budget:
        ctx = ScreenContext(Embedder(), VectorCache(conn, 'synthetic'), {'anzsco2022:221111': np.array([1., 0.])},
                            None, budget, 'openai/sol', .6, 'p')
        yield conn, pol, hyps, ctx
    conn.close()


def add(conn, pid=1, title='Operations Support Officer', source='seek', city='Sydney', company='Acme', text='Reconcile supplier ledgers daily.'):
    conn.execute('INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,location,description,first_seen_at,last_seen_at) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (pid, source, str(pid), f'https://example.invalid/{pid}', str(pid), str(pid), title, company, city, text, '2026-01-01','2026-01-01'))
    conn.execute('INSERT INTO sightings(posting_id,source,source_id,url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)',
                 (pid,source,str(pid),f'https://example.invalid/{pid}','2026-01-01','2026-01-01'))
    store.admit(conn, pid, 'h', {})
    conn.commit()
    return {'id':pid, 'title':title, 'company':company, 'location':city, 'source':source, 'sources':{source}}


def test_related_duties_and_verbatim_embedding_quote(env):
    conn, pol, hyps, ctx = env
    text = 'Reconcile supplier ledgers daily. ' * 12
    result = judge_relevance({'id':1,'title':'Operations Officer'}, text, pol, hyps, context=ctx)
    assert result.relevant == 'yes' and result.method == 'embedding'
    assert result.quotes and all(q in text and len(q) <= 300 for q in result.quotes)


def test_no_without_verifiable_quote_is_uncertain_and_prompt_has_no_personal_facts(env, monkeypatch):
    _, pol, hyps, ctx = env
    from pipeline.agentic import runtime
    seen = []
    def run(role, data, *args, **kwargs):
        seen.append(data)
        return SimpleNamespace(output=discovery.RelevanceExtraction(relevant='no', field_title='Cleaner',
            quotes=('Invented duties not in ad',), reason='Different field'))
    monkeypatch.setattr(runtime, 'run_role', run)
    out = judge_relevance({'id':1,'title':'Accountant'}, 'Clean offices overnight.', pol, hyps, context=ctx)
    assert out.relevant == 'uncertain' and out.reason == 'quote_not_verified'
    assert set(seen[0]) == {'title','ad_text','candidate_fields','strategy'}
    assert seen[0]['candidate_fields'] == ['Accountant']


def test_verified_no_and_unavailable_model(env, monkeypatch):
    _, pol, hyps, ctx = env
    from pipeline.agentic import runtime
    monkeypatch.setattr(runtime, 'run_role', lambda *a,**k: SimpleNamespace(output=discovery.RelevanceExtraction(
        relevant='no',field_title='Cleaner',quotes=('Clean offices overnight.',),reason='Different duties')))
    assert judge_relevance({'id':1,'title':'Accountant'},'Clean offices overnight.',pol,hyps,context=ctx).relevant == 'no'
    def boom(*a,**k): raise RuntimeErrorSafe('model_unavailable')
    monkeypatch.setattr(runtime, 'run_role', boom)
    assert judge_relevance({'id':1,'title':'Accountant'},'Clean offices overnight.',pol,hyps,context=ctx).relevant == 'uncertain'


def test_real_counted_role_extraction_uses_only_public_ad_and_field_titles(env):
    _, pol, hyps, ctx = env
    from tests.occupations.fixtures import approved_llm, hash_transport
    requests = []
    def chat(body):
        requests.append(body)
        return 200, {'choices':[{'message':{'content':json.dumps({'tool':'complete_relevance','arguments':{
            'relevant':'no','field_title':'Cleaner','quotes':['CLEAN OFFICES OVERNIGHT.'],
            'reason':'Cleaning duties are outside accounting.'}})}}],
            'usage':{'prompt_tokens':30,'completion_tokens':20}}
    ctx.llm = approved_llm(hash_transport(chat=chat))
    before = ctx.budget.charged_tokens
    result = judge_relevance({'id':1,'title':'Accountant'},'Clean offices overnight.',pol,hyps,context=ctx)
    assert result.relevant == 'no' and result.quotes == ('Clean offices overnight',)
    assert ctx.budget.charged_tokens > before
    assert requests and json.loads(requests[0]['messages'][1]['content']) == {
        'title':'Accountant','ad_text':'Clean offices overnight.','candidate_fields':['Accountant'],'strategy':pol.strategy}


def test_passages_are_bounded_overlapping_windows():
    text = 'abcdefghij' * 20
    p = ad_passages('Title', text, size=50, overlap=10, limit=3)
    assert p[0] == 'Title\n' + text[:50] and p[1] == text[40:90] and len(p) == 3


def test_screen_stores_once_shadow_does_not_archive_and_on_reuses_judgment(env, monkeypatch):
    conn, pol, hyps, ctx = env
    add(conn)
    from pipeline.agentic import service
    monkeypatch.setattr(service, '_capture', lambda c,p: ({},'Full advert text','full'))
    monkeypatch.setattr(discovery, 'judge_relevance', lambda p,t,*a,**k: discovery.RelevanceJudgment(
        posting_id=p['id'],relevant='no',quotes=('Full advert text',),similarity=.1,
        matched_hypotheses=(),reason='Different duties',ad_hash=discovery.hashlib.sha256(t.encode()).hexdigest(),plan_hash='p'))
    out = discovery.screen_step(conn, {}, context=ctx)
    assert out['judged'] == 1 and out['archived'] == 0
    assert conn.execute('SELECT stage FROM pipeline_state').fetchone()[0] == 'ingested'
    assert discovery.latest_judgment(conn,1).relevant == 'no'
    assert discovery.screen_step(conn,{},context=ctx)['judged'] == 0
    out = discovery.screen_step(conn, {'agentic':{'relevance':'on'}}, context=ctx)
    assert out['archived'] == 1
    assert discovery.restore_archived(conn) == 1
    assert conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0] == 0


def test_partial_ads_and_missing_refresh_cost_nothing(env, monkeypatch):
    conn, pol, hyps, ctx = env
    add(conn)
    from pipeline.agentic import service
    monkeypatch.setattr(service, '_capture', lambda c,p: ({},'partial','partial'))
    assert discovery.screen_step(conn,{},context=ctx)['judged'] == 0 and ctx.embedder.calls == []
    monkeypatch.setattr(discovery, '_current_plan', lambda p: (pol,None))
    assert discovery.screen_step(conn,{}) == {}
    assert conn.execute('SELECT COUNT(*) FROM posting_relevance').fetchone()[0] == 0


def test_screen_failure_defers_without_archiving_and_respects_limit(env, monkeypatch):
    conn, pol, hyps, ctx = env
    add(conn); add(conn,2)
    from pipeline.agentic import service
    monkeypatch.setattr(service, '_capture', lambda c,p: ({},'ledgers','full'))
    assert discovery.screen_step(conn, {'discovery':{'screen_per_run':1}}, context=ctx)['judged'] == 1
    def boom(texts): raise RuntimeErrorSafe('token_limit')
    ctx.embedder.embed_documents = boom
    monkeypatch.setattr(service, '_capture', lambda c,p: ({},'changed ad','full'))
    assert 'deferred' in discovery.screen_step(conn,{},context=ctx)
    assert conn.execute("SELECT COUNT(*) FROM pipeline_state WHERE stage='archived'").fetchone()[0] == 0


def test_rule_prefilter_uses_confirmed_policy_by_default_and_no_model(env, monkeypatch):
    conn, _, _, ctx = env
    add(conn)
    pol = build_policy({'version':1,'facts':[{'id':'f1','section':'exclusion','basis':'evidence','value':{'kind':'employer','value':'Acme'}}]})
    monkeypatch.setattr(discovery,'policy_for',lambda p:pol)
    from pipeline.agentic import service
    monkeypatch.setattr(service,'_capture',lambda c,p: ({},'complete ad','full'))
    assert discovery.enforce_exclusions(conn,{}) == [1]
    assert discovery.enforce_exclusions(conn,{'agentic':{'decision_policy':'profile'}}) == []
    assert ctx.embedder.calls == []


def test_structured_duplicate_guards():
    a = dict(company='Acme Pty Ltd',title='Accounts Officer',location='Sydney',sources={'seek'})
    b = dict(company='ACME',title='Accounts Officer',location='Sydney',sources={'jobspy'})
    assert discovery.same_vacancy_structured(a,b,.99,min_cosine=.95)
    for changes in ({'company':''},{'company':'Recruiter'},{'location':'Perth'}, {'title':'Software Developer'}, {'sources':{'seek'}}):
        assert not discovery.same_vacancy_structured(a,{**b,**changes},.99,min_cosine=.95)


def test_duplicate_archives_newer_cross_source_only_and_ready_survives(env, monkeypatch):
    conn, _, _, ctx = env
    add(conn,1,source='seek'); add(conn,2,source='jobspy'); add(conn,3,source='other')
    store.move(conn,3,'test',Stage.INGESTED,Stage.READY)
    from pipeline.agentic import service
    monkeypatch.setattr(service,'_capture',lambda c,p: ({},'ledgers full text','full'))
    assert discovery.semantic_duplicates(conn,{},context=ctx) == 1
    assert conn.execute('SELECT stage FROM pipeline_state WHERE posting_id=3').fetchone()[0] == 'ready'
    assert conn.execute('SELECT reason FROM pipeline_state WHERE posting_id=2').fetchone()[0] == 'duplicate_of:1'
    before = len(ctx.embedder.calls)
    assert discovery.semantic_duplicates(conn,{},context=ctx) == 0
    assert len(ctx.embedder.calls) == before
