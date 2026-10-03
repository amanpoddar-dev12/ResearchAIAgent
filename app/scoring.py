"""Explainable, deterministic confidence scoring for claims and evidence."""

from pydantic import BaseModel, Field

from app.models import Evidence, Finding, ResearchState


class ScoreBreakdown(BaseModel):
    source_quality: float = Field(ge=0, le=1)
    evidence_relevance: float = Field(ge=0, le=1)
    source_agreement: float = Field(ge=0, le=1)
    freshness: float = Field(ge=0, le=1)
    citation_validity: float = Field(ge=0, le=1)
    verification_agreement: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)
    formula: str


def score_finding(state: ResearchState, finding: Finding) -> ScoreBreakdown:
    from app.evidence import linked_evidence
    evidence = linked_evidence(state, finding)
    sources = {source.id: source for source in state.sources}
    if not evidence:
        return ScoreBreakdown(source_quality=0, evidence_relevance=0, source_agreement=0,
            freshness=0, citation_validity=0, verification_agreement=0, score=0,
            formula="No validated evidence; score = 0.")
    quality = [sources[item.source_id].quality.total for item in evidence if item.source_id in sources and sources[item.source_id].quality]
    relevance = [item.relevance_score for item in evidence]
    freshness = [item.freshness_score for item in evidence]
    support = len({sources[item.source_id].domain for item in evidence if item.relation == "supports" and item.source_id in sources})
    contradict = len({sources[item.source_id].domain for item in evidence if item.relation == "contradicts" and item.source_id in sources})
    agreement = support / max(1, support + contradict)
    validity = sum(item.source_id in sources for item in evidence) / len(evidence)
    verification = 1.0 if finding.evidence_status == "Supported" else .5 if finding.evidence_status == "Partially Supported" else 0.0
    factors = {
        "source_quality": sum(quality) / len(quality) if quality else 0,
        "evidence_relevance": sum(relevance) / len(relevance) if relevance else 0,
        "source_agreement": agreement,
        "freshness": sum(freshness) / len(freshness) if freshness else 0,
        "citation_validity": validity,
        "verification_agreement": verification,
    }
    score = sum(factors.values()) / len(factors)
    if finding.evidence_status == "Unverified":
        score = min(score, .25)
    return ScoreBreakdown(**factors, score=round(score, 4),
        formula="Average of source quality, evidence relevance, agreement by distinct domain, freshness, citation validity, and verification agreement; Unverified claims capped at 0.25. Estimate, not probability of truth.")
