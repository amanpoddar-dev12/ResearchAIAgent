"""Bounded hybrid context, saved-session input, and streamed citation validation."""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from app.chat import ChatCitation, ChatRequest, ChatResponse
from app.pdf_documents import PDFContext
from app.models import ResearchState, Source
from app.rag import SessionIndex


class AssistantRequest(ChatRequest):
    # Browser-saved sessions can be used after the process-local job expires.
    # Existing live jobs always take precedence over this untrusted snapshot.
    saved_state: dict[str, Any] | None = Field(default=None, max_length=100)
    pdf_context: PDFContext | None = None


def restore_saved_state(request: AssistantRequest) -> ResearchState | None:
    saved = request.saved_state
    if not saved:
        return None
    if len(json.dumps(saved).encode("utf-8")) > 4_000_000 or not saved.get("final_report"):
        raise ValueError("The saved research snapshot is missing its report or exceeds the size limit")
    snapshot = {**saved, "sources": [{**source, "content": source.get("content", "")} for source in saved.get("sources", [])]}
    return ResearchState.model_validate(snapshot)


@dataclass
class AssistantContext:
    text: str
    sources: dict[str, Source]
    full: bool


def _tokens(text: str) -> list[str]:
    stop = {"the", "a", "an", "and", "is", "of", "in", "on", "to", "what", "were", "this", "that", "about", "please"}
    return [word for word in re.findall(r"\w+", text.lower()) if len(word) > 1 and word not in stop]


