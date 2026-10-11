"""Deterministic quality benchmark: fictional evidence, no live providers."""
import json
from contextlib import contextmanager
import pytest
from app.research_depth import document_chunks, select_passages, evidence_packets, packet_context, quality_diagnostics, prioritize_gaps
from app.models import Evidence, Finding, ResearchPlan, SubQuestion, ReportDraft, ReportBlock, ReportBlockReviews, ReportBlockReview, ClaimExtraction
from app.extractor import Extractor
from app.synthesizer import Synthesizer, build_structured_report
from tests.test_evidence_pipeline import state_with_source
from tests.test_pdf_assistant import pdf_bytes


def packet_state():
    state = state_with_source('Synthetic widget costs 10 USD in 2024. Methods used 30 samples. Limitations: one laboratory.')
    state.mode = 'deep'; state.sources[0].retrieval_method = 'fetch'
    state.plan = ResearchPlan(objective='Synthetic quality test', sub_question_tasks=[SubQuestion(id='Q1', question='What does the widget cost?', query='widget cost'), SubQuestion(id='Q2', question='Does it replicate?', query='widget replication')])
    state.evidence = [Evidence(id='E1', source_id='S1', excerpt='Synthetic widget costs 10 USD in 2024.', relation='supports', strength='direct')]
    state.findings = [Finding(id='C1', claim='Synthetic widget costs 10 USD in 2024.', explanation='', confidence=.8, category='fact', source_ids=['S1'], evidence_ids=['E1'], evidence_status='Supported', sub_question_ids=['Q1'], importance='high')]
    return state


def test_chunk_spans_are_verbatim_bounded_and_overlap():
    text = ('Methods and limitations are important. ' * 400) + 'Ending.'
    chunks = document_chunks(text)
    assert all(chunk in text and len(chunk) <= 1800 for chunk in chunks)
    assert chunks[-1].endswith('Ending.')
    assert chunks[0][-180:] == chunks[1][:180]
    with pytest.raises(ValueError): document_chunks(text, 100, 200)


