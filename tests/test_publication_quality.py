"""One bounded quality-driven recovery; all models/searches are synthetic."""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from app.agent import ResearchAgent
from app.models import GapAssessment, GapQuery, StopDecision, BudgetOverrides
from app.research_control import audit
from app.researcher import Researcher
from tests.test_research_depth import packet_state
from tests.research_fakes import SyntheticLLM


class Reviewer:
    supports_task_routing = True
    max_requests = 20
    reserved_final_calls = 3
    requests_used = 0
    def __init__(self, queries=None, failure=False):
        self.queries = queries or []; self.failure = failure
    def generate_structured(self, prompt, schema, *, task):
        self.requests_used += 1
        assert task == 'gap_analysis' and schema is GapAssessment
        assert 'untrusted data' in prompt
        if self.failure: raise RuntimeError('Synthetic failure')
        return GapAssessment(targeted_queries=self.queries)


def query(text='synthetic replication methods', ids=None):
    return GapQuery(query=text, sub_question_ids=ids or ['Q2'], reason='Replication evidence is missing', priority='high')


def setup(reviewer):
    agent = object.__new__(ResearchAgent)
    agent.llm = reviewer
    agent.settings = SimpleNamespace(additional_research_rounds=2)
    calls = []
    async def collect(state, emit, executor, started, deadline, **options):
        calls.append(options)
        assert deadline < started + state.max_wall_seconds
        state.iteration += 1; state.searches_performed += 1
    agent.researcher = SimpleNamespace(run_async=collect)
    state = packet_state(); state.max_iterations = 3; state.iteration = 2
    state.max_wall_seconds = 60; state.max_searches = 6
    return agent, state, calls


def run(agent, state):
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        asyncio.run(agent._quality_research(state, lambda *args: None, executor, started, started + state.max_wall_seconds))


def test_model_identified_gap_runs_exactly_one_recovery_and_preserves_limits():
    agent, state, calls = setup(Reviewer([query()]))
    caps = state.max_iterations, state.max_searches, state.max_sources
    run(agent, state)
    assert len(calls) == 1 and calls[0]['iteration_limit'] == 1
    assert calls[0]['resume_queries'][0][2] == ['Q2']
    assert (state.max_iterations, state.max_searches, state.max_sources) == caps
    assert state.iteration == 3
    assert any(item.startswith('Quality check:') for item in state.unresolved_questions)
    assert any(entry.action == 'publication_recovery' for entry in state.audit_log)


@pytest.mark.parametrize('limit', ['search', 'source', 'iteration', 'calls', 'time', 'plateau', 'disabled'])
def test_exhausted_budgets_and_plateau_skip_new_model_calls(limit):
    reviewer = Reviewer([query()]); agent, state, calls = setup(reviewer)
    if limit == 'search': state.searches_performed = state.max_searches
    if limit == 'source': state.max_sources = len(state.sources)
    if limit == 'iteration': state.iteration = state.max_iterations
    if limit == 'calls': reviewer.requests_used = reviewer.max_requests - 5
    if limit == 'time': state.max_wall_seconds = 1
    if limit == 'disabled': agent.settings.additional_research_rounds = 0
    if limit == 'plateau': state.stop_decisions = [StopDecision(stop=True, reason='New-evidence gain plateau', coverage=0)]
    run(agent, state)
    assert reviewer.requests_used == (15 if limit == 'calls' else 0)
    assert not calls
    assert state.audit_log[-1].details['reasons']


def test_invalid_repeated_and_out_of_scope_queries_are_not_executed():
    reviewer = Reviewer([query(ids=['UNKNOWN']), query('https://127.0.0.1/private'), query('already completed')])
    agent, state, calls = setup(reviewer); state.searched_queries = ['already completed']
    run(agent, state)
    assert reviewer.requests_used == 1 and not calls
    assert state.audit_log[-1].details['accepted_queries'] == 0


