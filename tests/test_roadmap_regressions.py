"""Offline regressions. All documents and measurements are fictional test data."""
import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agent import ResearchAgent
from app.chat import ChatRequest, ChatResponse, answer_chat
from app.evidence import apply_assessments, validate_evidence
from app.extractor import Extractor
from app.llm import LLMRequestBudgetExceeded, LLMRouter
from app.models import (ClaimExtraction, Evidence, EvidenceAssessment, EvidenceAssessmentBatch,
                        Finding, ReportBlock, ReportBlockReview, ReportBlockReviews,
                        ReportDraft, ResearchPlan, QuestionAnalysis, GapAssessment,
                        Source, SubQuestion, DataPoint, DataPointExtraction)
from app.synthesizer import SECTION_TITLES, build_structured_report
from app.researcher import Researcher
from app.models import SourceFilters, SearchResult
from app.modes import MODES
from server.api import research
from server.api.models import ResearchRequest
from tests.research_fakes import SYNTHETIC_TEXT, synthetic_search, synthetic_settings
from tests.test_evidence_pipeline import state_with_source


def finding(**changes):
    values = dict(id="C1", claim="Synthetic widget speed is ten units.", explanation="Fictional test only.",
                  source_ids=["S1"], evidence_ids=["E1"], confidence=.9, category="fact", sub_question_ids=["Q1"])
    return Finding(**(values | changes))


@pytest.mark.parametrize("mode", ["quick", "academic"])
def test_real_router_pipeline_schemas_budgets_and_reports(monkeypatch, mode):
    """Exercise production routing and validation instead of the legacy fake adapter."""
    router = LLMRouter(synthetic_settings())
    tasks = []

    async def respond(messages, *, task, **kwargs):
        tasks.append(task)
        schema = json.loads(messages[-1]["content"].split("schema:\n", 1)[1])
        assert schema["type"] == "object"
        if task == "question_analysis":
            result = QuestionAnalysis(refined_question="Synthetic widget test speed")
        elif task == "planning":
            result = ResearchPlan(objective="Fictional test", search_queries=["Test widget speed"],
                sub_question_tasks=[SubQuestion(id="Q1", question="Test widget speed", query="Test widget speed")])
        elif task == "evidence_extraction":
            source_id = re.search(r"--- (S\d+) \|", messages[0]["content"])[1]
            result = ClaimExtraction(findings=[finding(id="local", source_ids=[source_id], evidence_ids=["local-evidence"])],
                evidence=[Evidence(id="local-evidence", source_id=source_id,
                    excerpt="Test widget Alpha has a test speed of 10 units.")], data_points=[
                    DataPoint(source_id=source_id, label="Test speed", value=10, unit="units", observation="2024", quote="In 2024, test speed was 10 units."),
                    DataPoint(source_id=source_id, label="Test speed", value=12, unit="units", observation="2025", quote="In 2025, test speed was 12 units.")])
        elif task == 'data_extraction':
            result = DataPointExtraction(data_points=[
                DataPoint(source_id='S1', label='Test speed', value=10, unit='units', observation='2024', quote='In 2024, test speed was 10 units.'),
                DataPoint(source_id='S1', label='Test speed', value=12, unit='units', observation='2025', quote='In 2025, test speed was 12 units.')])
        elif task in {"evidence_evaluation", "independent_review"}:
            result = EvidenceAssessmentBatch(assessments=[EvidenceAssessment(claim_id="C1", evidence_id="E1",
                relation="supports", strength="direct", reasoning="Synthetic passage states this measurement.")])
        elif task == "gap_analysis":
            result = GapAssessment()
        elif task == "final_synthesis":
            result = ReportDraft(title="Synthetic test report", executive_summary="", conclusion="",
                blocks=[ReportBlock(id="B1", section_id="analysis", text="Synthetic widget speed is ten units.",
                    claim_ids=["C1"], evidence_ids=["E1"])])
        elif task == "final_review":
            result = ReportBlockReviews(reviews=[ReportBlockReview(block_id="B1", supported=True)])
        else:
            pytest.fail(f"Unexpected task {task}")
        return result.model_dump_json()

    for provider in [*router.providers.values(), router.review_provider]:
        monkeypatch.setattr(provider, "complete", respond)
    monkeypatch.setattr("app.agent.GeminiClient", lambda *_args, **_kwargs: router)
    monkeypatch.setattr("app.researcher.search_web", synthetic_search)
    monkeypatch.setattr("app.researcher.fetch_webpage", lambda *_args, **_kwargs: SYNTHETIC_TEXT + " In 2024, test speed was 10 units. In 2025, test speed was 12 units.")
    events = []
    state = ResearchAgent(synthetic_settings()).run("Test widget speed", mode=mode,
        emit=lambda kind, *_args: events.append(kind))
    assert state.findings[0].evidence_status == "Supported"
    assert state.extraction_completed == ["S1"]
    assert tasks.count("evidence_extraction") == 1
    assert tasks.count('data_extraction') == 1
    assert 0 < state.llm_requests_used <= 10
    assert sum(item["attempts"] for item in state.llm_usage.values()) == state.llm_requests_used
    assert [section.id for section in state.structured_report.sections] == [key for key, _ in SECTION_TITLES]
    assert len(state.structured_report.charts) >= 2 and state.structured_report.tables
    assert len(state.data_points) == 2
    timeline = next(chart for chart in state.structured_report.charts if chart.origin == "retrieved")
    assert timeline.data == [{"observation": 2024, "value": 10.0}, {"observation": 2025, "value": 12.0}]
    assert timeline.source_ids == ["S1"] and timeline.caption and timeline.provenance
    assert state.report_blocks[0].id == "B1"
    assert events.index("source_evaluated") < events.index("evidence_linked") < events.index("report_generated")
    if mode == "academic":
        assert "independent_review" in tasks
        assert state.completion_quality == "partial"  # One domain cannot provide independent corroboration.


