"""Bounded iterative research; workers return values, one coordinator commits them."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
import math
import time
from urllib.parse import urlsplit
from app.extractor import Extractor
from app.models import GapAssessment, ResearchState, Source, SubQuestion, Finding, StopDecision
from app.prompts import GAP_DETECTION
from app.llm import LLMClient
from tools.web_search import search_web, normalize_url
from tools.webpage import fetch_webpage
from app.modes import MODES
from app.source_quality import filter_reason, infer_source_type, score_source
from app.deduplication import near_duplicate
from app.evidence import merge_extraction, validate_evidence
from app.research_control import audit, bounded_call, coverage_gaps, decide_stop

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(self, llm: LLMClient, tavily_key: str, max_searches: int, max_sources: int, max_iterations: int) -> None:
        self.llm, self.tavily_key = llm, tavily_key
        self.max_searches, self.max_sources, self.max_iterations = max_searches, max_sources, max_iterations
        self.extractor = Extractor(llm)

    def run(self, state: ResearchState, emit=None) -> ResearchState:
        executor = ThreadPoolExecutor(max_workers=state.max_parallel_tasks)
        started = time.monotonic()
        try:
            return asyncio.run(self.run_async(state, emit, executor, started, started + state.max_wall_seconds))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _collect(self, query, filters, mode, deadline):
        """No shared state or events are accessible to this worker."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        results = search_web(self.tavily_key, query, search_depth=mode.search_depth, timeout=min(20, remaining))
        candidates, filtered = [], []
        for result in results:
            try:
                url = normalize_url(result.url)
            except ValueError:
                filtered.append({"url": result.url, "reason": "Invalid retrieved URL"})
                continue
            source = Source(id="", title=result.title, url=url, domain=urlsplit(url).netloc,
                content=result.content, publication_date=result.published_date, search_query=query,
                retrieved_at=datetime.now(timezone.utc).isoformat(), retrieval_method="search")
            source.source_type = infer_source_type(source)
            reason = filter_reason(source, filters)
            if reason:
                filtered.append({"url": url, "reason": reason})
                continue
            if not source.content:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                source.content = fetch_webpage(url, timeout=min(15, remaining))
                source.retrieval_method = "fetch"
            candidates.append(source)
        return len(results), candidates, filtered

    async def run_async(self, state, emit, executor, started, deadline):
        emit = emit or (lambda *_args: None)
        if not state.plan:
            raise ValueError("Research plan is required")
        state.status, state.provenance_required = "researching", True
        mode = MODES[state.mode]
        state.max_searches = state.budget_overrides.max_searches or min(self.max_searches, mode.queries)
        state.max_sources = state.budget_overrides.max_sources or min(self.max_sources, state.max_sources)
        state.max_iterations = state.budget_overrides.max_iterations or min(self.max_iterations, mode.iterations)
        state.explicit_sub_question_links = bool(state.plan.sub_question_tasks)
        if not state.plan.sub_question_tasks:
            queries = list(dict.fromkeys(state.plan.search_queries))[:state.max_searches]
            state.plan.sub_question_tasks = [SubQuestion(id=f"Q{i+1}", question=(state.plan.sub_questions[i] if i < len(state.plan.sub_questions) else query), query=query) for i, query in enumerate(queries)]
            for question in state.plan.sub_questions[len(queries):]:
                state.plan.sub_question_tasks.append(SubQuestion(id=f"Q{len(state.plan.sub_question_tasks)+1}", question=question, query=question))
        tasks = state.plan.sub_question_tasks
        task_map = {task.id: task for task in tasks}
        invalid = set()
        def check(key, path):
            if key in path or key not in task_map:
                invalid.update(path)
                return
            for dependency in task_map[key].depends_on:
                check(dependency, path + [key])
        for task in tasks:
            check(task.id, [])
        if len(task_map) != len(tasks):
            invalid.update(task_map)
        for key in sorted(invalid):
            audit(state, "dependency_rejected", "Sub-question has a cyclic, ambiguous or unknown dependency", sub_question_id=key)
        pending = [(task.query, "Initial planned sub-question", [task.id]) for task in tasks if task.id not in invalid]
        batch_size = max(1, math.ceil(min(len(tasks), state.max_searches) / state.max_iterations))
        emitted_claims, emitted_evidence, analyzed = set(), set(), set()
        try:
            for iteration in range(state.max_iterations):
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                state.iteration = iteration + 1
                before_evidence, before_sources = len(state.evidence), len(state.sources)
                slots = min(batch_size, state.max_searches - state.searches_performed)
                # Each wave is ready-only; dependent questions cannot overtake prerequisites.
                while slots > 0 and pending and len(state.sources) < state.max_sources:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    ready = [entry for entry in pending if all(all(dep in state.searched_sub_questions for dep in task_map[qid].depends_on) for qid in entry[2] if qid in task_map)]
                    wave = ready[:min(slots, state.max_parallel_tasks)]
                    if not wave:
                        break
                    for query, reason, qids in wave:
                        pending.remove((query, reason, qids))
                        state.searches_performed += 1
                        audit(state, "search", query, reason=reason, sub_question_ids=qids, iteration=state.iteration)
                        emit("search_started", f"Searching the web: {query}", {"query": query, "reason": reason, "iteration": state.iteration})
                    results = await asyncio.gather(*(bounded_call(executor, deadline, self._collect, query, state.filters.model_copy(deep=True), mode, deadline) for query, _, _ in wave), return_exceptions=True)
                    for (query, reason, qids), result in zip(wave, results):
                        if isinstance(result, TimeoutError):
                            raise result
                        if isinstance(result, BaseException):
                            audit(state, "search_failed", "Search could not complete", query=query, error=type(result).__name__)
                            emit("search_completed", "Search could not complete", {"query": query, "count": 0})
                            continue
                        count, candidates, filtered = result
                        state.searched_sub_questions = list(dict.fromkeys(state.searched_sub_questions + qids))
                        emit("search_completed", f"Found {count} search results", {"query": query, "count": count})
                        for item in filtered:
                            state.filtered_sources.append(item)
                            audit(state, "source_filtered", item["reason"], url=item["url"])
                            emit("source_filtered", item["reason"], item)
                        for source in candidates:
                            source.quality = score_source(source, state.question.question, mode)
                        candidates.sort(key=lambda source: (state.filters.prefer_primary and source.source_type in {"primary", "academic", "documentation"}, source.quality.total), reverse=True)
                        for source in candidates:
                            if source.url not in state.retrieved_urls:
                                state.retrieved_urls.append(source.url)
                            duplicate = next((old for old in state.sources if old.url == source.url or source.url in old.aliases or near_duplicate(old.content, source.content)), None)
                            if duplicate:
                                duplicate.sub_question_ids = list(dict.fromkeys(duplicate.sub_question_ids + qids))
                                duplicate.aliases = list(dict.fromkeys(duplicate.aliases + ([source.url] if source.url != duplicate.url else [])))
                                record = {"kind": "source", "from": source.url, "to": duplicate.id}
                                state.merge_records.append(record)
                                audit(state, "source_deduplicated", "Equivalent URL or near-identical content", **record)
                                continue
                            if len(state.sources) >= state.max_sources:
                                audit(state, "source_filtered", "Source budget reached", url=source.url)
                                continue
                            source.id, source.sub_question_ids = f"S{len(state.sources)+1}", qids
                            state.sources.append(source)
                            audit(state, "source_kept", source.title, source_id=source.id, url=source.url)
                            emit("source_found", f"Source discovered: {source.domain}", source.model_copy(deep=True))
                            emit("source_evaluated", f"Evaluated {source.title}", {"source_id": source.id, "quality": source.quality.model_dump(), "status": "evaluated"})
                    slots -= len(wave)
                if len(state.sources) > before_sources:
                    eligible = [source.model_copy(deep=True) for source in state.sources if source.quality and source.quality.relevance >= mode.relevance_threshold]
                    strategy = f"\nStrategy: {mode.strategy}\nTarget claims: {state.question.target_claims}\nComparison items: {state.question.comparison_items}\nSub-questions: {tasks}. Set finding.sub_question_ids ONLY for questions the quoted evidence addresses.\nExisting claims: {[(c.id, c.claim) for c in state.findings]}. Use unique new claim IDs; reference existing dependencies as existing:C1, etc. Include depends_on only for logical prerequisites. Excerpts must be verbatim."
                    result = await bounded_call(executor, deadline, self.extractor.extract_evidence, state.question.question, eligible, strategy)
                    merge_extraction(state, result)
                if state.mode == "fact_check":
                    for claim in state.question.target_claims:
                        if not any(near_duplicate(old.claim, claim, claim=True) for old in state.findings):
                            state.findings.append(Finding(id=f"C{len(state.findings)+1}", claim=claim, explanation="No matching evidence was extracted.", confidence=0, category="fact"))
                validate_evidence(state)
                for source in state.sources:
                    if source.id not in analyzed:
                        emit("source_analyzed", f"Analyzed {source.title}", {"source_id": source.id, "status": "analyzed" if not source.quality or source.quality.relevance >= mode.relevance_threshold else "below_relevance_threshold", "evidence_count": sum(item.source_id == source.id for item in state.evidence)})
                        analyzed.add(source.id)
                for item in state.evidence:
                    if item.id not in emitted_evidence:
                        emit("evidence_linked", "Validated source excerpt", item.model_copy(deep=True))
                        emitted_evidence.add(item.id)
                for finding in state.findings:
                    emit("finding_updated" if finding.id in emitted_claims else "finding_extracted", "Finding verified", finding.model_copy(deep=True))
                    emitted_claims.add(finding.id)
                state.evidence_gains.append(max(0, len(state.evidence) - before_evidence))
                coverage, gaps = coverage_gaps(state)
                state.unresolved_questions = list(dict.fromkeys(reason for _, reason, _ in gaps))
                state.elapsed_seconds = time.monotonic() - started
                decision = decide_stop(coverage=coverage, unresolved=state.unresolved_questions, gains=state.evidence_gains,
                    searches=state.searches_performed, sources=len(state.sources), iterations=state.iteration, elapsed=state.elapsed_seconds,
                    max_searches=state.max_searches, max_sources=state.max_sources, max_iterations=state.max_iterations, max_wall_seconds=state.max_wall_seconds)
                state.stop_decisions.append(decision)
                audit(state, "stop_decision", decision.reason, stop=decision.stop, coverage=coverage, unresolved=state.unresolved_questions)
                emit("research_progress", "Assessing iteration evidence", {"phase": "evidence", "progress": 20 + round(50 * state.iteration / state.max_iterations), "iteration": state.iteration})
                emit("research_snapshot", "Iteration complete", state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}}))
                if decision.stop:
                    break
                # Rebuild the worklist exclusively from measured gaps. Unsearched tasks go first.
                pending = [entry for entry in gaps if not any(qid in invalid for qid in entry[2])]
                pending.sort(key=lambda entry: any(qid in state.searched_sub_questions for qid in entry[2]))
                for query, reason, qids in pending:
                    audit(state, "expansion", "Targeted evidence gap", query=query, reason=reason, sub_question_ids=qids)
            assessment = await bounded_call(executor, deadline, self.llm.generate_structured,
                GAP_DETECTION.format(question=state.question.question, plan=state.plan, findings=state.findings), GapAssessment)
            generated_gaps = assessment.gaps if isinstance(assessment, GapAssessment) else list(assessment.get("gaps", []))
            state.gaps = list(dict.fromkeys(state.unresolved_questions + generated_gaps))
        except TimeoutError:
            self.record_timeout(state, started)
        except (ValueError, TypeError, RuntimeError) as exc:
            audit(state, "analysis_failed", "Continuing with validated evidence", error=type(exc).__name__)
            logger.warning("Evidence analysis stopped: %s", type(exc).__name__)
            state.unresolved_questions = [reason for _, reason, _ in coverage_gaps(state)[1]]
            state.gaps = list(dict.fromkeys(state.gaps + state.unresolved_questions))
            state.stop_decisions.append(StopDecision(stop=True, reason="Evidence analysis unavailable", coverage=coverage_gaps(state)[0], unresolved=state.unresolved_questions))
            audit(state, "stop_decision", "Evidence analysis unavailable", stop=True, unresolved=state.unresolved_questions)
        for rejection in state.citation_rejections:
            emit("citation_rejected", rejection.reason, rejection)
        for gap in state.gaps:
            emit("gap_detected", f"Research gap detected: {gap}", {"gap": gap})
        state.llm_requests_used = getattr(self.llm, "requests_used", state.llm_requests_used)
        state.status = "researched"
        return state

    @staticmethod
    def record_timeout(state, started):
        state.elapsed_seconds = time.monotonic() - started
        coverage, gaps = coverage_gaps(state)
        state.unresolved_questions = list(dict.fromkeys([reason for _, reason, _ in gaps] + ["Research ended before all analysis stages completed"]))
        decision = decide_stop(coverage=coverage, unresolved=state.unresolved_questions, gains=state.evidence_gains,
            searches=state.searches_performed, sources=len(state.sources), iterations=state.iteration, elapsed=state.max_wall_seconds,
            max_searches=state.max_searches, max_sources=state.max_sources, max_iterations=state.max_iterations, max_wall_seconds=state.max_wall_seconds)
        if not state.stop_decisions or state.stop_decisions[-1].reason != decision.reason:
            state.stop_decisions.append(decision)
            audit(state, "stop_decision", decision.reason, stop=True, unresolved=state.unresolved_questions)
        state.gaps = list(dict.fromkeys(state.gaps + state.unresolved_questions))
