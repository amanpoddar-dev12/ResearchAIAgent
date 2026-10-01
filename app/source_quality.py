"""Transparent source heuristics, not a factual reliability guarantee."""

from datetime import date
from email.utils import parsedate_to_datetime
import re
from urllib.parse import urlsplit

from app.models import Source, SourceFilters, SourceQuality
from app.modes import ModeConfig, SourceType


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
    if host.endswith(".edu") or host in {"arxiv.org", "pubmed.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov"} or "doi.org" == host:
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
    host = (urlsplit(source.url).hostname or "").lower()
    authority = .85 if host.endswith((".gov", ".edu")) else .65 if source.source_type in {"academic", "documentation", "primary"} else .35
    published = publication_date(source.publication_date)
    age = ((today or date.today()) - published).days if published else None
    freshness = max(0.0, 1 - age / 1825) if age is not None and age >= 0 else 0.0
    evidence_strength = min(len(source.content.strip()) / 2000, 1.0)
    scores = dict(relevance=round(relevance, 4), authority=authority, freshness=round(freshness, 4),
        source_type=1.0 if source.source_type in mode.preferred_types else .3,
        evidence_strength=round(evidence_strength, 4))
    notes = ["Heuristic estimates: lexical relevance, domain/type authority proxy, five-year freshness decay, mode type preference, and text length as an evidence proxy.", "Source type inferred from URL/title metadata; not independently verified."]
    if age is None or age < 0:
        notes.append("Publication date missing, invalid or in the future; freshness scored zero.")
    return SourceQuality(**scores, total=round(sum(scores[key] * weight for key, weight in mode.weights.model_dump().items()), 4), notes=notes)
