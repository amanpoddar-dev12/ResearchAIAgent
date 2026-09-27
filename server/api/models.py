from typing import Literal
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    question: str = Field(min_length=3)
    depth: Literal["quick", "standard", "deep"] = "standard"
    max_sources: int = Field(default=10, ge=1, le=20)


class ResearchStarted(BaseModel):
    research_id: str
    status: Literal["started"] = "started"
