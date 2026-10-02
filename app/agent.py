"""Existing plan/research/conflict/report stages with one session coordinator."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
from app.config import Settings
from app.llm import LLMRouter, invoke_structured
from app.llm.routing import EVIDENCE_EVALUATION, FINAL_VERIFICATION, INDEPENDENT_REVIEW, QUESTION_ANALYSIS
from pydantic import BaseModel, Field
from app.models import (ResearchQuestion, ResearchState, SourceFilters, BudgetOverrides, ResearchPlan,
    ReportDraft, QuestionAnalysis, VerificationBatch, ReviewBatch)
from app.modes import MODES, ModeName
from app.evidence import reject, source_rejection, evidence_conflicts, validate_evidence
from app.planner import Planner, refine_question
from app.researcher import Researcher
from app.synthesizer import Synthesizer, build_structured_report, render_report
from app.research_control import audit, bounded_call
from app.scoring import score_finding
from app.prompts import (EVIDENCE_RULES, EVIDENCE_EVALUATION as EVIDENCE_EVALUATION_PROMPT,
    INDEPENDENT_REVIEW as INDEPENDENT_REVIEW_PROMPT, QUESTION_ANALYSIS as QUESTION_ANALYSIS_PROMPT)


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
        if getattr(self.llm, "supports_task_routing", False):
            try:
                analysis = await bounded_call(
                    executor, deadline, invoke_structured, self.llm,
                    QUESTION_ANALYSIS_PROMPT.format(question=state.question.question),
                    QuestionAnalysis, task=QUESTION_ANALYSIS,
                )
                state.question.refined_question = analysis.refined_question
                state.question.assumptions = list(dict.fromkeys(state.question.assumptions + analysis.assumptions))
                state.question.ambiguities = list(dict.fromkeys(state.question.ambiguities + analysis.ambiguities))
                audit(state, "question_analysis", analysis.refined_question, ambiguities=analysis.ambiguities)
            except (TimeoutError, RuntimeError, ValueError):
                audit(state, "question_analysis_failed", "Question analysis unavailable; continuing with deterministic refinement")
        try:
            state.plan = await bounded_call(executor, deadline, self.planner.create_plan, state.question.model_copy(deep=True))
        except TimeoutError:
            state.plan = ResearchPlan(objective=state.question.question, search_queries=[state.question.question])
            self.researcher.record_timeout(state, started)
        emit("planning_completed", "Research plan created", state.plan.model_copy(deep=True))
        emit("research_progress", "Plan ready", {"phase": "search", "progress": 20})
        if deadline - time.monotonic() > 0.01:
            await self.researcher.run_async(state, emit, executor, started, deadline)
        else:
            self.researcher.record_timeout(state, started)
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
        if getattr(self.llm, "supports_task_routing", False) and state.mode != "quick" and state.findings:
            try:
                emit("verification_started", "Verifying claims against stored evidence")
                verification_input = [
                    {
                        "claim_id": finding.id,
                        "claim": finding.claim,
                        "evidence": [item.model_dump(mode="json") for item in state.evidence if item.id in finding.evidence_ids],
                    }
                    for finding in state.findings if finding.evidence_ids
                ]
                evaluation = await bounded_call(
                    executor, deadline, invoke_structured, self.llm,
                    EVIDENCE_EVALUATION_PROMPT.format(claims=verification_input),
                    VerificationBatch, task=EVIDENCE_EVALUATION,
                )
                review = await bounded_call(
                    executor, deadline, invoke_structured, self.llm,
                    INDEPENDENT_REVIEW_PROMPT.format(evaluations=evaluation.model_dump(mode="json")),
                    ReviewBatch, task=INDEPENDENT_REVIEW,
                )
                final_verification = await bounded_call(
                    executor, deadline, invoke_structured, self.llm,
                    EVIDENCE_RULES + "Produce final verification results using only these claims, evidence, Gemini evaluations, and Mistral reviews. "
                    "Return confirmed, weakened, refuted, or insufficient_evidence with a short rationale. "
                    f"Claims and evidence: {verification_input}\nGemini evaluations: {evaluation.model_dump(mode='json')}\nMistral reviews: {review.model_dump(mode='json')}",
                    VerificationBatch, task=FINAL_VERIFICATION,
                )
                verdicts = {item.claim_id: item for item in final_verification.results}
                reviews = {item.claim_id: item for item in review.reviews}
                valid_evidence = {item.id for item in state.evidence}
                for finding in state.findings:
                    result = verdicts.get(finding.id)
                    if not result:
                        continue
                    if any(evidence_id not in valid_evidence for evidence_id in result.supporting_evidence_ids):
                        audit(state, "verification_rejected", "Verification referenced unknown evidence", claim_id=finding.id)
                        continue
                    finding.confidence = min(finding.confidence, 1.0) if result.verdict == "confirmed" else (
                        min(finding.confidence, .5) if result.verdict == "weakened" else 0.0
                    )
                    finding.evidence_status = {
                        "confirmed": "Supported",
                        "weakened": "Partially Supported",
                        "refuted": "Contradicted",
                        "insufficient_evidence": "Unverified",
                    }[result.verdict]
                    score = score_finding(state, finding)
                    finding.confidence_score = score.score
                    finding.score_source_quality = score.source_quality
                    finding.score_evidence_relevance = score.evidence_relevance
                    finding.score_source_agreement = score.source_agreement
                    finding.score_freshness = score.freshness
                    finding.score_citation_validity = score.citation_validity
                    finding.score_verification_agreement = score.verification_agreement
                    finding.score_formula = score.formula
                    state.verifications.append(Verification(
                        claim_id=finding.id, status=finding.evidence_status,
                        supporting_count=len(finding.supporting_evidence_ids),
                        contradicting_count=len(finding.contradicting_evidence_ids),
                        verified_by=["gemini", "mistral"],
                        reasoning=result.reasoning_summary,
                        confidence_score=score.score,
                        independent_review=reviews.get(finding.id).reasoning if reviews.get(finding.id) else None,
                    ))
                    audit(state, "fact_verification", result.verdict, claim_id=finding.id, issues=result.issues)
                    event_type = {
                        "Supported": "claim_verified",
                        "Partially Supported": "claim_partially_verified",
                        "Contradicted": "claim_contradicted",
                        "Unverified": "claim_unverified",
                    }[finding.evidence_status]
                    emit(event_type, f"Claim {finding.evidence_status.lower()}", state.verifications[-1])
                emit("verification_completed", "Claim verification completed", {"count": len(state.verifications)})
            except (TimeoutError, RuntimeError, ValueError):
                audit(state, "verification_unavailable", "Fact verification unavailable; retained evidence-derived statuses")
                emit("verification_completed", "Independent verification unavailable", {"count": 0, "status": "unavailable"})
        emit("synthesis_started", "Writing final report")
        emit("research_progress", "Writing final report", {"phase": "synthesis", "progress": 85})
        try:
            synthesis_state = state.model_copy(deep=True)
            synthesis_state.findings = [
                finding for finding in synthesis_state.findings
                if finding.evidence_status in {"Supported", "Partially Supported"}
            ]
            draft = await bounded_call(executor, deadline, self.synthesizer.draft, synthesis_state)
        except TimeoutError:
            self.researcher.record_timeout(state, started)
            draft = ReportDraft(title=f"Research Report: {state.question.question}", executive_summary="", conclusion="", limitations=state.gaps)
        state.structured_report = build_structured_report(draft, state)
        state.final_report = render_report(draft, state)
        state.elapsed_seconds = time.monotonic() - started
        state.llm_requests_used = self.llm.requests_used
        state.status = "complete"
        emit("research_snapshot", "Research state finalized", state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}}))
        emit("report_generated", "Final report generated", state.final_report)
        emit("research_progress", "Report ready", {"phase": "complete", "progress": 100})
        emit("research_completed", "Research completed", {"searches_used": state.searches_performed, "sources": len(state.sources), "llm_requests_used": state.llm_requests_used})
        return state
