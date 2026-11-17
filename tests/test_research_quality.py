"""Offline regressions for question coverage, honest explanations and diagnosis."""
import pytest
from app.models import EvidenceAssessment, ReportBlock, ReportDraft, ResearchState, ResearchQuestion, ResearchPlan, SubQuestion
from app.research_quality import answer_checklist, research_diagnosis, report_usefulness, recovery_queries
from app.research_depth import evidence_packets
from app.synthesizer import build_structured_report
from app.research_control import audit, coverage_gaps
from tests.test_research_depth import packet_state


def report(state, draft=None):
    state.structured_report = build_structured_report(draft or ReportDraft(title='Synthetic', executive_summary='', conclusion=''), state)
    return {section.id: section.content for section in state.structured_report.sections}


def test_partial_answer_cannot_hide_unanswered_parts():
    state = packet_state()
    rows = answer_checklist(state)
    assert rows[0]['status'] == 'supported findings' and rows[1]['status'] == 'unanswered'
    sections = report(state)
    assert 'Answer checklist' in sections['executive-summary']
    assert 'Does it replicate?' in sections['executive-summary']
    assert 'not be read as a complete answer' in sections['executive-summary']
    assert 'Evidence needed to improve' in sections['conclusion']


@pytest.mark.parametrize('mode', ['quick', 'deep', 'technical', 'academic', 'fact_check', 'compare'])
def test_empty_research_returns_useful_brief_in_every_mode(mode):
    state = ResearchState(question=ResearchQuestion(question='Synthetic unknown topic'), mode=mode)
    sections = report(state)
    assert 'Evidence-limited research brief' in sections['abstract']
    assert 'Why the answer is limited' in sections['executive-summary']
    assert 'does not prove that evidence is absent elsewhere' in sections['executive-summary']
    assert 'Seek matched primary evidence' in sections['conclusion']
    assert all(report_usefulness(state)['checks'].values())
    assert len(state.structured_report.sections) == 11


def test_source_access_extraction_and_rejection_are_distinguishable():
    state = packet_state()
    state.findings = []; state.evidence = []
    state.sources[0].sub_question_ids = ['Q1']; state.sources[0].retrieval_method = 'search'
    first = answer_checklist(state)[0]
    assert 'discovery snippets' in ' '.join(first['causes'])
    assert 'No completed extraction' in ' '.join(first['causes'])
    state.extraction_completed = ['S1']
    assert 'admissible linked evidence' in ' '.join(answer_checklist(state)[0]['causes'])
    audit(state, 'search_failed', 'Synthetic failure')
    audit(state, 'analysis_failed', 'Synthetic failure')
    assert research_diagnosis(state)['search_failures'] == research_diagnosis(state)['analysis_unavailable'] == 1


def test_unretrieved_and_fabricated_quotes_cannot_fill_checklist_or_writer_packets():
    state = packet_state(); state.retrieved_urls = []
    assert answer_checklist(state)[0]['status'] == 'unanswered'
    assert not evidence_packets(state)[0]['evidence']
    state = packet_state(); state.evidence[0].excerpt = 'Not in document'
    assert not answer_checklist(state)[0]['evidence_ids']


def test_disagreement_queries_seek_methods_instead_of_repeating_discovery():
    state = packet_state()
    state.findings[0].evidence_assessments = [EvidenceAssessment(claim_id='C1', evidence_id='E1', relation='contradicts')]
    rows = answer_checklist(state)
    assert rows[0]['status'] == 'disputed'
    assert 'methods population definitions' in recovery_queries(state, state.plan.sub_question_tasks[0])[1]
    assert 'full text original study' in recovery_queries(state, state.plan.sub_question_tasks[1])[1]


def test_completed_queries_are_not_repeated_during_recovery():
    state = packet_state()
    task = state.plan.sub_question_tasks[1]
    variants = recovery_queries(state, task)
    state.searched_queries = [variants[0].casefold(), variants[1].casefold()]
    _, gaps = coverage_gaps(state)
    assert next(query for query, _, ids in gaps if ids == ['Q2']) == variants[2]


