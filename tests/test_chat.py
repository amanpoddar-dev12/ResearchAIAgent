import asyncio
import pytest
from app.chat import ChatCitation, ChatContext, ChatDraft, ChatRequest, ChatResponse, answer_chat, retrieve_context, validate_response
from app.models import Evidence, Finding, ResearchQuestion, ResearchState, Source, ReportBlock, ReportBlockReview, ReportBlockReviews


def sample_state() -> ResearchState:
    return ResearchState(
        question=ResearchQuestion(question="Does FastAPI support async endpoints?"),
        sources=[Source(id="S1", title="Docs", url="https://example.test/docs", domain="example.test", content="async")],
        findings=[Finding(id="C1", claim="FastAPI supports async endpoints.", explanation="Docs state this.", source_ids=["S1"], confidence=0.8, category="fact", evidence_ids=["E1"])],
        evidence=[Evidence(id="E1", source_id="S1", claim_id="C1", excerpt="FastAPI supports async endpoints.", relation="supports", strength="direct")],
    )


def test_chat_context_resolves_explicit_claim_reference():
    context = retrieve_context(sample_state(), ChatRequest(message="Explain @claim:C1"))
    assert [item.id for item in context.claims] == ["C1"]
    assert [item.id for item in context.evidence] == ["E1"]
    assert [item.id for item in context.sources] == ["S1"]


def test_chat_response_drops_unresolved_citations():
    context = retrieve_context(sample_state(), ChatRequest(message="Explain the claim"))
    response = ChatResponse(
        intent="EXPLAIN",
        answer="Answer",
        citations=[
            ChatCitation(citation_id="S1", source_id="S1", title="Docs"),
            ChatCitation(citation_id="BAD", source_id="S99", title="Invented"),
        ],
    )
    validated = validate_response(response, context)
    assert [item.citation_id for item in validated.citations] == ["S1"]


def test_generation_schema_requires_reviewable_blocks():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatDraft.model_validate({"intent": "SIMPLIFY", "answer": "A legacy unreviewable answer."})
    # The public API contract still accepts legacy responses.
    assert ChatResponse(intent="SIMPLIFY", answer="Legacy").blocks == []


def test_router_repairs_missing_blocks_and_returns_a_reviewed_answer(monkeypatch):
    from app.llm import LLMRouter
    from tests.research_fakes import synthetic_settings
    router = LLMRouter(synthetic_settings(), max_requests=6)
    calls = []
    async def respond(messages, *, task, **kwargs):
        calls.append(task)
        if task == "final_review":
            return ReportBlockReviews(reviews=[ReportBlockReview(block_id="B1", supported=True)]).model_dump_json()
        if calls.count(task) == 1:
            assert '"blocks"' in messages[-1]["content"]
            return ChatResponse(intent="SIMPLIFY", answer="Legacy answer with no blocks.").model_dump_json()
        assert "Repair this response" in messages[-1]["content"]
        return ChatDraft(intent="SIMPLIFY", answer="", blocks=[ReportBlock(id="B1", section_id="answer",
            text="Synthetic test: async endpoints can await work.", claim_ids=["C1"], evidence_ids=["E1"])]).model_dump_json()
    for provider in [*router.providers.values(), router.review_provider]:
        monkeypatch.setattr(provider, "complete", respond)
    result = answer_chat(router, ChatRequest(message="Explain this research in simple terms."), sample_state())
    assert "async endpoints can await work" in result.answer and result.citations
    assert calls == ["chat_response", "chat_response", "final_review"]
    assert router.requests_used == 3


class ChatFake:
    def __init__(self, *, text="Synthetic test: async endpoints can await work.", claim_ids=None, review_error=False, supported=True):
        self.text, self.claim_ids = text, ["C1"] if claim_ids is None else claim_ids
        self.review_error, self.supported = review_error, supported

    def generate_structured(self, prompt, schema, *, task):
        if task == "final_review":
            if self.review_error:
                raise RuntimeError("Synthetic provider failure")
            return ReportBlockReviews(reviews=[ReportBlockReview(block_id="B1", supported=self.supported)])
        assert schema is ChatDraft
        return ChatDraft(intent="SIMPLIFY", answer="Ignored free-form prose", blocks=[ReportBlock(
            id="B1", section_id="answer", text=self.text, claim_ids=self.claim_ids, evidence_ids=["E1"])])


def test_simple_explanation_returns_reviewed_prose_and_canonical_citations():
    result = answer_chat(ChatFake(), ChatRequest(message="Explain this research in simple terms."), sample_state())
    assert "async endpoints can await work" in result.answer
    assert "Ignored free-form" not in result.answer
    assert [citation.source_id for citation in result.citations] == ["S1"]
    assert all("No answer block" not in item for item in result.limitations)
    assert all("No validated citation" not in item for item in result.limitations)


@pytest.mark.parametrize("marker", ["[1]", "[S1]", "[E1]"])
def test_inline_citation_labels_are_not_rejected_as_numbers(marker):
    result = answer_chat(ChatFake(text="Synthetic test: async endpoints can await work. " + marker),
                         ChatRequest(message="Explain this research."), sample_state())
    assert "async endpoints can await work" in result.answer
    assert result.answer.count("[1]") == 1
    assert len(result.citations) == 1


def test_evidence_only_explanations_can_pass_review():
    result = answer_chat(ChatFake(claim_ids=[]), ChatRequest(message="Explain @evidence:E1"), sample_state())
    assert "async endpoints can await work" in result.answer and result.citations


def test_review_failure_returns_excerpts_without_unreviewed_generated_claims():
    result = answer_chat(ChatFake(text="Invented synthetic speed is 999 units.", review_error=True),
                         ChatRequest(message="Explain this research."), sample_state())
    assert "999" not in result.answer
    assert sample_state().evidence[0].excerpt in result.answer
    assert "review is temporarily unavailable" in result.answer
    assert result.citations[0].supporting_text == sample_state().evidence[0].excerpt


def test_explicitly_rejected_answer_is_not_published():
    result = answer_chat(ChatFake(text="An unsupported synthetic conclusion.", supported=False),
                         ChatRequest(message="Explain this research."), sample_state())
    assert "An unsupported synthetic conclusion" not in result.answer
    assert not result.citations


def test_generation_failure_returns_session_excerpts():
    class Broken:
        def generate_structured(self, *_args, **_kwargs):
            raise RuntimeError("Synthetic generation failure")
    result = answer_chat(Broken(), ChatRequest(message="Explain this research."), sample_state())
    assert sample_state().evidence[0].excerpt in result.answer and result.citations


def test_chat_budget_is_bounded_per_question_not_exhausted_for_the_session(monkeypatch):
    import server.api.research as research
    calls = []
    async def events(job, request):
        calls.append(request.message)
        yield "chat_complete", ChatResponse(intent="General knowledge", answer="[General knowledge]\nSYNTHETIC TEST ONLY")
    monkeypatch.setattr(research, "jobs", {"synthetic-chat": research.ResearchJob(state=sample_state())})
    monkeypatch.setattr(research, "_hybrid_events", events)
    async def run():
        for _ in range(8):
            result = await research.chat_research("synthetic-chat", ChatRequest(message="Synthetic test question"))
            assert result.answer.endswith("SYNTHETIC TEST ONLY")
    asyncio.run(run())
    assert len(calls) == 8
