from app.models import ReportDraft, ResearchQuestion, ResearchState, Source
from app.synthesizer import render_report


def test_report_contains_numbered_sources():
    state = ResearchState(question=ResearchQuestion(question="Question"), sources=[
        Source(id="S1", title="Source", url="https://example.com", domain="example.com", content="Evidence")
    ])
    report = render_report(ReportDraft(
        title="Report", executive_summary="Summary", key_findings=["Claim [S1]"],
        detailed_analysis=[], limitations=[], conclusion="Conclusion",
    ), state)
    assert "- Claim [1]" in report
    assert "[1] Source — [https://example.com](https://example.com)" in report
