"""Synthetic ATS acquisition; no network, profile, tracker or paid calls."""
import json
from datetime import datetime,timezone
import pytest
from jobwatch.interview_ad import structured_ad,ats_target,InterviewAdUnavailable

BODY='Analyse financial records and explain results to stakeholders. '*400
class Fetcher:
    def __init__(self,data):self.data=data;self.calls=[]
    def fetch_bytes(self,url,**kwargs):
        self.calls.append(url)
        return json.dumps(self.data).encode()

@pytest.mark.parametrize('url,payload,endpoint',[
    ('https://job-boards.greenhouse.io/example/jobs/123',{'id':123,'title':'Analyst','content':BODY},'https://boards-api.greenhouse.io/v1/boards/example/jobs/123?content=true'),
    ('https://jobs.lever.co/example/abc',{'id':'abc','text':'Analyst','descriptionPlain':BODY,'lists':[{'text':'Requirements','content':'<p>SQL and reporting</p>'}],'additionalPlain':'Closing details'},'https://api.lever.co/v0/postings/example/abc?mode=json'),
    ('https://jobs.ashbyhq.com/example/abc',{'jobs':[{'id':'other','title':'Wrong','descriptionPlain':BODY},{'id':'abc','title':'Analyst','descriptionPlain':BODY}]},'https://api.ashbyhq.com/posting-api/job-board/example'),
    ('https://example.wd3.myworkdayjobs.com/en-US/Careers/job/Melbourne/Analyst_R123',{'jobPostingInfo':{'title':'Analyst','jobDescription':BODY,'jobReqId':'R123','externalPath':'/job/Melbourne/Analyst_R123'}},'https://example.wd3.myworkdayjobs.com/wday/cxs/example/Careers/job/Melbourne/Analyst_R123'),
])
def test_structured_providers_keep_complete_identified_ad(url,payload,endpoint):
    fetcher=Fetcher(payload);ad=structured_ad(url,fetcher=fetcher)
    assert fetcher.calls==[endpoint]
    assert ad.title=='Analyst' and ad.url==url and ad.source_url==endpoint
    assert len(ad.text)>16000 and BODY.strip() in ad.text
    assert ad.acquisition=='structured_ats' and len(ad.text_hash)==64
    if 'lever' in url:assert 'SQL and reporting' in ad.text and 'Closing details' in ad.text

@pytest.mark.parametrize('payload',[
    {'id':124,'title':'Wrong role','content':BODY},
    {'id':123,'title':'Analyst','content':'Careers Contact Privacy'},
    {'id':123,'content':BODY},
    {'id':123,'title':'Analyst','content':None},
])
def test_missing_or_mismatched_content_requires_browser(payload):
    assert structured_ad('https://boards.greenhouse.io/example/jobs/123',fetcher=Fetcher(payload)) is None

@pytest.mark.parametrize('fields',[{'isActive':False},{'isListed':False},{'validThrough':'2020-01-01'}])
def test_closed_record_requires_pasted_jd(fields):
    with pytest.raises(InterviewAdUnavailable,match='^interview_ad_closed$'):
        structured_ad('https://boards.greenhouse.io/example/jobs/123',fetcher=Fetcher(dict(id=123,title='Analyst',content=BODY,**fields)),now=datetime(2026,1,1,tzinfo=timezone.utc))

def test_oversize_is_rejected_not_truncated():
    with pytest.raises(InterviewAdUnavailable,match='^interview_ad_too_large$'):
        structured_ad('https://boards.greenhouse.io/example/jobs/123',fetcher=Fetcher({'id':123,'title':'Analyst','content':'x'*100001}))

def test_unknown_host_never_uses_structured_network():
    fetcher=Fetcher({})
    assert structured_ad('https://boards.greenhouse.io.attacker.example/example/jobs/123',fetcher=fetcher) is None
    assert fetcher.calls==[]

@pytest.mark.parametrize('url',['http://jobs.lever.co/example/abc','https://secret:secret@jobs.lever.co/example/abc','https://jobs.lever.co:22/example/abc','https://jobs.lever.co/%2e%2e/abc','https://example.wd3.myworkdayjobs.com/Careers/job/../admin'])
def test_invalid_url_cannot_change_endpoint(url):
    with pytest.raises(InterviewAdUnavailable,match='^interview_url_invalid$'):ats_target(url)

def test_provider_error_is_fixed_unavailable_not_page_text():
    from pipeline.agentic.research import ResearchUnavailable
    class Failed:
        def fetch_bytes(self,*a,**kw):raise ResearchUnavailable()
    assert structured_ad('https://jobs.lever.co/example/abc',fetcher=Failed()) is None


@pytest.mark.parametrize('identity',[{}, {'jobReqId':'R999'}, {'externalPath':'/job/Other_R999'}, {'jobReqId':'R123','externalPath':'/job/Other_R999'}])
def test_workday_rejects_missing_or_mismatched_role_identity(identity):
    assert structured_ad('https://example.wd3.myworkdayjobs.com/Careers/job/Melbourne/Analyst_R123',
        fetcher=Fetcher({'jobPostingInfo':dict(title='Analyst',jobDescription=BODY,**identity)})) is None

@pytest.mark.parametrize('provider,content',[
    ('lever','<p>Use &lt;customer_id&gt; columns.</p>'),
    ('greenhouse','<p>Use &lt;customer_id&gt; columns.</p>'),
    ('greenhouse','&lt;p&gt;Use &amp;lt;customer_id&amp;gt; columns.&lt;/p&gt;')])
def test_escaped_literal_source_text_is_preserved(provider,content):
    if provider=='lever':
        url='https://jobs.lever.co/example/abc';record={'id':'abc','text':'Analyst','description':content+BODY}
    else:
        url='https://boards.greenhouse.io/example/jobs/123';record={'id':123,'title':'Analyst','content':content+BODY}
    assert '<customer_id>' in structured_ad(url,fetcher=Fetcher(record)).text


def test_oracle_closed_workday_403_and_extra_json():
    from jobwatch.interview_ad import ats_target
    from jobwatch.llm import parse_json
    assert ats_target('https://x.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1005438')[0]=='oracle'
    assert parse_json('{"tool":"a","arguments":{}} Next\n{"tool":"b","arguments":{}}')=={'tool':'a','arguments':{}}


# Regression: Oracle HCM answers 200 with no items once a requisition is taken down; that is closed, not "couldn't read".
def test_oracle_empty_result_means_closed():
    import pytest
    from jobwatch.interview_ad import InterviewAdUnavailable
    url='https://x.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1005411'
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_closed'):
        structured_ad(url,fetcher=Fetcher({'items':[],'count':0,'hasMore':False,'limit':499,'offset':0}))
