"""Synthetic evidence fixtures for report clarity; no live model calls."""
from app.models import Evidence, Finding, ReportBlock, ReportDraft
from app.synthesizer import build_structured_report
from tests.test_evidence_pipeline import state_with_source


def report_fixture(mode="deep", second_source=False, contradicts=False, draft=None, shared_study=False):
    state = state_with_source("Synthetic widget costs 10 USD in 2024. Synthetic widget costs 20 USD in 2024.")
    state.mode = mode
    state.sources[0].publication_date = "2025-01-01"
    state.evidence = [Evidence(id="E1", source_id="S1", excerpt="Synthetic widget costs 10 USD in 2024.", relation="supports", strength="direct")]
    state.findings = [Finding(id="C1", claim="Synthetic widget costs 10 USD in 2024", explanation="", confidence=.8, category="fact", evidence_status="Supported", source_ids=["S1"], evidence_ids=["E1"])]
    if second_source:
        source = state.sources[0].model_copy(update={"id": "S2", "url": "https://independent.invalid/a", "domain": "independent.invalid"})
        state.sources.append(source)
        state.retrieved_urls.append(source.url)
        state.evidence.append(state.evidence[0].model_copy(update={"id": "E2", "source_id": "S2"}))
        state.findings[0].evidence_ids.append("E2")
        state.findings[0].source_ids.append("S2")
        if shared_study:
            for source in state.sources:
                source.reference_urls = ['https://doi.org/10.9999/synthetic']
    if contradicts:
        state.evidence.append(Evidence(id="E3", source_id="S1", excerpt="Synthetic widget costs 20 USD in 2024.", relation="contradicts"))
        state.findings[0].evidence_ids.append("E3")
        state.findings[0].evidence_status = "Partially Supported"
    state.gaps = ["Manufacturing cost outside the reported population is missing"]
    report = build_structured_report(draft or ReportDraft(title="Synthetic", executive_summary="", conclusion=""), state)
    return report, {section.id: section.content for section in report.sections}


def test_evidence_strength_distinguishes_corroboration_and_disagreement():
    _, single = report_fixture()
    assert "**Limited evidence:**" in single["executive-summary"]
    _, corroborated = report_fixture(second_source=True)
    assert "**Well supported:**" in corroborated["executive-summary"]
    _, disputed = report_fixture(contradicts=True)
    assert "**Disputed:**" in disputed["executive-summary"]
    assert disputed["executive-summary"].startswith("The available evidence does not establish")
    assert "**Limited evidence:**" in report_fixture(second_source=True, shared_study=True)[1]['executive-summary']


def test_freshness_unknowns_and_next_questions_remain_explicit():
    _, sections = report_fixture()
    assert "2025-01-01" in sections["methodology"]
    assert "Publication dates are not observation dates" in sections["methodology"]
    assert "Next research questions" in sections["conclusion"]
    assert "Manufacturing cost outside" in sections["conclusion"]
    assert "independent primary source" in sections["conclusion"]
    assert "geography/population" in sections["comparison"]


def test_modes_keep_references_and_emphasize_relevant_report_content():
    quick, sections = report_fixture("quick")
    assert len(quick.sections) == 11
    assert quick.sections[0].id == "abstract"
    assert "Quick review" in sections['abstract']
    assert "methodology" in sections and "references" in sections
    assert "Implementation trade-offs" in report_fixture("technical")[1]["analysis"]
    assert "Claim verdicts" in report_fixture("fact_check")[1]["executive-summary"]
    assert "not a systematic review" in report_fixture("academic")[1]["methodology"]


def test_reviewed_model_blocks_do_not_replace_answer_or_limitations():
    draft = ReportDraft(title='Synthetic', executive_summary='', conclusion='', blocks=[
        ReportBlock(id='B1', section_id='abstract', text='Synthetic widget costs 10 USD in 2024.', claim_ids=['C1'], evidence_ids=['E1']),
        ReportBlock(id='B2', section_id='conclusion', text='Synthetic widget costs 10 USD in 2024.', claim_ids=['C1'], evidence_ids=['E1']),
    ])
    draft._approved_blocks = {'B1', 'B2'}
    _, sections = report_fixture(draft=draft)
    assert sections['abstract'].startswith('Synthetic widget costs 10 USD in 2024.')
    assert 'does not establish exhaustive coverage' in sections['abstract']
    assert 'Future work should address' in sections['conclusion']
    assert 'Next research questions' in sections['conclusion']
