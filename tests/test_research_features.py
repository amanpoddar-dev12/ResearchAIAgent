"""All sources, claims and numbers here are explicitly fictional test fixtures."""

from datetime import date
import pytest
from pydantic import ValidationError
from app.models import (Evidence, Finding, ResearchQuestion, ResearchState, Source,
    SourceFilters, ReportDraft, ResearchPlan)
from app.modes import MODES
from app.source_quality import score_source, filter_reason, infer_source_type
from app.evidence import evidence_status, validate_evidence
from app.synthesizer import render_report
from app.planner import Planner
from app.researcher import Researcher
from server.api.models import ResearchRequest
from tests.research_fakes import SYNTHETIC_TEXT, SyntheticLLM, synthetic_search


def synthetic_source(**changes):
    fields = dict(id="S1", title="SYNTHETIC TEST: Test widget documentation", url="https://docs.synthetic.invalid/docs/widgets",
        domain="docs.synthetic.invalid", content=SYNTHETIC_TEXT, source_type="documentation", publication_date="2026-09-01")
    fields.update(changes)
    source = Source(**fields)
    source.quality = score_source(source, "Test widget", MODES["quick"], today=date(2026, 10, 1))
    return source


@pytest.mark.parametrize("mode", ["quick", "deep", "technical", "academic", "fact_check", "compare"])
def test_mode_config_drives_planning_and_search(monkeypatch, mode):
    config = MODES[mode]
    assert sum(config.weights.model_dump().values()) == pytest.approx(1)
    question = ResearchQuestion(question="Test widget", mode=mode)
    llm = SyntheticLLM()
    plan = Planner(llm).create_plan(question)
    assert len(plan.search_queries) == config.queries
    calls = []
    def search(*args, **kwargs):
        calls.append(kwargs)
        return synthetic_search()
    monkeypatch.setattr("app.researcher.search_web", search)
    state = ResearchState(question=question, plan=plan, mode=mode)
    Researcher(llm, "synthetic-not-a-key", 10, 20, 5).run(state)
    assert len(calls) == config.queries
    assert all(call["search_depth"] == config.search_depth for call in calls)
    assert state.iteration == config.iterations
    assert len(state.sources) == 1  # Actual deduplication, unlike the original budget-only test.
    assert state.findings[0].evidence_status == "Supported"


def test_quality_components_weighted_total_and_unknown_date():
    source = synthetic_source()
    assert source.quality.relevance == 1
    score = score_source(source, "Test widget", MODES["technical"], today=date(2026, 10, 1))
    assert score.source_type == 1
    assert score.total == pytest.approx(sum(getattr(score, name) * weight for name, weight in MODES["technical"].weights.model_dump().items()), abs=.0001)
    assert score_source(source, "Unrelated bananas", MODES["quick"]).relevance == 0
    source.publication_date = None
    assert score_source(source, "Test widget", MODES["quick"]).freshness == 0
    assert infer_source_type(source) == "documentation"


@pytest.mark.parametrize("filters,reason", [
    (SourceFilters(include_domains=["synthetic.invalid"]), None),
    (SourceFilters(exclude_domains=["synthetic.invalid"]), "Excluded domain"),
    (SourceFilters(include_domains=["other.invalid"]), "Outside included domains"),
    (SourceFilters(source_types=["news"]), "Excluded source type"),
    (SourceFilters(date_from="2026-09-01", date_to="2026-09-01"), None),
    (SourceFilters(date_from="2026-09-02"), "Before date range"),
    (SourceFilters(date_to="2026-08-31"), "After date range"),
])
def test_source_filters(filters, reason):
    assert filter_reason(synthetic_source(), filters) == reason


def test_unknown_dates_and_domain_boundaries():
    assert filter_reason(synthetic_source(publication_date="unknown"), SourceFilters(date_from="2026-01-01"))
    assert filter_reason(synthetic_source(url="https://notsynthetic.invalid/docs"), SourceFilters(include_domains=["synthetic.invalid"]))
    with pytest.raises(ValidationError):
        SourceFilters(date_from="2026-10-01", date_to="2026-01-01")
    with pytest.raises(ValidationError):
        SourceFilters(include_domains=["https://synthetic.invalid/path"])


def test_filtering_precedes_extraction_and_fetch(monkeypatch):
    monkeypatch.setattr("app.researcher.search_web", synthetic_search)
    monkeypatch.setattr("app.researcher.fetch_webpage", lambda *_: pytest.fail("Filtered source must not be fetched"))
    state = ResearchState(question=ResearchQuestion(question="Test widget"), mode="quick",
        filters=SourceFilters(exclude_domains=["synthetic.invalid"]), plan=ResearchPlan(objective="Synthetic", search_queries=["Test widget"]))
    Researcher(SyntheticLLM(), "synthetic-not-a-key", 3, 10, 1).run(state)
    assert not state.sources and not state.evidence
    assert state.filtered_sources[0]["reason"] == "Excluded domain"


