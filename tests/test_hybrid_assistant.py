"""Hybrid assistant behavior without live model calls or new dependencies."""

import asyncio
import json

import httpx
import pytest

from app.assistant_context import AssistantRequest, HybridAnswer, build_context
from app.models import Source
from tests.test_chat import sample_state
from tests.research_fakes import synthetic_settings


@pytest.fixture
def gemini(monkeypatch):
    import server.api.research as research
    original = httpx.AsyncClient
    calls = []
    replies = []

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"inputTokenLimit": 1048576})
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith(":streamGenerateContent")
        calls.append(json.loads(request.content))
        reply = replies.pop(0)
        chunks = [reply[i:i + 7] for i in range(0, len(reply), 7)]

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    await asyncio.sleep(0)
                    payload = {"candidates": [{"content": {"parts": [{"text": chunk}]}}]}
                    yield f"data: {json.dumps(payload)}\n\n".encode()

        return httpx.Response(200, stream=Stream())

    async def review(self, messages, *, task, response_model=None, **kwargs):
        from app.models import ReportBlockReviews, ReportBlockReview
        assert task == 'final_review'
        blocks = json.loads(messages[-1]['content'])['blocks']
        return ReportBlockReviews(reviews=[ReportBlockReview(block_id=block['block_id'], supported=True) for block in blocks])
    monkeypatch.setattr(research.LLMRouter, 'complete', review)
    monkeypatch.setattr(research, "Settings", synthetic_settings)
    monkeypatch.setattr(research, "_gemini_input_limits", {})
    monkeypatch.setattr(research.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return calls, replies


def test_small_context_is_sent_in_full_with_report_claim_status_and_sources():
    state = sample_state()
    state.final_report = "## Findings\nFastAPI supports async endpoints.\n## Limitations\nNo throughput measurements."
    context = build_context(state, "What were the main findings?", [], 1048576)
    assert context.full
    assert "No throughput measurements" in context.text
    assert "evidenceStatus" in context.text
    assert state.sources[0].url in context.text


def test_large_context_uses_bounded_relevant_chunks():
    state = sample_state()
    state.sources[0].content = "Unrelated introduction. " * 30000 + "Quantum widgets are limited by photon loss."
    context = build_context(state, "What limits quantum widgets?", [], 32768)
    assert not context.full
    assert "photon loss" in context.text
    data = json.loads(context.text)
    assert len(data["documents"]) <= 8
    assert len(context.text.encode("utf-8")) <= 32768 - 6000


@pytest.mark.parametrize("reply,origin,source_ids", [
    ("[From research]\nThe main finding is support for async endpoints [S1].", "From research", ["S1"]),
    ("[General knowledge]\nAn API is an interface through which programs communicate.", "General knowledge", []),
    ("[Mixed]\nThe research does not cover manufacturing cost.\nGeneral knowledge: Costs depend on materials and production methods [uncertain].", "Mixed", []),
])
def test_hybrid_tags_citations_and_single_gemini_generation(gemini, reply, origin, source_ids):
    import server.api.research as research
    calls, replies = gemini
    replies.append(reply)
    async def run():
        events = [event async for event in research._hybrid_events(research.ResearchJob(state=sample_state()),
            AssistantRequest(message="What were the main findings?"))]
        assert len([event for event in events if event[0] == "chat_delta"]) > 1
        result = events[-1][1]
        assert result.intent == origin
        assert result.answer.startswith(f"[{origin}]\n")
        assert [item.source_id for item in result.citations] == source_ids
        assert "".join(event[1]["text"] for event in events if event[0] == "chat_delta") == result.answer
    asyncio.run(run())
    assert len(calls) == 1
    instruction = calls[0]["systemInstruction"]["parts"][0]["text"]
    assert "Never fabricate citations or statistics" in instruction
    assert "ONLY from the provided research" in instruction


def test_last_eight_exchanges_are_sent_for_reference_resolution(gemini):
    import server.api.research as research
    calls, replies = gemini
    replies.append("[From research]\nThe second source describes sync endpoints [S2].")
    state = sample_state()
    state.sources.append(Source(id="S2", title="Second source", url="https://second.test", domain="second.test", content="Sync endpoints."))
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"} for i in range(20)]
    async def run():
        events = [event async for event in research._hybrid_events(research.ResearchJob(state=state),
            AssistantRequest(message="What about the second one?", history=history))]
        assert events[-1][1].citations[0].source_id == "S2"
    asyncio.run(run())
    content = json.dumps(calls[0]["contents"])
    assert "turn-0\"" not in content
    assert "turn-3\"" not in content
    assert "turn-4" in content and "turn-19" in content
    assert "What about the second one?" in content


def test_unknown_and_general_section_citations_are_not_published():
    context = build_context(sample_state(), "Explain", [])
    answer = HybridAnswer(context)
    text = "[Mixed]\nAsync endpoints are supported [S1]. No research data exists [S99].\nGeneral knowledge: A general statement [S1]."
    output = "".join(answer.feed(text[i:i + 3]) for i in range(0, len(text), 3)) + answer.feed("", final=True)
    result = answer.response()
    assert "[S99]" not in output
    assert output.count("[S1]") == 1
    assert "[uncertain]" in output
    assert [item.source_id for item in result.citations] == ["S1"]


def test_general_knowledge_never_exposes_research_citations():
    answer = HybridAnswer(build_context(sample_state(), "General question", []))
    answer.feed("[General knowledge]\nDefinition [S1].")
    answer.feed("", final=True)
    assert not answer.response().citations
    assert "[S1]" not in answer.response().answer


def test_saved_browser_context_restores_without_registering_a_job(monkeypatch):
    import server.api.research as research
    monkeypatch.setattr(research, "jobs", {})
    state = sample_state()
    state.final_report = "Research report"
    snapshot = state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}})
    request = AssistantRequest(message="What were the main findings?", saved_state=snapshot)
    job = research.assistant_job("saved-session", request)
    assert job.state.question.question == state.question.question
    assert job.state.sources[0].content == ""
    assert not research.jobs


