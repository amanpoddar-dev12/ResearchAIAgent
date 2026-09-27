"""Safe, bounded webpage text extraction."""

import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def fetch_webpage(url: str, timeout: float = 15.0, max_chars: int = 30_000) -> str:
    try:
        response = httpx.get(url, follow_redirects=True, timeout=timeout, headers={"User-Agent": "AIResearchAgent/1.0"})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            return response.text[:max_chars]
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
            tag.decompose()
        return " ".join(soup.get_text(" ", strip=True).split())[:max_chars]
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not fetch webpage %s: %s", url, exc)
        return ""

