"""Evidence and claim extraction."""

import logging
from app.llm import LLMClient
from app.models import ClaimExtraction, Finding, Source, ResearchState
from app.evidence import validate_evidence, merge_extraction
from app.modes import MODES
from app.prompts import BATCH_CLAIM_EXTRACTION, CLAIM_EXTRACTION

logger = logging.getLogger(__name__)


class Extractor:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def extract(self, question: str, source: Source) -> list[Finding]:
        prompt = CLAIM_EXTRACTION.format(question=question, source_id=source.id, content=source.content[:30_000])
        try:
            result = self.llm.generate_structured(prompt, ClaimExtraction)
            return result.findings
        except (ValueError, TypeError) as exc:
            logger.warning("Claim extraction failed for %s: %s", source.url, exc)
            return []

    def extract_many(self, question: str, sources: list[Source]) -> list[Finding]:
        return self.extract_evidence(question, sources).findings

    def extract_evidence(self, question: str, sources: list[Source], strategy: str = "") -> ClaimExtraction:
        if not sources:
            return ClaimExtraction()
        source_text = "\n\n".join(
            f"--- {source.id} | {source.title} | {source.url} ---\nRetrieved for sub-questions: {source.sub_question_ids}\n{source.content[:5_000]}"
            for source in sources
        )[:50_000]
        try:
            result = self.llm.generate_structured(
                BATCH_CLAIM_EXTRACTION.format(question=question, sources=source_text) + strategy,
                ClaimExtraction,
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
