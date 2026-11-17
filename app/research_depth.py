"""Bounded document retrieval and evidence packets; no extra model calls or storage."""
import json
import math
import re
from collections import Counter
from app.source_quality import independent_source_count

STOP = {'the', 'a', 'an', 'of', 'and', 'or', 'to', 'in', 'on', 'for', 'is', 'are', 'what', 'how', 'does', 'about', 'research', 'evidence'}

def tokens(text):
    return [word for word in re.findall(r"[\w-]+", text.casefold()) if len(word) > 2 and word not in STOP]

def document_chunks(text: str, size: int = 1800, overlap: int = 180) -> list[str]:
    """Return exact source spans so quotations remain independently checkable."""
    if size < 200 or overlap < 0 or overlap >= size:
        raise ValueError('Invalid chunk bounds')
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(' ', start + size // 2, end)
            if boundary > start: end = boundary
        chunks.append(text[start:end])
        if end == len(text): break
        start = max(start + 1, end - overlap)
    return chunks

def select_passages(text: str, question: str, limit: int = 10000, *, numerical: bool = False) -> str:
    if len(text) <= limit: return text
    chunks = document_chunks(text)
    counts = [Counter(tokens(chunk)) for chunk in chunks]
    terms = set(tokens(question))
    df = {term: sum(term in count for count in counts) for term in terms}
    average = sum(sum(count.values()) for count in counts) / max(1, len(counts))
    scores = []
    for index, (chunk, count) in enumerate(zip(chunks, counts)):
        length = sum(count.values())
        score = sum(math.log(1 + (len(chunks)-df[term]+.5)/(df[term]+.5)) * count[term]*2.2 /
                    (count[term]+1.2*(.25+.75*length/max(1,average))) for term in terms if count[term])
        if re.search(r'\b(methods?|limitations?|sample|participants|confidence interval)\b', chunk, re.I): score += .25
        if numerical and score > 0 and re.search(r'\d+(?:\.\d+)?\s*(?:%|percent|USD|million|billion|participants|samples)', chunk, re.I): score += 1
        scores.append((score, index))
    selected, used = [], 0
    for score, index in sorted(scores, key=lambda row: (-row[0], row[1])):
        # Preserve a document introduction, but spend most context on relevant passages.
        if score <= 0 and selected: continue
        if used + len(chunks[index]) + 2 > limit: continue
        selected.append(index); used += len(chunks[index]) + 2
    if not selected: return text[:limit]
    return '\n\n'.join(chunks[index] for index in sorted(selected))

def evidence_packets(state) -> list[dict]:
    from app.evidence import source_rejection
    sources = {source.id: source for source in state.sources if not source_rejection(state, source.id)}
    evidence = {item.id: item for item in state.evidence if item.source_id in sources and item.excerpt and item.excerpt in sources[item.source_id].content}
    tasks = state.plan.sub_question_tasks if state.plan else []
    packets = []
    task_ids = {task.id for task in tasks}
    include_unassigned = any(not task_ids.intersection(claim.sub_question_ids) for claim in state.findings)
    for task in list(tasks) + ([None] if include_unassigned or not tasks else []):
        claims = [claim for claim in state.findings if (not task_ids.intersection(claim.sub_question_ids) if task is None else task.id in claim.sub_question_ids)]
        linked = list(dict.fromkeys(key for claim in claims for key in claim.evidence_ids if key in evidence))
        ids = list(dict.fromkeys(evidence[key].source_id for key in linked))
        packets.append({'question_id': task.id if task else 'main', 'question': task.question if task else state.question.question,
            'claims': [{**{key: getattr(claim, key) for key in ('id', 'claim', 'evidence_ids', 'evidence_status', 'importance')}, 'assessments': [item.model_dump() for item in claim.evidence_assessments]} for claim in sorted(claims, key=lambda claim: {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}[claim.importance])],
            'evidence': [{field: getattr(evidence[key], field) for field in ('id', 'source_id', 'excerpt', 'relation', 'strength')} for key in linked],
            'sources': [{'id': sid, 'title': sources[sid].title, 'url': sources[sid].url,
                'retrieval': sources[sid].retrieval_method, 'publication_date': sources[sid].publication_date,
                'reporting_signals': [label for label, pattern in [('methods', r'\bmethods?\b'), ('limitations', r'\blimitations?\b'), ('sample', r'\b(?:samples?|participants)\b')] if re.search(pattern, sources[sid].content, re.I)]} for sid in ids],
            'independent_origin_groups': independent_source_count([sources[sid] for sid in ids]),
            'measurements': [point.model_dump() for point in state.data_points if point.source_id in ids],
            'missing': [] if linked else ['No validated evidence addresses this question.']})
    return packets

def quality_diagnostics(state) -> dict:
    return {'sources': len(state.sources), 'full_text_sources': sum(source.retrieval_method == 'fetch' for source in state.sources),
        'snippet_only_sources': sum(source.retrieval_method != 'fetch' for source in state.sources),
        'extracted_sources': len(set(state.extraction_completed)), 'claims': len(state.findings),
        'supported_claims': sum(claim.evidence_status == 'Supported' for claim in state.findings),
        'verbatim_evidence': sum(bool(item.excerpt and any(source.id == item.source_id and item.excerpt in source.content for source in state.sources)) for item in state.evidence),
        'reviewed_report_blocks': len(state.report_blocks), 'unanswered_questions': len(state.unresolved_questions),
        'stop_reasons': [item.reason for item in state.stop_decisions if item.stop]}


def packet_context(state, max_chars: int = 60000) -> str:
    """Bound prompt size without cutting JSON or changing stored evidence."""
    packets = evidence_packets(state)
    used, selected = 2, []
    for position, packet in enumerate(packets):
        allocation = (max_chars - used - 2 * (len(packets) - position)) // max(1, len(packets) - position)
        packet = {**packet, 'claims': packet['claims'][:8], 'measurements': packet['measurements'][:12]}
        available = {item['id'] for item in packet['evidence']}
        representatives = list(dict.fromkeys(next((eid for eid in claim['evidence_ids'] if eid in available), '') for claim in packet['claims']))
        linked = {eid for claim in packet['claims'] for eid in claim['evidence_ids']}
        packet['evidence'] = sorted(packet['evidence'], key=lambda item: (item['id'] not in representatives, item['id'] not in linked))[:16]
        text = json.dumps(packet, ensure_ascii=False, default=str)
        while len(text) > allocation and packet['claims']:
            packet['claims'] = packet['claims'][:-1]
            retained = {key for claim in packet['claims'] for key in claim['evidence_ids']}
            packet['evidence'] = [item for item in packet['evidence'] if item['id'] in retained]
            source_ids = {item['source_id'] for item in packet['evidence']}
            packet['sources'] = [source for source in packet['sources'] if source['id'] in source_ids]
            packet['measurements'] = [point for point in packet['measurements'] if point['source_id'] in source_ids]
            packet['independent_origin_groups'] = independent_source_count([source for source in state.sources if source.id in source_ids])
            packet['missing'] = ['Some evidence was omitted to respect writing context limits; omitted evidence must not be inferred.']
            text = json.dumps(packet, ensure_ascii=False, default=str)
        if used + len(text) > max_chars: break
        selected.append(packet); used += len(text) + 2
    return json.dumps(selected, ensure_ascii=False, default=str)


def prioritize_gaps(state, gaps):
    """Prioritize missing coverage, high-impact contradictions, then corroboration."""
    def priority(entry):
        query, reason, ids = entry
        linked = [claim for claim in state.findings if any(qid in claim.sub_question_ids for qid in ids)]
        importance = max(({'low': 0, 'medium': 1, 'high': 2, 'critical': 3}[claim.importance] for claim in linked), default=1)
        missing = 'no verified evidence' in reason
        disputed = any(claim.evidence_status in {'Contradicted', 'Partially Supported'} for claim in linked)
        primary = 'primary source' in reason
        return (not missing, not disputed, -importance, not primary)
    return sorted(gaps, key=priority)