def test_stream_disconnect_cancels_the_upstream_task(monkeypatch):
    import server.api.research as research
    cancelled = []
    monkeypatch.setattr(research, "jobs", {"active": research.ResearchJob(state=sample_state())})
    async def upstream(_job, _request):
        try:
            await asyncio.sleep(60)
            yield "chat_complete", None
        finally:
            cancelled.append(True)
    monkeypatch.setattr(research, "_hybrid_events", upstream)
    async def run():
        stream = research.stream_chat("active", AssistantRequest(message="Explain"))
        first = await anext(stream)
        assert "chat_started" in first
        await stream.aclose()
    asyncio.run(run())
    assert cancelled == [True]


def test_general_chat_streams_without_research_and_keeps_no_server_state(gemini, monkeypatch):
    import server.api.research as research
    calls, replies = gemini
    monkeypatch.setattr(research, "jobs", {})
    replies.append("[General knowledge]\nAn API lets programs communicate.")
    request = AssistantRequest(message="Explain what an API is.")
    session_id = "general-chat-11111111-1111-4111-8111-111111111111"
    assert research.assistant_job(session_id, request).state is None
    async def run():
        response = await research.chat_research(session_id, request)
        assert response.intent == "General knowledge"
        assert not response.citations
    asyncio.run(run())
    assert len(calls) == 1
    assert "No active research session" in json.dumps(calls[0]["contents"])
    assert not research.jobs
    with pytest.raises(LookupError):
        research.assistant_job("general-chat-invalid", request)
    with pytest.raises(LookupError):
        research.assistant_job("expired-research", request)


def test_pdf_answers_use_only_retrieved_pages_and_validate_citations(gemini):
    import server.api.research as research
    calls, replies = gemini
    replies.append("[From research]\nQuantum throughput is 42 units per hour [P300]. Cost is not in these excerpts [P999].")
    request = AssistantRequest(message="What is quantum throughput?", pdf_context={"document_id":"document", "name":"large.pdf", "page_count":1000,"chunks":[{"page":300,"text":"Quantum throughput is 42 units per hour."}]})
    async def run():
        events = [event async for event in research._hybrid_events(research.ResearchJob(state=sample_state()), request)]
        answer = events[-1][1]
        assert [item.source_id for item in answer.citations] == ["P300"]
        assert "[P999]" not in answer.answer
        assert answer.citations[0].url is None
        assert "42 units" in answer.citations[0].supporting_text
    asyncio.run(run())
    assert len(calls) == 1
    assert "uploaded PDF ONLY" in calls[0]["systemInstruction"]["parts"][0]["text"]
    context = calls[0]["contents"][0]["parts"][0]["text"]
    assert "Quantum throughput" in context
    assert "FastAPI" not in context
