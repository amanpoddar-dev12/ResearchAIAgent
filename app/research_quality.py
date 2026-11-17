"""Session-derived answer coverage and recovery diagnostics, not factuality scores."""
from __future__ import annotations

from app.models import ResearchState
from app.evidence import source_rejection
from app.source_quality import independent_source_count


def answer_checklist(state: ResearchState) -> list[dict]:
    """Only admissible verbatim evidence can contribute to an answer checklist."""
    sources = {source.id: source for source in state.sources if not source_rejection(state, source.id)}
    evidence = {item.id: item for item in state.evidence if item.source_id in sources
                and item.excerpt and item.excerpt in sources[item.source_id].content}
    tasks = [(task.id, task.question) for task in state.plan.sub_question_tasks] if state.plan else []
    if not tasks:
        tasks = [('main', state.question.refined_question or state.question.question)]
    rows = []
    for key, question in tasks:
        claims = [claim for claim in state.findings if (key == 'main' or key in claim.sub_question_ids)]
        linked_claims = [claim for claim in claims if any(eid in evidence for eid in claim.evidence_ids)]
        linked = list(dict.fromkeys(eid for claim in linked_claims for eid in claim.evidence_ids if eid in evidence))
        source_ids = list(dict.fromkeys(evidence[eid].source_id for eid in linked))
        relevant = [source for source in state.sources if key == 'main' or key in source.sub_question_ids]
        supported = [claim for claim in linked_claims if claim.evidence_status == 'Supported']
        disputed = [claim for claim in linked_claims if claim.evidence_status == 'Contradicted'
                    or any(item.relation == 'contradicts' for item in claim.evidence_assessments)
                    or any(evidence[eid].relation == 'contradicts' for eid in claim.evidence_ids if eid in evidence)]
        status = 'disputed' if disputed else 'supported findings' if supported else 'limited evidence' if linked else 'unanswered'
        causes = []
        searched = key in state.searched_sub_questions or (key == 'main' and state.searches_performed > 0)
        if not relevant:
            causes.append('No retained source addresses this question.' if searched else 'This question was not searched within the session budget.')
        elif not any(source.id in sources for source in relevant):
            causes.append('Retained sources failed provenance or relevance checks; they cannot establish this answer.')
        elif not linked:
            if all(source.retrieval_method != 'fetch' for source in relevant):
                causes.append('Only discovery snippets were retained; full-document text is unavailable in this session.')
            if not any(source.id in state.extraction_completed for source in relevant):
                causes.append('No completed extraction was recorded for these sources.')
            else:
                causes.append('Collected text did not yield admissible linked evidence for this question.')
        if linked and not supported:
            causes.append('Linked evidence does not establish a fully supported answer.')
        if disputed:
            causes.append('Conflicting evidence remains; no resolution is assumed.')
        if linked and independent_source_count([sources[sid] for sid in source_ids]) < 2:
            causes.append('Independent corroboration has not been established; source-origin grouping is heuristic.')
        rows.append({'id': key, 'question': question, 'status': status, 'claim_ids': [claim.id for claim in linked_claims],
                     'supported_claim_ids': [claim.id for claim in supported], 'evidence_ids': linked,
                     'source_ids': source_ids, 'causes': causes,
                     'next_step': 'Seek matched primary evidence and methods for: ' + question})
    return rows


def research_diagnosis(state: ResearchState) -> dict:
    rows = answer_checklist(state)
    actions = [entry.action for entry in state.audit_log]
    return {'questions': rows, 'unanswered': sum(row['status'] == 'unanswered' for row in rows),
            'disputed': sum(row['status'] == 'disputed' for row in rows),
            'search_failures': actions.count('search_failed'),
            'analysis_unavailable': actions.count('analysis_failed') + actions.count('verification_unavailable'),
            'rejected_evidence_or_citations': len(state.citation_rejections),
            'reviewed_blocks': len(state.report_blocks),
            'stopping_reasons': list(dict.fromkeys(item.reason for item in state.stop_decisions if item.stop)),
            'interpretation': 'Session diagnostics only; supported findings do not establish a complete answer or factual accuracy.'}


def report_usefulness(state: ResearchState) -> dict:
    """A reproducible structural rubric; human review still judges explanations and entailment."""
    rows = answer_checklist(state)
    explained = {cid for block in state.report_blocks if block.kind == 'interpretation' and block.limitations for cid in block.claim_ids}
    missing_explanations = [claim.id for claim in state.findings if claim.evidence_status == 'Supported' and claim.id not in explained]
    sections = {section.id: section.content for section in state.structured_report.sections} if state.structured_report else {}
    checks = {'answer_checklist_present': 'Answer checklist' in sections.get('executive-summary', ''),
              'missing_evidence_explained': not any(row['status'] == 'unanswered' for row in rows) or 'Why the answer is limited' in sections.get('executive-summary', ''),
              'next_steps_present': 'Next research questions' in sections.get('conclusion', ''),
              'reviewed_explanations_for_supported_claims': not missing_explanations}
    return {'checks': checks, 'claims_without_reviewed_interpretation': missing_explanations,
            'unanswered_question_ids': [row['id'] for row in rows if row['status'] == 'unanswered'],
            'human_review_required': ['Exact-question relevance and completeness', 'Citation entailment and methodological quality',
                                      'Explanation usefulness', 'Measurement comparability', 'Repetition and actionable conclusions'],
            'interpretation': 'Structural checks, not a correctness score; an absent interpretation may be appropriate when evidence is insufficient.'}


def recovery_queries(state: ResearchState, task) -> list[str]:
    """Choose bounded search variants by the observed gap; never relax user filters."""
    row = next((row for row in answer_checklist(state) if row['id'] == task.id), None)
    if row and row['status'] == 'disputed':
        suffixes = ['conflicting results methods population definitions', 'original study replication limitations', 'primary source evidence']
    elif row and not row['evidence_ids']:
        suffixes = ['full text original study methods', 'official documentation report', 'alternative terminology review evidence']
    else:
        suffixes = ['independent replication evidence', 'primary source methods limitations', 'official dataset measurement definitions']
    return [task.query, *(task.query + ' ' + suffix for suffix in suffixes)]
