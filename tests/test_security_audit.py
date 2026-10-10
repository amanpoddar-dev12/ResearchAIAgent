"""Offline regression checks for sensitive data crossing logging boundaries."""
import asyncio
import logging

import pytest
from pydantic import BaseModel
from app.config import Settings
from app.llm.router import LLMRouter
from app.llm.base import ProviderResponseError
from tools.web_search import search_web
from tools.webpage import fetch_webpage


def test_search_query_is_not_logged(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr('tools.web_search.httpx.post', lambda *a, **k: type('Response', (), {
        'raise_for_status': lambda self: None, 'json': lambda self: {'results': []}})())
    search_web('synthetic-key', 'PRIVATE_MEDICAL_QUERY')
    assert 'PRIVATE_MEDICAL_QUERY' not in caplog.text


def test_rejected_fetch_does_not_log_url_credentials(monkeypatch, caplog):
    monkeypatch.setattr('tools.webpage._public_address', lambda _: None)
    assert fetch_webpage('https://example.invalid/?token=PRIVATE_TOKEN') == ''
    assert 'PRIVATE_TOKEN' not in caplog.text


def test_validation_error_does_not_expose_model_values(monkeypatch):
    class Schema(BaseModel):
        count: int
    router = LLMRouter(Settings(_env_file=None), max_requests=2)
    async def invalid(*a, **k):
        return '{"count":"PRIVATE_MODEL_VALUE"}'
    monkeypatch.setattr(router.providers['gemini'], 'complete', invalid)
    with pytest.raises(ProviderResponseError) as error:
        asyncio.run(router.complete([], task='final_synthesis', response_model=Schema))
    assert 'PRIVATE_MODEL_VALUE' not in str(error.value)
    assert error.value.__suppress_context__


def test_share_snapshot_discards_nested_private_fields():
    from server.productivity import share_snapshot
    snapshot = share_snapshot({'question': 'Synthetic', 'report': 'Public report',
        'structuredReport': {'title': 'Synthetic', 'privateContext': 'PRIVATE_NESTED',
            'sections': [], 'charts': [], 'tables': [{'id': 't', 'title': 'Synthetic',
                'caption': 'Synthetic', 'columns': ['Value'],
                'rows': [{'Value': 1, 'secret': 'PRIVATE_ROW'}]}]}})
    assert 'PRIVATE_' not in __import__('json').dumps(snapshot)
    assert snapshot['structuredReport']['tables'][0]['rows'] == [{'Value': 1}]


def test_chat_failure_logs_do_not_include_exception_values(monkeypatch, caplog):
    from server.api import research
    from app.assistant_context import AssistantRequest
    async def fail(*a, **k):
        raise ValueError('PRIVATE_EXCEPTION_VALUE')
        yield  # Keep the mocked producer an async generator.
    monkeypatch.setattr(research, '_hybrid_events', fail)
    async def run():
        return [event async for event in research.stream_chat(
            'general-chat-00000000-0000-0000-0000-000000000000', AssistantRequest(message='Synthetic'))]
    events = asyncio.run(run())
    assert any('chat_error' in event for event in events)
    assert 'PRIVATE_EXCEPTION_VALUE' not in caplog.text
