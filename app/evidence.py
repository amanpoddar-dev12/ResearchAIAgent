"""Validate citations against this session and derive statuses from evidence."""

from collections import Counter
import re
from app.models import CitationRejection, Evidence, EvidenceStatus, ResearchState
from app.scoring import score_finding
from app.modes import MODES
from app.research_control import audit
from app.deduplication import near_duplicate
from app.models import ClaimExtraction, Conflict


def evidence_status(items: list[Evidence]) -> EvidenceStatus:
    support = [item for item in items if item.relation == "supports"]
    opposition = [item for item in items if item.relation == "contradicts"]
    if support and opposition:
        return "Partially Supported"
    if opposition:
        return "Contradicted"
    if any(item.strength == "direct" for item in support):
        return "Supported"
    if support:
        return "Partially Supported"
    return "Unverified"


def reject(state: ResearchState, claim_id: str, reason: str, source_id: str | None = None, evidence_id: str | None = None) -> None:
    rejection = CitationRejection(claim_id=claim_id, reason=reason, source_id=source_id, evidence_id=evidence_id)
    if rejection not in state.citation_rejections:
        state.citation_rejections.append(rejection)
        audit(state, "rejection", reason, claim_id=claim_id, source_id=source_id, evidence_id=evidence_id)


def source_rejection(state: ResearchState, source_id: str) -> str | None:
    source = next((source for source in state.sources if source.id == source_id), None)
    if source is None:
        return "Nonexistent source"
    if state.provenance_required and source.url not in state.retrieved_urls:
        return "Source URL was not retrieved in this session"
    if source.quality is None:
        return "Source has not been evaluated"
    if source.quality.relevance < MODES[state.mode].relevance_threshold:
        return "Source below relevance threshold"
    return None


def validate_evidence(state: ResearchState) -> None:
    candidates = {item.id: item for item in state.evidence}
    duplicate_ids = {key for key, count in Counter(item.id for item in state.evidence).items() if count > 1}
    accepted: dict[str, Evidence] = {}
    sources = {source.id: source for source in state.sources}
    for index, finding in enumerate(state.findings, 1):
        finding.id = finding.id or f"C{index}"
        linked = []
        untraceable_url = False
        if state.provenance_required:
            from tools.web_search import normalize_url
            for url in re.findall(r"https?://[^\s<>\])]+", finding.claim):
                try:
                    known = normalize_url(url.rstrip(".,;")) in state.retrieved_urls
                except ValueError:
                    known = False
                if not known:
                    untraceable_url = True
                    reject(state, finding.id, "Claim contains an untraceable URL")
        for evidence_id in dict.fromkeys(finding.evidence_ids):
            item = candidates.get(evidence_id)
            reason = "Nonexistent evidence" if item is None else "Ambiguous evidence ID" if evidence_id in duplicate_ids else source_rejection(state, item.source_id)
            if item and not reason:
                excerpt = item.excerpt
                content = sources[item.source_id].content
                if not excerpt or excerpt not in content:
                    reason = "Excerpt is not present in collected source text"
            if reason:
                reject(state, finding.id, reason, item.source_id if item else None, evidence_id)
            elif item and not untraceable_url:
                linked.append(item)
                accepted[item.id] = item
        linked_sources = list(dict.fromkeys(item.source_id for item in linked))
        for source_id in finding.source_ids:
            reason = source_rejection(state, source_id)
            if reason or source_id not in linked_sources:
                reject(state, finding.id, reason or "Citation has no validated supporting excerpt", source_id)
        finding.evidence_ids = [item.id for item in linked]
        finding.source_ids = linked_sources
        finding.supporting_evidence_ids = [item.id for item in linked if item.relation == "supports"]
        finding.contradicting_evidence_ids = [item.id for item in linked if item.relation == "contradicts"]
        finding.evidence_status = evidence_status(linked)
        retrieved_questions = list(dict.fromkeys(qid for item in linked for qid in sources[item.source_id].sub_question_ids))
        finding.sub_question_ids = [qid for qid in finding.sub_question_ids if qid in retrieved_questions] if state.explicit_sub_question_links else retrieved_questions
        if state.provenance_required:
            finding.explanation = "Validated excerpt(s): " + ", ".join(item.id for item in linked) if linked else "No traceable supporting evidence was retrieved."
        if not linked:
            reject(state, finding.id, "Claim has no traceable evidence; retained as Unverified")
    state.evidence = list(accepted.values())
    for finding in state.findings:
        score = score_finding(state, finding)
        finding.confidence_score = score.score
        finding.score_source_quality = score.source_quality
        finding.score_evidence_relevance = score.evidence_relevance
        finding.score_source_agreement = score.source_agreement
        finding.score_freshness = score.freshness
        finding.score_citation_validity = score.citation_validity
        finding.score_verification_agreement = score.verification_agreement
        finding.score_formula = score.formula
    validate_dependencies(state)


