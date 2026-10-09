from typing import Literal
from pydantic import BaseModel, Field, model_validator
from app.models import SourceFilters, BudgetOverrides
from app.modes import ModeName


class ResearchRequest(BaseModel):
    parent_research_id: str | None = Field(default=None, min_length=1, max_length=150, pattern=r'^[A-Za-z0-9_-]+$')
    question: str = Field(min_length=3)
    depth: Literal["quick", "standard", "deep"] = "standard"
    max_sources: int = Field(default=10, ge=1, le=20)
    mode: ModeName | None = None
    filters: SourceFilters = Field(default_factory=SourceFilters)
    budgets: BudgetOverrides = Field(default_factory=BudgetOverrides)
    target_claims: list[str] = Field(default_factory=list, max_length=10)
    comparison_items: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_targets(self):
        self.target_claims = list(dict.fromkeys(item.strip() for item in self.target_claims if item.strip()))
        self.comparison_items = list(dict.fromkeys(item.strip() for item in self.comparison_items if item.strip()))
        if self.mode == "compare" and len(self.comparison_items) < 2:
            raise ValueError("Compare requires at least two distinct items")
        return self


class ResearchStarted(BaseModel):
    research_id: str
    status: Literal["started"] = "started"
