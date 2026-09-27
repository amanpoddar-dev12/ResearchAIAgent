"""Bounded iterative research loop."""

import logging
from urllib.parse import urlsplit
from app.extractor import Extractor
from app.models import GapAssessment, ResearchState, Source
from app.prompts import GAP_DETECTION
from app.llm import LLMClient, LLMRequestBudgetExceeded
from tools.web_search import search_web
from tools.webpage import fetch_webpage

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(self, llm: LLMClient, tavily_key: str, max_searches: int, max_sources: int, max_iterations: int) -> None:
        self.llm, self.tavily_key = llm, tavily_key
        self.max_searches, self.max_sources, self.max_iterations = max_searches, max_sources, max_iterations
        self.extractor = Extractor(llm)

    def run(self, state: ResearchState, emit=None) -> ResearchState:
        emit = emit or (lambda *_args: None)
        state.status = "researching"
        if not state.plan:
            raise ValueError("Research plan is required")
        queries = list(state.plan.search_queries)
        for iteration in range(self.max_iterations):
            if not queries or state.searches_performed >= self.max_searches or len(state.sources) >= self.max_sources:
                break
            state.iteration = iteration + 1
            query = queries.pop(0)
            emit("search_started", f"Searching the web: {query}", {"query": query})
            results = search_web(self.tavily_key, query)
            state.searches_performed += 1
            emit("search_completed", f"Found {len(results)} search results", {"query": query, "count": len(results)})
            for result in results:
                if len(state.sources) >= self.max_sources:
                    break
                if any(source.url == result.url for source in state.sources):
                    continue
                content = result.content or fetch_webpage(result.url)
                source = Source(
                    id=f"S{len(state.sources) + 1}", title=result.title, url=result.url,
                    domain=urlsplit(result.url).netloc, content=content,
                    publication_date=result.published_date,
                    search_query=query,
                )
                state.sources.append(source)
                emit("source_found", f"Source discovered: {source.domain}", source)
        try:
            state.findings = self.extractor.extract_many(
                state.question.question, state.sources
            ) if hasattr(self.extractor, "extract_many") else [
                finding
                for source in state.sources
                for finding in self.extractor.extract(state.question.question, source)
            ]
            for finding in state.findings:
                emit("finding_extracted", "Finding extracted", finding)
            assessment = self.llm.generate_structured(
                GAP_DETECTION.format(question=state.question.question, plan=state.plan, findings=state.findings),
                GapAssessment,
            )
            state.gaps = assessment.gaps if isinstance(assessment, GapAssessment) else list(assessment.get("gaps", []))
            for gap in state.gaps:
                emit("gap_detected", f"Research gap detected: {gap}", {"gap": gap})
        except LLMRequestBudgetExceeded as exc:
            logger.warning("%s", exc)
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.warning("Evidence analysis failed: %s", type(exc).__name__)
        state.llm_requests_used = getattr(self.llm, "requests_used", state.llm_requests_used)
        state.status = "researched"
        return state
