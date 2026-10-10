import pytest

from job_agent.services.discovery import canonicalize


def test_canonicalize_removes_tracking_query_and_trailing_slash():
    assert canonicalize("HTTPS://Example.COM/job/123/?utm_source=x") == "https://example.com/job/123"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "relative/path", ""])
def test_canonicalize_rejects_non_http_or_relative_urls(url):
    with pytest.raises(ValueError):
        canonicalize(url)
