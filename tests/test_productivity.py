"""Offline ownership and workflow tests; no real users or model calls."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from app.models import ResearchGap, ResearchPlan, SubQuestion
from server import workspace, productivity
from server.main import app
from server.api.research import ResearchJob, jobs
from server.api.models import ResearchRequest


@pytest.fixture
def owned(monkeypatch):
    records = {}
    monkeypatch.setattr(workspace, 'configured', lambda: True)
    async def auth(request):
        return {'id': request.headers.get('test-owner', 'owner-a'), 'is_anonymous': request.headers.get('test-guest') == 'yes'}
    async def load(owner, kind, identifier):
        return records.get((owner, kind, identifier))
    monkeypatch.setattr(workspace, 'authenticate', auth)
    monkeypatch.setattr(workspace, 'load', load)
    return records


def test_brief_is_bounded_and_optional():
    assert ResearchRequest(question='Synthetic question').brief == {}
    with pytest.raises(ValueError):
        ResearchRequest(question='Synthetic question', brief={'goal': 'x'*501})
    with pytest.raises(ValueError):
        ResearchRequest(question='Synthetic question', brief={'secret': 'invalid field'})


def test_collections_remap_citations_and_never_load_another_owner(owned):
    owned[('owner-a','collection','c')] = {'id':'c','name':'Synthetic collection','researchIds':['r','foreign'],'pdfIds':['p'],'chatIds':['chat']}
    owned[('owner-a','research','r')] = {'question':'Synthetic research','report':'Synthetic finding [1].','sources':[{'id':'S1','title':'Synthetic source','url':'https://example.invalid','domain':'example.invalid','content':'Synthetic evidence'}]}
    owned[('owner-b','research','foreign')] = {'report':'PRIVATE OTHER USER CONTENT','sources':[]}
    owned[('owner-a','pdf','p')] = {'name':'Synthetic PDF','pages':[{'page':999,'text':'Late-page synthetic detail: amber.'}]}
    owned[('owner-a','chat','chat')] = {'title':'Synthetic chat','messages':[{'role':'assistant','content':'An unverified conversation statement'}]}
    state = asyncio.run(productivity.collection_state('owner-a','c'))
    assert len({source.id for source in state.sources}) == len(state.sources)
    assert 'PRIVATE OTHER USER' not in state.model_dump_json()
    assert 'Late-page synthetic detail' in state.model_dump_json()
    assert any(source.domain.startswith('conversation') for source in state.sources)
    with pytest.raises(HTTPException) as error:
        asyncio.run(productivity.validate_productivity('owner-a','collection', {'id':'c','name':'Synthetic','researchIds':['foreign']}))
    assert error.value.status_code == 404


def test_collection_stream_preserves_conversation_identity_and_cleans_context(owned, monkeypatch):
    from app.chat import ChatResponse
    import server.api.research as research
    owned[('owner-a','collection','c')] = {'id':'c','name':'Synthetic','researchIds':[]}
    async def answer(*args):
        yield 'chat_complete', ChatResponse(intent='From research', answer='[From research]\nThe collection has no evidence.')
    monkeypatch.setattr(research,'_hybrid_events',answer)
    conversation = 'general-chat-00000000-0000-4000-8000-000000000001'
    async def run():
        before = set(jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response = await client.post('/api/library/collections/c/chat',json={'message':'Synthetic question','conversation_id':conversation})
            assert response.status_code == 200
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            assert all(event['research_id'] == conversation for event in events)
            assert events[-1]['type'] == 'chat_complete'
        assert set(jobs) == before
    asyncio.run(run())


def test_large_collection_pdf_retrieves_a_late_page_with_bounded_context(owned):
    from app.assistant_context import build_context
    owned[('owner-a','collection','large')] = {'id':'large','name':'Synthetic PDF collection','pdfIds':['large-pdf']}
    pages = [{'page':page,'text':'Ordinary repeated synthetic content. '*40} for page in range(1,1001)]
    pages[-1]['text'] = 'Page 1000 synthetic detail: ambernectar has a measured value of 42 fictional units.'
    owned[('owner-a','pdf','large-pdf')] = {'name':'Synthetic large PDF','pages':pages}
    state = asyncio.run(productivity.collection_state('owner-a','large'))
    context = build_context(state,'What is the ambernectar measurement?',[],input_token_limit=32768)
    assert not context.full
    assert 'ambernectar has a measured value of 42' in context.text
    assert len(context.text.encode()) < 16000


def test_share_whitelists_report_and_revoke_removes_public_access(owned, monkeypatch):
    owned[('owner-a','research','r')] = {'question':'Synthetic report','report':'Synthetic finding [1]','sources':[{'id':'S1','title':'Synthetic source','url':'https://example.invalid','domain':'example.invalid','content':'SECRET RAW SOURCE'}], 'state':{'audit_log':['PRIVATE AUDIT'],'evidence':['PRIVATE EVIDENCE']}, 'assistantChat':['PRIVATE CHAT']}
    shares = []
    async def remote(method,path,**kwargs):
        if method == 'POST':
            shares[:] = [kwargs['json']]
        elif method == 'DELETE':
            shares.clear()
        else:
            return shares
    monkeypatch.setattr(workspace,'remote',remote)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/api/library/shares/r', headers={'test-owner':'owner-b'})).status_code == 404
            created = await client.post('/api/library/shares/r')
            token = created.json()['token']
            assert len(token) == 43 and token not in json.dumps(shares)
            public = await client.get('/api/public/reports/'+token)
            assert public.status_code == 200
            assert all(text not in public.text for text in ['PRIVATE','SECRET RAW'])
            assert public.headers['cache-control'] == 'no-store'
            await client.delete('/api/library/shares/r')
            assert (await client.get('/api/public/reports/'+token)).status_code == 404
    asyncio.run(run())


def test_checkpoint_rejects_other_owner_stale_token_and_unknown_gap(owned):
    async def run():
        job = ResearchJob(owner_id='owner-a', review_token='a'*32, review_gaps={'G1'})
        job.review_future = asyncio.get_running_loop().create_future()
        jobs['synthetic-checkpoint'] = job
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                path = '/api/research/synthetic-checkpoint/checkpoint'
                assert (await client.post(path,json={'token':'a'*32},headers={'test-owner':'owner-b'})).status_code == 404
                assert (await client.post(path,json={'token':'b'*32})).status_code == 409
                assert (await client.post(path,json={'token':'a'*32,'gap_ids':['OTHER']})).status_code == 400
                assert (await client.post(path,json={'token':'a'*32,'gap_ids':['G1']})).status_code == 200
                assert job.review_future.result() == ['G1']
                assert (await client.post(path,json={'token':'a'*32})).status_code == 409
        finally:
            jobs.pop('synthetic-checkpoint',None)
    asyncio.run(run())


def test_alerts_require_member_and_enforce_database_limit(owned, monkeypatch):
    owned[('owner-a','research','r')] = {'report':'Synthetic report'}
    async def remote(*args,**kwargs):
        return False
    monkeypatch.setattr(workspace,'remote',remote)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/api/library/alerts',json={'research_id':'r'},headers={'test-guest':'yes'})).status_code == 403
            assert (await client.post('/api/library/alerts',json={'research_id':'r','interval_days':1})).status_code == 409
            assert (await client.post('/api/library/alerts',json={'research_id':'r','interval_days':2})).status_code == 422
    asyncio.run(run())


def test_checkpoint_followup_keeps_original_question_and_total_iteration_budget(monkeypatch):
    from app.agent import ResearchAgent
    from tests.research_fakes import SyntheticLLM, synthetic_settings
    monkeypatch.setattr('app.agent.GeminiClient', SyntheticLLM)
    agent = ResearchAgent(synthetic_settings())
    calls = []
    async def collect(state,*args):
        calls.append([task.query for task in state.plan.sub_question_tasks])
        state.iteration = 1
        state.searches_performed += 1
        state.research_gaps = [ResearchGap(gap_id='G1',description='Synthetic missing cost',reason='Synthetic gap',recommended_search='Synthetic cost primary source')]
    monkeypatch.setattr(agent.researcher,'run_async',collect)
    state = agent.run('Synthetic original question',mode='deep',brief={'goal':'Synthetic decision'},review_checkpoint=lambda state:['G1'])
    assert state.question.question == 'Synthetic original question'
    assert state.brief['goal'] == 'Synthetic decision'
    assert len(calls) == 2 and calls[1] == ['Synthetic cost primary source']
    assert state.iteration == 2 and state.iteration <= state.max_iterations
    assert 'User-requested research brief' in state.final_report


def test_alert_worker_reports_record_changes_without_fabricating_discoveries(owned, monkeypatch):
    from app.models import ResearchState, ResearchQuestion, Source
    import server.api.research as research
    owned[('owner-a','research','r')] = {'question':'Synthetic topic','state':{'findings':[],'sources':[]}}
    patches = []
    async def remote(method,path,**kwargs):
        if path.endswith('/claim_research_alert'):
            return [{'id':'synthetic-alert','owner_id':'owner-a','research_id':'r'}]
        patches.append(kwargs['json'])
    monkeypatch.setattr(workspace,'remote',remote)
    synthetic_jobs = {}
    monkeypatch.setattr(research,'jobs',synthetic_jobs)
    async def start(request,user):
        assert user['id'] == 'owner-a' and request.mode == 'quick' and request.parent_research_id == 'r'
        state = ResearchState(question=ResearchQuestion(question='Synthetic'),sources=[Source(id='S1',title='Synthetic',url='https://example.invalid/new',domain='example.invalid',content='Synthetic')])
        synthetic_jobs['updated'] = ResearchJob(state=state,done=True,task=asyncio.create_task(asyncio.sleep(0)))
        return 'updated'
    monkeypatch.setattr(research,'start_research',start)
    asyncio.run(productivity.run_due_alert())
    assert any(item.get('last_research_id') == 'updated' for item in patches)
    assert patches[-1]['has_update'] is True
    assert 'not proof of new discoveries' in patches[-1]['status']
