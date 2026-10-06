"""Explicitly synthetic, offline test data. Never research evidence."""

import re
from app.config import Settings
from app.models import (ClaimExtraction, ConflictAssessment, Evidence, Finding,
    GapAssessment, ReportDraft, ResearchPlan, SearchResult)

SYNTHETIC_TEXT = "SYNTHETIC TEST DATA: Test widget Alpha has a test speed of 10 units. Test widget Beta has a test speed of 5 units. These are fictional test fixtures."


def synthetic_settings():
    return Settings(_env_file=None, gemini_api_key="synthetic-not-a-key", tavily_api_key="synthetic-not-a-key",
        gemini_model="synthetic-test-model", groq_api_key="synthetic-not-a-key", groq_model="synthetic-groq-model",
        groq_review_model="synthetic-review-model",
        llm_timeout_seconds=60, llm_max_retries=2,
        max_searches=10, max_iterations=5, max_sources=20, max_llm_requests=10)


def synthetic_search(*args, **kwargs):
    return [SearchResult(title="SYNTHETIC TEST ONLY: Test widget documentation", url="https://docs.synthetic.invalid/docs/widgets",
        content=SYNTHETIC_TEXT, source_domain="docs.synthetic.invalid", published_date="2026-09-01")]


class SyntheticLLM:
    def __init__(self, *args, max_requests=10, **kwargs):
        self.requests_used = 0
        self.max_requests = max_requests
        self.model_name = "synthetic-test-model"

    def generate_structured(self, prompt, schema):
        self.requests_used += 1
        if schema is ResearchPlan:
            return ResearchPlan(objective="SYNTHETIC TEST ONLY", search_queries=[f"Test widget query {index}" for index in range(10)])
        if schema is ClaimExtraction:
            source_ids = re.findall(r"--- (S\d+) \|", prompt)
            if not source_ids:
                return ClaimExtraction()
            return ClaimExtraction(findings=[Finding(id="model-claim", claim="SYNTHETIC TEST ONLY: Test widget Alpha has a test speed of 10 units.",
                explanation="Fictional fixture, not real research.", source_ids=[source_ids[0]], confidence=.5, category="comparison",
                evidence_ids=["E1"], comparison_item="Alpha", comparison_criterion="Test speed")],
                evidence=[Evidence(id="E1", source_id=source_ids[0], excerpt="Test widget Alpha has a test speed of 10 units.", relation="supports", strength="direct")])
        if schema is GapAssessment:
            return GapAssessment(gaps=["SYNTHETIC TEST ONLY: No real-world coverage"], follow_up_queries=[])
        if schema is ConflictAssessment:
            return ConflictAssessment()
        if schema is ReportDraft:
            return ReportDraft(title="SYNTHETIC TEST REPORT — NOT REAL RESEARCH", executive_summary="Fictional test summary [S1].",
                key_findings=[], detailed_analysis=[], limitations=["Synthetic fixtures only."], conclusion="Not real research.")
        raise AssertionError(f"Unexpected schema: {schema}")
