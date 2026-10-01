"""Report drafting and citation rendering."""

import logging
import json
import re
from app.llm import LLMClient
from app.models import ConflictAssessment, ReportDraft, ResearchState
from app.prompts import CONFLICT_DETECTION, SYNTHESIS
from app.modes import MODES
from app.evidence import reject, source_rejection

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
                    question=state.question.question, plan=state.plan, sources=[source.model_dump(exclude={"content"}) for source in state.sources],
                    findings=state.findings, conflicts=state.conflicts, gaps=state.gaps,
                ) + f"\nMode: {MODES[state.mode].strategy}\nValidated excerpts: {state.evidence}\nRespect derived evidence_status; do not upgrade unverified claims.",
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
    if state.provenance_required:
        # Free-form model summaries cannot establish provenance. Summarize validated
        # claim records and keep unsupported claims visibly Unverified instead.
        if draft.executive_summary or draft.key_findings or draft.detailed_analysis:
            reject(state, "report", "Free-form model prose replaced by traceable claim records")
        draft = ReportDraft(title=f"Research Report: {state.question.question}",
            executive_summary="\n".join(f"- {finding.claim} — {finding.evidence_status} " + " ".join(f"[{sid}]" for sid in finding.source_ids) for finding in state.findings if finding.evidence_ids) or "No traceable evidence was extracted; the question remains Unverified.",
            limitations=state.gaps + state.unresolved_questions, conclusion="")
    citation_numbers = {source.id: str(number) for number, source in enumerate(state.sources, 1)}
    sources = {source.id: source for source in state.sources}
    mode = MODES[state.mode]

    def citations(text: str) -> str:
        def replace_token(token: str) -> str:
            source_id = token if token.startswith("S") else next((key for key, value in citation_numbers.items() if value == token), token)
            source = sources.get(source_id)
            reason = "Nonexistent source" if source is None else "Source below relevance threshold" if source.quality and source.quality.relevance < mode.relevance_threshold else None
            if not reason and state.provenance_required:
                reason = source_rejection(state, source_id)
                if not reason and not any(item.source_id == source_id for item in state.evidence):
                    reason = "Citation has no validated supporting excerpt"
            if reason:
                reject(state, "report", reason, source_id)
                return "[citation rejected]"
            if source.quality is None:
                reject(state, "report", "Legacy citation: quality unavailable; unverified", source_id)
            return f"[{citation_numbers[source_id]}]"
        # Strip arbitrary links from model prose; source URLs are rendered from collected metadata below.
        def link(match):
            reject(state, "report", "Model-supplied URL removed; URLs must come from retrieved source metadata")
            return "[" + match.group(1) + "]" if re.fullmatch(r"(?:S\d+|\d+)(?:\s*[,;]\s*(?:S\d+|\d+))*", match.group(1)) else match.group(1)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", link if state.provenance_required else lambda match: "[" + match.group(1) + "]" if re.fullmatch(r"(?:S\d+|\d+)(?:\s*[,;]\s*(?:S\d+|\d+))*", match.group(1)) else match.group(1), text)
        if state.provenance_required:
            def url(match):
                reject(state, "report", "Untraceable prose URL removed")
                return "[URL removed]"
            text = re.sub(r"https?://[^\s<>]+", url, text)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        return re.sub(r"\[((?:S\d+|\d+)(?:\s*[,;]\s*(?:S\d+|\d+))*)\]", lambda match: " ".join(replace_token(token.strip()) for token in re.split(r"[,;]", match.group(1))), text)

    lines = [f"# {citations(draft.title.replace(chr(10), ' '))}", "", "## Executive Summary", citations(draft.executive_summary), "",
        "## Methodology", f"Mode: {mode.label}. {mode.strategy}",
        f"Filters applied: {json.dumps(state.filters.model_dump(mode='json'), ensure_ascii=False)}",
        f"Source count: {len(state.sources)} retained; {len(state.filtered_sources)} filtered out. Searches: {state.searches_performed}. Iterations: {state.iteration}.",
        f"Budgets: {state.max_searches} searches; {state.max_sources} sources; {state.max_iterations} iterations; {state.max_parallel_tasks} parallel tasks; {state.max_wall_seconds:g} seconds.",
        "Research scope: " + citations(state.question.refined_question or state.question.question),
        "Assumptions: " + citations("; ".join(state.question.assumptions) or "None added."),
        f"Quality weights: {json.dumps(mode.weights.model_dump())}. Citation relevance threshold: {mode.relevance_threshold:.0%}.",
        "Scores are heuristic estimates, not verified reliability: lexical overlap, domain/type authority proxy, freshness, mode preference and available text length. Missing dates receive zero freshness and are excluded by active date filters. Primary preference prioritizes primary, academic and documentation sources within each search batch.",
        "Statuses derive from validated excerpts: direct support = Supported; partial support or mixed support/contradiction = Partially Supported; contradiction only = Contradicted; context/no evidence = Unverified. Evidence relations are model assessments and still need human review.", "", "## Key Findings"]
    if state.findings:
        for finding in state.findings:
            refs = " ".join(f"[{source_id}]" for source_id in finding.source_ids)
            lines.append(f"- {citations(finding.claim)} — **{finding.evidence_status}** {citations(refs)}")
    else:
        lines.extend(f"- {citations(item)} (Unverified)" for item in draft.key_findings)
        if not draft.key_findings:
            lines.append("No validated findings were extracted.")
    if state.mode == "compare":
        items = state.question.comparison_items
        def cell(text: str) -> str:
            return citations(text).replace("|", "\\|").replace("\n", " ")
        criteria = list(dict.fromkeys(finding.comparison_criterion for finding in state.findings if finding.comparison_criterion)) or ["Available evidence"]
        lines += ["", "| Criterion | " + " | ".join(cell(item) for item in items) + " |", "| --- | " + " | ".join("---" for _ in items) + " |"]
        for criterion in criteria:
            cells = []
            for item in items:
                matches = [finding for finding in state.findings if finding.comparison_item == item and finding.comparison_criterion == criterion]
                cells.append("; ".join(cell(f"{finding.claim} ({finding.evidence_status}) " + " ".join(f"[{sid}]" for sid in finding.source_ids)) for finding in matches) or "Unverified — no linked evidence")
            lines.append("| " + cell(criterion) + " | " + " | ".join(cells) + " |")
    lines += ["", "## Evidence"]
    for finding in state.findings:
        for evidence in state.evidence:
            if evidence.id in finding.evidence_ids:
                lines += [f"- {finding.id} / {evidence.id} ({evidence.relation}, {evidence.strength}) {citations('[' + evidence.source_id + ']')}",
                    "  > " + (citations(evidence.excerpt) if state.provenance_required else evidence.excerpt).replace("\n", " ")]
    if not state.evidence:
        lines.append("No validated supporting excerpts available.")
    lines += ["", "## Conflicts"]
    lines.extend(f"- {citations(c.topic)}: {citations(c.explanation)} " + citations(" ".join(f"[{sid}]" for sid in c.source_a + c.source_b)) for c in state.conflicts)
    if not state.conflicts:
        lines.append("No conflicts identified in the collected evidence; this does not establish consensus.")
    lines += ["", "## Limitations"]
    lines.extend(f"- {citations(item)}" for item in dict.fromkeys(draft.limitations + state.gaps))
    lines.extend(f"- Stopped: {decision.reason}. Unresolved: {citations('; '.join(decision.unresolved)) or 'none'}" for decision in state.stop_decisions if decision.stop)
    lines.append("- Coverage is limited to the current session. Scores and model assessments are not guarantees of accuracy.")
    lines.append(f"- {len(state.citation_rejections)} citation/evidence rejection(s) recorded in this session.")
    lines += ["", "## Sources"]
    for number, source in enumerate(state.sources, 1):
        if state.provenance_required and source.url not in state.retrieved_urls:
            reject(state, "report", "Unretrieved source URL excluded", source.id)
            continue
        lines.append(f"[{number}] {source.title} — [{source.url}]({source.url})")
        if source.quality:
            lines.append(f"  Date: {source.publication_date or 'unknown'}; type: {source.source_type}; quality: {source.quality.total:.0%} (heuristic).")
    return "\n".join(lines) + "\n"
