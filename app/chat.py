"""Grounded, session-scoped research chat."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import invoke_structured
from app.llm.routing import CHAT_RESPONSE
from app.models import Evidence, Finding, ResearchState, Source, Verification


class ChatContext(BaseModel):
    claim_ids: list[str] = Field(default_factory=list, max_length=10)
    finding_ids: list[str] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: ChatContext = Field(default_factory=ChatContext)
    history: list[dict[str, Literal["user", "assistant"] | str]] = Field(default_factory=list, max_length=20)


class ChatCitation(BaseModel):
    citation_id: str
    source_id: str | None = None
    claim_id: str | None = None
    evidence_id: str | None = None
    title: str
    url: str | None = None
    supporting_text: str | None = None


class ChatResponse(BaseModel):
    intent: str
    answer: str
    citations: list[ChatCitation] = Field(default_factory=list)
    related_claims: list[str] = Field(default_factory=list)
    related_evidence: list[str] = Field(default_factory=list)
    related_sources: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


class ChatContextBundle(BaseModel):
    claims: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    verifications: list[Verification] = Field(default_factory=list)
    report_excerpt: str = ""


def _references(message: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"claim": set(), "finding": set(), "evidence": set(), "source": set()}
    for kind, value in re.findall(r"@(claim|finding|evidence|source):([A-Za-z0-9_.-]+)", message, re.I):
        found[kind.lower()].add(value)
    return found


def retrieve_context(state: ResearchState, request: ChatRequest) -> ChatContextBundle:
    refs = _references(request.message)
    claim_ids = set(request.context.claim_ids) | set(request.context.finding_ids) | refs["claim"] | refs["finding"]
    evidence_ids = set(request.context.evidence_ids) | refs["evidence"]
    source_ids = set(request.context.source_ids) | refs["source"]
    terms = {term.lower() for term in re.findall(r"[A-Za-z0-9]{3,}", request.message)}

    def relevant(text: str) -> bool:
        lowered = text.lower()
        return bool(terms & set(re.findall(r"[a-z0-9]{3,}", lowered)))

    claims = [item for item in state.findings if item.id in claim_ids or relevant(item.claim)][:8]
    if not claims:
        claims = state.findings[:8]
    selected_claim_ids = {item.id for item in claims}
    evidence = [item for item in state.evidence if item.id in evidence_ids or item.claim_id in selected_claim_ids or item.source_id in source_ids][:20]
    if not evidence and state.evidence:
        evidence = state.evidence[:12]
    selected_source_ids = {item.source_id for item in evidence} | source_ids | {source_id for claim in claims for source_id in claim.source_ids}
    sources = [item for item in state.sources if item.id in selected_source_ids or item.id in source_ids][:12]
    verifications = [item for item in (state.verifications if hasattr(state, "verifications") else []) if item.claim_id in selected_claim_ids]
    report_excerpt = (state.final_report or "")[:6000]
    return ChatContextBundle(claims=claims, evidence=evidence, sources=sources, verifications=verifications, report_excerpt=report_excerpt)


def validate_response(response: ChatResponse, context: ChatContextBundle) -> ChatResponse:
    claims = {item.id for item in context.claims}
    evidence = {item.id: item for item in context.evidence}
    sources = {item.id: item for item in context.sources}
    citations: list[ChatCitation] = []
    for citation in response.citations:
        if citation.claim_id and citation.claim_id not in claims:
            continue
        if citation.evidence_id and citation.evidence_id not in evidence:
            continue
        if citation.source_id and citation.source_id not in sources:
            continue
        source = sources.get(citation.source_id or (evidence.get(citation.evidence_id).source_id if citation.evidence_id in evidence else ""))
        if citation.url and source and citation.url != source.url:
            citation.url = source.url
        if not citation.url and source:
            citation.url = source.url
        citations.append(citation)
    response.citations = citations
    response.related_claims = [item for item in response.related_claims if item in claims]
    response.related_evidence = [item for item in response.related_evidence if item in evidence]
    response.related_sources = [item for item in response.related_sources if item in sources]
    if not response.citations:
        response.limitations.append("No validated citation was returned for this answer.")
    return response


def chat_prompt(message: str, context: ChatContextBundle) -> str:
    return f"""You are a grounded research assistant. Answer only from the supplied research context.
Never invent claims, evidence, sources, URLs, quotes, or numbers. If the context is insufficient, say so.
Return only JSON matching the requested schema. Use citation IDs that exist in the context.
Classify intent as one of: EXPLAIN, VERIFY, SOURCE_LOOKUP, EVIDENCE_LOOKUP, COMPARE, CONFLICT_ANALYSIS,
GAP_ANALYSIS, SIMPLIFY, SUMMARY, METHODOLOGY, NEXT_RESEARCH, REPORT_QUESTION, GENERAL_RESEARCH_CONTEXT.

User question:
{message}

Claims:
{[item.model_dump(mode="json") for item in context.claims]}

Evidence:
{[item.model_dump(mode="json") for item in context.evidence]}

Sources:
{[{key: value for key, value in item.model_dump(mode="json").items() if key != "content"} for item in context.sources]}

Verification:
{[item.model_dump(mode="json") for item in context.verifications]}

Report excerpt:
{context.report_excerpt}
"""


def answer_chat(llm, request: ChatRequest, state: ResearchState) -> ChatResponse:
    context = retrieve_context(state, request)
    response = invoke_structured(llm, chat_prompt(request.message, context), ChatResponse, task=CHAT_RESPONSE)
    return validate_response(response, context)
