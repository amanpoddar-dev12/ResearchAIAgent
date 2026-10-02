import asyncio
import json

from app.models import Evidence, Finding, ResearchQuestion, ResearchState, Source, SourceQuality
from app.scoring import score_finding
from server.api import research
from tests.research_fakes import synthetic_settings


def test_claim_score_returns_explainable_breakdown():
    state = ResearchState(
        question=ResearchQuestion(question="What happened?"),
        sources=[Source(
            id="S1", title="Source", url="https://example.com", domain="example.com", content="quoted text",
            quality=SourceQuality(relevance=.9, authority=.8, freshness=.7, source_type=.8,
                                  evidence_strength=.9, total=.82),
        )],
        evidence=[Evidence(id="E1", source_id="S1", excerpt="quoted text", relation="supports",
                           strength="direct", relevance_score=.9, freshness_score=.7)],
    )
    finding = Finding(id="C1", claim="Claim", explanation="", source_ids=["S1"], evidence_ids=["E1"],
                      confidence=.8, category="fact", evidence_status="Supported")
    breakdown = score_finding(state, finding)
    assert 0 < breakdown.score <= 1
    assert "source quality" in breakdown.formula.lower()


def test_sse_events_have_research_identity_and_sequence(monkeypatch):
    research.jobs.clear()
    monkeypatch.setattr("server.api.research.Settings", synthetic_settings)
    monkeypatch.setattr("app.agent.GeminiClient", __import__("tests.research_fakes", fromlist=["SyntheticLLM"]).SyntheticLLM)
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: [])

    async def run():
        identifier = await research.start_research(
            __import__("server.api.models", fromlist=["ResearchRequest"]).ResearchRequest(question="Test widget", mode="quick")
        )
        events = [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        assert events
        assert all(event["research_id"] == identifier for event in events)
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert all(event.get("stage") for event in events)

    asyncio.run(run())
