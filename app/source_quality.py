"""Transparent source heuristics, not a factual reliability guarantee."""

from datetime import date
from email.utils import parsedate_to_datetime
import re
from urllib.parse import urlsplit

from app.models import Source, SourceFilters, SourceQuality
from app.modes import ModeConfig, SourceType


def independent_source_count(sources: list[Source]) -> int:
    """Conservative origin proxy: shared DOI references do not prove replication."""
    groups: list[tuple[set[str], set[str]]] = []
    for source in sources:
        domains = {source.domain.casefold()}
        studies = {url.rstrip('/').casefold() for url in [source.url, *source.reference_urls]
                   if (urlsplit(url).hostname or '').casefold() in {'doi.org', 'dx.doi.org'}}
        merged = []
        for old_domains, old_studies in groups:
            if domains & old_domains or studies & old_studies:
                domains |= old_domains
                studies |= old_studies
            else:
                merged.append((old_domains, old_studies))
        # Repeat to handle a bridge between earlier groups.
        while any(domains & d or studies & s for d, s in merged):
            rest = []
            for d, s in merged:
                if domains & d or studies & s:
                    domains |= d
                    studies |= s
                else:
                    rest.append((d, s))
            merged = rest
        groups = [*merged, (domains, studies)]
    return len(groups)


def publication_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return parsedate_to_datetime(value).date()
        except (ValueError, TypeError, OverflowError):
            return None


def infer_source_type(source: Source) -> SourceType:
    host = (urlsplit(source.url).hostname or "").lower()
    path = urlsplit(source.url).path.lower()
    text = (source.title + " " + source.content[:2000]).lower()
    if source.primary_basis or host.endswith(".edu") or host in {"arxiv.org", "pubmed.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov"} or "doi.org" == host:
        return "academic"
    if host.startswith("docs.") or any(part in path for part in ("/docs/", "/documentation/", "/reference/")):
        return "documentation"
    if host.endswith(".gov") or any(part in path for part in ("/press-release", "/investor", "/dataset")):
        return "primary"
    if any(term in text for term in ("opinion", "commentary", "analysis:")):
        return "analysis"
    if "news" in host.split(".") or "/news/" in path:
        return "news"
    return "other"


def filter_reason(source: Source, filters: SourceFilters) -> str | None:
    host = (urlsplit(source.url).hostname or "").lower()
    def matches(domain: str) -> bool:
        return host == domain or host.endswith("." + domain)
    if any(matches(domain) for domain in filters.exclude_domains):
        return "Excluded domain"
    if filters.include_domains and not any(matches(domain) for domain in filters.include_domains):
        return "Outside included domains"
    if filters.source_types and source.source_type not in filters.source_types:
        return "Excluded source type"
    published = publication_date(source.publication_date)
    if filters.date_from or filters.date_to:
        if not published:
            return "Unknown date under an active date filter"
        if filters.date_from and published < filters.date_from:
            return "Before date range"
        if filters.date_to and published > filters.date_to:
            return "After date range"
    return None


def score_source(source: Source, question: str, mode: ModeConfig, *, today: date | None = None) -> SourceQuality:
    # ponytail: lexical/metadata heuristics are explainable but do not certify authority or truth.
    stop = {"the", "a", "an", "of", "in", "to", "and", "or", "is", "are", "what", "how", "does", "compare", "with", "for", "versus"}
    terms = set(re.findall(r"\w+", question.lower())) - stop
    content_terms = set(re.findall(r"\w+", (source.title + " " + source.content).lower()))
    relevance = len(terms & content_terms) / len(terms) if terms else 0.0
    if source._discovery_relevance is not None:
        # Discovery can rescue lexical synonyms, but never sets evidence status or truth.
        relevance = max(relevance, .4 * max(0, min(1, source._discovery_relevance)))
    host = (urlsplit(source.url).hostname or "").lower()
    authority = .85 if host.endswith((".gov", ".edu")) else .65 if source.source_type in {"academic", "documentation", "primary"} else .35
    published = publication_date(source.publication_date)
    age = ((today or date.today()) - published).days if published else None
    freshness = max(0.0, 1 - age / 1825) if age is not None and age >= 0 else 0.0
    text = source.content.lower()
    signals = [bool(re.search(r"\b(methods?|methodology|sample|participants|dataset)\b", text)),
               bool(re.search(r"\b(limitations?|uncertainty|confidence interval)\b", text)),
               bool(re.search(r"\b(results?|measurements?|observations?)\b", text)),
               source.retrieval_method == "fetch"]
    evidence_strength = sum(signals) / len(signals)
    scores = dict(relevance=round(relevance, 4), authority=authority, freshness=round(freshness, 4),
        source_type=1.0 if source.source_type in mode.preferred_types else .3,
        evidence_strength=round(evidence_strength, 4))
    notes = ["Heuristic estimates: lexical relevance, domain/type authority proxy, five-year freshness decay, mode preference, and reporting signals (methods, limitations, results, original text). Signals do not establish study validity.", "Source type inferred from URL/title metadata; not independently verified."]
    if source._discovery_relevance is not None:
        notes.append("Relevance also includes a bounded discovery-provider signal; this does not verify the source or its claims.")
    if age is None or age < 0:
        notes.append("Publication date missing, invalid or in the future; freshness scored zero.")
    return SourceQuality(**scores, total=round(sum(scores[key] * weight for key, weight in mode.weights.model_dump().items()), 4), notes=notes)
