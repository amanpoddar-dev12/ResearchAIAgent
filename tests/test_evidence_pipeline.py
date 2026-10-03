from app.evidence import validate_evidence
from app.extractor import Extractor
from app.models import (ChartSpec, Conflict, DataPoint, DataPointExtraction, Evidence, Finding, GapAssessment,
                        ReportDraft, ResearchPlan, ResearchQuestion, ResearchState, Source, SourceQuality, SubQuestion)
from app.researcher import Researcher
from app.synthesizer import build_structured_report, render_report


def state_with_source(content="Exact retrieved quote."):
    state = ResearchState(
        question=ResearchQuestion(question="What happened?"),
        provenance_required=True,
        retrieved_urls=["https://example.com/a"],
        sources=[Source(
            id="S1", title="Retrieved", url="https://example.com/a", domain="example.com",
            content=content, quality=SourceQuality(
                relevance=1, authority=1, freshness=1, source_type=1,
                evidence_strength=1, total=1,
            ),
        )],
    )
    return state


def test_non_verbatim_quote_is_rejected():
    state = state_with_source()
    state.evidence = [Evidence(id="E1", source_id="S1", excerpt="Paraphrased quote.", relation="supports", strength="direct")]
    state.findings = [Finding(id="C1", claim="A claim", explanation="", source_ids=["S1"],
                              evidence_ids=["E1"], confidence=.8, category="fact")]
    validate_evidence(state)
    assert state.findings[0].evidence_ids == []
    assert any("not present" in item.reason for item in state.citation_rejections)


def test_unknown_source_id_is_rejected():
    state = state_with_source()
    state.evidence = [Evidence(id="E1", source_id="S999", excerpt="Exact retrieved quote.", relation="supports", strength="direct")]
    state.findings = [Finding(id="C1", claim="A claim", explanation="", source_ids=["S999"],
                              evidence_ids=["E1"], confidence=.8, category="fact")]
    validate_evidence(state)
    assert state.evidence == []
    assert state.findings[0].evidence_status == "Unverified"
    assert any(item.source_id == "S999" for item in state.citation_rejections)


def test_claim_without_valid_evidence_is_retained_as_unverified():
    state = state_with_source()
    state.findings = [Finding(id="C1", claim="A claim", explanation="", source_ids=[],
                              evidence_ids=[], confidence=.8, category="fact")]
    validate_evidence(state)
    assert state.findings[0].evidence_status == "Unverified"
    assert state.findings[0].evidence_ids == []


def test_conflict_is_present_in_final_report():
    state = state_with_source()
    state.conflicts = [Conflict(
        topic="The result", claim_a="It increased", claim_b="It decreased",
        source_a=["S1"], source_b=["S1"], explanation="Retrieved excerpts disagree.",
    )]
    report = render_report(
        type("Draft", (), {
            "title": "Report", "executive_summary": "", "key_findings": [],
            "detailed_analysis": [], "limitations": [], "conclusion": "",
        })(),
        state,
    )
    assert "## Conflicts" in report
    assert "The result" in report


def test_routed_extraction_combines_source_work_in_one_call():
    class RoutedFake:
        supports_task_routing = True

        def __init__(self):
            self.tasks = []

        def generate_structured(self, prompt, schema, *, task):
            self.tasks.append(task)
            from app.models import ClaimExtraction, SourceSummary
            if schema is SourceSummary:
                return SourceSummary(source_id="S1", summary="Exact summary.")
            return ClaimExtraction()

    fake = RoutedFake()
    source = state_with_source().sources[0]
    result = Extractor(fake).extract_evidence("What happened?", [source])
    assert result.findings == []
    assert fake.tasks == ["evidence_extraction"]


def test_routed_data_point_extraction_keeps_only_verbatim_points():
    class RoutedDataFake:
        supports_task_routing = True

        def generate_structured(self, _prompt, schema, *, task):
            assert task == "data_extraction"
            assert schema is DataPointExtraction
            return DataPointExtraction(data_points=[
                DataPoint(source_id="S1", label="Adoption", value=42, observation="2024",
                          unit="percent", quote="In 2024, adoption reached 42 percent."),
                DataPoint(source_id="S1", label="Adoption", value=99, observation="2025",
                          unit="percent", quote="This quote is not in the source."),
            ])

    state = state_with_source("In 2024, adoption reached 42 percent.")
    Extractor(RoutedDataFake()).extract_data_points("What happened?", state.sources, state)
    assert len(state.data_points) == 1
    assert state.data_points[0].value == 42
    assert any(item.id == "DP1-evidence" for item in state.evidence)


def test_extracted_points_produce_cited_timeline_chart_and_table():
    state = state_with_source("In 2024, adoption reached 42 percent. In 2025, adoption reached 51 percent.")
    state.evidence = [
        Evidence(id="E1", source_id="S1", excerpt="In 2024, adoption reached 42 percent.", relation="context", strength="direct"),
        Evidence(id="E2", source_id="S1", excerpt="In 2025, adoption reached 51 percent.", relation="context", strength="direct"),
    ]
    state.data_points = [
        DataPoint(id="D1", source_id="S1", label="Adoption", value=42, observation="2024", unit="percent",
                  quote="In 2024, adoption reached 42 percent."),
        DataPoint(id="D2", source_id="S1", label="Adoption", value=51, observation="2025", unit="percent",
                  quote="In 2025, adoption reached 51 percent."),
    ]
    report = build_structured_report(ReportDraft(title="Report", executive_summary="", conclusion=""), state)
    chart = next(item for item in report.charts if item.origin == "retrieved")
    assert isinstance(chart, ChartSpec)
    assert chart.section_id == "timeline"
    assert chart.data == [{"observation": 2024, "value": 42.0}, {"observation": 2025, "value": 51.0}]
    assert any(table.section_id == "timeline" for table in report.tables)


def test_gap_followups_are_bounded_by_additional_research_rounds(monkeypatch):
    class RoutedGapLLM:
        supports_task_routing = True

        def __init__(self):
            self.gap_calls = 0

        def generate_structured(self, _prompt, schema, *, task):
            assert task == "gap_analysis"
            assert schema is GapAssessment
            self.gap_calls += 1
            return GapAssessment(follow_up_queries=[f"follow-up-{self.gap_calls}"])

    llm = RoutedGapLLM()
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: [])
    researcher = Researcher(llm, "synthetic", max_searches=4, max_sources=4, max_iterations=4,
                            additional_research_rounds=2)
    state = ResearchState(
        question=ResearchQuestion(question="What happened?"),
        plan=ResearchPlan(objective="x", sub_question_tasks=[SubQuestion(id="Q1", question="x", query="initial")]),
        max_searches=4, max_sources=4, max_iterations=4, max_wall_seconds=10,
    )
    researcher.run(state)
    assert llm.gap_calls <= 3
