import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations.search import (
    HttpJsonSearch,
    SearchRequest,
    allowed_domains,
    public_source_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/report",
        "https://www.other-company.org/products",
        "https://en.wikipedia.org/wiki/Company",
        "https://8.8.8.8/report",
        "https://[2606:4700:4700::1111]/report",
    ],
)
def test_empty_domain_list_allows_public_websites(url):
    assert allowed_domains(Settings(_env_file=None)) == []
    assert public_source_url(url, []) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest",
        "http://[::1]/private",
        "http://[::ffff:127.0.0.1]/private",
        "http://localhost/x",
        "http://db/x",
        "http://metadata.google.internal/x",
        "http://host.docker.internal/x",
        "http://2130706433/x",
        "http://0177.0.0.1/x",
        "http://0x7f.0x0.0x0.0x1/x",
        "https://example.com:8443/x",
        "file:///etc/passwd",
        "https://user:password@example.com/x",
        "https://example.com/x?api_key=fixture",
        "https://example.com/x\\@localhost",
        "http://224.0.0.1/x",
        "http://[ff02::1]/x",
    ],
)
def test_public_web_scope_still_blocks_local_or_credential_bearing_urls(url):
    assert public_source_url(url, []) is None


def test_explicit_domain_list_can_still_narrow_sources():
    assert public_source_url("https://www.example.com/a", ["example.com"])
    assert public_source_url("https://other-company.org/a", ["example.com"]) is None


def test_normalized_search_sends_empty_domain_list_for_public_web(monkeypatch):
    settings = Settings(_env_file=None, search_endpoint="https://fixture.invalid/search")
    original = httpx.Client
    seen = []

    def respond(request):
        body = json.loads(request.content)
        assert body["allowed_domains"] == []
        assert body["protocol_version"] == "1.0"
        SearchRequest.model_validate(body)
        seen.append(body)
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    HttpJsonSearch(settings).search("fictional company", request_id="fixture-public-search")
    assert len(seen) == 1