def test_pair_reviews_cannot_upgrade_unrelated_or_disputed_evidence():
    state = state_with_source("Fictional test: widget speed is ten units.")
    state.semantic_validation_required = True
    state.evidence = [Evidence(id="E1", source_id="S1", excerpt=state.sources[0].content)]
    state.findings = [finding()]
    validate_evidence(state)
    assert state.findings[0].evidence_status == "Unverified"
    apply_assessments(state, EvidenceAssessmentBatch(assessments=[
        EvidenceAssessment(claim_id="C1", evidence_id="missing", relation="supports", strength="direct"),
        EvidenceAssessment(claim_id="C1", evidence_id="E1", relation="supports", strength="direct")]))
    assert state.findings[0].evidence_status == "Supported"
    apply_assessments(state, EvidenceAssessmentBatch(assessments=[
        EvidenceAssessment(claim_id="C1", evidence_id="E1", relation="contradicts", strength="direct")]), challenge=True)
    assert state.findings[0].evidence_status == "Unverified"
    assert state.citation_rejections


def test_extraction_partial_failure_preserves_success_and_namespaces_ids():
    class Fake:
        supports_task_routing = True
        calls = 0

        def generate_structured(self, prompt, schema, *, task):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("Synthetic batch failure")
            sid = re.search(r"--- (S\d+) \|", prompt)[1]
            return ClaimExtraction(findings=[finding(id="same", source_ids=[sid], evidence_ids=["same"])],
                evidence=[Evidence(id="same", source_id=sid, excerpt="Synthetic test.")])

    sources = [Source(id=f"S{i}", title="Synthetic test", url=f"https://synthetic.invalid/{i}",
                      domain="synthetic.invalid", content="Synthetic test.") for i in range(1, 8)]
    result = Extractor(Fake()).extract_evidence("Synthetic test", sources)
    assert [item.id for item in result.findings] == ["batch0:same", "batch6:same"]
    assert result.processed_source_ids == ["S1", "S2", "S3", "S7"]
    assert [item.evidence_ids[0] for item in result.findings] == [item.id for item in result.evidence]


def test_router_reservations_are_safe_across_threads_and_event_loops(monkeypatch):
    router = LLMRouter(synthetic_settings(), max_requests=6)
    router.reserved_final_calls = 2
    async def respond(*_args, **_kwargs):
        return "Synthetic response"
    for provider in [*router.providers.values(), router.review_provider]:
        monkeypatch.setattr(provider, "complete", respond)
    def request():
        try:
            return asyncio.run(router.complete([], task="planning"))
        except LLMRequestBudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: request(), range(12)))
    assert sum(item is not None for item in results) == 4
    asyncio.run(router.complete([], task="final_synthesis"))
    asyncio.run(router.complete([], task="final_review"))
    assert router.requests_used == 6
    router.cancelled.set()
    with pytest.raises(LLMRequestBudgetExceeded, match="cancelled"):
        asyncio.run(router.complete([], task="final_review"))


def test_report_cannot_self_approve_or_publish_invented_numbers():
    state = state_with_source("Synthetic test speed is 10 units.")
    state.evidence = [Evidence(id="E1", source_id="S1", excerpt=state.sources[0].content, relation="supports", strength="direct")]
    state.findings = [finding(claim=state.sources[0].content)]
    validate_evidence(state)
    draft = ReportDraft.model_validate(dict(title="Synthetic", executive_summary="", conclusion="",
        _approved_blocks=["B1"], blocks=[dict(id="B1", section_id="analysis", text="Synthetic test speed is 999 units.", claim_ids=["C1"], evidence_ids=["E1"])]))
    assert not draft._approved_blocks
    draft._approved_blocks = {"B1"}
    report = build_structured_report(draft, state)
    assert "999" not in " ".join(section.content for section in report.sections)


