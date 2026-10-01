"""Session research strategies; standard is retained for Phase 1 clients."""

from typing import Literal
from pydantic import BaseModel, ConfigDict

ModeName = Literal["quick", "deep", "technical", "academic", "fact_check", "compare", "standard"]
SourceType = Literal["primary", "academic", "documentation", "news", "analysis", "other"]


class QualityWeights(BaseModel):
    relevance: float
    authority: float
    freshness: float
    source_type: float
    evidence_strength: float
    model_config = ConfigDict(frozen=True)


class ModeConfig(BaseModel):
    label: str
    search_depth: Literal["basic", "advanced"]
    queries: int
    iterations: int
    preferred_types: tuple[SourceType, ...]
    strategy: str
    weights: QualityWeights
    relevance_threshold: float = 0.3
    sources: int = 15
    parallel_tasks: int = 3
    wall_seconds: float = 180
    model_config = ConfigDict(frozen=True)


MODES: dict[ModeName, ModeConfig] = {
    "quick": ModeConfig(label="Quick", search_depth="basic", queries=3, iterations=1, sources=8, parallel_tasks=2, wall_seconds=60,
        preferred_types=("primary", "news"), strategy="Answer the central question concisely from the strongest available evidence.",
        weights=QualityWeights(relevance=.4, authority=.15, freshness=.2, source_type=.1, evidence_strength=.15)),
    "deep": ModeConfig(label="Deep", search_depth="advanced", queries=10, iterations=5,
        preferred_types=("primary", "academic", "analysis"), strategy="Investigate multiple perspectives, uncertainties and conflicting evidence across several search rounds; identify remaining coverage gaps.",
        weights=QualityWeights(relevance=.3, authority=.2, freshness=.1, source_type=.1, evidence_strength=.3)),
    "technical": ModeConfig(label="Technical", search_depth="advanced", queries=8, iterations=4, wall_seconds=150,
        preferred_types=("documentation", "primary"), strategy="Investigate implementation details, versions, constraints and reproducible benchmarks using original documentation.",
        weights=QualityWeights(relevance=.3, authority=.15, freshness=.15, source_type=.2, evidence_strength=.2)),
    "academic": ModeConfig(label="Academic", search_depth="advanced", queries=8, iterations=4,
        preferred_types=("academic", "primary"), strategy="Investigate original studies, methods, sample sizes, limitations and replication; distinguish preprints from reviewed work.",
        weights=QualityWeights(relevance=.25, authority=.25, freshness=.05, source_type=.2, evidence_strength=.25)),
    "fact_check": ModeConfig(label="Fact Check", search_depth="advanced", queries=6, iterations=3, parallel_tasks=2, wall_seconds=120,
        preferred_types=("primary", "academic"), strategy="Verify each supplied specific claim independently. Seek both supporting and contradicting evidence; never assume the claim is true.",
        weights=QualityWeights(relevance=.35, authority=.2, freshness=.05, source_type=.1, evidence_strength=.3)),
    "compare": ModeConfig(label="Compare", search_depth="advanced", queries=8, iterations=4,
        preferred_types=("primary", "documentation", "analysis"), strategy="Research every supplied item against the same criteria. Build a side-by-side comparison; leave unsupported cells explicitly unverified.",
        weights=QualityWeights(relevance=.35, authority=.15, freshness=.15, source_type=.1, evidence_strength=.25)),
    "standard": ModeConfig(label="Standard (legacy)", search_depth="basic", queries=6, iterations=3, parallel_tasks=2, wall_seconds=120,
        preferred_types=("primary", "news"), strategy="Provide a balanced evidence-based overview.",
        weights=QualityWeights(relevance=.3, authority=.2, freshness=.15, source_type=.1, evidence_strength=.25)),
}
