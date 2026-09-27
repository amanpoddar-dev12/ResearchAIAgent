"""High-level orchestration for the research agent."""

import logging
from app.config import Settings
from app.llm import GeminiClient
from app.models import ResearchQuestion, ResearchState
from app.planner import Planner
from app.researcher import Researcher
from app.synthesizer import Synthesizer, render_report

logger = logging.getLogger(__name__)


class ResearchAgent:
    def __init__(self, settings: Settings) -> None:
        settings.validate_configuration()
        llm = GeminiClient(
            settings.gemini_model,
            settings.gemini_api_key,
            max_requests=settings.max_llm_requests,
            timeout=settings.gemini_timeout,
        )
        self.llm = llm
        self.planner = Planner(llm)
        self.researcher = Researcher(llm, settings.tavily_api_key, settings.max_searches, settings.max_sources, settings.max_iterations)
        self.synthesizer = Synthesizer(llm)

    def run(self, question: str, emit=None) -> ResearchState:
        state = ResearchState(
            question=ResearchQuestion(question=question),
            max_llm_requests=self.llm.max_requests,
            max_searches=self.researcher.max_searches,
            max_sources=self.researcher.max_sources,
            max_iterations=self.researcher.max_iterations,
            llm_model=self.llm.model_name,
        )
        emit = emit or (lambda *_args: None)
        emit("planning_started", "Creating research plan")
        state.plan = self.planner.create_plan(state.question)
        emit("planning_completed", "Research plan created", state.plan)
        self.researcher.run(state, emit=emit)
        emit("analysis_started", "Checking for conflicting information")
        try:
            state.conflicts = self.synthesizer.detect_conflicts(state).conflicts
            for conflict in state.conflicts:
                emit("conflict_detected", f"Conflict detected: {conflict.topic}", conflict)
        except (ValueError, RuntimeError) as exc:
            logger.warning("Conflict detection failed: %s", type(exc).__name__)
            logger.warning("Conflict detection failed; continuing without generated conflicts")
        emit("synthesis_started", "Writing final report")
        state.final_report = render_report(self.synthesizer.draft(state), state)
        state.status = "complete"
        emit("report_generated", "Final report generated", state.final_report)
        emit("research_completed", "Research completed", {
            "searches_used": state.searches_performed,
            "sources": len(state.sources),
            "llm_requests_used": self.llm.requests_used,
        })
        return state
