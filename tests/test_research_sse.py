"""Offline end-to-end API/SSE tests using visibly synthetic source data."""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from server.main import app
from server.api import research
from server.api.models import ResearchRequest
from tests.research_fakes import SyntheticLLM, synthetic_search, synthetic_settings


@pytest.fixture
def offline_pipeline(monkeypatch):
    research.jobs.clear()
    monkeypatch.setattr("app.agent.GeminiClient", SyntheticLLM)
    monkeypatch.setattr("app.researcher.search_web", synthetic_search)
    monkeypatch.setattr(research, "Settings", synthetic_settings)
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: pytest.fail("External HTTP is forbidden in synthetic tests"))
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: pytest.fail("External HTTP is forbidden in synthetic tests"))
    yield
    research.jobs.clear()


@pytest.mark.parametrize("mode,queries", [("quick", 3), ("academic", 8)])
def test_sse_event_order_and_progress_synchronized(offline_pipeline, mode, queries):
    with TestClient(app) as client:
        response = client.post("/api/research", json={"question": "Test widget", "mode": mode, "max_sources": 20})
        assert response.status_code == 200
        identifier = response.json()["research_id"]
        with client.stream("GET", f"/api/research/{identifier}/stream") as stream:
            events = [json.loads(line[6:]) for line in stream.iter_lines() if line.startswith("data: ")]
        kinds = [event["type"] for event in events]
        expected = ["research_started", "planning_started", "planning_completed", "search_started", "search_completed", "source_found",
            "finding_extracted", "gap_detected", "analysis_started", "synthesis_started", "report_generated", "research_completed", "complete"]
        assert [kinds.index(kind) for kind in expected] == sorted(kinds.index(kind) for kind in expected)
        assert kinds[0] == "research_started" and kinds[-1] == "complete"
        assert [event["progress"] for event in events] == sorted(event["progress"] for event in events)
        assert all(event["mode"] == mode and 0 <= event["progress"] <= 100 for event in events)
        assert events[0]["progress"] == 0
        assert events[kinds.index("report_generated")]["progress"] == 100
        assert events[-1]["phase"] == "complete" and events[-1]["progress"] == 100
        assert isinstance(events[kinds.index("report_generated")]["data"], str)  # Old payload remains a string.
        assert events[kinds.index("source_evaluated")]["data"]["source_id"] == "S1"
        assert kinds.index("source_evaluated") < kinds.index("source_analyzed") < kinds.index("finding_extracted")
        for event in events:
            assert {"type", "message", "timestamp"} <= event.keys()
            if event["type"] == "research_progress":
                assert event["progress"] == event["data"]["progress"]
                assert event["phase"] == event["data"]["phase"]
        state = events[-1]["data"]["state"]
        assert state["searches_performed"] == queries
        assert state["findings"][0]["evidence_status"] == "Supported"
        assert state["evidence"][0]["source_id"] == "S1"
        assert "content" not in state["sources"][0]
        assert client.get(f"/api/research/{identifier}").json() == state


def test_sessions_are_isolated_and_filters_reach_pipeline(offline_pipeline):
    async def run():
        first = await research.start_research(ResearchRequest(question="Test widget", mode="quick"))
        second = await research.start_research(ResearchRequest(question="Test widget", mode="quick", filters={"exclude_domains": ["synthetic.invalid"]}))
        async def consume(identifier):
            return [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        a, b = await asyncio.gather(consume(first), consume(second))
        assert len(a[-1]["data"]["state"]["sources"]) == 1
        assert b[-1]["data"]["state"]["sources"] == []
        assert b[-1]["data"]["state"]["filtered_sources"]
        assert research.jobs[first].state is not research.jobs[second].state
    asyncio.run(run())


def test_configuration_failure_terminates_stream(offline_pipeline, monkeypatch):
    def broken():
        raise ValueError("Synthetic configuration failure")
    monkeypatch.setattr(research, "Settings", broken)
    async def run():
        identifier = await research.start_research(ResearchRequest(question="Test widget"))
        events = [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        assert [event["type"] for event in events] == ["research_started", "research_failed"]
        assert research.jobs[identifier].done
    asyncio.run(run())


@pytest.mark.parametrize("mode,targets", [("fact_check", {"target_claims": ["SYNTHETIC TEST ONLY: Test widget Alpha has a test speed of 10 units.", "SYNTHETIC TEST: Test widget Gamma flies."]}),
    ("compare", {"comparison_items": ["Alpha", "Beta"]})])
def test_targeted_modes_finish_with_evidence_or_explicit_unknowns(offline_pipeline, mode, targets):
    async def run():
        identifier = await research.start_research(ResearchRequest(question="Test widget", mode=mode, **targets))
        events = [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        state = events[-1]["data"]["state"]
        if mode == "fact_check":
            assert [item["evidence_status"] for item in state["findings"]] == ["Supported", "Unverified"]
            assert state["findings"][1]["source_ids"] == []
        else:
            assert "| Criterion | Alpha | Beta |" in state["final_report"]
            assert "Test speed" in state["final_report"]
            assert "Unverified — no linked evidence" in state["final_report"]
        assert state["llm_requests_used"] == 5
    asyncio.run(run())


def test_api_mode_limits_respect_environment_caps(offline_pipeline, monkeypatch):
    def capped_settings():
        settings = synthetic_settings()
        settings.max_searches = 2
        settings.max_sources = 1
        settings.max_iterations = 1
        return settings
    monkeypatch.setattr(research, "Settings", capped_settings)
    async def run():
        identifier = await research.start_research(ResearchRequest(question="Test widget", mode="deep", max_sources=20))
        events = [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        state = events[-1]["data"]["state"]
        assert state["max_searches"] == 2 and state["searches_performed"] <= 2
        assert state["max_sources"] == 1 and len(state["sources"]) == 1
        assert state["max_iterations"] == 1 and state["iteration"] == 1
    asyncio.run(run())


def test_terminal_event_is_flushed_after_worker_completion(offline_pipeline, monkeypatch):
    from app.models import ResearchQuestion, ResearchState

    class ImmediateAgent:
        def __init__(self, _settings):
            pass

        def run(self, question, emit, **_kwargs):
            state = ResearchState(question=ResearchQuestion(question=question), status="complete", final_report="SYNTHETIC TEST REPORT")
            emit("report_generated", "Synthetic report", state.final_report)
            emit("research_completed", "Synthetic completion", {})
            return state

    monkeypatch.setattr(research, "ResearchAgent", ImmediateAgent)

    async def run():
        identifier = await research.start_research(ResearchRequest(question="SYNTHETIC TEST"))
        events = [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        assert [event["type"] for event in events][-3:] == ["report_generated", "research_completed", "complete"]
        assert events[-1]["data"]["state"] == research.get_public_state(identifier)
        assert research.jobs[identifier].done
    asyncio.run(run())
