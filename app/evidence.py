"""Validate citations against this session and derive statuses from evidence."""

from collections import Counter
import re
from app.models import CitationRejection, Evidence, EvidenceStatus, ResearchState
from app.scoring import score_finding
from app.modes import MODES
from app.research_control import audit
from app.deduplication import near_duplicate
from app.models import ClaimExtraction, Conflict


def linked_evidence(state, finding):
    """Assessments belong to a claim/evidence pair, never to a whole source."""
    assessments = {item.evidence_id: item for item in finding.evidence_assessments if item.claim_id == finding.id}
    result = []
    for item in state.evidence:
        if item.id not in finding.evidence_ids:
            continue
        assessment = assessments.get(item.id)
        if assessment:
            item = item.model_copy(update={"relation": assessment.relation, "strength": assessment.strength, "reasoning": assessment.reasoning})
        elif state.semantic_validation_required:
            # Exact quotation supports reporting what the source says; broader claims need review.
            normalize = lambda value: " ".join(value.casefold().split()).strip(" .!?")
            exact = normalize(finding.claim) == normalize(item.excerpt)
            item = item.model_copy(update={"relation": "supports" if exact else "context", "strength": "direct" if exact else "partial"})
        if state.semantic_validation_required:
            item = item.model_copy(update={"relevance_score": (1 if item.strength == "direct" else .5) if item.relation != "context" else 0,
                                          "strength_score": 1 if item.strength == "direct" else .5,
                                          "supports_claim": item.relation == "supports"})
        result.append(item)
    return result


def apply_assessments(state, batch, *, challenge=False):
    counts = Counter((item.claim_id, item.evidence_id) for item in batch.assessments)
    claims = {claim.id: claim for claim in state.findings}
    for item in batch.assessments:
        claim = claims.get(item.claim_id)
        if not claim or item.evidence_id not in claim.evidence_ids or counts[(item.claim_id, item.evidence_id)] != 1:
            reject(state, item.claim_id, "Review references unrelated or ambiguous evidence", evidence_id=item.evidence_id)
            continue
        prior = next((old for old in claim.evidence_assessments if old.evidence_id == item.evidence_id), None)
        if challenge:
            if prior is None:
                continue
            if prior.relation != item.relation:
                item = item.model_copy(update={"relation": "context", "strength": "partial", "reasoning": "Reviewers disagree: " + item.reasoning})
            elif prior.strength == "partial":
                item.strength = "partial"
        claim.evidence_assessments = [old for old in claim.evidence_assessments if old.evidence_id != item.evidence_id] + [item]
    validate_evidence(state)


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
        assessed = linked_evidence(state, finding)
        finding.supporting_evidence_ids = [item.id for item in assessed if item.relation == "supports"]
        finding.contradicting_evidence_ids = [item.id for item in assessed if item.relation == "contradicts"]
        finding.evidence_status = evidence_status(assessed)
        retrieved_questions = list(dict.fromkeys(qid for item in linked for qid in sources[item.source_id].sub_question_ids))
        finding.sub_question_ids = [qid for qid in finding.sub_question_ids if qid in retrieved_questions] if state.explicit_sub_question_links else retrieved_questions
        if state.provenance_required:
            finding.explanation = "Validated excerpt(s): " + ", ".join(item.id for item in linked) if linked else "No traceable supporting evidence was retrieved."
        if not linked:
            reject(state, finding.id, "Claim has no traceable evidence; retained as Unverified")
    # Quantitative observations can be valid without being a prose claim.
    for point in state.data_points:
        for item in state.evidence:
            if item.source_id == point.source_id and point.quote in item.excerpt and not source_rejection(state, item.source_id) and item.excerpt in sources[item.source_id].content:
                accepted[item.id] = item
    state.evidence = list(accepted.values())
    if state.semantic_validation_required:
        for item in state.evidence:
            pairs = [pair for claim in state.findings for pair in linked_evidence(state, claim) if pair.id == item.id]
            relations = {pair.relation for pair in pairs}
            item.relation = next(iter(relations)) if len(relations) == 1 else "context"
            item.strength = "direct" if pairs and all(pair.strength == "direct" for pair in pairs) else "partial"
            item.evidence_type = {"supports": "supporting", "contradicts": "contradicting", "context": "contextual"}[item.relation]
            item.supports_claim = item.relation == "supports"
            item.relevance_score = max((pair.relevance_score for pair in pairs), default=0)
            item.strength_score = 1 if item.strength == "direct" else .5
    validate_dependencies(state)
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
    duplicate_claims = {key for key, count in Counter(item.id for item in result.findings).items() if count > 1}
    pending = []
    for index, claim in enumerate(result.findings, 1):
        original = claim.id or f"C{index}"
        if original in duplicate_claims:
            reject(state, "extraction", "Ambiguous claim ID", evidence_id=original)
            continue
        claim.evidence_assessments = []  # Extraction cannot impersonate a separate review.
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
    from app.synthesizer import _cell_occurs, _metric_matches
    for point in result.data_points:
        source = next((source for source in state.sources if source.id == point.source_id), None)
        if not source or source_rejection(state, source.id) or not point.quote or point.quote not in source.content:
            continue
        if not _cell_occurs(point.value, point.quote) or not _cell_occurs(point.observation, point.quote) or not _metric_matches(point.value, point.label + " " + point.unit, point.observation, point.quote):
            reject(state, "data", "Observation does not match quoted metric and value", point.source_id)
            continue
        if any((old.source_id, old.quote, old.label, old.value) == (point.source_id, point.quote, point.label, point.value) for old in state.data_points):
            continue
        point.id = f"DP{len(state.data_points) + 1}"
        state.data_points.append(point)
        state.evidence.append(Evidence(id=f"{point.id}-evidence", source_id=point.source_id, excerpt=point.quote))
    validate_evidence(state)


def evidence_conflicts(state: ResearchState) -> list[Conflict]:
    result = []
    for claim in state.findings:
        opposing = [item for item in linked_evidence(state, claim) if item.relation == "contradicts"]
        if opposing:
            supporting = [item for item in linked_evidence(state, claim) if item.relation == "supports"]
            result.append(Conflict(topic=claim.claim, claim_a=claim.claim, claim_b="Contradicting retrieved evidence",
                source_a=list(dict.fromkeys(item.source_id for item in supporting)), source_b=list(dict.fromkeys(item.source_id for item in opposing)),
                explanation="Retrieved excerpts contradict this claim; review the linked evidence.",
                claim_ids=[claim.id], evidence_ids=[item.id for item in supporting + opposing]))
    return result
