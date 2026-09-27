"""Research planning."""

from app.llm import LLMClient
from app.models import ResearchPlan, ResearchQuestion
from app.prompts import PLANNING
import logging

logger = logging.getLogger(__name__)


class Planner:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def create_plan(self, question: ResearchQuestion) -> ResearchPlan:
        try:
            return self.llm.generate_structured(PLANNING.format(question=question.question), ResearchPlan)
        except (RuntimeError, ValueError) as exc:
            logger.warning("Using deterministic fallback plan: %s", exc)
            return ResearchPlan(
                objective=question.question,
                research_areas=["Recent developments", "Evidence and deployments", "Limitations and outlook"],
                sub_questions=[
                    f"What are the latest documented developments related to {question.question}?",
                    f"Which primary or reputable sources provide evidence about {question.question}?",
                    f"What limitations or disagreements exist in the evidence about {question.question}?",
                ],
                search_queries=[
                    question.question,
                    f"{question.question} primary source report",
                    f"{question.question} limitations evidence",
                ],
            )
