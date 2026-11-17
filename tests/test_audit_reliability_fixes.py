"""Regression coverage for the five runtime audit fixes, without live services."""
import asyncio
import json
import time
from types import SimpleNamespace
import httpx
import pytest
from app.llm.providers import HTTPProvider
from app.llm.router import LLMRouter
from app.llm.base import LLMRequestBudgetExceeded
from app.models import ClaimExtraction, Evidence, Finding, GapAssessment, ReportDraft, ReportBlockReviews, ReportBlockReview, BudgetOverrides
from app.researcher import Researcher
from app.synthesizer import Synthesizer, build_structured_report
from app.assistant_context import AssistantContext, HybridAnswer, build_context, review_hybrid_answer
from tests.test_research_depth import packet_state
from tests.research_fakes import synthetic_settings


def test_search_failure_is_not_an_empty_search_or_a_secret_leak(monkeypatch):
    from tools.web_search import search_web, SearchUnavailable
    monkeypatch.setattr('tools.web_search.httpx.post', lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError('PRIVATE QUERY AND KEY')))
    with pytest.raises(SearchUnavailable) as caught: search_web('private-key', 'private-query')
    assert 'private' not in str(caught.value).lower()
    monkeypatch.setattr('tools.web_search.httpx.post', lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'results':[]}))
    assert search_web('synthetic', 'synthetic') == []


def test_provider_joins_visible_parts_and_rejects_truncation():
    assert HTTPProvider._extract_text({'candidates':[{'content':{'parts':[{'text':'PRIVATE THOUGHT','thought':True},{'text':'first '},{'text':'second'}]}}]}) == 'first second'
    for payload in [{'choices':[{'finish_reason':'length','message':{'content':'partial'}}]}, {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}]}]:
        with pytest.raises(ValueError, match='output token limit'): HTTPProvider._extract_text(payload)


def test_reserved_recovery_attempts_cannot_consume_final_writer_capacity():
    router = LLMRouter(synthetic_settings(), max_requests=10)
    router.reserved_final_calls = 2; router.recovery_reserve = 3
    for _ in range(5): router._reserve_attempt('evidence_extraction')
    with pytest.raises(LLMRequestBudgetExceeded): router._reserve_attempt('evidence_extraction')
    router._reserve_attempt('final_synthesis')
    assert router.requests_used == 6


@pytest.mark.parametrize('empty_first', [True, False])
def test_known_sources_are_reextracted_for_new_scope_or_empty_result(monkeypatch, empty_first):
    state = packet_state(); state.findings = []; state.evidence = []
    state.sources[0].source_type = 'documentation'; state.sources[0].sub_question_ids = ['Q1']
    state.budget_overrides = BudgetOverrides(max_searches=2, max_iterations=2)
    class Model:
        def generate_structured(self, *args, **kwargs): return GapAssessment()
    researcher = Researcher(Model(), 'synthetic', 2, 4, 2)
    monkeypatch.setattr(researcher, '_collect', lambda *args: (1, [state.sources[0].model_copy(deep=True)], []))
    calls = []
    def extract(question, sources, strategy):
        calls.append(sources[0].sub_question_ids[:])
        if empty_first and len(calls) == 1: return ClaimExtraction(processed_source_ids=['S1'])
        return ClaimExtraction(findings=[Finding(id='new',claim='Synthetic widget costs 10 USD in 2024.', explanation='Useful model explanation.',confidence=.8, category='fact',source_ids=['S1'],evidence_ids=['local'], sub_question_ids=sources[0].sub_question_ids)],
            evidence=[Evidence(id='local',source_id='S1',excerpt='Synthetic widget costs 10 USD in 2024.',relation='supports',strength='direct')],processed_source_ids=['S1'])
    monkeypatch.setattr(researcher.extractor, 'extract_evidence', extract)
    researcher.run(state)
    assert len(calls) == 2 and 'Q2' in calls[-1]
    assert len(state.sources) == 1 and state.extraction_completed == ['S1']
    assert state.findings[0].explanation == 'Useful model explanation.'


