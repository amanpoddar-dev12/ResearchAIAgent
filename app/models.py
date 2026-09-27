"""Typed data contracts used throughout the research pipeline."""

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


Category = Literal["fact", "statistic", "quote", "event", "comparison", "analysis", "inference"]


class ResearchQuestion(BaseModel):
    question: str = Field(min_length=3)
    audience: str | None = None
    desired_depth: str | None = None
    output_format: str | None = None


class ResearchPlan(BaseModel):
    objective: str
    sub_questions: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    research_areas: list[str] = Field(default_factory=list)


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
    model_config = ConfigDict(validate_assignment=True)


class Finding(BaseModel):
    claim: str
    explanation: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    category: Category


class ClaimExtraction(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class Conflict(BaseModel):
    topic: str
    claim_a: str
    claim_b: str
    source_a: list[str] = Field(default_factory=list)
    source_b: list[str] = Field(default_factory=list)
    explanation: str


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
