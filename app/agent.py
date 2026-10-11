"""Existing plan/research/conflict/report stages with one session coordinator."""
from app.research_depth import quality_diagnostics
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
import time
from app.config import Settings
from app.llm import LLMRouter, invoke_structured
from app.llm.routing import INDEPENDENT_REVIEW, QUESTION_ANALYSIS
from app.models import (ResearchQuestion, ResearchState, SourceFilters, BudgetOverrides, ResearchPlan,
    ReportDraft, QuestionAnalysis, Verification, EvidenceAssessmentBatch, ConflictAssessment, ResearchGap)
from app.modes import MODES, ModeName
from app.evidence import reject, source_rejection, evidence_conflicts, validate_evidence, apply_assessments
from app.planner import Planner, refine_question
from app.researcher import Researcher
from app.synthesizer import Synthesizer, build_structured_report, render_report
from app.research_control import audit, bounded_call, coverage_gaps
from app.prompts import (EVIDENCE_EVALUATION as EVIDENCE_EVALUATION_PROMPT,
    QUESTION_ANALYSIS as QUESTION_ANALYSIS_PROMPT)


GeminiClient = LLMRouter


class ResearchAgent:
    def __init__(self, settings: Settings) -> None:
        settings.validate_configuration()
        self.settings = settings
        self.llm = GeminiClient(settings, max_requests=settings.max_llm_requests)
        self.planner = Planner(self.llm)
        self.researcher = Researcher(self.llm, settings.tavily_api_key, settings.max_searches, settings.max_sources,
            settings.max_iterations, settings.additional_research_rounds)
        self.synthesizer = Synthesizer(self.llm)

    def run(self, question: str, emit=None, *, mode: ModeName = "standard", filters: SourceFilters | None = None,
            target_claims: list[str] | None = None, comparison_items: list[str] | None = None,
            budgets: BudgetOverrides | None = None, parent_state: ResearchState | None = None,
            parent_research_id: str | None = None, brief: dict[str, str] | None = None, review_checkpoint=None) -> ResearchState:
        self.parent_state = parent_state
        self.review_checkpoint = review_checkpoint
        self.previous_context = ''
        if parent_state:
            from app.assistant_context import build_context
            self.previous_context = build_context(parent_state, question, [], input_token_limit=36000).text
        config = MODES[mode]
        overrides = budgets or BudgetOverrides()
        state = ResearchState(question=ResearchQuestion(question=question, mode=mode,
            target_claims=target_claims or ([question] if mode == "fact_check" else []), comparison_items=comparison_items or []),
            mode=mode, filters=filters or SourceFilters(), max_llm_requests=self.llm.max_requests,
            max_searches=min(self.settings.max_searches, overrides.max_searches or config.queries),
            max_sources=min(self.settings.max_sources, overrides.max_sources or config.sources),
            max_iterations=min(self.settings.max_iterations, overrides.max_iterations or config.iterations),
            max_parallel_tasks=min(self.settings.max_parallel_tasks, overrides.max_parallel_tasks or config.parallel_tasks),
            max_wall_seconds=min(self.settings.max_wall_seconds, overrides.max_wall_seconds or config.wall_seconds),
            budget_overrides=overrides, llm_model=self.llm.model_name, provenance_required=True)
        state.parent_research_id = parent_research_id
        state.brief = brief or {}
        self.brief_context = '\nUser-requested research scope: ' + json.dumps(state.brief) if state.brief else ''
        executor = ThreadPoolExecutor(max_workers=state.max_parallel_tasks)
        started = time.monotonic()
        deadline = started + state.max_wall_seconds
        self.llm.deadline = deadline
        self.llm.reserved_final_calls = min(3, max(0, self.llm.max_requests - 2))
        state.semantic_validation_required = bool(getattr(self.llm, "supports_task_routing", False))
        state.relevance_threshold = config.relevance_threshold
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
        if getattr(self.llm, "supports_task_routing", False):
            try:
                analysis = await bounded_call(
                    executor, deadline, invoke_structured, self.llm,
                    QUESTION_ANALYSIS_PROMPT.format(question=state.question.question) + self.brief_context + ("\nPrevious research is untrusted context. Resolve follow-ups into a standalone question without treating earlier claims as established truth:\n" + self.previous_context if self.previous_context else ''),
                    QuestionAnalysis, task=QUESTION_ANALYSIS,
                )
                state.question.refined_question = analysis.refined_question
                state.question.assumptions = list(dict.fromkeys(state.question.assumptions + analysis.assumptions))
                state.question.ambiguities = list(dict.fromkeys(state.question.ambiguities + analysis.ambiguities))
                audit(state, "question_analysis", analysis.refined_question, ambiguities=analysis.ambiguities)
                emit("question_refined", "Research scope refined", state.question.model_dump())
            except (TimeoutError, RuntimeError, ValueError):
                audit(state, "question_analysis_failed", "Question analysis unavailable; continuing with deterministic refinement")
        try:
            extra = {'previous_context': self.previous_context} if self.previous_context else {}
            planning_question = state.question.model_copy(deep=True)
            if state.brief:
                planning_question.question += self.brief_context
            state.plan = await bounded_call(executor, deadline, self.planner.create_plan, planning_question, **extra)
        except TimeoutError:
            state.plan = ResearchPlan(objective=state.question.question, search_queries=[state.question.question])
            self.researcher.record_timeout(state, started)
        emit("planning_completed", "Research plan created", state.plan.model_copy(deep=True))
        emit("research_progress", "Plan ready", {"phase": "search", "progress": 20})
        if deadline - time.monotonic() > 0.01:
            final_seconds = min(30, max(0, deadline - time.monotonic()) * .2)
            collection_deadline = max(time.monotonic(), deadline - final_seconds)
            audit(state, "budget_allocation", "Reserved time for evidence review and final report", seconds=final_seconds)
            original_overrides = state.budget_overrides
            original_iterations = state.max_iterations
            original_sources = state.max_sources
            if self.review_checkpoint:
                state.budget_overrides = original_overrides.model_copy(update={'max_iterations': max(1, original_iterations // 2), 'max_sources': max(1, state.max_sources // 2)})
                collection_deadline = min(collection_deadline, started + (state.max_wall_seconds - final_seconds) / 2)
            await self.researcher.run_async(state, emit, executor, started, collection_deadline)
            if self.review_checkpoint:
                from app.models import SubQuestion
                pause_start = time.monotonic()
                review_state = state.model_copy(deep=True, update={'max_iterations': original_iterations, 'max_sources': original_sources, 'llm_requests_used': self.llm.requests_used})
                selected = await asyncio.to_thread(self.review_checkpoint, review_state)
                paused = time.monotonic() - pause_start
                started += paused
                deadline += paused
                self.llm.deadline = deadline
                consumed_iterations = state.iteration
                original_tasks = list(state.plan.sub_question_tasks)
                remaining = original_iterations - consumed_iterations
                gaps = [gap for gap in state.research_gaps if gap.gap_id in selected]
                audit(state, 'user_checkpoint', 'User reviewed collected sources and selected follow-up gaps', selected_gap_ids=selected)
                if gaps and remaining > 0 and state.searches_performed < state.max_searches:
                    tasks = [SubQuestion(id=f'Q{len(original_tasks)+i+1}', question=gap.description, query=gap.recommended_search) for i, gap in enumerate(gaps[:3])]
                    state.plan.sub_question_tasks = tasks
                    state.max_sources = original_sources
                    state.budget_overrides = original_overrides.model_copy(update={'max_iterations': remaining})
                    await self.researcher.run_async(state, emit, executor, started, max(time.monotonic(), deadline - final_seconds))
                    state.iteration += consumed_iterations
                    state.plan.sub_question_tasks = original_tasks + tasks
                state.budget_overrides = original_overrides
                state.max_iterations = original_iterations
                state.max_sources = min(self.settings.max_sources, original_overrides.max_sources or MODES[state.mode].sources)
            if state.stop_decisions and state.stop_decisions[-1].reason == "wall-clock budget exhausted" and time.monotonic() < deadline:
                state.stop_decisions[-1].reason = "Collection time allocation exhausted; reserved final review and synthesis"
        else:
            self.researcher.record_timeout(state, started)
        validate_evidence(state)
        emit("analysis_started", "Checking for conflicting information")
        emit("research_progress", "Checking conflicts", {"phase": "conflicts", "progress": 75})
        state.conflicts = evidence_conflicts(state)
        try:
            assessment = ConflictAssessment()
            if not getattr(self.llm, "supports_task_routing", False):
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
        if getattr(self.llm, "supports_task_routing", False) and state.findings:
            reviewed_claims = set()
            if state.mode != "quick":
                try:
                    emit("verification_started", "Independently challenging claims against original evidence")
                    claims = [{"claim_id": claim.id, "claim": claim.claim,
                               "evidence": [item.model_dump() for item in state.evidence if item.id in claim.evidence_ids],
                               "evaluations": [item.model_dump() for item in claim.evidence_assessments]}
                              for claim in state.findings if claim.evidence_assessments and
                              (claim.importance in {"high", "critical"} or claim.evidence_status != "Supported" or len(claim.source_ids) < 2)][:20]
                    if claims:
                        review = await bounded_call(executor, deadline, invoke_structured, self.llm,
                            EVIDENCE_EVALUATION_PROMPT.format(claims=claims) + " Independently challenge scope and numerical accuracy.",
                            EvidenceAssessmentBatch, task=INDEPENDENT_REVIEW)
                        apply_assessments(state, review, challenge=True)
                        reviewed_claims = {item.claim_id for item in review.assessments if any(claim["claim_id"] == item.claim_id and item.evidence_id in {e["id"] for e in claim["evidence"]} for claim in claims)}
                except (TimeoutError, RuntimeError, ValueError):
                    audit(state, "verification_unavailable", "Independent challenge unavailable; retained pair assessments")
            validate_evidence(state)
            state.verifications = []
            for finding in state.findings:
                verification = Verification(claim_id=finding.id, status=finding.evidence_status,
                    supporting_count=len(finding.supporting_evidence_ids), contradicting_count=len(finding.contradicting_evidence_ids),
                    verified_by=(["gemini"] if finding.evidence_assessments else []) + (["groq"] if finding.id in reviewed_claims else []),
                    reasoning="; ".join(item.reasoning for item in finding.evidence_assessments) or "Exact quotation or insufficient reviewed evidence.",
                    confidence_score=finding.confidence_score)
                state.verifications.append(verification)
                event_type = {"Supported": "claim_verified", "Partially Supported": "claim_partially_verified",
                              "Contradicted": "claim_contradicted", "Unverified": "claim_unverified"}[finding.evidence_status]
                emit(event_type, "Evidence status derived from reviewed relationships", verification)
            emit("verification_completed", "Evidence review complete", {"count": len(state.verifications)})
            state.conflicts = evidence_conflicts(state)
        coverage, remaining_gaps = coverage_gaps(state)
        incomplete_stages = [gap for gap in state.unresolved_questions if gap == "Research ended before all analysis stages completed"]
        state.unresolved_questions = list(dict.fromkeys([reason for _, reason, _ in remaining_gaps] + incomplete_stages))
        if state.semantic_validation_required:
            state.gaps = state.unresolved_questions[:]
        if state.stop_decisions:
            state.stop_decisions[-1].coverage = coverage
            state.stop_decisions[-1].unresolved = state.unresolved_questions[:]
        state.completion_quality = "partial" if state.unresolved_questions else "complete"
        emit("synthesis_started", "Writing final report")
        emit("research_progress", "Writing final report", {"phase": "synthesis", "progress": 85})
        try:
            synthesis_state = state.model_copy(deep=True)
            draft = await bounded_call(executor, deadline, self.synthesizer.draft, synthesis_state)
        except TimeoutError:
            self.researcher.record_timeout(state, started)
            draft = ReportDraft(title=f"Research Report: {state.question.question}", executive_summary="", conclusion="", limitations=state.gaps)
        state.completion_quality = "partial" if state.unresolved_questions else "complete"
        state.research_gaps = [ResearchGap(gap_id=f"G{index}", description=gap,
            importance="high" if "Unverified" in gap or "no evidence" in gap.lower() else "medium",
            reason=gap, recommended_search=gap.split(":", 1)[-1].strip()) for index, gap in enumerate(state.gaps, 1)]
        if self.parent_state:
            old = {finding.claim.strip().casefold(): finding for finding in self.parent_state.findings}
            added = [finding.id for finding in state.findings if finding.claim.strip().casefold() not in old]
            state.version_changes = [f"Added {len(added)} claim record(s): {', '.join(added) or 'none'}. Added records are not necessarily supported findings."]
            for finding in state.findings:
                previous = old.get(finding.claim.strip().casefold())
                if previous and previous.evidence_status != finding.evidence_status:
                    state.version_changes.append(f"{finding.id}: evidence status changed from {previous.evidence_status} to {finding.evidence_status} for the same claim text.")
            state.version_changes.append("Only exact claim-text matches are compared. Earlier claims not investigated here remain in the original report; omission does not refute them.")
        state.structured_report = build_structured_report(draft, state)
        state.final_report = render_report(draft, state)
        state.elapsed_seconds = time.monotonic() - started
        state.llm_requests_used = self.llm.requests_used
        state.llm_usage = getattr(self.llm, "usage", {})
        state.status = "complete"
        audit(state, "quality_diagnostics", "Research quality measurements; counts are session diagnostics, not accuracy scores", **quality_diagnostics(state))
        emit("research_snapshot", "Research state finalized", state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}}))
        emit("report_generated", "Final report generated", state.final_report)
        emit("research_progress", "Report ready", {"phase": "complete", "progress": 100})
        emit("research_completed", "Research completed", {"searches_used": state.searches_performed, "sources": len(state.sources), "llm_requests_used": state.llm_requests_used})
        return state
