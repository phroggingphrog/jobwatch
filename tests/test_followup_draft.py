
from jobwatch.util import model_choice as model_choice
from jobwatch.settings import DEFAULT_MODEL
import json
from types import SimpleNamespace

import pytest

from jobwatch.candidate.evidence import snapshot_evidence
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.followup import CRITERIA, FollowupProposal, compose_followup
from pipeline.agentic.runtime import BatchBudget, JobBudget


class Writer:
    base_url = model_choice.SERVER_URL
    def __init__(self, bundle, *, bad_quote=False):
        self.bundle=bundle; self.calls=[]; self.bad_quote=bad_quote
    def chat_once(self,model,messages,**kwargs):
        self.calls.append((model,messages))
        item=self.bundle.items[0]
        if len(self.calls)%2:
            data={'tool':'read_candidate_evidence','arguments':{'evidence_ids':[item.id]}}
        else:
            args={'subject':'Accounts role at Example','body':'I applied for the Accounts role at Example. I reconciled ledgers. Would a conversation about the role be useful?',
                'claims':[{'text':'I reconciled ledgers.','kind':'qualification','citations':[{'source_id':item.source_file,'content_hash':item.source_hash,'quote':'invented unsupported claim' if self.bad_quote else item.quote}]}]}
            data={'tool':'complete_followup','arguments':args}
        return SimpleNamespace(data=data,usage={'prompt_tokens':10,'completion_tokens':10})


class Reviewer:
    base_url = model_choice.SERVER_URL
    def __init__(self, *, verdicts=('approve',), bad_hash=False, missing_criterion=False):
        self.calls=[];self.verdicts=iter(verdicts);self.bad_hash=bad_hash;self.missing=missing_criterion
    def chat_once(self,model,messages,**kwargs):
        self.calls.append((model,messages))
        ctx=json.loads(messages[-1]['content'])
        criteria={k:True for k in CRITERIA}
        if self.missing:criteria.pop('claims_supported')
        verdict=next(self.verdicts)
        return SimpleNamespace(data={'tool':'complete_review','arguments':{'draft_hash':'0'*64 if self.bad_hash else ctx['draft_hash'],
            'verdict':verdict,'criteria':criteria,'feedback':['Make the opening more specific.'] if verdict=='revise' else []}},usage={'prompt_tokens':10,'completion_tokens':10})


@pytest.fixture
def case(tmp_path):
    (tmp_path/'cv.md').write_text('# Synthetic Example\n\n## Skills\n- Reconciled ledgers.\n')
    bundle=snapshot_evidence(tmp_path)
    application={'title':'Accounts role','company':'Example','applied_on':'2026-10-01','prior_drafts':[]}
    budget=JobBudget('a'*64,BatchBudget('followup-test'),token_ceiling=250000)
    return bundle,application,budget


def compose(case,writer=None,reviewer=None):
    bundle,app,budget=case
    return compose_followup(app,'Example seeks an accounts assistant.',bundle,budget,writer or Writer(bundle),reviewer or Reviewer())


def test_real_deepagents_tools_and_independent_hash_bound_review(case):
    bundle,app,budget=case;writer=Writer(bundle);reviewer=Reviewer()
    draft=compose(case,writer,reviewer)
    assert draft.proposal.draft_hash==draft.review.draft_hash
    assert draft.review.verdict=='approve' and budget.charged_tokens==60
    assert [m for m,_ in writer.calls]==[DEFAULT_MODEL]*2  # owner 2026-10-19: no Claude subscription
    assert reviewer.calls[0][0]==DEFAULT_MODEL
    ctx=json.loads(reviewer.calls[0][1][-1]['content'])
    assert 'review_feedback' not in ctx and 'previous_proposal' not in ctx
    assert 'cited_candidate_evidence' in ctx
    assert 'prior_drafts' in app and app['prior_drafts']==[]


@pytest.mark.parametrize('mode',['bad_quote','bad_hash','missing_criterion','reject'])
def test_invalid_proof_or_review_never_returns_approved_draft(case,mode):
    writer=Writer(case[0],bad_quote=mode=='bad_quote')
    reviewer=Reviewer(bad_hash=mode=='bad_hash',missing_criterion=mode=='missing_criterion',verdicts=('reject',) if mode=='reject' else ('approve',))
    with pytest.raises(AgenticError):compose(case,writer,reviewer)


def test_one_revision_is_reviewed_again_and_bounded(case):
    writer=Writer(case[0]);reviewer=Reviewer(verdicts=('revise','approve'))
    draft=compose(case,writer,reviewer)
    assert draft.review.verdict=='approve' and len(writer.calls)==4 and len(reviewer.calls)==2
    revised_context=json.loads(writer.calls[2][1][-1]['content'])
    assert revised_context['review_feedback']==['Make the opening more specific.']


def test_repeated_revision_holds_instead_of_returning_unreviewed_text(case):
    with pytest.raises(AgenticError,match='followup_review_not_accepted'):
        compose(case,reviewer=Reviewer(verdicts=('revise','revise')))


def test_linkedin_length_limit_is_enforced_before_review(case):
    from pipeline.agentic.followup import validate_proposal
    draft=compose(case)
    long=draft.proposal.model_copy(update={'body':draft.proposal.body+' extra'*60})
    with pytest.raises(AgenticError,match='invalid_followup_length'):
        validate_proposal(long,{**case[1],'channel':'linkedin'},'Example seeks an accounts assistant.',case[0])
