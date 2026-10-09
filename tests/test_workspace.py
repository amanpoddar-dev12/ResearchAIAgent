"""Offline checks for authenticated ownership, restoration and quota boundaries."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.models import ResearchState, ResearchQuestion, Source
from server.main import app
from server import workspace
from server.api import research
from server.api.models import ResearchRequest


@pytest.fixture
def private_client(monkeypatch):
    monkeypatch.setattr(workspace, 'configured', lambda: True)
    async def user(request):
        if request.headers.get('Authorization') != 'Bearer valid':
            raise HTTPException(401, 'Invalid session')
        return {'id': 'owner-a', 'is_anonymous': True}
    monkeypatch.setattr(workspace, 'authenticate', user)
    monkeypatch.setattr(workspace, 'load', AsyncMock(return_value=None))
    research.jobs.clear()
    with TestClient(app) as client:
        yield client
    research.jobs.clear()


def test_private_endpoints_reject_missing_session(private_client):
    assert private_client.get('/api/workspace/research').status_code == 401
    assert private_client.post('/api/research', json={'question': 'Test question'}).status_code == 401
    assert private_client.post('/api/assistant/pdf', content=b'%PDF-test').status_code == 401


@pytest.mark.parametrize('suffix,method', [('', 'get'),('/status','get'),('/stream','get'),
    ('/cancel','post'),('/chat/index','get'),('/chat/stream','post')])
def test_other_owner_jobs_are_hidden(private_client, suffix, method):
    research.jobs['private'] = research.ResearchJob(owner_id='owner-b')
    response = getattr(private_client, method)('/api/research/private'+suffix,
        headers={'Authorization': 'Bearer valid'})
    assert response.status_code == 404


def test_cloud_restoration_keeps_source_text(private_client, monkeypatch):
    state = ResearchState(question=ResearchQuestion(question='Saved test question'),
        sources=[Source(id='S1',title='Test source',url='https://example.com',domain='example.com',content='The actual supporting passage')],
        final_report='Saved report')
    monkeypatch.setattr(workspace, 'load', AsyncMock(return_value={'state': state.model_dump(mode='json'), 'status': 'complete'}))
    response = private_client.get('/api/research/saved-id', headers={'Authorization':'Bearer valid'})
    assert response.status_code == 200
    assert 'content' not in response.json()['sources'][0]
    assert research.jobs['saved-id'].state.sources[0].content == 'The actual supporting passage'
    assert research.jobs['saved-id'].owner_id == 'owner-a'


def test_quota_denial_does_not_start_job(monkeypatch):
    monkeypatch.setattr(workspace, 'remote', AsyncMock(return_value=False))
    research.jobs.clear()
    async def run():
        with pytest.raises(HTTPException) as error:
            await research.start_research(ResearchRequest(question='Test question'), {'id':'guest', 'is_anonymous':True})
        assert error.value.status_code == 403
        assert not research.jobs
    asyncio.run(run())


def test_failed_start_refunds_guest(monkeypatch):
    monkeypatch.setattr(workspace, 'reserve', AsyncMock())
    monkeypatch.setattr(workspace, 'save', AsyncMock(side_effect=HTTPException(503, 'Unavailable')))
    refunded = AsyncMock()
    monkeypatch.setattr(workspace, 'refund', refunded)
    research.jobs.clear()
    async def run():
        with pytest.raises(HTTPException):
            await research.start_research(ResearchRequest(question='Test question'), {'id':'guest','is_anonymous':True})
        assert not research.jobs
        refunded.assert_awaited_once()
        assert refunded.call_args.args[0] == 'guest'
    asyncio.run(run())


def test_cloud_rename_cannot_replace_evidence(private_client, monkeypatch):
    original = {'state': {'sources': [{'id':'S1','content':'original'}]}, 'report':'original report'}
    monkeypatch.setattr(workspace, 'load', AsyncMock(return_value=original))
    saved = AsyncMock()
    monkeypatch.setattr(workspace, 'save', saved)
    response = private_client.put('/api/workspace/research/test-id', headers={'Authorization':'Bearer valid'},
        json={'owner_id':'owner-b','name':'New title','state':{'sources':[]},'report':'fabricated'})
    assert response.status_code == 200
    assert saved.call_args.args == ('owner-a','research','test-id',{**original,'name':'New title'})


def test_invalid_transfer_token_is_rejected(private_client, monkeypatch):
    async def signed_user(request):
        return {'id':'signed-user','is_anonymous':False}
    monkeypatch.setattr(workspace, 'authenticate', signed_user)
    remote = AsyncMock(return_value=False)
    monkeypatch.setattr(workspace, 'remote', remote)
    response = private_client.post('/api/workspace/transfer', json={'token':'expired'}, headers={'Authorization':'Bearer valid'})
    assert response.status_code == 410
    assert remote.call_args.kwargs['json']['p_token'] != 'expired'


def test_pdf_path_must_belong_to_owned_document(private_client, monkeypatch):
    monkeypatch.setattr(workspace, 'load', AsyncMock(return_value=None))
    response = private_client.put('/api/workspace/pdf/chat-id', headers={'Authorization':'Bearer valid'},
        json={'id':'someone-elses-pdf','storage_path':'owner-b/file.pdf','page_count':1,'pages':[{'page':1,'text':'Test'}]})
    assert response.status_code == 403


def test_modern_secret_is_not_sent_as_bearer(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(workspace, 'Settings', lambda: SimpleNamespace(supabase_url='https://supabase.synthetic.invalid',
        supabase_secret_key='sb_secret_synthetic', supabase_publishable_key='sb_publishable_synthetic'))
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, url, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(is_success=True, content=b'[]', json=lambda: [])
    monkeypatch.setattr(workspace.httpx, 'AsyncClient', Client)
    asyncio.run(workspace.remote('GET','/rest/v1/workspace_records'))
    assert calls[0]['headers']['apikey'] == 'sb_secret_synthetic'
    assert 'Authorization' not in calls[0]['headers']


def test_partial_config_does_not_disable_authentication(monkeypatch):
    from types import SimpleNamespace
    from starlette.requests import Request
    monkeypatch.setattr(workspace, 'Settings', lambda: SimpleNamespace(supabase_url='https://supabase.synthetic.invalid',
        supabase_secret_key='', supabase_publishable_key=''))
    assert workspace.configured()
    request = Request({'type':'http','headers':[(b'authorization',b'Bearer synthetic-token')]})
    with pytest.raises(HTTPException) as error:
        asyncio.run(workspace.authenticate(request))
    assert error.value.status_code == 503


def test_provider_failure_refunds_even_when_persistence_fails(monkeypatch):
    class FailingAgent:
        def __init__(self, settings): pass
        def run(self, *args, **kwargs): raise RuntimeError('Synthetic provider failure')
    monkeypatch.setattr(research, 'ResearchAgent', FailingAgent)
    monkeypatch.setattr(workspace, 'save', AsyncMock(side_effect=HTTPException(503,'Offline')))
    refunded = AsyncMock()
    monkeypatch.setattr(workspace, 'refund', refunded)
    research.jobs.clear()
    async def run():
        research.jobs['failed-run'] = research.ResearchJob(owner_id='guest')
        await research._run_job('failed-run', ResearchRequest(question='Synthetic test'))
        refunded.assert_awaited_once_with('guest','failed-run')
        assert research.jobs['failed-run'].done
    asyncio.run(run())
    research.jobs.clear()

def test_continuation_rejects_unowned_parent_before_reserving_run(private_client, monkeypatch):
    reserve = AsyncMock()
    monkeypatch.setattr(workspace, 'reserve', reserve)
    response = private_client.post('/api/research', headers={'Authorization': 'Bearer valid'}, json={'question':'Synthetic follow-up', 'parent_research_id':'someone-elses-report'})
    assert response.status_code == 404
    reserve.assert_not_awaited()


def test_continuation_loads_only_owned_parent_and_creates_separate_job(private_client, monkeypatch):
    parent = ResearchState(question=ResearchQuestion(question='Synthetic original'), status='complete', final_report='Original report')
    load = AsyncMock(return_value={'id':'original', 'status':'complete', 'state':parent.model_dump(mode='json')})
    monkeypatch.setattr(workspace, 'load', load)
    monkeypatch.setattr(workspace, 'reserve', AsyncMock())
    monkeypatch.setattr(workspace, 'save', AsyncMock())
    monkeypatch.setattr(research, '_run_job', AsyncMock())
    response = private_client.post('/api/research', headers={'Authorization': 'Bearer valid'}, json={'question':'Synthetic follow-up', 'parent_research_id':'original'})
    assert response.status_code == 200
    identifier = response.json()['research_id']
    assert identifier != 'original'
    assert research.jobs[identifier].parent_state.final_report == 'Original report'
    load.assert_awaited_once_with('owner-a', 'research', 'original')
