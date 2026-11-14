import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import DomainError
from app.modules.intake.a03_plugin import (
    plugin_configuration,
    read_deepseek_source,
    validate_provider_query,
)


def configured():
    return Settings(
        _env_file=None,
        a03_web_backend="pi_web_access",
        a03_plugin_provider="deepseek",
        a03_plugin_api_key=SecretStr("fixture-key"),
        a03_plugin_base_url="https://fixture.invalid",
    )


def test_deepseek_uses_explicit_account_and_no_other_provider():
    config = plugin_configuration(configured(), [])
    assert config["deepseekBaseUrl"] == "https://fixture.invalid"
    assert config["deepseekApiKey"] == "fixture-key"
    assert config["webSearch"]["allowedProviders"] == ["deepseek"]
    assert config["fetchContent"]["domainPolicy"]["allow"] == []
    assert config["ssrf"] == {"allowRanges": [], "trustEnvProxy": False}


@pytest.mark.parametrize(
    "base",
    [
        "http://fixture.invalid",
        "https://user:secret@fixture.invalid",
        "https://fixture.invalid/?key=fixture",
    ],
)
def test_unapproved_plugin_endpoint_format_is_rejected(base):
    settings = configured()
    settings.a03_plugin_base_url = base
    with pytest.raises(DomainError):
        plugin_configuration(settings, [])


def test_deepseek_query_limit_includes_domain_filters():
    settings = configured()
    validate_provider_query(settings, "x" * 128, [])
    with pytest.raises(DomainError):
        validate_provider_query(settings, "x" * 129, [])
    with pytest.raises(DomainError):
        validate_provider_query(settings, "x" * 120, ["example.com"])


def test_native_page_transport_preserves_source_and_never_sends_chat_prompt(monkeypatch):
    settings = configured()
    requests = []
    original = httpx.Client

    def respond(request):
        requests.append(request)
        assert str(request.url) == "https://fixture.invalid/v1/tools/fetch"
        assert request.headers["Authorization"] == "Bearer fixture-key"
        assert request.headers["Idempotency-Key"] == "fixture-page"
        assert json.loads(request.content) == {"url": "https://example.com/report"}
        return httpx.Response(
            200, json={"title": "Public page", "content": "Original source text. 2025."}
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    source = read_deepseek_source(settings, "https://example.com/report", "fixture-page", [])
    assert source == {
        "url": "https://example.com/report",
        "text": "Original source text. 2025.",
        "source_date": None,
    }
    with pytest.raises(DomainError):
        read_deepseek_source(settings, "http://127.0.0.1/private", "fixture-blocked", [])
    assert len(requests) == 1


def test_missing_source_content_never_becomes_a_page(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"answer": "Generated answer without page content"}
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(ValueError, match="original content"):
        read_deepseek_source(configured(), "https://example.com/report", "fixture-page", [])


def test_session_reports_deepseek_search_configuration(api, runtime):
    settings = runtime[0]
    settings.a03_web_backend = "pi_web_access"
    settings.a03_plugin_provider = "deepseek"
    settings.a03_plugin_api_key = SecretStr("fixture-key")
    result = api.get("/api/v1/auth/me")
    assert result.status_code == 200
    assert result.json()["capabilities"]["search_configured"] is True
    assert "fixture-key" not in result.text
