"""Evidence and claim extraction."""

import logging
from concurrent.futures import ThreadPoolExecutor
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
        prompt = CLAIM_EXTRACTION.format(question=question, source_id=source.id, content=source.content[:30_000])
        try:
            result = invoke_structured(self.llm, prompt, ClaimExtraction, task=SOURCE_EXTRACTION)
            return result.findings
        except (ValueError, TypeError) as exc:
            logger.warning("Claim extraction failed for %s: %s", source.url, exc)
            return []

    def extract_many(self, question: str, sources: list[Source]) -> list[Finding]:
        return self.extract_evidence(question, sources).findings

    def extract_evidence(self, question: str, sources: list[Source], strategy: str = "") -> ClaimExtraction:
        if not sources:
            return ClaimExtraction()
        if getattr(self.llm, "supports_task_routing", False):
            merged = ClaimExtraction()
            # Bounded batches share context once; one failed batch cannot erase prior results.
            for offset in range(0, len(sources), 3):
                batch = sources[offset:offset + 3]
                text = "\n\n".join(f"--- {source.id} | {source.title} ---\nSub-questions: {source.sub_question_ids}\n{source.content[:10000]}" for source in batch)
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
            f"--- {source.id} | {source.title} | {source.url} ---\nRetrieved for sub-questions: {source.sub_question_ids}\n{source.content[:5_000]}"
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

        def extract_one(source: Source) -> DataPointExtraction:
            try:
                return invoke_structured(
                    self.llm,
                    DATA_POINT_EXTRACTION.format(question=question, source_id=source.id, content=source.content[:30_000]),
                    DataPointExtraction,
                    task=DATA_EXTRACTION,
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                logger.warning("Data-point extraction failed for %s: %s", source.url, type(exc).__name__)
                return DataPointExtraction()

        with ThreadPoolExecutor(max_workers=min(3, len(sources))) as executor:
            batches = list(executor.map(extract_one, sources))
        for batch in batches:
            for point in batch.data_points:
                source = next((item for item in sources if item.id == point.source_id), None)
                if not source or not point.quote or point.quote not in source.content:
                    continue
                point.id = point.id or f"DP{len(state.data_points) + 1}"
                state.data_points.append(point)
                if not any(item.source_id == point.source_id and item.excerpt == point.quote for item in state.evidence):
                    state.evidence.append(Evidence(
                        id=f"{point.id}-evidence", source_id=point.source_id, excerpt=point.quote,
                        relation="context", strength="direct",
                    ))
