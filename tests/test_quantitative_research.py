"""Fictional measurements: test extraction boundaries, never real research data."""
from app.models import DataPoint, Evidence, DataPointExtraction, ReportDraft, Source
from app.extractor import Extractor
from app.synthesizer import build_structured_report
from tests.test_evidence_pipeline import state_with_source


def test_dedicated_pass_is_one_bounded_call_and_rejects_wrong_values():
    calls = []
    class Model:
        supports_task_routing = True
        def generate_structured(self, prompt, schema, *, task):
            calls.append((task, prompt))
            return DataPointExtraction(data_points=[
                DataPoint(source_id='S1', label='Adoption', value=42, unit='percent', observation='2024', quote='In 2024, adoption reached 42 percent.'),
                DataPoint(source_id='S1', label='Adoption', value=99, unit='percent', observation='2024', quote='In 2024, adoption reached 42 percent.'),
                DataPoint(source_id='other-session', label='Adoption', value=42, observation='2024', quote='In 2024, adoption reached 42 percent.')])
    state = state_with_source('In 2024, adoption reached 42 percent.')
    Extractor(Model()).extract_data_points('Synthetic adoption', state.sources, state)
    assert len(calls) == 1 and calls[0][0] == 'data_extraction'
    assert [point.value for point in state.data_points] == [42]
    report = build_structured_report(ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    charts = [chart for chart in report.charts if chart.origin == 'retrieved']
    assert len(charts) == 1 and charts[0].type == 'bar'
    assert any(table.id == charts[0].id + '-table' for table in report.tables)
    comparison = next(section.content for section in report.sections if section.id == 'comparison')
    assert '**42.0**' in comparison and '[1]' in comparison
    assert '**99.0**' not in comparison


def test_same_metric_from_different_sources_is_not_joined_into_a_trend():
    state = state_with_source('In 2024, adoption reached 42 percent.')
    state.sources.append(Source(id='S2', title='Different synthetic population', url='https://other.invalid/study', domain='other.invalid', content='In 2025, adoption reached 51 percent.', quality=state.sources[0].quality))
    state.retrieved_urls.append('https://other.invalid/study')
    state.evidence = [Evidence(id='E1', source_id='S1', excerpt=state.sources[0].content), Evidence(id='E2', source_id='S2', excerpt=state.sources[1].content)]
    state.data_points = [DataPoint(source_id='S1', label='Adoption', value=42, unit='percent', observation='2024', quote=state.sources[0].content),
        DataPoint(source_id='S2', label='Adoption', value=51, unit='percent', observation='2025', quote=state.sources[1].content)]
    report = build_structured_report(ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    charts = [chart for chart in report.charts if chart.origin == 'retrieved']
    assert len(charts) == 2
    assert all(chart.type == 'bar' and len(chart.source_ids) == 1 for chart in charts)


def test_conflicting_values_for_same_observation_are_withheld():
    state = state_with_source('In 2024, adoption reached 42 percent. In 2024, adoption reached 51 percent.')
    quotes = ['In 2024, adoption reached 42 percent.', 'In 2024, adoption reached 51 percent.']
    state.evidence = [Evidence(id=f'E{i}', source_id='S1', excerpt=quote) for i, quote in enumerate(quotes)]
    state.data_points = [DataPoint(source_id='S1', label='Adoption', value=value, unit='percent', observation='2024', quote=quote) for value, quote in zip([42,51], quotes)]
    report = build_structured_report(ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    assert not any(chart.origin == 'retrieved' for chart in report.charts)
    assert any('Conflicting values' in rejection.reason for rejection in state.citation_rejections)


def test_observation_year_at_sentence_end_still_renders_a_chart():
    quote = 'The agency estimates Adoption reached 42 percent in 2024.'
    state = state_with_source(quote)
    from app.evidence import merge_extraction
    from app.models import ClaimExtraction
    from app.synthesizer import _cell_occurs
    merge_extraction(state, ClaimExtraction(data_points=[DataPoint(
        source_id='S1', label='Adoption', value=42, unit='percent', observation='2024', quote=quote)]))
    report = build_structured_report(ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    assert any(chart.origin == 'retrieved' and all(record.estimated for record in chart.provenance) for chart in report.charts)
    assert _cell_occurs(2024, quote)
    assert not _cell_occurs(12, 'The value is 12.5.')
    assert not _cell_occurs(20, 'The year is 2020.')
