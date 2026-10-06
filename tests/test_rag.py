"""Offline checks of canonical retrieval, citation grounding and streaming."""

import asyncio
import json
import httpx

from app.chat import ChatDraft, ChatRequest, answer_chat, retrieved_bundle
from app.models import ReportBlock, ReportBlockReview, ReportBlockReviews, Source
from app.rag import ChunkReference, RetrievedContext, SessionIndex
from tests.test_chat import sample_state


def selection(index, session_id="active", document_id="evidence:E1", query="Does FastAPI support async endpoints?"):
    document = index.documents[document_id]
    return RetrievedContext(session_id=session_id, query=query,
        chunks=[ChunkReference(document_id=document_id, start=0, end=min(1600, len(document["text"])))] )


class AnswerModel:
    def generate_structured(self, prompt, schema, *, task):
        if task == "final_review":
            return ReportBlockReviews(reviews=[ReportBlockReview(block_id="B1", supported=True)])
        assert "FIRST sentence" in prompt
        assert "S99" not in prompt
        return ChatDraft(intent="EXPLAIN", answer="", blocks=[ReportBlock(id="B1", section_id="answer",
            text="Yes, FastAPI supports async endpoints.", claim_ids=[], evidence_ids=["E1"])])


def test_index_updates_incrementally_and_includes_full_source_query_and_validation():
    index = SessionIndex("Async endpoint research", "quick")
    state = sample_state()
    index.update("source_found", state.sources[0])
    index.update("claim_extracted", state.findings[0])
    index.update("evidence_found", state.evidence[0])
    assert "evidence:E1" in index.documents
    public = state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}})
    public["citation_rejections"] = [{"claim_id": "C1", "reason": "Missing linked quotation"}]
    public["final_report"] = "## Findings\nFastAPI supports async endpoints.\n## Limitations\nNo performance benchmark."
    index.update("research_snapshot", public)
    assert index.documents["source:S1"]["text"] == "async"
    assert "rejection:0" in index.documents
    assert len([key for key in index.documents if key.startswith("report:")]) == 2


def test_index_updates_do_not_mutate_existing_sse_snapshot_payloads():
    snapshot = sample_state().model_dump(mode="json")
    index = SessionIndex()
    index.update("research_snapshot", snapshot)
    index.update("source_found", {"id": "S2", "title": "New source", "url": "https://new.test", "content": "New text"})
    assert len(snapshot["sources"]) == 1
    assert "source:S2" in index.documents


def test_chunks_are_resolved_from_server_content_and_capped():
    index = SessionIndex()
    index.update("research_snapshot", sample_state())
    refs = [ChunkReference(document_id="source:S99", start=0, end=1),
            ChunkReference(document_id="source:S1", start=0, end=2000),
            ChunkReference(document_id="source:S1", start=0, end=5)]
    chunks = index.resolve(refs)
    assert len(chunks) == 1 and chunks[0]["text"] == "async"


def test_specific_finding_answer_is_direct_and_numbered_citation_is_canonical():
    state = sample_state()
    state.sources.append(Source(id="S99", title="Unrelated source", url="https://unrelated.test", domain="unrelated.test", content="Unrelated material."))
    index = SessionIndex()
    index.update("research_snapshot", state)
    deltas = []
    request = ChatRequest(message="Does FastAPI support async endpoints?", retrieval=selection(index))
    result = answer_chat(AnswerModel(), request, state, index=index, on_delta=lambda text, citations: deltas.append(text))
    assert result.answer.startswith("Yes, FastAPI supports async endpoints.")
    assert "[1]" in result.answer
    assert result.citations[0].source_id == "S1"
    assert result.citations[0].url == state.sources[0].url
    assert "".join(deltas) == result.answer


