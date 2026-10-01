"""Typed data contracts used throughout the research pipeline."""

from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, computed_field, field_validator, model_validator
from app.modes import ModeName, SourceType


Category = Literal["fact", "statistic", "quote", "event", "comparison", "analysis", "inference"]


class SourceFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    source_types: list[SourceType] = Field(default_factory=list)
    prefer_primary: bool = False

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def domains(cls, domains: list[str]) -> list[str]:
        import re
        normalized = [domain.strip().lower().removeprefix("www.").rstrip(".") for domain in domains if domain.strip()]
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or ".." in domain for domain in normalized):
            raise ValueError("Use domain names only, without URLs or paths")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Start date must be on or before end date")
        return self


class SourceQuality(BaseModel):
    relevance: float = Field(ge=0, le=1)
    authority: float = Field(ge=0, le=1)
    freshness: float = Field(ge=0, le=1)
    source_type: float = Field(ge=0, le=1)
    evidence_strength: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)
    notes: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    id: str
    source_id: str
    excerpt: str
    relation: Literal["supports", "contradicts", "context"] = "context"
    strength: Literal["direct", "partial"] = "partial"


class CitationRejection(BaseModel):
    claim_id: str
    source_id: str | None = None
    evidence_id: str | None = None
    reason: str


EvidenceStatus = Literal["Supported", "Partially Supported", "Contradicted", "Unverified"]


class BudgetOverrides(BaseModel):
    max_searches: int | None = Field(default=None, ge=1, le=100)
    max_sources: int | None = Field(default=None, ge=1, le=100)
    max_iterations: int | None = Field(default=None, ge=1, le=20)
    max_parallel_tasks: int | None = Field(default=None, ge=1, le=8)
    max_wall_seconds: float | None = Field(default=None, gt=0, le=3600)


class AuditEntry(BaseModel):
    id: int
    timestamp: str
    action: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SubQuestion(BaseModel):
    id: str
    question: str
    query: str
    depends_on: list[str] = Field(default_factory=list)


class StopDecision(BaseModel):
    stop: bool
    reason: str
    coverage: float
    unresolved: list[str] = Field(default_factory=list)


class ResearchQuestion(BaseModel):
    question: str = Field(min_length=3)
    audience: str | None = None
    desired_depth: str | None = None
    output_format: str | None = None
    mode: ModeName = "standard"
    target_claims: list[str] = Field(default_factory=list)
    comparison_items: list[str] = Field(default_factory=list)
    refined_question: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    objective: str
    sub_questions: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    research_areas: list[str] = Field(default_factory=list)
    sub_question_tasks: list[SubQuestion] = Field(default_factory=list)


class SearchResult(BaseModel):
    title: str
    url: str
    content: str = ""
    score: float | None = None
    published_date: str | None = None
    source_domain: str


class Source(BaseModel):
    id: str
    title: str
    url: str
    domain: str
    content: str
    publication_date: str | None = None
    source_type: str | None = None
    search_query: str | None = None
    credibility_notes: str | None = None
    quality: SourceQuality | None = None
    sub_question_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    retrieved_at: str | None = None
    retrieval_method: Literal["search", "fetch"] | None = None
    model_config = ConfigDict(validate_assignment=True)


class Finding(BaseModel):
    claim: str
    explanation: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    category: Category
    id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_status: EvidenceStatus = "Unverified"
    comparison_item: str | None = None
    comparison_criterion: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    sub_question_ids: list[str] = Field(default_factory=list)
    dependency_rejected: bool = False


class ClaimExtraction(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class Conflict(BaseModel):
    topic: str
    claim_a: str
    claim_b: str
    source_a: list[str] = Field(default_factory=list)
    source_b: list[str] = Field(default_factory=list)
    explanation: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchState(BaseModel):
    question: ResearchQuestion
    plan: ResearchPlan | None = None
    searches_performed: int = 0
    sources: list[Source] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    iteration: int = 0
    status: str = "created"
    final_report: str | None = None
    llm_requests_used: int = 0
    max_llm_requests: int = 10
    max_searches: int = 10
    max_sources: int = 15
    max_iterations: int = 5
    llm_provider: str = "gemini"
    llm_model: str = ""
    mode: ModeName = "standard"
    filters: SourceFilters = Field(default_factory=SourceFilters)
    evidence: list[Evidence] = Field(default_factory=list)
    citation_rejections: list[CitationRejection] = Field(default_factory=list)
    filtered_sources: list[dict[str, str]] = Field(default_factory=list)
    max_parallel_tasks: int = 3
    max_wall_seconds: float = 180
    budget_overrides: BudgetOverrides = Field(default_factory=BudgetOverrides)
    elapsed_seconds: float = 0
    audit_log: list[AuditEntry] = Field(default_factory=list)
    merge_records: list[dict[str, str]] = Field(default_factory=list)
    stop_decisions: list[StopDecision] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    evidence_gains: list[int] = Field(default_factory=list)
    searched_sub_questions: list[str] = Field(default_factory=list)
    retrieved_urls: list[str] = Field(default_factory=list)
    provenance_required: bool = False  # Legacy deserialized sessions predate retrieval provenance.
    explicit_sub_question_links: bool = False

    @computed_field
    @property
    def graph(self) -> dict[str, list[dict[str, Any]]]:
        from app.graph import derive_graph
        return derive_graph(self)


class GapAssessment(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list)


class ConflictAssessment(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)


class ReportDraft(BaseModel):
    title: str
    executive_summary: str
    key_findings: list[str] = Field(default_factory=list)
    detailed_analysis: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    conclusion: str
