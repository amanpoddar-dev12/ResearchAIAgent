"""Tavily web search integration."""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import httpx
from app.models import SearchResult, SourceFilters

logger = logging.getLogger(__name__)


class SearchUnavailable(RuntimeError):
    """A failed provider request, distinct from a valid empty result."""


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Invalid URL: {url}")
    query = sorted((key, value) for key, value in parse_qsl(parts.query) if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid"})
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/") or "/", urlencode(query), ""))


def search_web(api_key: str, query: str, max_results: int = 5, timeout: float = 20.0, *, search_depth: str = "basic", filters: SourceFilters | None = None) -> list[SearchResult]:
    if not api_key:
        raise ValueError("TAVILY_API_KEY is missing")
    logger.info("Searching Tavily")
    payload = {"api_key": api_key, "query": query, "max_results": max_results, "include_answer": False, "search_depth": search_depth}
    if filters:
        if filters.include_domains:
            payload["include_domains"] = filters.include_domains
        if filters.exclude_domains:
            payload["exclude_domains"] = filters.exclude_domains
    try:
        response = httpx.post("https://api.tavily.com/search", json=payload, timeout=timeout)
        response.raise_for_status()
        items = response.json().get("results", [])
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Tavily search failed (%s)", type(exc).__name__)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise SearchUnavailable(f"Search provider unavailable ({status or type(exc).__name__})") from None
    results: list[SearchResult] = []
    seen: set[str] = set()
    for item in items:
        try:
            url = normalize_url(str(item["url"]))
            if url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(
                title=str(item.get("title", url)),
                url=str(item["url"]).strip(),
                content=str(item.get("content", "")),
                score=item.get("score"),
                published_date=item.get("published_date"),
                source_domain=urlsplit(url).netloc,
            ))
        except (KeyError, ValueError, TypeError):
            logger.warning("Ignoring malformed Tavily result")
    logger.info("Tavily returned %d usable results", len(results))
    return results

