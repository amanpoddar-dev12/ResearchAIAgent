"""Typed data contracts used throughout the research pipeline."""

from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, PrivateAttr, computed_field, field_validator, model_validator
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
    claim_id: str | None = None
    relation: Literal["supports", "contradicts", "context"] = "context"
    strength: Literal["direct", "partial"] = "partial"
    evidence_type: Literal["direct", "indirect", "supporting", "contradicting", "contextual"] = "contextual"
    relevance_score: float = Field(default=0, ge=0, le=1)
    strength_score: float = Field(default=0, ge=0, le=1)
    freshness_score: float = Field(default=0, ge=0, le=1)
    supports_claim: bool | None = None
    reasoning: str = ""
    source_location: str | None = None

    @property
    def quote(self) -> str:
        return self.excerpt


class EvidenceAssessment(BaseModel):
    claim_id: str
    evidence_id: str
    relation: Literal["supports", "contradicts", "context"]
    strength: Literal["direct", "partial"] = "partial"
    reasoning: str = ""


class EvidenceAssessmentBatch(BaseModel):
    assessments: list[EvidenceAssessment] = Field(default_factory=list)


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
    _discovery_relevance: float | None = PrivateAttr(default=None)
    id: str
    title: str
    url: str
    domain: str
    content: str
    summary: str = ""
    discovery_snippet: str = ""
    original_url: str | None = None
    primary_basis: str | None = None
    reference_urls: list[str] = Field(default_factory=list)
    publication_date: str | None = None
    source_type: str | None = None
    search_query: str | None = None
    credibility_notes: str | None = None
    quality: SourceQuality | None = None
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    authority_score: float | None = Field(default=None, ge=0, le=1)
    freshness_score: float | None = Field(default=None, ge=0, le=1)
    quality_score_value: float | None = Field(default=None, ge=0, le=1)
    sub_question_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    retrieved_at: str | None = None
    retrieval_method: Literal["search", "fetch"] | None = None
    model_config = ConfigDict(validate_assignment=True)

    @property
    def published_date(self) -> str | None:
        return self.publication_date

    @property
    def quality_score(self) -> float | None:
        return self.quality_score_value if self.quality_score_value is not None else self.quality.total if self.quality else None

    @property
    def quality_notes(self) -> list[str]:
        return self.quality.notes if self.quality else []