def test_uncovered_question_has_no_fabrication_or_unrelated_fallback():
    class NeverCalled:
        def generate_structured(self, *_args, **_kwargs):
            raise AssertionError("No retrieved chunks must not call generation")
    state = sample_state()
    index = SessionIndex()
    index.update("research_snapshot", state)
    request = ChatRequest(message="What is penguin migration speed?",
        retrieval=RetrievedContext(session_id="active", query="penguin migration speed", chunks=[]))
    result = answer_chat(NeverCalled(), request, state, index=index)
    assert result.answer.startswith("Not found in this research:")
    assert not result.citations


def test_model_reports_missing_information_when_keyword_overlap_is_not_an_answer():
    class Missing:
        def generate_structured(self, *_args, **_kwargs):
            return ChatDraft(intent="EXPLAIN", answer="", answerable=False,
                missing_context="a throughput benchmark for FastAPI",
                blocks=[ReportBlock(id="B1", section_id="answer", text="")])
    state = sample_state()
    index = SessionIndex()
    index.update("research_snapshot", state)
    result = answer_chat(Missing(), ChatRequest(message="What is FastAPI throughput?", retrieval=selection(index)), state, index=index)
    assert result.answer.startswith("Not found in this research:")
    assert "throughput benchmark" in result.answer and not result.citations


def test_retrieved_source_excerpt_can_answer_without_an_extracted_claim():
    state = sample_state()
    state.sources[0].content = "FastAPI throughput reaches 10 test units in this fictional benchmark."
    state.findings = []
    state.evidence = []
    index = SessionIndex()
    index.update("research_snapshot", state)
    request = ChatRequest(message="What is FastAPI throughput?", retrieval=selection(index, document_id="source:S1"))
    context = retrieved_bundle(state, request, index)
    assert context.evidence[0].excerpt == state.sources[0].content
    assert context.evidence[0].source_id == "S1"
    assert context.evidence[0].id == "RAG1"


def test_prompt_context_is_bounded_even_for_long_original_evidence():
    state = sample_state()
    state.evidence[0].excerpt = "Evidence text. " * 10000
    index = SessionIndex()
    index.update("research_snapshot", state)
    request = ChatRequest(message="Evidence?", retrieval=selection(index))
    context = retrieved_bundle(state, request, index)
    assert sum(len(item.excerpt) for item in context.evidence) <= 8000
    assert all(len(item.excerpt) <= 1600 for item in context.evidence)


def test_api_stream_preserves_event_envelope_and_isolates_sessions(monkeypatch):
    import server.api.research as research
    from server.main import app
    index = SessionIndex()
    state = sample_state()
    index.update("research_snapshot", state)
    monkeypatch.setattr(research, "jobs", {"active": research.ResearchJob(state=state, rag_index=index)})
    monkeypatch.setattr("server.main.jobs", research.jobs)
    async def events(_job, _request):
        from app.chat import ChatCitation, ChatResponse
        citation = ChatCitation(citation_id="S1", source_id="S1", title="Docs", url="https://example.test/docs")
        yield "chat_delta", {"text": "[From research]\nAsync endpoints are supported [S1].", "citations": [citation]}
        yield "chat_complete", ChatResponse(intent="From research", answer="[From research]\nAsync endpoints are supported [S1].", citations=[citation])
    monkeypatch.setattr(research, "_hybrid_events", events)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            catalog = await client.get("/api/research/active/chat/index")
            assert catalog.status_code == 200 and catalog.json()["research_id"] == "active"
            payload = {"message": "Does FastAPI support async endpoints?", "retrieval": selection(index).model_dump()}
            response = await client.post("/api/research/active/chat/stream", json=payload)
            events = [json.loads(frame[6:]) for frame in response.text.split("\n\n") if frame.startswith("data: ")]
            assert [event["type"] for event in events] == ["chat_started", "chat_delta", "chat_complete"]
            assert all(event["research_id"] == "active" and "timestamp" in event for event in events)
            assert events[-1]["data"]["citations"][0]["citation_id"] == "S1"
            payload["retrieval"]["session_id"] = "other"
            assert (await client.post("/api/research/active/chat/stream", json=payload)).status_code == 400
            assert (await client.post("/api/research/active/chat", json=payload)).status_code == 400
    asyncio.run(run())
