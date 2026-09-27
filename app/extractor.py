"""Evidence and claim extraction."""

import logging
from app.llm import LLMClient
from app.models import ClaimExtraction, Finding, Source
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
        if not sources:
            return []
        source_text = "\n\n".join(
            f"--- {source.id} | {source.title} | {source.url} ---\n{source.content[:5_000]}"
            for source in sources
        )[:50_000]
        try:
            result = self.llm.generate_structured(
                BATCH_CLAIM_EXTRACTION.format(question=question, sources=source_text),
                ClaimExtraction,
            )
            valid_ids = {source.id for source in sources}
            return [finding for finding in result.findings if set(finding.source_ids) <= valid_ids]
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.warning("Batch claim extraction failed: %s", type(exc).__name__)
            return []