def build_context(state: ResearchState, question: str, history: list[dict],
                  input_token_limit: int = 32768, index: SessionIndex | None = None) -> AssistantContext:
    index = index or SessionIndex()
    index.update("research_snapshot", state)
    documents = list(index.documents.values())
    if state.structured_report:
        for kind, items in [("chart", state.structured_report.charts), ("table", state.structured_report.tables)]:
            for item in items:
                documents.append({"id": f"{kind}:{item.id}", "text": item.model_dump_json(),
                                  "metadata": {"type": kind, "sourceIds": item.source_ids}})
    documents.append({"id": "insights", "text": json.dumps({
        "gaps": state.gaps, "research_gaps": [item.model_dump() for item in state.research_gaps],
        "conflicts": [item.model_dump() for item in state.conflicts], "unresolved_questions": state.unresolved_questions,
        "completion_quality": state.completion_quality, "stop_decisions": [item.model_dump() for item in state.stop_decisions]}, ensure_ascii=False),
        "metadata": {"type": "insight"}})
    scope = {"query": state.question.question, "mode": state.mode}
    source_catalog = [{"id": source.id, "title": source.title, "url": source.url,
                       "quality": source.quality_score} for source in state.sources]

    def selected_sources(items: list[dict]) -> set[str]:
        identifiers = set()
        for document in items:
            metadata = document["metadata"]
            if metadata.get("sourceId"):
                identifiers.add(metadata["sourceId"])
            identifiers.update(metadata.get("sourceIds", []))
            claim = next((item for item in state.findings if item.id == metadata.get("claimId")), None)
            if claim:
                identifiers.update(claim.source_ids)
            identifiers.update(item.source_id for item in state.evidence if item.id in metadata.get("evidenceIds", []))
            identifiers.update(source.id for source in state.sources if source.url in document["text"] or f"[{source.id}]" in document["text"])
        return identifiers

    def serialize(items: list[dict], *, full: bool = False) -> str:
        included = source_catalog if full else [source for source in source_catalog if source["id"] in selected_sources(items)]
        return json.dumps({"research_scope": scope, "sources": included, "documents": items}, ensure_ascii=False)

    # UTF-8 bytes give a conservative upper bound without adding a tokenizer.
    # Keep substantial room for history, instructions, output and provider overhead.
    history_bytes = len(json.dumps(history, ensure_ascii=False).encode("utf-8"))
    budget = max(8000, min(262144, input_token_limit // 3) - history_bytes - 6000)
    full = serialize(documents, full=True)
    if len(full.encode("utf-8")) <= budget:
        return AssistantContext(full, {source.id: source for source in state.sources}, True)

    chunks = []
    for document in documents:
        text = document["text"]
        for start in range(0, len(text), 1440):
            chunks.append({**document, "text": text[start:start + 1600]})
    query = question + " " + " ".join(str(item.get("content", "")) for item in history[-4:])
    terms = set(_tokens(query))
    frequencies = [Counter(_tokens(chunk["text"] + " " + str(chunk["metadata"].get("title", "")) + " " +
        str(chunk["metadata"].get("type", "")) + " " + str(chunk["metadata"].get("sourceId", "")))) for chunk in chunks]
    df = Counter(term for frequency in frequencies for term in frequency)
    average = sum(sum(frequency.values()) for frequency in frequencies) / max(1, len(chunks)) or 1
    ranked = []
    ordinal = re.search(r"\b(first|second|third|fourth)\s+source\b", question, re.I)
    target_source = None
    if ordinal:
        position = ["first", "second", "third", "fourth"].index(ordinal[1].lower())
        target_source = state.sources[position].id if position < len(state.sources) else None
    for chunk, frequency in zip(chunks, frequencies):
        length = sum(frequency.values())
        score = sum(math.log(1 + (len(chunks) - df[term] + 0.5) / (df[term] + 0.5)) * frequency[term] * 2.2 /
                    (frequency[term] + 1.2 * (0.25 + 0.75 * length / average)) for term in terms if frequency[term])
        metadata = chunk["metadata"]
        if target_source and metadata.get("sourceId") == target_source:
            score += 8
        score *= 1 + 0.3 * (metadata.get("qualityScore") or 0) + (0.25 if metadata.get("evidenceStatus") == "Supported" else 0)
        if not score and re.search(r"main findings|summari[sz]e|summary|research", question, re.I):
            score = 0.1 if metadata.get("type") in {"report", "claim", "evidence", "insight"} else 0
        ranked.append((score, chunk))
    selected = []
    document_counts = Counter()
    for score, chunk in sorted(ranked, key=lambda item: item[0], reverse=True):
        if score <= 0 or len(selected) >= 8:
            break
        if document_counts[chunk["id"]] >= 2:
            continue
        if len(serialize([*selected, chunk]).encode("utf-8")) <= budget:
            selected.append(chunk)
            document_counts[chunk["id"]] += 1
    identifiers = selected_sources(selected)
    selected_text = {}
    for chunk in selected:
        source_id = chunk['metadata'].get('sourceId')
        if source_id:
            selected_text.setdefault(source_id, []).append(chunk['text'])
    return AssistantContext(serialize(selected), {source.id: source.model_copy(update={'content': '\n\n'.join(selected_text.get(source.id, []))}) for source in state.sources if source.id in identifiers}, False)


class HybridAnswer:
    """Publish text incrementally, holding incomplete tags/citations until validated."""

    def __init__(self, context: AssistantContext):
        self.context = context
        self.tag: str | None = None
        self.answer = ""
        self.pending = ""
        self.raw_body = ""
        self.references: dict[str, ChatCitation] = {}
        self.invalid_citations = False

    def feed(self, text: str, *, final: bool = False) -> str:
        self.pending += text
        prefix = ""
        if self.tag is None:
            if "\n" not in self.pending:
                if final or len(self.pending) > 100:
                    raise ValueError("The assistant response did not contain a valid origin tag")
                return ""
            line, self.pending = self.pending.split("\n", 1)
            if line.strip() not in {"[From research]", "[General knowledge]", "[Mixed]"}:
                raise ValueError("The assistant response did not contain a valid origin tag")
            self.tag = line.strip()[1:-1]
            prefix = f"[{self.tag}]\n"
            self.answer = prefix
            self.raw_body = self.pending
        else:
            self.raw_body += text
        cut = len(self.pending)
        opening = self.pending.rfind("[")
        if not final and opening >= 0 and "]" not in self.pending[opening:]:
            cut = opening
        raw, self.pending = self.pending[:cut], self.pending[cut:]
        if final and re.search(r"\[[SP][^\]\n]*$", raw):
            raw = re.sub(r"\[[SP][^\]\n]*$", "[uncertain]", raw)
            self.invalid_citations = True
        offset = len(self.raw_body) - len(raw) - len(self.pending)
        general = re.search(r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:General knowledge|\[General knowledge\])(?:\*\*)?\s*:?", self.raw_body)

        def citation(match: re.Match) -> str:
            source_id = match.group()[1:-1]
            if self.tag == "General knowledge" or source_id not in self.context.sources or (general and match.start() + offset >= general.start()):
                self.invalid_citations = True
                return "[uncertain]"
            source = self.context.sources[source_id]
            self.references[source_id] = ChatCitation(citation_id=source_id, source_id=source_id, title=source.title, url=source.url or None, supporting_text=source.content[:2000] if source_id.startswith("P") or not source.url else None)
            return match.group()

        safe = re.sub(r"\[[SP][A-Za-z0-9_.-]*\]", citation, raw)
        for tag in ["From research", "General knowledge", "Mixed"]:
            safe = safe.replace(f"[{tag}]", "General knowledge:" if tag == "General knowledge" else "")
        self.answer += safe
        return prefix + safe

    def response(self) -> ChatResponse:
        if not self.tag or not self.answer.split("\n", 1)[-1].strip():
            raise ValueError("The assistant returned no answer text")
        return ChatResponse(intent=self.tag, answer=self.answer.strip(), citations=list(self.references.values()),
            related_sources=list(self.references), limitations=["An unsupported research citation was replaced with [uncertain]."] if self.invalid_citations else [])
