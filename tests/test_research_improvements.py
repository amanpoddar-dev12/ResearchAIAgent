"""Synthetic regressions for bounded gap searches and answer-first reports."""
from app.models import ClaimExtraction, GapAssessment, ResearchPlan, ResearchQuestion, ResearchState, Source, SubQuestion, ReportDraft
from app.researcher import Researcher
from app.synthesizer import build_structured_report


def test_source_budget_leaves_room_for_gap_driven_second_round(monkeypatch):
    class LLM:
        def generate_structured(self, prompt, schema):
            return GapAssessment()
    researcher = Researcher(LLM(), 'synthetic', 2, 4, 2)
    queries = []
    def collect(query, *args):
        queries.append(query)
        wave = len(queries)
        return 4, [Source(id='', title='Synthetic cache evidence', url=f'https://synthetic.invalid/{wave}/{i}', domain='synthetic.invalid',
            content=' '.join(f'fictional{wave}_{i}_{word}' for word in range(40))) for i in range(4)], []
    monkeypatch.setattr(researcher, '_collect', collect)
    monkeypatch.setattr(researcher.extractor, 'extract_evidence', lambda *args: ClaimExtraction())
    state = ResearchState(question=ResearchQuestion(question='Synthetic cache evidence'), mode='deep', max_sources=4,
        plan=ResearchPlan(objective='Synthetic fixture', sub_question_tasks=[SubQuestion(id='Q1', question='Synthetic cache evidence', query='Synthetic cache evidence')]))
    result = researcher.run(state)
    assert len(queries) == 2
    assert queries[0] != queries[1]
    assert len(result.sources) == 4
    assert sum('/2/' in source.url for source in result.sources) == 2
    assert result.searches_performed == 2
    assert any(entry.message == 'Source capacity reserved for follow-up evidence' for entry in result.audit_log)


def test_answer_first_report_explicitly_preserves_missing_evidence():
    state = ResearchState(question=ResearchQuestion(question='Synthetic unknown question'), gaps=['No measured manufacturing cost'])
    report = build_structured_report(ReportDraft(title='Synthetic test', executive_summary='', conclusion=''), state)
    abstract = next(section.content for section in report.sections if section.id == 'abstract')
    summary = next(section.content for section in report.sections if section.id == 'executive-summary')
    assert abstract.startswith('The available evidence does not establish a supported answer')
    assert 'What remains unknown' in summary
    assert 'No measured manufacturing cost' in summary

def test_shared_study_does_not_count_as_independent_corroboration():
    from app.source_quality import independent_source_count
    from app.research_control import coverage_gaps
    from app.models import Finding
    sources = [Source(id=f'S{i}', title='Synthetic study coverage', url=f'https://news{i}.invalid/article', domain=f'news{i}.invalid', content='Synthetic fixture',
        reference_urls=['https://doi.org/10.9999/synthetic-test']) for i in (1, 2)]
    assert independent_source_count(sources) == 1
    sources.append(Source(id='S3', title='Independent synthetic fixture', url='https://independent.invalid/study', domain='independent.invalid', content='Synthetic fixture'))
    assert independent_source_count(sources) == 2
    state = ResearchState(question=ResearchQuestion(question='Synthetic question'), semantic_validation_required=True, mode='deep', sources=sources,
        plan=ResearchPlan(objective='Synthetic', sub_question_tasks=[SubQuestion(id='Q1', question='Synthetic?', query='Synthetic')]),
        findings=[Finding(id='C1', claim='Synthetic claim', explanation='', confidence=.8, category='fact', evidence_status='Supported', source_ids=['S1', 'S2'], sub_question_ids=['Q1'])])
    coverage, gaps = coverage_gaps(state)
    assert coverage == 0
    assert any('independent corroboration' in reason for _, reason, _ in gaps)


def test_disagreement_report_shows_roles_dates_and_unknown_explanation():
    from app.models import Evidence, Conflict
    from tests.test_evidence_pipeline import state_with_source
    state = state_with_source('Synthetic widget works. Synthetic widget fails.')
    state.sources[0].publication_date = '2025-01-01'
    state.evidence = [Evidence(id='E1', source_id='S1', excerpt='Synthetic widget works.', relation='supports'),
        Evidence(id='E2', source_id='S1', excerpt='Synthetic widget fails.', relation='contradicts')]
    state.conflicts = [Conflict(topic='Synthetic widget', claim_a='Works', claim_b='Fails', explanation='Synthetic fixture', evidence_ids=['E1', 'E2'])]
    report = build_structured_report(ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    discussion = next(section.content for section in report.sections if section.id == 'discussion')
    assert 'Supports evidence' in discussion and 'Contradicts evidence' in discussion
    assert '2025-01-01' in discussion and '[1]' in discussion
    assert 'no resolution is assumed' in discussion


def test_comparison_preserves_missing_cells_without_inventing_winner():
    state = ResearchState(question=ResearchQuestion(question='Synthetic comparison', comparison_items=['Alpha', 'Beta']), mode='compare')
    report = build_structured_report(ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    comparison = next(section.content for section in report.sections if section.id == 'comparison')
    assert '| Criterion | Alpha | Beta |' in comparison
    assert comparison.count('Unverified — no linked evidence') == 2
    assert 'no winner is inferred' in comparison

def test_research_reserves_finalization_time_inside_total_budget(monkeypatch):
    import time
    from app.agent import ResearchAgent
    from tests.research_fakes import SyntheticLLM, synthetic_settings, synthetic_search
    monkeypatch.setattr('app.agent.GeminiClient', SyntheticLLM)
    monkeypatch.setattr('app.researcher.search_web', synthetic_search)
    agent = ResearchAgent(synthetic_settings())
    captured = []
    original = agent.researcher.run_async
    async def collect(state, emit, executor, started, deadline):
        captured.append((deadline, agent.llm.deadline, time.monotonic()))
        return await original(state, emit, executor, started, deadline)
    monkeypatch.setattr(agent.researcher, 'run_async', collect)
    result = agent.run('Synthetic widget test speed', mode='quick')
    collection, total, now = captured[0]
    assert now < collection < total
    assert total - collection <= 30
    assert any(entry.action == 'budget_allocation' for entry in result.audit_log)
    assert result.max_wall_seconds == 60

def test_continuation_preserves_original_and_reports_new_claim_records(monkeypatch):
    from app.agent import ResearchAgent
    from tests.research_fakes import SyntheticLLM, synthetic_settings, synthetic_search
    monkeypatch.setattr('app.agent.GeminiClient', SyntheticLLM)
    monkeypatch.setattr('app.researcher.search_web', synthetic_search)
    parent = ResearchState(question=ResearchQuestion(question='Synthetic original'), status='complete', final_report='Original unchanged report')
    before = parent.model_dump_json()
    agent = ResearchAgent(synthetic_settings())
    result = agent.run('Synthetic widget test speed', mode='quick', parent_state=parent, parent_research_id='original')
    assert parent.model_dump_json() == before
    assert result.parent_research_id == 'original'
    assert 'Synthetic original' in agent.previous_context
    assert result.version_changes and 'Added' in result.version_changes[0]
    assert 'Changes from the previous report' in result.final_report
    assert 'not automatically promoted to verified evidence' in result.final_report
