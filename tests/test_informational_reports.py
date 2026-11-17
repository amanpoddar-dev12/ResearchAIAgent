"""General information is useful without masquerading as sourced verification."""
import pytest
from app.models import ReportDraft, ResearchQuestion, ResearchState
from app.synthesizer import Synthesizer, build_structured_report


class Model:
    def __init__(self, mode): self.mode = mode
    def generate_structured(self, prompt, schema, **kwargs):
        assert ('INFORMATIONAL EXCEPTION' in prompt) == (self.mode != 'fact_check')
        return ReportDraft(title='Synthetic', executive_summary='', conclusion='', background_review=
            'An API is an interface through which software components communicate. [S1]\n\nFor example, an application may request data through an API. [Details](https://unverified.invalid)')


@pytest.mark.parametrize('mode', ['quick', 'deep', 'technical', 'academic', 'compare', 'standard'])
def test_informational_reports_explain_topic_without_supported_claims(mode):
    state = ResearchState(question=ResearchQuestion(question='Explain what an API is'), mode=mode)
    draft = Synthesizer(Model(mode)).draft(state)
    report = build_structured_report(draft, state)
    sections = {section.id: section.content for section in report.sections}
    assert sections['executive-summary'].startswith('### General knowledge')
    assert 'An API is an interface' in sections['executive-summary']
    background = sections['background'].split('### Retrieved source material')[0]
    assert '[S1]' not in background and 'https://' not in background
    assert 'not verified' in background and 'may contain errors' in background
    assert not state.findings and not state.report_blocks
    assert not state.citation_rejections


def test_fact_check_keeps_strict_verification_and_does_not_publish_general_fallback():
    state = ResearchState(question=ResearchQuestion(question='Check a synthetic claim'), mode='fact_check')
    report = build_structured_report(Synthesizer(Model('fact_check')).draft(state), state)
    assert 'An API is an interface' not in str(report)
    assert 'General knowledge' not in str(report)


def test_imported_unreviewed_prose_does_not_receive_general_knowledge_opt_in():
    state = ResearchState(question=ResearchQuestion(question='Synthetic topic'))
    draft = ReportDraft(title='Imported', executive_summary='', conclusion='', background_review='UNSUPPORTED IMPORTED ASSERTION')
    report = build_structured_report(draft, state)
    assert 'UNSUPPORTED IMPORTED ASSERTION' not in str(report)
    assert '_general_background' not in draft.model_dump()
    assert '_general_background' not in ReportDraft.model_json_schema()['properties']


def test_unavailable_model_does_not_invent_an_informational_fallback():
    class Unavailable:
        def generate_structured(self, *args, **kwargs): raise RuntimeError('Synthetic budget exhaustion')
    state = ResearchState(question=ResearchQuestion(question='Synthetic topic'))
    draft = Synthesizer(Unavailable()).draft(state)
    assert not draft._general_background
    assert 'General knowledge' not in str(build_structured_report(draft, state))
