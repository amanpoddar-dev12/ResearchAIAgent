import pytest
from tools.web_search import normalize_url


def test_normalize_url_removes_tracking_parameters():
    assert normalize_url("HTTPS://Example.COM/page/?utm_source=x&x=1#part") == "https://example.com/page?x=1"


def test_normalize_url_rejects_invalid_urls():
    with pytest.raises(ValueError):
        normalize_url("not-a-url")