class Finding(BaseModel):
    claim: str
    explanation: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    category: Category
    id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_status: EvidenceStatus = "Unverified"
    importance: Literal["low", "medium", "high", "critical"] = "medium"
    relevance: float = Field(default=0, ge=0, le=1)
    confidence_score: float = Field(default=0, ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    score_source_quality: float = Field(default=0, ge=0, le=1)
    score_evidence_relevance: float = Field(default=0, ge=0, le=1)
    score_source_agreement: float = Field(default=0, ge=0, le=1)
    score_freshness: float = Field(default=0, ge=0, le=1)
    score_citation_validity: float = Field(default=0, ge=0, le=1)
    score_verification_agreement: float = Field(default=0, ge=0, le=1)
    score_formula: str = ""
    comparison_item: str | None = None
    comparison_criterion: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    sub_question_ids: list[str] = Field(default_factory=list)
    dependency_rejected: bool = False
    evidence_assessments: list[EvidenceAssessment] = Field(default_factory=list)


class Verification(BaseModel):
    claim_id: str
    status: EvidenceStatus
    supporting_count: int = Field(default=0, ge=0)
    contradicting_count: int = Field(default=0, ge=0)
    verified_by: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence_score: float = Field(default=0, ge=0, le=1)
    independent_review: str | None = None


class ClaimExtraction(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    data_points: list["DataPoint"] = Field(default_factory=list)
    processed_source_ids: list[str] = Field(default_factory=list)


class DataPoint(BaseModel):
    id: str = ""
    source_id: str
    label: str
    value: float
    unit: str = ""
    observation: str
    quote: str
    estimated: bool = False


class DataPointExtraction(BaseModel):
    data_points: list[DataPoint] = Field(default_factory=list)


class Conflict(BaseModel):
    topic: str
    claim_a: str
    claim_b: str
    source_a: list[str] = Field(default_factory=list)
    source_b: list[str] = Field(default_factory=list)
    explanation: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    severity: Literal["minor", "major"] = "major"
    resolution: Literal["resolved", "unresolved"] = "unresolved"
    resolution_basis: str | None = None
    methodology_differences: list[str] = Field(default_factory=list)
    publication_dates: list[str] = Field(default_factory=list)


class ResearchGap(BaseModel):
    gap_id: str
    description: str
    importance: Literal["low", "medium", "high"] = "medium"
    reason: str
    recommended_search: str


class ReportSection(BaseModel):
    id: str
    title: str
    content: str = ""


class ReportBlock(BaseModel):
    id: str
    section_id: str
    kind: Literal["observation", "comparison", "interpretation"] = "observation"
    text: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: str = ""


class ReportBlockReview(BaseModel):
    block_id: str
    supported: bool = False
    reason: str = ""


class ReportBlockReviews(BaseModel):
    reviews: list[ReportBlockReview] = Field(default_factory=list)


class ChartSeries(BaseModel):
    key: str
    label: str
    color: str | None = None


class VisualProvenance(BaseModel):
    """Verbatim support for one displayed row/cell, checked before publication."""

    row: int = Field(ge=0)
    key: str
    evidence_id: str
    quote: str
    estimated: bool = False


class ChartSpec(BaseModel):
    id: str
    type: Literal["line", "bar", "area", "pie", "scatter"]
    title: str
    caption: str
    x_key: str = "name"
    series: list[ChartSeries] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    section_id: str = "analysis"
    provenance: list[VisualProvenance] = Field(default_factory=list)
    origin: Literal["retrieved", "session"] = "retrieved"


class TableSpec(BaseModel):
    id: str
    title: str
    caption: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    section_id: str = "analysis"
    provenance: list[VisualProvenance] = Field(default_factory=list)
    origin: Literal["retrieved", "session"] = "retrieved"


class StructuredReport(BaseModel):
    title: str = ""
    sections: list[ReportSection] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    tables: list[TableSpec] = Field(default_factory=list)


class ResearchState(BaseModel):
    brief: dict[str, str] = Field(default_factory=dict)
    parent_research_id: str | None = None
    version_changes: list[str] = Field(default_factory=list)
    question: ResearchQuestion
    plan: ResearchPlan | None = None
    searches_performed: int = 0
    sources: list[Source] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    research_gaps: list[ResearchGap] = Field(default_factory=list)
    iteration: int = 0
    status: str = "created"
    final_report: str | None = None
    structured_report: StructuredReport | None = None
    llm_requests_used: int = 0
    max_llm_requests: int = 24
    max_searches: int = 10
    max_sources: int = 15
    max_iterations: int = 5
    llm_provider: str = "gemini"
    llm_model: str = ""
    mode: ModeName = "standard"
    filters: SourceFilters = Field(default_factory=SourceFilters)
    evidence: list[Evidence] = Field(default_factory=list)
    data_points: list[DataPoint] = Field(default_factory=list)
    verifications: list[Verification] = Field(default_factory=list)
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
    semantic_validation_required: bool = False
    searched_queries: list[str] = Field(default_factory=list)
    extraction_completed: list[str] = Field(default_factory=list)
    report_blocks: list[ReportBlock] = Field(default_factory=list)
    llm_usage: dict[str, Any] = Field(default_factory=dict)
    relevance_threshold: float = .3
    completion_quality: Literal["complete", "partial"] = "partial"

    @computed_field
    @property
    def graph(self) -> dict[str, list[dict[str, Any]]]:
        from app.graph import derive_graph
        return derive_graph(self)


class GapAssessment(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list)
    targeted_queries: list["GapQuery"] = Field(default_factory=list)


class GapQuery(BaseModel):
    query: str
    sub_question_ids: list[str] = Field(default_factory=list)
    reason: str
    priority: Literal["high", "medium", "low"] = "medium"


class QuestionAnalysis(BaseModel):
    refined_question: str
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class SourceSummary(BaseModel):
    source_id: str
    summary: str
    rationale: str = ""


class Claim(BaseModel):
    id: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["supported", "partially_supported", "unsupported", "contradicted", "unverified"]
    confidence: float = Field(ge=0, le=1)


class VerificationResult(BaseModel):
    claim_id: str
    verdict: Literal["confirmed", "weakened", "refuted", "insufficient_evidence"]
    reasoning_summary: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class VerificationBatch(BaseModel):
    results: list[VerificationResult] = Field(default_factory=list)


class ReviewItem(BaseModel):
    claim_id: str
    issues: list[str] = Field(default_factory=list)
    reasoning: str = ""


class ReviewBatch(BaseModel):
    reviews: list[ReviewItem] = Field(default_factory=list)


class ConflictRecord(BaseModel):
    id: str
    claim_ids: list[str] = Field(min_length=1)
    description: str
    severity: Literal["minor", "major"]
    resolution: Literal["resolved", "unresolved"]
    resolution_basis: str | None = None


class ConflictAssessment(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)


class ReportDraft(BaseModel):
    _approved_blocks: set[str] = PrivateAttr(default_factory=set)
    _general_background: str = PrivateAttr(default="")
    title: str
    executive_summary: str
    key_findings: list[str] = Field(default_factory=list)
    detailed_analysis: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    conclusion: str
    abstract: str = ""
    introduction: str = ""
    methodology: str = ""
    background_review: str = ""
    timeline: str = ""
    comparative_analysis: str = ""
    discussion: str = ""
    future_directions: str = ""
    references: str = ""
    sections: list[ReportSection] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    tables: list[TableSpec] = Field(default_factory=list)
    blocks: list[ReportBlock] = Field(default_factory=list)