def test_chat_rejects_reviewed_but_invented_measurements():
    state = state_with_source("Synthetic test speed is 10 units.")
    state.evidence = [Evidence(id="E1", source_id="S1", excerpt=state.sources[0].content, relation="supports", strength="direct")]
    state.findings = [finding(claim=state.sources[0].content)]
    validate_evidence(state)
    class Fake:
        def generate_structured(self, prompt, schema, *, task):
            if task == "final_review":
                return ReportBlockReviews(reviews=[ReportBlockReview(block_id="B1", supported=True)])
            return ChatResponse(intent="EXPLAIN", answer="Unsafe free-form answer", blocks=[
                ReportBlock(id="B1", section_id="answer", text="Synthetic test speed is 999 units.", claim_ids=["C1"], evidence_ids=["E1"])])
    result = answer_chat(Fake(), ChatRequest(message="Explain @claim:C1"), state)
    assert "999" not in result.answer and "Unsafe" not in result.answer
    assert result.citations == []


def test_sse_broadcast_replay_and_failed_ring_recovery():
    async def run():
        job = research.ResearchJob(done=True, finished_at=time.monotonic(), sequence=3,
            events=[dict(type="synthetic", sequence=i) for i in range(1, 4)])
        research.jobs["synthetic-test"] = job
        async def read(after=0):
            return [json.loads(chunk[6:]) async for chunk in research.stream_research("synthetic-test", after)]
        first, second = await asyncio.gather(read(), read())
        assert first == second and len(first) == 3
        assert [item["sequence"] for item in await read(2)] == [3]
        job.events = [dict(type="research_failed", sequence=3)]
        job.latest_snapshot = {"status": "researching"}
        job.error = "Synthetic failure"
        assert (await read())[0]["type"] == "research_failed"
    try:
        asyncio.run(run())
    finally:
        research.jobs.pop("synthetic-test", None)


def test_cancel_before_job_starts_emits_terminal_and_releases_capacity(monkeypatch):
    monkeypatch.setattr(research, "Settings", lambda: pytest.fail("Cancelled job must not load providers"))
    async def run():
        identifier = await research.start_research(ResearchRequest(question="Synthetic test only"))
        assert research.cancel_research(identifier)
        await research.jobs[identifier].task
        assert research.jobs[identifier].done
        assert research.get_job_status(identifier)["status"] == "failed"
        assert research.jobs[identifier].events[-1]["type"] == "research_failed"
        research.jobs.pop(identifier)
    asyncio.run(run())


def test_retrieval_reuses_session_documents_and_follows_real_reference_urls(monkeypatch):
    class Fake:
        supports_task_routing = True
    calls = []
    def fetch(url, *, metadata, **kwargs):
        calls.append(url)
        metadata.update(title="SYNTHETIC TEST: widget reference", reference_urls=["https://synthetic.invalid/references/study"])
        return "SYNTHETIC TEST: widget methods and results."
    monkeypatch.setattr("app.researcher.fetch_webpage", fetch)
    monkeypatch.setattr("app.researcher.search_web", lambda *_args, **_kwargs: [SearchResult(
        title="SYNTHETIC TEST widget", url="https://synthetic.invalid/docs/widget", content="Synthetic snippet", source_domain="synthetic.invalid")])
    researcher = Researcher(Fake(), "synthetic", 3, 3, 2)
    _, first, _ = researcher._collect("widget", SourceFilters(), MODES["quick"], time.monotonic() + 10)
    assert first[0].retrieval_method == "fetch" and first[0].reference_urls
    _, repeated, _ = researcher._collect("widget related", SourceFilters(), MODES["quick"], time.monotonic() + 10,
                                       {first[0].url: first[0]})
    assert len(calls) == 1 and repeated[0].content == first[0].content
    monkeypatch.setattr("app.researcher.search_web", lambda *_args, **_kwargs: pytest.fail("Linked reference uses direct retrieval"))
    _, linked, _ = researcher._collect(first[0].reference_urls[0], SourceFilters(), MODES["academic"], time.monotonic() + 10)
    assert linked[0].title.startswith("SYNTHETIC TEST") and len(calls) == 2
    _, excluded, filtered = researcher._collect(first[0].reference_urls[0], SourceFilters(exclude_domains=["synthetic.invalid"]),
                                              MODES["academic"], time.monotonic() + 10)
    assert excluded == [] and filtered and len(calls) == 2


def test_expired_jobs_are_evicted_without_removing_active_sessions(monkeypatch):
    monkeypatch.setattr(research, "jobs", {})
    research.jobs.update(expired=research.ResearchJob(done=True, finished_at=time.monotonic() - research.RETENTION_SECONDS - 1),
                         active=research.ResearchJob(), recent=research.ResearchJob(done=True, finished_at=time.monotonic()))
    research.cleanup_jobs()
    assert set(research.jobs) == {"active", "recent"}
