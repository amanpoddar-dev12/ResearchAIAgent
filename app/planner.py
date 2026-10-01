"""Research planning."""

from app.llm import LLMClient
from app.models import ResearchPlan, ResearchQuestion
from app.prompts import PLANNING
from app.modes import MODES
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)


def refine_question(question: ResearchQuestion) -> None:
    text = question.question.strip()
    if len(text.split()) < 5:
        question.ambiguities.append("Scope and evaluation criteria are unspecified")
        question.assumptions.append("Use a general overview of documented evidence, limitations and disagreements.")
    if re.search(r"\b(best|better|effective)\b", text, re.I):
        question.ambiguities.append("Evaluation criteria are unspecified")
        question.assumptions.append("Compare documented benefits and limitations without assuming a universal winner.")
    if re.search(r"\b(latest|today|current|recent)\b", text, re.I):
        question.assumptions.append(f"Interpret relative time as of {date.today().isoformat()}.")
    question.refined_question = text + (" Research scope: " + " ".join(question.assumptions) if question.assumptions else "")


class Planner:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def create_plan(self, question: ResearchQuestion) -> ResearchPlan:
        mode = MODES[question.mode]
        instructions = f"\nMode: {mode.label}. Strategy: {mode.strategy}\nCreate up to {mode.queries} distinct queries. Prefer source types: {', '.join(mode.preferred_types)}."
        instructions += "\nProvide sub_question_tasks with unique Q IDs, question, query, and depends_on Q IDs for genuine prerequisites only. Independent tasks have no dependencies."
        if question.target_claims:
            instructions += f"\nSpecific claims to verify: {question.target_claims}"
        if question.comparison_items:
            instructions += f"\nItems to compare against common criteria: {question.comparison_items}"
        try:
            plan = self.llm.generate_structured(PLANNING.format(question=question.refined_question or question.question) + instructions, ResearchPlan)
            plan.search_queries = list(dict.fromkeys(plan.search_queries))[:mode.queries]
            return plan
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
                search_queries=([f"{claim} evidence verification" for claim in question.target_claims] or [f"{item} {question.question}" for item in question.comparison_items] or [
                    question.question,
                    f"{question.question} primary source report",
                    f"{question.question} limitations evidence",
                ])[:mode.queries],
            )
