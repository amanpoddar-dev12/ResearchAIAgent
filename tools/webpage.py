"""Safe, bounded webpage text extraction."""

import tempfile
from pathlib import Path
from app.pdf_documents import process_pdf, MAX_UPLOAD_BYTES
from app.research_depth import select_passages
import ipaddress
import httpx
import logging
import socket
import time
from urllib.parse import urljoin, urlsplit
from contextlib import contextmanager
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _public_address(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return None
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))}
    except OSError:
        return None
    if addresses and all(ipaddress.ip_address(address).is_global and not ipaddress.ip_address(address).is_multicast for address in addresses):
        return sorted(addresses)[0]
    return None


def _public_url(url: str) -> bool:
    return _public_address(url) is not None


@contextmanager
def _open_stream(url, address, timeout):
    parts = urlsplit(url)
    # Pin the checked destination; a second DNS lookup cannot redirect to a private IP.
    pinned = httpx.URL(url).copy_with(host=address)
    with httpx.Client(trust_env=False) as client:
        with client.stream("GET", pinned, follow_redirects=False, timeout=timeout,
                           headers={"User-Agent": "AIResearchAgent/1.0", "Host": parts.netloc},
                           extensions={"sni_hostname": parts.hostname}) as response:
            yield response


def fetch_webpage(url: str, timeout: float = 15.0, max_chars: int = 30_000, *, metadata: dict | None = None, query: str = "") -> str:
    current = url
    deadline = time.monotonic() + timeout
    try:
        for _ in range(4):
            address = _public_address(current)
            if not address:
                raise ValueError("URL resolves to a non-public host")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ""
            with _open_stream(current, address, remaining) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return ""
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if not any(kind in content_type for kind in ("text/html", "text/plain", "application/xhtml+xml", "application/pdf")):
                    return ""
                pdf = "application/pdf" in content_type
                limit = min(MAX_UPLOAD_BYTES, 8 * 1024 * 1024) if pdf else max_chars * 4
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > limit:
                    raise ValueError("Response exceeds fetch limit")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        break
                    remaining = limit - size
                    if remaining <= 0:
                        if pdf:
                            raise ValueError("PDF response exceeds fetch limit")
                        break
                    if pdf and len(chunk) > remaining:
                        raise ValueError('PDF response exceeds fetch limit')
                    chunks.append(chunk[:remaining])
                    size += len(chunks[-1])
                raw = b"".join(chunks)
                body = raw.decode(response.encoding or "utf-8", errors="replace") if not pdf else ''
            if pdf:
                if not raw.startswith(b'%PDF-') or time.monotonic() >= deadline: return ''
                with tempfile.TemporaryDirectory(prefix='findings-pdf-') as folder:
                    document = Path(folder) / 'source.pdf'; document.write_bytes(raw)
                    result = process_pdf(str(document), str(Path(folder) / 'result.json'), timeout=max(.1, deadline-time.monotonic()))
                text = '\n\n'.join(f"Page {page['page']}\n{page['text']}" for page in result['pages'])
                if metadata is not None:
                    metadata.update({'document_type': 'pdf', 'page_count': result['page_count'], 'warnings': list(result.get('warnings', []))})
                    if len(text) > max_chars:
                        metadata['warnings'].append('Collected text is a bounded selection, not the complete document.')
                return select_passages(text, query, max_chars) if query else text[:max_chars]
            if "html" not in content_type:
                return select_passages(body, query, max_chars) if query else body[:max_chars]
            soup = BeautifulSoup(body, "html.parser")
            if metadata is not None:
                if soup.title:
                    metadata["title"] = soup.title.get_text(" ", strip=True)
                date_tag = soup.select_one('meta[property="article:published_time"], meta[name="citation_publication_date"], meta[name="date"], time[datetime]')
                if date_tag:
                    metadata["publication_date"] = date_tag.get("content") or date_tag.get("datetime")
                if soup.select_one('meta[name="citation_doi"]'):
                    metadata["primary_basis"] = "Scholarly publication metadata; study type requires review"
                references = []
                for anchor in soup.select('[id*="reference"] a[href], [class*="reference"] a[href], a[rel~="cite"]'):
                    linked = urljoin(current, anchor.get("href", ""))
                    parts = urlsplit(linked)
                    if parts.scheme in {"http", "https"} and parts.hostname and linked.split("#")[0] != current.split("#")[0]:
                        references.append(linked)
                metadata["reference_urls"] = list(dict.fromkeys(references))[:6]
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
                tag.decompose()
            text = "\n\n".join(" ".join(part.split()) for part in soup.get_text("\n", strip=True).splitlines() if part.strip())
            if metadata is not None and len(text) > max_chars:
                metadata.setdefault('warnings', []).append('Collected text is a bounded selection, not the complete document.')
            return select_passages(text, query, max_chars) if query else text[:max_chars]
        raise ValueError("Too many redirects")
    except (httpx.HTTPError, OSError, ValueError, UnicodeError) as exc:
        logger.warning("Could not fetch webpage (%s)", type(exc).__name__)
        return ""