def test_cited_legacy_paraphrase_gets_semantic_review_and_can_answer_first():
    state = packet_state()
    class Model:
        supports_task_routing = True; max_requests = 10; requests_used = 0
        def generate_structured(self, prompt, schema, **kwargs):
            self.requests_used += 1
            if schema is ReportBlockReviews:
                return ReportBlockReviews(reviews=[ReportBlockReview(block_id='legacy:executive-summary:0', supported=True)])
            return ReportDraft(title='Synthetic',executive_summary='The reported synthetic widget price was 10 USD in 2024. [S1]',conclusion='')
    draft = Synthesizer(Model()).draft(state)
    report = build_structured_report(draft, state)
    summary = next(section.content for section in report.sections if section.id == 'executive-summary')
    assert summary.startswith('The reported synthetic widget price')
    assert 'legacy:executive-summary:0' in draft._approved_blocks


def test_overflow_candidates_can_fill_later_source_capacity(monkeypatch):
    state = packet_state(); state.sources=[];state.evidence=[];state.findings=[]
    state.max_sources=4; state.budget_overrides=BudgetOverrides(max_searches=2,max_iterations=2)
    source = packet_state().sources[0]
    class Model:
        def generate_structured(self, *args, **kwargs): return GapAssessment()
    researcher=Researcher(Model(),'synthetic',2,4,2)
    calls=[]
    def collect(*args):
        calls.append(True)
        return (5,[source.model_copy(update={'id':'','url':f'https://e{i}.invalid/doc','domain':f'e{i}.invalid','content':f'Synthetic widget costs {i} USD with distinct measured parameters and limitations.'}) for i in range(5)],[]) if len(calls)==1 else (0,[],[])
    monkeypatch.setattr(researcher,'_collect',collect)
    monkeypatch.setattr(researcher.extractor,'extract_evidence',lambda *args: ClaimExtraction())
    researcher.run(state)
    assert len(state.sources)==4
    assert any(entry.action=='source_deferred' for entry in state.audit_log)


def test_numbered_report_citations_retain_source_mapping_and_complete_evidence():
    state=packet_state(); state.sources[0].content='Irrelevant. '*15000
    state.final_report='## Findings\nSynthetic widget costs 10 USD in 2024. [1]'
    state.structured_report=None
    context=build_context(state,'What is the synthetic widget cost?',[],32768)
    assert 'S1' in context.sources
    assert 'Synthetic widget costs 10 USD in 2024.' in context.sources['S1'].content
    assert len(context.text.encode())<=32768-6000


@pytest.mark.parametrize('approved', [True,False])
def test_active_qa_requires_entailment_not_just_a_known_citation(approved):
    state=packet_state(); context=build_context(state,'What is the cost?',[])
    answer=HybridAnswer(context);answer.feed('[From research]\nSynthetic widget cost was 10 USD [S1].');answer.feed('',final=True)
    class Reviewer:
        def remaining_time(self): return 10
        async def complete(self,messages,**kwargs):
            assert kwargs['task']=='final_review' and 'metric association' in messages[0]['content']
            return ReportBlockReviews(reviews=[ReportBlockReview(block_id='A0',supported=approved)])
    response=asyncio.run(review_hybrid_answer(Reviewer(),context,'What is the cost?',answer.response()))
    assert ('I could not verify' in response.answer) is not approved
    if not approved: assert 'Retrieved excerpt (not a verified conclusion)' in response.answer


def test_unsupported_number_is_not_published_even_if_review_would_approve():
    context=build_context(packet_state(),'What is the cost?',[])
    answer=HybridAnswer(context);answer.feed('[From research]\nThe cost is 99999 USD [S1].');answer.feed('',final=True)
    class Reviewer:
        def remaining_time(self): return 10
        async def complete(self,*args,**kwargs): raise AssertionError('Invalid numerical block must not reach model review')
    response=asyncio.run(review_hybrid_answer(Reviewer(),context,'Cost?',answer.response()))
    assert '99999' not in response.answer


