"""Single-source task routing for the supported model providers."""

from typing import Final

QUESTION_ANALYSIS: Final = "question_analysis"
PLANNING: Final = "planning"
SOURCE_EXTRACTION: Final = "source_extraction"
SOURCE_SUMMARY: Final = "source_summary"
EVIDENCE_EXTRACTION: Final = "evidence_extraction"
DATA_EXTRACTION: Final = "data_extraction"
CLAIM_EXTRACTION: Final = "claim_extraction"
GAP_ANALYSIS: Final = "gap_analysis"
SOURCE_QUALITY: Final = "source_quality"
CONFLICT_ANALYSIS: Final = "conflict_analysis"
FACT_VERIFICATION: Final = "fact_verification"
EVIDENCE_EVALUATION: Final = "evidence_evaluation"
INDEPENDENT_REVIEW: Final = "independent_review"
FINAL_VERIFICATION: Final = "final_verification"
FINAL_SYNTHESIS: Final = "final_synthesis"
FINAL_REVIEW: Final = "final_review"
CHAT_RESPONSE: Final = "chat_response"

TASK_PROVIDER: Final[dict[str, str]] = {
    QUESTION_ANALYSIS: "gemini",
    PLANNING: "gemini",
    SOURCE_EXTRACTION: "groq",
    SOURCE_SUMMARY: "groq",
    EVIDENCE_EXTRACTION: "groq",
    DATA_EXTRACTION: "groq",
    CLAIM_EXTRACTION: "groq",
    GAP_ANALYSIS: "gemini",
    SOURCE_QUALITY: "groq",
    CONFLICT_ANALYSIS: "gemini",
    FACT_VERIFICATION: "mistral",
    EVIDENCE_EVALUATION: "gemini",
    INDEPENDENT_REVIEW: "mistral",
    FINAL_VERIFICATION: "gemini",
    FINAL_SYNTHESIS: "gemini",
    FINAL_REVIEW: "mistral",
    CHAT_RESPONSE: "gemini",
}