@pytest.mark.parametrize('failure', [True, False])
def test_failed_or_satisfied_review_preserves_collected_state(failure):
    agent, state, calls = setup(Reviewer(failure=failure))
    evidence = state.evidence[:]; claims = state.findings[:]
    run(agent, state)
    assert state.evidence == evidence and state.findings == claims
    assert not calls and agent.llm.requests_used == 1


def test_real_resume_uses_remaining_iteration_and_search_cap_without_replanning(monkeypatch):
    state = packet_state(); state.iteration = 2; state.searches_performed = 2
    state.budget_overrides = BudgetOverrides(max_searches=3, max_iterations=3)
    state.searched_queries = ['initial', 'another']
    researcher = Researcher(SyntheticLLM(), 'synthetic', 3, 10, 3)
    queries = []
    monkeypatch.setattr(researcher, '_collect', lambda query, *args: (queries.append(query) or 0, [], []))
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        asyncio.run(researcher.run_async(state, None, executor, started, started+60, iteration_limit=1,
                                        resume_queries=[('new replication', 'Quality gap', ['Q2']), ('must not exceed cap', 'Quality gap', ['Q1'])]))
    assert queries == ['new replication']
    assert state.iteration == state.max_iterations == 3
    assert state.searches_performed == state.max_searches == 3
    assert state.plan.sub_question_tasks[0].id == 'Q1'
    assert state.sources[0].id == 'S1'


def test_agent_reserves_one_iteration_and_publishes_once_after_recovery(monkeypatch):
    from app.models import QuestionAnalysis, ResearchPlan, SubQuestion
    from tests.research_fakes import synthetic_settings
    class Model(SyntheticLLM):
        supports_task_routing = True
        def generate_structured(self, prompt, schema, *, task):
            if schema is QuestionAnalysis:
                self.requests_used += 1
                return QuestionAnalysis(refined_question='Synthetic widget evidence')
            if schema is ResearchPlan:
                self.requests_used += 1
                return ResearchPlan(objective='Synthetic', sub_question_tasks=[SubQuestion(id='Q1', question='Synthetic widget evidence?', query='synthetic widget evidence')])
            if schema is GapAssessment:
                self.requests_used += 1
                return GapAssessment(targeted_queries=[query(ids=['Q1'])])
            return super().generate_structured(prompt, schema)
    monkeypatch.setattr('app.agent.GeminiClient', Model)
    settings = synthetic_settings().model_copy(update={'max_llm_requests': 30})
    agent = ResearchAgent(settings)
    phases = []
    async def collect(state, emit, executor, started, deadline, **options):
        phases.append(options)
        state.iteration += options['iteration_limit']
        state.searches_performed += 1
    monkeypatch.setattr(agent.researcher, 'run_async', collect)
    events = []
    result = agent.run('Synthetic widget evidence', mode='deep', emit=lambda kind, *args: events.append(kind))
    assert [phase['iteration_limit'] for phase in phases] == [4, 1]
    assert 'resume_queries' in phases[1]
    assert result.iteration == result.max_iterations == 5
    assert events.count('report_generated') == 1
    assert result.status == 'complete' and result.completion_quality == 'partial'
    assert 'Quality check:' in result.final_report
    assert agent.llm.requests_used <= agent.llm.max_requests


@pytest.mark.parametrize('targeted', [True, False])
def test_only_new_evidence_linked_to_requested_questions_counts_as_recovery(targeted):
    agent, state, calls = setup(Reviewer([query()]))
    async def collect(state, *args, **options):
        state.iteration += 1; state.searches_performed += 1
        state.evidence.append(state.evidence[0].model_copy(update={'id': 'E2'}))
        state.findings.append(state.findings[0].model_copy(update={'id': 'C2', 'evidence_ids': ['E2'], 'sub_question_ids': ['Q2' if targeted else 'Q1']}))
    agent.researcher.run_async = collect
    run(agent, state)
    assert any(item.startswith('Quality check:') for item in state.unresolved_questions) is not targeted
    assert state.audit_log[-1].details['new_linked_excerpts'] == int(targeted)