def validate_dependencies(state: ResearchState) -> None:
    claims = {claim.id: claim for claim in state.findings}
    visiting: list[str] = []
    done: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            for member in visiting[visiting.index(key):]:
                claims[member].dependency_rejected = True
                reject(state, member, "Dependency cycle rejected")
            return
        if key in done:
            return
        visiting.append(key)
        claim = claims[key]
        for dep in claim.depends_on:
            if dep not in claims:
                claim.dependency_rejected = True
                reject(state, key, "Unknown claim dependency", evidence_id=dep)
            else:
                visit(dep)
        visiting.pop()
        if claim.dependency_rejected:
            claim.evidence_status = "Unverified"
        elif claim.evidence_status == "Supported":
            statuses = [claims[dep].evidence_status for dep in claim.depends_on]
            if any(status in {"Unverified", "Contradicted"} for status in statuses):
                claim.evidence_status = "Unverified"
            elif "Partially Supported" in statuses:
                claim.evidence_status = "Partially Supported"
        done.add(key)

    for key in claims:
        visit(key)
    for claim in state.findings:
        if claim.dependency_rejected:
            claim.depends_on = []
        audit(state, "verification", claim.evidence_status, claim_id=claim.id, depends_on=claim.depends_on)


def merge_extraction(state: ResearchState, result: ClaimExtraction) -> None:
    """Coordinator-only commit; model IDs are scoped to each extraction batch."""
    ids: dict[str, str] = {}
    duplicate_evidence = {key for key, count in Counter(item.id for item in result.evidence).items() if count > 1}
    for item in result.evidence:
        if item.id in duplicate_evidence:
            reject(state, "extraction", "Ambiguous evidence ID", item.source_id, item.id)
            continue
        existing = next((old for old in state.evidence if (old.source_id, old.excerpt, old.relation, old.strength) == (item.source_id, item.excerpt, item.relation, item.strength)), None)
        original = item.id
        if existing:
            ids[original] = existing.id
        else:
            item.id = f"E{max([int(e.id[1:]) for e in state.evidence if e.id[1:].isdigit()] or [0]) + 1}"
            item.evidence_type = {
                "supports": "supporting",
                "contradicts": "contradicting",
                "context": "contextual",
            }[item.relation]
            item.supports_claim = item.relation == "supports"
            item.strength_score = 1.0 if item.strength == "direct" else .5
            item.relevance_score = max(item.relevance_score, .5 if item.relation != "context" else .25)
            ids[original] = item.id
            state.evidence.append(item)
    aliases: dict[str, str] = {}
    pending = []
    for index, claim in enumerate(result.findings, 1):
        original = claim.id or f"C{index}"
        claim.evidence_ids = [ids.get(key, f"missing:{key}") for key in claim.evidence_ids]
        existing = next((old for old in state.findings if near_duplicate(old.claim, claim.claim, claim=True)), None)
        if existing:
            existing.evidence_ids = list(dict.fromkeys(existing.evidence_ids + claim.evidence_ids))
            existing.source_ids = list(dict.fromkeys(existing.source_ids + claim.source_ids))
            existing.sub_question_ids = list(dict.fromkeys(existing.sub_question_ids + claim.sub_question_ids))
            aliases[original] = existing.id
            pending.append((existing, claim.depends_on))
            record = {"kind": "claim", "from": original, "to": existing.id, "text": claim.claim}
            state.merge_records.append(record)
            audit(state, "claim_merged", "Merged equivalent claim; retained evidence links", **record)
        else:
            claim.id = f"C{len(state.findings) + 1}"
            aliases[original] = claim.id
            pending.append((claim, claim.depends_on[:]))
            claim.depends_on = []
            state.findings.append(claim)
            audit(state, "claim", claim.claim, claim_id=claim.id)
    for claim, dependencies in pending:
        claim.depends_on = list(dict.fromkeys(claim.depends_on + [aliases.get(key, key.removeprefix("existing:")) for key in dependencies]))
        for evidence_id in claim.evidence_ids:
            evidence = next((item for item in state.evidence if item.id == evidence_id), None)
            if evidence and evidence.claim_id is None:
                evidence.claim_id = claim.id
                source = next((item for item in state.sources if item.id == evidence.source_id), None)
                evidence.freshness_score = source.freshness_score if source and source.freshness_score is not None else 0
    validate_evidence(state)


def evidence_conflicts(state: ResearchState) -> list[Conflict]:
    result = []
    for claim in state.findings:
        opposing = [item for item in state.evidence if item.id in claim.evidence_ids and item.relation == "contradicts"]
        if opposing:
            result.append(Conflict(topic=claim.claim, claim_a=claim.claim, claim_b="Contradicting retrieved evidence",
                source_a=claim.source_ids, source_b=list(dict.fromkeys(item.source_id for item in opposing)),
                explanation="Retrieved excerpts contradict this claim; review the linked evidence.",
                claim_ids=[claim.id], evidence_ids=[item.id for item in opposing]))
    return result