def test_unreviewed_finding_explanation_is_not_published_as_fact():
    state = packet_state(); state.findings[0].explanation = 'UNSUPPORTED MAGIC CURES EVERYTHING'
    sections = report(state)
    assert 'UNSUPPORTED MAGIC' not in str(sections)
    assert 'no independently reviewed interpretation' in sections['discussion']
    assert report_usefulness(state)['claims_without_reviewed_interpretation'] == ['C1']


def test_reviewed_scoped_interpretation_is_retained_and_measured():
    state = packet_state()
    draft = ReportDraft(title='Synthetic', executive_summary='', conclusion='', blocks=[ReportBlock(
        id='B1', section_id='discussion', kind='interpretation', text='The quoted cost describes this synthetic observation.',
        claim_ids=['C1'], evidence_ids=['E1'], limitations='It does not establish manufacturing cost elsewhere.')])
    draft._approved_blocks = {'B1'}
    sections = report(state, draft)
    assert '**Interpretation:**' in sections['discussion']
    assert 'manufacturing cost elsewhere' in sections['discussion']
    assert report_usefulness(state)['checks']['reviewed_explanations_for_supported_claims']


def test_planner_keeps_checklist_and_public_question_list_consistent():
    from app.planner import Planner
    class Model:
        def generate_structured(self, prompt, schema):
            assert 'answer checklist' in prompt
            return ResearchPlan(objective='Synthetic', sub_questions=['Unrelated stale question'], sub_question_tasks=[SubQuestion(id='Q1', question='Synthetic cost?', query='Synthetic cost')])
    plan = Planner(Model()).create_plan(ResearchQuestion(question='Synthetic cost?', mode='quick'))
    assert plan.sub_questions == ['Synthetic cost?']


def test_completed_synthesis_worker_diagnostics_reach_final_state(monkeypatch):
    from app.agent import ResearchAgent
    from tests.research_fakes import SyntheticLLM, synthetic_settings, synthetic_search
    monkeypatch.setattr('app.agent.GeminiClient', SyntheticLLM)
    monkeypatch.setattr('app.researcher.search_web', synthetic_search)
    agent = ResearchAgent(synthetic_settings())
    def draft(copy):
        audit(copy, 'synthetic_review', 'Synthesis worker reviewed output')
        return ReportDraft(title='Synthetic', executive_summary='', conclusion='')
    monkeypatch.setattr(agent.synthesizer, 'draft', draft)
    state = agent.run('Synthetic widget test speed', mode='quick')
    assert sum(entry.action == 'synthetic_review' for entry in state.audit_log) == 1
    assert any(entry.action == 'report_usefulness' for entry in state.audit_log)
    assert len({entry.id for entry in state.audit_log}) == len(state.audit_log)


def test_offline_evaluator_has_no_accuracy_score_and_does_not_mutate_session():
    from tools.evaluate_report_quality import evaluate
    state = packet_state(); report(state); before = state.model_dump_json()
    result = evaluate(state)
    assert 'not a correctness score' in result['usefulness']['interpretation']
    assert result['usefulness']['human_review_required']
    assert before == state.model_dump_json()


@pytest.mark.parametrize('valid', [True, False])
def test_local_evaluation_cli_handles_valid_and_invalid_state_without_network(monkeypatch, capsys, valid):
    import sys
    from pathlib import Path
    from tools.evaluate_report_quality import main
    state = packet_state(); report(state)
    monkeypatch.setattr(sys, 'argv', ['evaluate_report_quality', 'synthetic.json'])
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: state.model_dump_json() if valid else 'invalid JSON')
    if valid:
        main()
        assert 'human_review_required' in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
        assert 'No data was uploaded' in capsys.readouterr().err
