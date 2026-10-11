"""Evidence and claim extraction."""
from app.research_depth import select_passages

import logging
import re
from app.llm import LLMClient, invoke_structured
from app.llm.routing import CLAIM_EXTRACTION, DATA_EXTRACTION, EVIDENCE_EXTRACTION, SOURCE_EXTRACTION, SOURCE_SUMMARY
from app.models import ClaimExtraction, DataPoint, DataPointExtraction, Evidence, Finding, Source, ResearchState, SourceSummary
from app.evidence import validate_evidence, merge_extraction
from app.modes import MODES
from app.prompts import BATCH_CLAIM_EXTRACTION, CLAIM_EXTRACTION, DATA_POINT_EXTRACTION, SOURCE_SUMMARY as SOURCE_SUMMARY_PROMPT

logger = logging.getLogger(__name__)


class Extractor:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def extract(self, question: str, source: Source) -> list[Finding]:
        prompt = CLAIM_EXTRACTION.format(question=question, source_id=source.id, content=select_passages(source.content, question, 30000))
        try:
            result = invoke_structured(self.llm, prompt, ClaimExtraction, task=SOURCE_EXTRACTION)
            return result.findings
        except (ValueError, TypeError) as exc:
            logger.warning("Claim extraction failed (%s)", type(exc).__name__)
            return []

    def extract_many(self, question: str, sources: list[Source]) -> list[Finding]:
        return self.extract_evidence(question, sources).findings

    def extract_quantitative(self, question: str, sources: list[Source]) -> DataPointExtraction:
        """One bounded model call; the coordinator validates and commits returned values."""
        selected = [source for source in sources if re.search(r'\d', source.content)][:4]
        if not selected:
            return DataPointExtraction()
        text = '\n\n'.join(f'--- {source.id} | {source.title} ---\n{select_passages(source.content, question, 5000, numerical=True)}' for source in selected)
        try:
            result = invoke_structured(self.llm, DATA_POINT_EXTRACTION.format(
                question=question, source_id=', '.join(source.id for source in selected), content=text)
                + '\nExtract at most 20 relevant observations across these sources. Use only supplied source IDs. '
                  'Keep each metric label and unit consistent and preserve population, geography, measurement period and definition. '
                  'Do not combine different studies or treat publication years as observation years. '
                  'Return an empty data_points array when useful measurements are absent.', DataPointExtraction, task=DATA_EXTRACTION)
            allowed = {source.id for source in selected}
            return DataPointExtraction(data_points=[point for point in result.data_points if point.source_id in allowed][:20])
        except (RuntimeError, ValueError, TypeError, TimeoutError):
            logger.warning('Dedicated numerical extraction unavailable; continuing with collected evidence')
            return DataPointExtraction()

    def extract_evidence(self, question: str, sources: list[Source], strategy: str = "") -> ClaimExtraction:
        if not sources:
            return ClaimExtraction()
        if getattr(self.llm, "supports_task_routing", False):
            merged = ClaimExtraction()
            # Bounded batches share context once; one failed batch cannot erase prior results.
            for offset in range(0, len(sources), 3):
                batch = sources[offset:offset + 3]
                text = "\n\n".join(f"--- {source.id} | {source.title} ---\nSub-questions: {source.sub_question_ids}\n{select_passages(source.content, question + " " + strategy, 10000)}" for source in batch)
                try:
                    result = invoke_structured(self.llm, BATCH_CLAIM_EXTRACTION.format(question=question, sources=text) + strategy,
                                               ClaimExtraction, task=EVIDENCE_EXTRACTION)
                except (RuntimeError, ValueError, TypeError, TimeoutError):
                    logger.warning("Extraction unavailable for batch %s", offset // 3)
                    continue
                prefix = f"batch{offset}:"
                claim_ids = {claim.id for claim in result.findings}
                for item in result.evidence:
                    item.id = prefix + item.id
                for claim in result.findings:
                    claim.id = prefix + claim.id
                    claim.evidence_ids = [prefix + key for key in claim.evidence_ids]
                    claim.depends_on = [prefix + key if key in claim_ids else key for key in claim.depends_on]
                merged.findings.extend(result.findings)
                merged.evidence.extend(result.evidence)
                merged.data_points.extend(result.data_points)
                merged.processed_source_ids.extend(source.id for source in batch)
            return merged
        source_text = "\n\n".join(
            f"--- {source.id} | {source.title} | {source.url} ---\nRetrieved for sub-questions: {source.sub_question_ids}\n{select_passages(source.content, question + " " + strategy, 5000)}"
            for source in sources
        )[:50_000]
        try:
            result = invoke_structured(self.llm,
                BATCH_CLAIM_EXTRACTION.format(question=question, sources=source_text) + strategy,
                ClaimExtraction, task=SOURCE_EXTRACTION,
            )
            return result
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.warning("Batch claim extraction failed: %s", type(exc).__name__)
            return ClaimExtraction()

    def extract_session(self, state: ResearchState) -> None:
        mode = MODES[state.mode]
        eligible = [source for source in state.sources if source.quality and source.quality.relevance >= mode.relevance_threshold]
        result = self.extract_evidence(state.question.question, eligible,
            f"\nStrategy: {mode.strategy}\nTarget claims: {state.question.target_claims}\nComparison items: {state.question.comparison_items}")
        merge_extraction(state, result)
        # Keep every explicit fact-check target visible even when there is no evidence.
        if state.mode == "fact_check":
            for claim in state.question.target_claims:
                if not any(finding.claim.strip().casefold() == claim.strip().casefold() for finding in state.findings):
                    state.findings.append(Finding(claim=claim, explanation="No matching evidence was extracted for this claim.", confidence=0, category="fact"))
        validate_evidence(state)
        self.extract_data_points(state.question.question, eligible, state)

    def extract_data_points(self, question: str, sources: list[Source], state: ResearchState) -> None:
        if not sources or not getattr(self.llm, "supports_task_routing", False):
            return
        result = self.extract_quantitative(question, sources)
        merge_extraction(state, ClaimExtraction(data_points=result.data_points))
