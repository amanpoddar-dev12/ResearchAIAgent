from app.chat import ChatCitation, ChatContext, ChatRequest, ChatResponse, retrieve_context, validate_response
from app.models import Evidence, Finding, ResearchQuestion, ResearchState, Source


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
