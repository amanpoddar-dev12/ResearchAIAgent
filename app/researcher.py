"""Bounded iterative research; workers return values, one coordinator commits them."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
import math
import time
from urllib.parse import urlsplit
from app.extractor import Extractor
from app.models import GapAssessment, ResearchGap, ResearchState, Source, SubQuestion, Finding, StopDecision, EvidenceAssessmentBatch, SearchResult, ClaimExtraction
from app.prompts import GAP_DETECTION, EVIDENCE_EVALUATION
from app.llm import LLMClient, invoke_structured
from app.llm.routing import GAP_ANALYSIS
from tools.web_search import search_web, normalize_url
from tools.webpage import fetch_webpage
from app.modes import MODES
from app.source_quality import filter_reason, infer_source_type, score_source, independent_source_count
from app.deduplication import near_duplicate
from app.evidence import merge_extraction, validate_evidence, apply_assessments
from app.research_control import audit, bounded_call, coverage_gaps, decide_stop

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(self, llm: LLMClient, tavily_key: str, max_searches: int, max_sources: int, max_iterations: int,
                 additional_research_rounds: int = 2) -> None:
        self.llm, self.tavily_key = llm, tavily_key
        self.max_searches, self.max_sources, self.max_iterations = max_searches, max_sources, max_iterations
        self.additional_research_rounds = additional_research_rounds
        self.extractor = Extractor(llm)

    def run(self, state: ResearchState, emit=None) -> ResearchState:
        executor = ThreadPoolExecutor(max_workers=state.max_parallel_tasks)
        started = time.monotonic()
        try:
            return asyncio.run(self.run_async(state, emit, executor, started, started + state.max_wall_seconds))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _collect(self, query, filters, mode, deadline, known_sources=None):
        """No shared state or events are accessible to this worker."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        linked_reference = query.startswith(("https://", "http://"))
        results = ([SearchResult(title="Linked document reference", url=query, content="", source_domain=urlsplit(query).netloc)]
                   if linked_reference else search_web(self.tavily_key, query, search_depth=mode.search_depth, timeout=min(20, remaining), filters=filters))
        candidates, filtered = [], []
        # Spend document-fetch latency on the strongest discovery candidates first.
        def priority(result):
            try:
                normalize_url(result.url)
            except ValueError:
                return -1
            candidate = Source(id="", title=result.title, url=result.url, domain=urlsplit(result.url).netloc,
                               content=result.content, publication_date=result.published_date)
            candidate.source_type = infer_source_type(candidate)
            return score_source(candidate, query, mode).total
        results = sorted(results, key=priority, reverse=True)
        fetches = 0
        for result in results:
            try:
                url = normalize_url(result.url)
            except ValueError:
                filtered.append({"url": result.url, "reason": "Invalid retrieved URL"})
                continue
            if known_sources and url in known_sources:
                candidates.append(known_sources[url].model_copy(deep=True))
                continue
            source = Source(id="", title=result.title, url=url, domain=urlsplit(url).netloc,
                content=result.content, publication_date=result.published_date, search_query=query,
                retrieved_at=datetime.now(timezone.utc).isoformat(), retrieval_method="search")
            source.original_url = result.url
            source.discovery_snippet = result.content
            source.source_type = infer_source_type(source)
            preliminary = filters.model_copy(update={"date_from": None, "date_to": None, "source_types": []})
            reason = filter_reason(source, preliminary)
            if reason:
                filtered.append({"url": url, "reason": reason})
                continue
            if not source.content or (getattr(self.llm, "supports_task_routing", False) and fetches < (1 if mode.label == "Quick" else 3)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                metadata = {}
                fetches += 1
                document = fetch_webpage(result.url, timeout=min(10, remaining), metadata=metadata)
                if document:
                    source.content = document
                    source.retrieval_method = "fetch"
                    source.publication_date = metadata.get("publication_date") or source.publication_date
                    source.primary_basis = metadata.get("primary_basis")
                    source.reference_urls = metadata.get("reference_urls", [])
                    source.title = metadata.get("title") or source.title
                    source.source_type = infer_source_type(source)
                elif linked_reference:
                    filtered.append({"url": url, "reason": "Linked document could not be retrieved"})
                    continue
            reason = filter_reason(source, filters)
            if reason:
                filtered.append({"url": url, "reason": reason})
                continue
            candidates.append(source)
        return len(results), candidates, filtered

    async def run_async(self, state, emit, executor, started, deadline):
        emit = emit or (lambda *_args: None)
        if not state.plan:
            raise ValueError("Research plan is required")
        state.status, state.provenance_required = "researching", True
        state.semantic_validation_required = bool(getattr(self.llm, "supports_task_routing", False))
        mode = MODES[state.mode]
        state.max_searches = min(self.max_searches, state.budget_overrides.max_searches or mode.queries)
        state.max_sources = min(self.max_sources, state.budget_overrides.max_sources or state.max_sources)
        state.max_iterations = min(self.max_iterations, state.budget_overrides.max_iterations or mode.iterations)
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
        gap_rounds = 0
        quantitative_passes = 0
        try:
            for iteration in range(state.max_iterations):
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                state.iteration = iteration + 1
                before_evidence = sum(len(c.supporting_evidence_ids) + len(c.contradicting_evidence_ids) for c in state.findings)
                before_sources = len(state.sources)
                # Keep room for evidence-driven follow-ups without raising any budget.
                remaining_rounds = min(state.max_iterations - iteration, state.max_searches - state.searches_performed)
                round_source_limit = min(state.max_sources, before_sources + math.ceil(
                    (state.max_sources - before_sources) / max(1, remaining_rounds)))
                slots = min(batch_size, state.max_searches - state.searches_performed)
                # Each wave is ready-only; dependent questions cannot overtake prerequisites.
                while slots > 0 and pending and len(state.sources) < round_source_limit:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    satisfied = set(state.searched_sub_questions)
                    if state.semantic_validation_required:
                        satisfied = {qid for claim in state.findings if claim.evidence_status in {"Supported", "Contradicted"}
                                     and independent_source_count([source for source in state.sources if source.id in claim.source_ids]) >= (1 if state.mode == "quick" else 2)
                                     for qid in claim.sub_question_ids}
                    ready = [entry for entry in pending if entry[0].strip().casefold() not in state.searched_queries and all(all(dep in satisfied for dep in task_map[qid].depends_on) for qid in entry[2] if qid in task_map)]
                    wave = ready[:min(slots, state.max_parallel_tasks)]
                    if not wave:
                        break
                    for query, reason, qids in wave:
                        pending.remove((query, reason, qids))
                        state.searches_performed += 1
                        state.searched_queries.append(query.strip().casefold())
                        audit(state, "search", query, reason=reason, sub_question_ids=qids, iteration=state.iteration)
                        emit("search_started", f"Searching the web: {query}", {"query": query, "reason": reason, "iteration": state.iteration})
                    known_sources = {source.url: source.model_copy(deep=True) for source in state.sources}
                    results = await asyncio.gather(*(bounded_call(executor, deadline, self._collect, query, state.filters.model_copy(deep=True), mode, deadline, known_sources) for query, _, _ in wave), return_exceptions=True)
                    wave_candidates = []
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
                            source.relevance_score = source.quality.relevance
                            source.authority_score = source.quality.authority
                            source.freshness_score = source.quality.freshness
                            source.quality_score_value = source.quality.total
                            wave_candidates.append((source, qids))
                    # Rank the whole parallel wave before spending the source cap.
                    used_domains = {source.domain for source in state.sources}
                    wave_candidates.sort(key=lambda entry: (state.filters.prefer_primary and entry[0].source_type in {"primary", "academic", "documentation"}, entry[0].quality.total + (.05 if entry[0].source_type in {"primary", "academic", "documentation"} else 0), entry[0].domain not in used_domains), reverse=True)
                    for source, qids in wave_candidates:
                        if source.quality.relevance < mode.relevance_threshold:
                            state.filtered_sources.append({"url": source.url, "reason": "Below relevance threshold"})
                            continue
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
                        if len(state.sources) >= round_source_limit:
                            audit(state, "source_filtered", "Source capacity reserved for follow-up evidence", url=source.url)
                            continue
                        source.id, source.sub_question_ids = f"S{len(state.sources)+1}", qids
                        state.sources.append(source)
                        audit(state, "source_kept", source.title, source_id=source.id, url=source.url)
                        emit("source_found", f"Source discovered: {source.domain}", source.model_copy(deep=True))
                        emit("source_evaluated", f"Evaluated {source.title}", {"source_id": source.id, "quality": source.quality.model_dump(), "status": "evaluated"})
                    slots -= len(wave)
                if len(state.sources) > before_sources:
                    eligible = [source.model_copy(deep=True) for source in state.sources if source.id not in state.extraction_completed and source.quality and source.quality.relevance >= mode.relevance_threshold]
                    if quantitative_passes < 2 and not state.data_points and state.semantic_validation_required and any(any(char.isdigit() for char in source.content) for source in eligible):
                        spare = getattr(self.llm, 'max_requests', float('inf')) - getattr(self.llm, 'requests_used', 0) - getattr(self.llm, 'reserved_final_calls', 0)
                        if spare >= 2:
                            quantitative_passes += 1
                            emit('research_progress', 'Extracting source-backed numerical data', {'phase': 'evidence', 'progress': 35})
                            numeric = await bounded_call(executor, deadline, self.extractor.extract_quantitative, state.question.refined_question or state.question.question, eligible)
                            before_points = len(state.data_points)
                            merge_extraction(state, ClaimExtraction(data_points=numeric.data_points))
                            audit(state, 'data_extraction', 'Dedicated numerical pass completed', accepted=len(state.data_points) - before_points, proposed=len(numeric.data_points))
                        else:
                            audit(state, 'data_extraction', 'Numerical pass skipped to preserve evidence and final report budget')
                    strategy = f"\nStrategy: {mode.strategy}\nTarget claims: {state.question.target_claims}\nComparison items: {state.question.comparison_items}\nSub-questions: {tasks}. Set finding.sub_question_ids ONLY for questions the quoted evidence addresses.\nExisting claims: {[(c.id, c.claim) for c in state.findings]}. Use unique new claim IDs; reference existing dependencies as existing:C1, etc. Include depends_on only for logical prerequisites. Excerpts must be verbatim."
                    result = await bounded_call(executor, deadline, self.extractor.extract_evidence, state.question.question, eligible, strategy)
                    merge_extraction(state, result)
                    state.extraction_completed.extend(result.processed_source_ids if getattr(self.llm, "supports_task_routing", False) else [source.id for source in eligible])
                    if getattr(self.llm, "supports_task_routing", False):
                        claims = [{"claim_id": claim.id, "claim": claim.claim,
                                   "evidence": [item.model_dump() for item in state.evidence if item.id in claim.evidence_ids and item.id not in {review.evidence_id for review in claim.evidence_assessments}]}
                                  for claim in state.findings]
                        claims = [claim for claim in claims if claim["evidence"]][:30]
                        if claims:
                            try:
                                assessment = await bounded_call(executor, deadline, invoke_structured, self.llm,
                                    EVIDENCE_EVALUATION.format(claims=claims), EvidenceAssessmentBatch, task="evidence_evaluation")
                                apply_assessments(state, assessment)
                            except (RuntimeError, ValueError, TimeoutError):
                                audit(state, "verification_unavailable", "Unreviewed paraphrases remain Unverified")
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
                        emit("evidence_found", "Evidence passage extracted", item.model_copy(deep=True))
                        emitted_evidence.add(item.id)
                for finding in state.findings:
                    emit("finding_updated" if finding.id in emitted_claims else "finding_extracted", "Finding verified", finding.model_copy(deep=True))
                    emit("claim_extracted", "Claim extracted from evidence", finding.model_copy(deep=True))
                    emitted_claims.add(finding.id)
                useful_evidence = sum(len(c.supporting_evidence_ids) + len(c.contradicting_evidence_ids) for c in state.findings)
                state.evidence_gains.append(max(0, useful_evidence - before_evidence))
                coverage, gaps = coverage_gaps(state)
                state.unresolved_questions = list(dict.fromkeys(reason for _, reason, _ in gaps))
                state.elapsed_seconds = time.monotonic() - started
                decision = decide_stop(coverage=coverage, unresolved=state.unresolved_questions, gains=state.evidence_gains,
                    searches=state.searches_performed, sources=len(state.sources), iterations=state.iteration, elapsed=state.elapsed_seconds,
                    max_searches=state.max_searches, max_sources=state.max_sources, max_iterations=state.max_iterations, max_wall_seconds=state.max_wall_seconds,
                    plateau_window=2 if state.semantic_validation_required and hasattr(self.llm, "reserved_final_calls") else 4)
                if not decision.stop and state.semantic_validation_required and getattr(self.llm, "requests_used", 0) >= getattr(self.llm, "max_requests", float("inf")) - getattr(self.llm, "reserved_final_calls", 0):
                    decision.stop, decision.reason = True, "LLM collection budget exhausted; reserved final review and synthesis"
                state.stop_decisions.append(decision)
                audit(state, "stop_decision", decision.reason, stop=decision.stop, coverage=coverage, unresolved=state.unresolved_questions)
                emit("research_progress", "Assessing iteration evidence", {"phase": "evidence", "progress": 20 + round(50 * state.iteration / state.max_iterations), "iteration": state.iteration})
                emit("research_snapshot", "Iteration complete", state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}}))
                if decision.stop:
                    break
                follow_up_queries, targeted = [], []
                if getattr(self.llm, "supports_task_routing", False) and gap_rounds < self.additional_research_rounds:
                    assessment = await bounded_call(executor, deadline, invoke_structured, self.llm,
                        GAP_DETECTION.format(question=state.question.question, plan=state.plan, findings=state.findings) + f"\nCompleted queries: {state.searched_queries}\nMeasured evidence gaps: {gaps}",
                        GapAssessment, task=GAP_ANALYSIS)
                    follow_up_queries = assessment.follow_up_queries
                    unresolved_ids = {qid for _, _, ids in gaps for qid in ids}
                    targeted = [(item.query, item.reason, [qid for qid in item.sub_question_ids if qid in unresolved_ids]) for item in sorted(assessment.targeted_queries, key=lambda item: {"high": 0, "medium": 1, "low": 2}[item.priority])]
                    targeted = [entry for entry in targeted if entry[2]]
                    gap_rounds += 1
                # Rebuild the worklist exclusively from measured gaps. Unsearched tasks go first.
                pending = [entry for entry in gaps if not any(qid in invalid for qid in entry[2])]
                unanswered = [task.id for task in tasks if any(task.id in entry[2] for entry in gaps)]
                if state.semantic_validation_required:
                    references = [(url, "Follow a retrieved document reference to address an evidence gap", [qid for qid in source.sub_question_ids if qid in unanswered])
                                  for source in state.sources for url in source.reference_urls]
                    pending = [entry for entry in references if entry[2]] + pending
                pending.extend((query, "LLM-detected evidence gap", unanswered[:1]) for query in follow_up_queries if query.strip())
                if targeted:
                    pending = targeted + pending
                unique = {}
                for entry in pending:
                    key = entry[0].strip().casefold()
                    if key and key not in state.searched_queries:
                        unique.setdefault(key, entry)
                pending = list(unique.values())
                pending.sort(key=lambda entry: any(qid in state.searched_sub_questions for qid in entry[2]))
                for query, reason, qids in pending:
                    audit(state, "expansion", "Targeted evidence gap", query=query, reason=reason, sub_question_ids=qids)
            generated_gaps = []
            if not state.semantic_validation_required or not hasattr(self.llm, "reserved_final_calls"):
                assessment = await bounded_call(executor, deadline, invoke_structured, self.llm,
                    GAP_DETECTION.format(question=state.question.question, plan=state.plan, findings=state.findings), GapAssessment,
                    task=GAP_ANALYSIS)
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
            emit("research_gap_detected", f"Research gap detected: {gap}", {"gap": gap})
        state.research_gaps = [
            ResearchGap(gap_id=f"G{index}", description=gap, importance="high" if "Unverified" in gap or "no evidence" in gap.lower() else "medium",
                        reason=gap, recommended_search=gap.split(":", 1)[-1].strip())
            for index, gap in enumerate(state.gaps, 1)
        ]
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