@pytest.mark.parametrize('position', [12000, 40000, 90000])
def test_late_findings_and_numbers_reach_extraction_without_more_calls(position):
    quote = 'In 2024 synthetic widget adoption was 42 percent across 30 samples.'
    text = ('Unrelated background. ' * (position // 20)) + quote + ' Methods: survey. Limitations: one district.'
    chosen = select_passages(text, 'synthetic widget adoption', 5000, numerical=True)
    assert quote not in text[:5000] and quote in chosen and len(chosen) <= 5000
    class Model:
        supports_task_routing = True
        def generate_structured(self, prompt, schema, *, task):
            assert quote in prompt
            return ClaimExtraction()
    Extractor(Model()).extract_evidence('synthetic widget adoption', [packet_state().sources[0].model_copy(update={'content': text})])


def test_packets_keep_questions_missing_evidence_and_method_signals_separate():
    state = packet_state(); packets = evidence_packets(state)
    assert packets[0]['claims'][0]['id'] == 'C1'
    assert packets[0]['evidence'][0]['excerpt'] in state.sources[0].content
    assert set(packets[0]['sources'][0]['reporting_signals']) == {'methods', 'sample', 'limitations'}
    assert packets[1]['missing'] and not packets[1]['claims']
    assert len(packet_context(state, 2500)) <= 2500
    json.loads(packet_context(state, 2500))
    state.evidence[0].excerpt = 'Fabricated quotation'
    assert not evidence_packets(state)[0]['evidence']


def test_priority_prefers_unanswered_questions_then_important_disagreements():
    state = packet_state(); state.findings[0].evidence_status = 'Partially Supported'
    gaps = [('replication', 'C1: lacks independent corroboration', ['Q1']), ('missing', 'Q2: sub-question has no verified evidence', ['Q2'])]
    assert prioritize_gaps(state, gaps)[0][0] == 'missing'
    assert quality_diagnostics(state)['full_text_sources'] == 1


def test_section_expansion_and_repair_still_require_independent_review():
    state = packet_state()
    original = ReportBlock(id='B1', section_id='analysis', text='Widget costs 10 USD.', claim_ids=['C1'], evidence_ids=['E1'])
    class Model:
        supports_task_routing = True; max_requests = 12; requests_used = 0
        def generate_structured(self, prompt, schema, *, task):
            self.requests_used += 1
            if 'Write only the' in prompt: return ReportDraft(title='', executive_summary='', conclusion='', blocks=[])
            if 'Repair these rejected' in prompt: return ReportDraft(title='', executive_summary='', conclusion='', blocks=[original.model_copy(update={'text': 'The synthetic widget was reported to cost 10 USD in 2024.'})])
            if schema is ReportBlockReviews:
                return ReportBlockReviews(reviews=[ReportBlockReview(block_id='B1', supported='repaired atomic' in prompt, reason='Synthetic review')])
            assert 'Evidence packets grouped by research question' in prompt
            return ReportDraft(title='Synthetic', executive_summary='', conclusion='', blocks=[original])
    draft = Synthesizer(Model()).draft(state)
    assert draft._approved_blocks == {'B1'}
    report = build_structured_report(draft, state)
    assert 'reported to cost 10 USD' in next(section.content for section in report.sections if section.id == 'analysis')
    assert any(entry.action == 'report_repair' and entry.details['accepted_blocks'] == 1 for entry in state.audit_log)


def test_low_budget_draft_never_spends_review_capacity_on_expansion():
    state = packet_state()
    class Model:
        supports_task_routing = True; max_requests = 2; requests_used = 0
        def generate_structured(self, prompt, schema, *, task):
            self.requests_used += 1
            assert 'Write only the' not in prompt
            return ReportDraft(title='Synthetic', executive_summary='', conclusion='')
    model = Model(); Synthesizer(model).draft(state)
    assert model.requests_used == 1


def test_pdf_fetch_uses_isolated_parser_and_original_page_text(monkeypatch):
    from tools.webpage import fetch_webpage
    raw = pdf_bytes(['Synthetic PDF finding: widget costs 10 USD.', 'Limitations: one synthetic laboratory.'])
    class Response:
        status_code = 200; headers = {'content-type': 'application/pdf'}; encoding = 'utf-8'
        def raise_for_status(self): pass
        def iter_bytes(self): yield raw
    @contextmanager
    def response(*args): yield Response()
    monkeypatch.setattr('tools.webpage._public_address', lambda url: '93.184.216.34')
    monkeypatch.setattr('tools.webpage._open_stream', response)
    metadata = {}; text = fetch_webpage('https://example.invalid/paper.pdf', metadata=metadata)
    assert 'Page 1' in text and '10 USD' in text and 'Page 2' in text
    assert metadata['document_type'] == 'pdf' and metadata['page_count'] == 2


def test_pdf_fetch_rejects_oversize_downloads(monkeypatch):
    from tools.webpage import fetch_webpage
    class Response:
        status_code = 200; headers = {'content-type': 'application/pdf', 'content-length': '999999999'}; encoding = 'utf-8'
        def raise_for_status(self): pass
        def iter_bytes(self): pytest.fail('Oversize PDF should not be read')
    @contextmanager
    def response(*args): yield Response()
    monkeypatch.setattr('tools.webpage._public_address', lambda url: '93.184.216.34')
    monkeypatch.setattr('tools.webpage._open_stream', response)
    assert fetch_webpage('https://example.invalid/paper.pdf') == ''


def test_unreviewed_expansion_is_never_published():
    state = packet_state()
    class Model:
        supports_task_routing = True; max_requests = 2; requests_used = 0
        def generate_structured(self, prompt, schema, *, task):
            self.requests_used += 1
            if schema is ReportBlockReviews: raise RuntimeError('Review unavailable')
            return ReportDraft(title='Synthetic', executive_summary='', conclusion='', blocks=[ReportBlock(id='B1', section_id='analysis', text='UNSUPPORTED SECRET CONCLUSION', claim_ids=['C1'], evidence_ids=['E1'])])
    draft = Synthesizer(Model()).draft(state)
    assert not draft._approved_blocks
    report = build_structured_report(draft, state)
    assert 'UNSUPPORTED SECRET CONCLUSION' not in str(report)


def test_pdf_redirect_to_private_host_is_blocked(monkeypatch):
    from tools.webpage import fetch_webpage
    class Redirect:
        status_code = 302; headers = {'location': 'http://127.0.0.1/internal.pdf'}
    opened = []
    @contextmanager
    def response(url, *args):
        opened.append(url); yield Redirect()
    monkeypatch.setattr('tools.webpage._public_address', lambda url: None if '127.0.0.1' in url else '93.184.216.34')
    monkeypatch.setattr('tools.webpage._open_stream', response)
    assert fetch_webpage('https://example.invalid/paper.pdf') == ''
    assert opened == ['https://example.invalid/paper.pdf']


def test_offline_benchmark_exposes_prefix_loss_without_claiming_model_accuracy():
    from tools.benchmark_research_quality import benchmark
    result = benchmark()
    assert result['baseline_hits'] == 0 and result['ranked_hits'] == result['total'] == 8
    assert all(case['context_characters'] <= 5000 for case in result['cases'])
    assert 'not real-world factual accuracy' in result['kind']


def test_unassigned_valid_claims_remain_available_to_writer():
    state = packet_state()
    state.findings[0].sub_question_ids = []
    packets = evidence_packets(state)
    assert packets[-1]['question_id'] == 'main'
    assert packets[-1]['claims'][0]['id'] == 'C1'
    assert packets[-1]['evidence'][0]['id'] == 'E1'
    assert len(packet_context(state, 2500)) <= 2500