def test_primary_preference_before_source_cap(monkeypatch):
    base = synthetic_search()[0]
    secondary = base.model_copy(update={"url": "https://secondary.synthetic.invalid/news/widgets", "source_domain": "secondary.synthetic.invalid"})
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: [secondary, base])
    state = ResearchState(question=ResearchQuestion(question="Test widget"), mode="quick", filters=SourceFilters(prefer_primary=True),
        plan=ResearchPlan(objective="Synthetic", search_queries=["Test widget"]))
    Researcher(SyntheticLLM(), "synthetic-not-a-key", 3, 1, 1).run(state)
    assert state.sources[0].source_type == "documentation"


@pytest.mark.parametrize("relations,expected", [([], "Unverified"), ([("context", "partial")], "Unverified"),
    ([("supports", "direct")], "Supported"), ([("supports", "partial")], "Partially Supported"),
    ([("contradicts", "direct")], "Contradicted"), ([("supports", "direct"), ("contradicts", "direct")], "Partially Supported")])
def test_evidence_status_derivation(relations, expected):
    items = [Evidence(id=f"E{index}", source_id="S1", excerpt="SYNTHETIC TEST", relation=relation, strength=strength) for index, (relation, strength) in enumerate(relations)]
    assert evidence_status(items) == expected


@pytest.mark.parametrize("case,reason", [("missing", "Nonexistent source"), ("irrelevant", "Source below relevance threshold"), ("fabricated_excerpt", "Excerpt is not present")])
def test_citation_rejections_remove_links_and_override_model_status(case, reason):
    source = synthetic_source()
    source_id = "S404" if case == "missing" else "S1"
    if case == "irrelevant":
        source.quality.relevance = 0
    state = ResearchState(question=ResearchQuestion(question="Test widget"), mode="quick", sources=[source],
        findings=[Finding(claim="SYNTHETIC TEST CLAIM", explanation="Fictional", confidence=1, category="fact", source_ids=[source_id], evidence_ids=["E1"], evidence_status="Supported")],
        evidence=[Evidence(id="E1", source_id=source_id, excerpt="MADE UP EXCERPT" if case == "fabricated_excerpt" else SYNTHETIC_TEXT, relation="supports", strength="direct")])
    validate_evidence(state)
    assert state.findings[0].source_ids == [] and state.findings[0].evidence_ids == []
    assert state.findings[0].evidence_status == "Unverified"
    assert not state.evidence
    assert any(reason in rejection.reason for rejection in state.citation_rejections)


def test_report_order_methodology_invalid_citations_and_comparison():
    state = ResearchState(question=ResearchQuestion(question="Test widget", comparison_items=["Alpha", "Beta"]), mode="compare", sources=[synthetic_source()])
    draft = ReportDraft(title="SYNTHETIC TEST REPORT", executive_summary="Invalid citation [S404].", key_findings=[], detailed_analysis=[], limitations=[], conclusion="")
    report = render_report(draft, state)
    assert [line[3:] for line in report.splitlines() if line.startswith("## ")] == ["Executive Summary", "Methodology", "Key Findings", "Evidence", "Conflicts", "Limitations", "Sources"]
    assert "Mode: Compare" in report and "Filters applied:" in report and "Source count: 1" in report
    assert "[S404]" not in report and state.citation_rejections
    assert "| Criterion | Alpha | Beta |" in report
    assert "Unverified — no linked evidence" in report


def test_legacy_request_and_compare_validation():
    assert ResearchRequest(question="Test widget").depth == "standard"
    with pytest.raises(ValidationError):
        ResearchRequest(question="Test widget", mode="compare", comparison_items=["Alpha"])
    assert ResearchRequest(question="Test widget", mode="compare", comparison_items=["Alpha", "Beta"]).comparison_items == ["Alpha", "Beta"]


def test_unlinked_and_duplicate_evidence_never_become_supported():
    source = synthetic_source()
    item = Evidence(id="E1", source_id="S1", excerpt=SYNTHETIC_TEXT, relation="supports", strength="direct")
    state = ResearchState(question=ResearchQuestion(question="Test widget"), sources=[source],
        findings=[Finding(claim="SYNTHETIC TEST", explanation="Fixture", confidence=1, category="fact", source_ids=["S1"], evidence_ids=["E1", "E404"])], evidence=[item, item])
    validate_evidence(state)
    assert state.findings[0].evidence_status == "Unverified"
    assert not state.findings[0].source_ids
    assert {entry.reason for entry in state.citation_rejections} >= {"Ambiguous evidence ID", "Nonexistent evidence", "Citation has no validated supporting excerpt"}


def test_irrelevant_report_citations_are_removed_from_all_sections():
    source = synthetic_source()
    source.quality.relevance = 0
    state = ResearchState(question=ResearchQuestion(question="Test widget"), sources=[source])
    draft = ReportDraft(title="SYNTHETIC TEST", executive_summary="Fixture [S1, S404].", key_findings=["Fixture [1](https://synthetic.invalid)"], limitations=["Fixture [S404]"], conclusion="")
    report = render_report(draft, state)
    body = report.split("## Sources")[0]
    assert "[S1]" not in body and "[1]" not in body and "[S404]" not in body
    assert {item.reason for item in state.citation_rejections} == {"Source below relevance threshold", "Nonexistent source"}
