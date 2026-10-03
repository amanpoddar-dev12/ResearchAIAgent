import pytest
from tools.web_search import normalize_url
from tools.webpage import fetch_webpage


def test_normalize_url_removes_tracking_parameters():
    assert normalize_url("HTTPS://Example.COM/page/?utm_source=x&x=1#part") == "https://example.com/page?x=1"


def test_normalize_url_rejects_invalid_urls():
    with pytest.raises(ValueError):
        normalize_url("not-a-url")


def test_fetch_rejects_private_hosts_without_http(monkeypatch):
    monkeypatch.setattr("tools.webpage.socket.getaddrinfo", lambda *args: [(None, None, None, None, ("127.0.0.1", 80))])
    monkeypatch.setattr("tools.webpage._open_stream", lambda *args, **kwargs: pytest.fail("private host must be rejected first"))
    assert fetch_webpage("http://localhost/private") == ""


def test_fetch_reads_only_the_bounded_response(monkeypatch):
    class Response:
        status_code = 200
        headers = {"content-type": "text/plain"}
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b"abcdefghij"
            yield b"klmnopqrst"

    monkeypatch.setattr("tools.webpage.socket.getaddrinfo", lambda *args: [(None, None, None, None, ("93.184.216.34", 80))])
    monkeypatch.setattr("tools.webpage._open_stream", lambda *args, **kwargs: Response())
    assert fetch_webpage("http://example.com", max_chars=3) == "abc"


def test_pinned_stream_preserves_host_and_tls_name(monkeypatch):
    from tools.webpage import _open_stream
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"trust_env": False}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def stream(self, method, url, **kwargs):
            calls.append((method, str(url), kwargs))
            return self
    monkeypatch.setattr("tools.webpage.httpx.Client", Client)
    with _open_stream("https://synthetic.invalid/docs", "93.184.216.34", 3):
        pass
    method, url, options = calls[0]
    assert method == "GET" and url == "https://93.184.216.34/docs"
    assert options["headers"]["Host"] == "synthetic.invalid"
    assert options["extensions"]["sni_hostname"] == "synthetic.invalid"
    assert options["follow_redirects"] is False


def test_html_metadata_and_cited_links_are_extracted_offline(monkeypatch):
    import httpx
    from contextlib import contextmanager
    from tools.webpage import fetch_webpage
    @contextmanager
    def stream(*_args):
        yield httpx.Response(200, request=httpx.Request("GET", "https://synthetic.invalid/docs"),
            headers={"content-type": "text/html"}, text='''<html><title>SYNTHETIC TEST</title>
            <meta name="citation_publication_date" content="2026-09-01">
            <meta name="citation_doi" content="synthetic-only">
            <article>Synthetic widget results.</article><div id="references">
            <a href="/study">Synthetic study</a><a href="javascript:alert(1)">Invalid</a></div></html>''')
    monkeypatch.setattr("tools.webpage._public_address", lambda *_args: "93.184.216.34")
    monkeypatch.setattr("tools.webpage._open_stream", stream)
    metadata = {}
    text = fetch_webpage("https://synthetic.invalid/docs", metadata=metadata)
    assert "Synthetic widget results" in text
    assert metadata["title"] == "SYNTHETIC TEST"
    assert metadata["publication_date"] == "2026-09-01"
    assert metadata["reference_urls"] == ["https://synthetic.invalid/study"]
