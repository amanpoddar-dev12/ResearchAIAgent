"""Existing plan/research/conflict/report stages with one session coordinator."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
from app.config import Settings
from app.llm import GeminiClient
from app.models import ResearchQuestion, ResearchState, SourceFilters, BudgetOverrides, ResearchPlan, ReportDraft
from app.modes import MODES, ModeName
from app.evidence import reject, source_rejection, evidence_conflicts, validate_evidence
from app.planner import Planner, refine_question
from app.researcher import Researcher
from app.synthesizer import Synthesizer, render_report
from app.research_control import audit, bounded_call


class ResearchAgent:
    def __init__(self, settings: Settings) -> None:
        settings.validate_configuration()
        self.settings = settings
        self.llm = GeminiClient(settings.gemini_model, settings.gemini_api_key,
            max_requests=settings.max_llm_requests, timeout=settings.gemini_timeout)
        self.planner = Planner(self.llm)
        self.researcher = Researcher(self.llm, settings.tavily_api_key, settings.max_searches, settings.max_sources, settings.max_iterations)
        self.synthesizer = Synthesizer(self.llm)

    def run(self, question: str, emit=None, *, mode: ModeName = "standard", filters: SourceFilters | None = None,
            target_claims: list[str] | None = None, comparison_items: list[str] | None = None,
            budgets: BudgetOverrides | None = None) -> ResearchState:
        config = MODES[mode]
        overrides = budgets or BudgetOverrides()
        state = ResearchState(question=ResearchQuestion(question=question, mode=mode,
            target_claims=target_claims or ([question] if mode == "fact_check" else []), comparison_items=comparison_items or []),
            mode=mode, filters=filters or SourceFilters(), max_llm_requests=self.llm.max_requests,
            max_searches=overrides.max_searches or min(self.settings.max_searches, config.queries),
            max_sources=overrides.max_sources or min(self.settings.max_sources, config.sources),
            max_iterations=overrides.max_iterations or min(self.settings.max_iterations, config.iterations),
            max_parallel_tasks=overrides.max_parallel_tasks or min(self.settings.max_parallel_tasks, config.parallel_tasks),
            max_wall_seconds=overrides.max_wall_seconds or min(self.settings.max_wall_seconds, config.wall_seconds),
            budget_overrides=overrides, llm_model=self.llm.model_name, provenance_required=True)
        executor = ThreadPoolExecutor(max_workers=state.max_parallel_tasks)
        started = time.monotonic()
        deadline = started + state.max_wall_seconds
        self.llm.deadline = deadline
        try:
            return asyncio.run(self._run(state, emit or (lambda *_: None), executor, started, deadline))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    async def _run(self, state, emit, executor, started, deadline):
        emit("planning_started", "Creating research plan")
        emit("research_progress", "Planning research", {"phase": "planning", "progress": 5, "mode": state.mode})
        refine_question(state.question)
        audit(state, "refinement", state.question.refined_question, original=state.question.question, assumptions=state.question.assumptions)
        emit("question_refined", "Research scope clarified", state.question.model_dump())
        try:
            state.plan = await bounded_call(executor, deadline, self.planner.create_plan, state.question.model_copy(deep=True))
        except TimeoutError:
            state.plan = ResearchPlan(objective=state.question.question, search_queries=[state.question.question])
            self.researcher.record_timeout(state, started)
        emit("planning_completed", "Research plan created", state.plan.model_copy(deep=True))
        emit("research_progress", "Plan ready", {"phase": "search", "progress": 20})
        await self.researcher.run_async(state, emit, executor, started, deadline)
        validate_evidence(state)
        emit("analysis_started", "Checking for conflicting information")
        emit("research_progress", "Checking conflicts", {"phase": "conflicts", "progress": 75})
        state.conflicts = evidence_conflicts(state)
        try:
            assessment = await bounded_call(executor, deadline, self.synthesizer.detect_conflicts, state.model_copy(deep=True))
            for conflict in assessment.conflicts:
                valid = True
                for sid in conflict.source_a + conflict.source_b:
                    reason = source_rejection(state, sid)
                    if reason:
                        reject(state, "conflict", reason, sid)
                        valid = False
                # Generated explanations must be tied to existing claims and evidence.
                linked = [claim for claim in state.findings if claim.claim in {conflict.claim_a, conflict.claim_b} and claim.evidence_ids]
                if valid and len(linked) >= 2:
                    conflict.claim_ids = [claim.id for claim in linked]
                    conflict.evidence_ids = list(dict.fromkeys(eid for claim in linked for eid in claim.evidence_ids))
                    conflict.source_a = linked[0].source_ids[:]
                    conflict.source_b = linked[1].source_ids[:]
                    conflict.topic = "Potential disagreement: " + " / ".join(conflict.claim_ids)
                    conflict.explanation = "The model flagged these validated claims as a potential disagreement; inspect their linked excerpts."
                    state.conflicts.append(conflict)
                else:
                    reject(state, "conflict", "Generated conflict is not traceable to validated claims")
        except TimeoutError:
            self.researcher.record_timeout(state, started)
        except (ValueError, RuntimeError):
            audit(state, "analysis_failed", "Generated conflict analysis unavailable; retained evidence-derived conflicts")
        for conflict in state.conflicts:
            emit("conflict_detected", f"Conflict detected: {conflict.topic}", conflict)
        emit("synthesis_started", "Writing final report")
        emit("research_progress", "Writing final report", {"phase": "synthesis", "progress": 85})
        try:
            draft = await bounded_call(executor, deadline, self.synthesizer.draft, state.model_copy(deep=True))
        except TimeoutError:
            self.researcher.record_timeout(state, started)
            draft = ReportDraft(title=f"Research Report: {state.question.question}", executive_summary="", conclusion="", limitations=state.gaps)
        state.final_report = render_report(draft, state)
        state.elapsed_seconds = time.monotonic() - started
        state.llm_requests_used = self.llm.requests_used
        state.status = "complete"
        emit("research_snapshot", "Research state finalized", state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}}))
        emit("report_generated", "Final report generated", state.final_report)
        emit("research_progress", "Report ready", {"phase": "complete", "progress": 100})
        emit("research_completed", "Research completed", {"searches_used": state.searches_performed, "sources": len(state.sources), "llm_requests_used": state.llm_requests_used})
        return state
