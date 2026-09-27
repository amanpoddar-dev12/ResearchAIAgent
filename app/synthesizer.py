"""Report drafting and citation rendering."""

import logging
from app.llm import LLMClient
from app.models import ConflictAssessment, ReportDraft, ResearchState
from app.prompts import CONFLICT_DETECTION, SYNTHESIS

logger = logging.getLogger(__name__)


class Synthesizer:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def detect_conflicts(self, state: ResearchState) -> ConflictAssessment:
        return self.llm.generate_structured(
            CONFLICT_DETECTION.format(findings=state.findings), ConflictAssessment
        )

    def draft(self, state: ResearchState) -> ReportDraft:
        try:
            return self.llm.generate_structured(
                SYNTHESIS.format(
                    question=state.question.question, plan=state.plan, sources=state.sources,
                    findings=state.findings, conflicts=state.conflicts, gaps=state.gaps,
                ),
                ReportDraft,
            )
        except (RuntimeError, ValueError) as exc:
            logger.warning("Using evidence-only fallback report: %s", exc)
            return ReportDraft(
                title=f"Research Report: {state.question.question}",
                executive_summary="The available sources were collected, but Gemini did not return a structured synthesis.",
                key_findings=[
                    f"{finding.claim} [{finding.source_ids[0]}]"
                    for finding in state.findings if finding.source_ids
                ],
                detailed_analysis=[],
                limitations=state.gaps or ["Structured synthesis was unavailable; review the source list directly."],
                conclusion="The available evidence is listed above and should be reviewed directly before drawing conclusions.",
            )


def render_report(draft: ReportDraft, state: ResearchState) -> str:
    citation_numbers = {source.id: str(number) for number, source in enumerate(state.sources, 1)}

    def citations(text: str) -> str:
        for source_id, number in citation_numbers.items():
            text = text.replace(f"[{source_id}]", f"[{number}]")
        return text
    lines = [f"# {draft.title}", "", "## Executive Summary", draft.executive_summary, "", "## Key Findings"]
    lines.extend(f"- {citations(item)}" for item in draft.key_findings)
    lines.extend(["", "## Detailed Analysis"])
    lines.extend(f"- {citations(item)}" for item in draft.detailed_analysis)
    if state.conflicts:
        lines.extend(["", "## Conflicting Information"])
        lines.extend(f"- {c.topic}: {c.explanation}" for c in state.conflicts)
    lines.extend(["", "## Evidence"])
    lines.extend(f"- {citations(item)}" for item in draft.detailed_analysis)
    lines.extend(["", "## Research Limitations"])
    lines.extend(f"- {item}" for item in draft.limitations or state.gaps)
    lines.extend(["", "## Conclusion", draft.conclusion, "", "## Sources"])
    for number, source in enumerate(state.sources, 1):
        lines.append(f"[{number}] {source.title} — [{source.url}]({source.url})")
    return "\n".join(lines) + "\n"