def test_report_exposes_processing_failures_as_processing_limits():
    from app.research_control import audit
    state=packet_state();audit(state,'search_failed','Search provider request failed')
    report=build_structured_report(ReportDraft(title='Synthetic',executive_summary='',conclusion=''),state)
    assert 'Collection and processing limitations' in str(report)
    assert 'not proof that information does not exist' in str(report)


def test_discovery_score_can_rescue_synonyms_without_verifying_a_claim():
    from app.source_quality import score_source
    from app.modes import MODES
    source=packet_state().sources[0].model_copy(update={'title':'Medical GPT deployments','content':'Medical GPT deployments report practical outcomes.'})
    baseline=score_source(source,'healthcare AI benefits',MODES['deep'])
    source._discovery_relevance=.9
    adjusted=score_source(source,'healthcare AI benefits',MODES['deep'])
    assert baseline.relevance==0 and adjusted.relevance==.36
    assert 'bounded discovery-provider signal' in ' '.join(adjusted.notes)
    assert '_discovery_relevance' not in source.model_dump()


def test_packet_cap_keeps_evidence_for_a_high_importance_claim_at_the_end():
    from app.research_depth import packet_context
    state=packet_state()
    state.evidence=[state.evidence[0].model_copy(update={'id':f'E{i}'}) for i in range(1,41)]
    state.findings=[state.findings[0].model_copy(update={'id':f'C{i}','evidence_ids':[f'E{j}' for j in range(i*5-4,i*5+1)], 'importance':'critical' if i==8 else 'low'}) for i in range(1,9)]
    packet=json.loads(packet_context(state))[0]
    assert packet['claims'][0]['id']=='C8'
    assert any(item['id'] in {'E36','E37','E38','E39','E40'} for item in packet['evidence'])
    assert len(packet['evidence'])<=16


def test_empty_reextraction_does_not_mark_new_scope_completed_using_old_evidence(monkeypatch):
    state=packet_state();state.status='researched';state.sources[0].source_type='documentation';state.sources[0].sub_question_ids=['Q1'];state.extraction_completed=['S1']
    state.budget_overrides=BudgetOverrides(max_searches=3,max_iterations=3)
    class Model:
        def generate_structured(self,*args,**kwargs): return GapAssessment()
    researcher=Researcher(Model(),'synthetic',3,4,3)
    researcher._extraction_scopes['S1']=('S1',('Q1',))
    monkeypatch.setattr(researcher,'_collect',lambda *args:(1,[state.sources[0].model_copy(deep=True)],[]))
    calls=[]
    def extract(*args): calls.append(True);return ClaimExtraction(processed_source_ids=['S1'])
    monkeypatch.setattr(researcher.extractor,'extract_evidence',extract)
    researcher.run(state)
    assert len(calls)==2
    assert researcher._extraction_scopes['S1']==('S1',('Q1',))


def test_source_selection_leaves_space_for_each_question_in_a_parallel_wave(monkeypatch):
    from app.models import Source
    state=packet_state();state.mode='quick';state.sources=[];state.evidence=[];state.findings=[]
    state.max_sources=2;state.budget_overrides=BudgetOverrides(max_searches=2,max_iterations=1)
    class Model:
        def generate_structured(self,*args,**kwargs): return GapAssessment()
    researcher=Researcher(Model(),'synthetic',2,2,1)
    def collect(query,*args):
        number=1 if 'cost' in query else 2
        return (5,[Source(id='',title='Synthetic widget cost replication',url=f'https://q{number}.invalid/{i}',domain=f'q{number}.invalid',content=f'Synthetic widget cost replication observation {number*10+i}.') for i in range(5)],[])
    monkeypatch.setattr(researcher,'_collect',collect)
    monkeypatch.setattr(researcher.extractor,'extract_evidence',lambda *args:ClaimExtraction())
    researcher.run(state)
    assert len(state.sources)==2
    assert {qid for source in state.sources for qid in source.sub_question_ids}=={'Q1','Q2'}
    assert state.searches_performed==2
