"""Explicit MCP provider configuration; credentials and API destinations belong to the host."""

import json
from urllib.parse import urlsplit

import httpx

from app.core.errors import DomainError
from app.integrations.search import public_source_url

PROVIDERS = {"brave", "tavily", "exa", "deepseek"}


def plugin_configuration(settings, domains):
    provider = settings.a03_plugin_provider
    if provider not in PROVIDERS or not settings.a03_plugin_api_key:
        raise DomainError("DEPENDENCY_NOT_READY", "搜索插件需要已支持的提供者和服务端凭据", 503)
    config = {
        "provider": provider,
        provider + "ApiKey": settings.a03_plugin_api_key.get_secret_value(),
        "webSearch": {"allowedProviders": [provider]},
        "autoOpenBrowser": False,
        "ssrf": {"allowRanges": [], "trustEnvProxy": False},
        "fetchRouting": {"allowRemoteHostedProviders": False},
        "fetchContent": {
            "redirects": "same-origin",
            "domainPolicy": {"allow": domains, "deny": []},
        },
    }
    if settings.a03_plugin_base_url:
        parsed = urlsplit(settings.a03_plugin_base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise DomainError("DEPENDENCY_NOT_READY", "搜索插件基址需要不含凭据的 HTTPS 地址", 503)
        config[provider + "BaseUrl"] = settings.a03_plugin_base_url.rstrip("/")
    return config


def validate_provider_query(settings, query, domains):
    if settings.a03_web_backend == "pi_web_access" and settings.a03_plugin_provider == "deepseek":
        built = query.strip() + (" " + " OR ".join("site:" + d for d in domains) if domains else "")
        if len(built) > 128:
            raise DomainError(
                "VALIDATION_ERROR", "DeepSeek 搜索词连同域名过滤最多 128 字符，请精简查询", 422
            )


def read_deepseek_source(settings, url, request_id, domains):
    """Native source fetch using the same explicitly selected DeepSeek account.

    Search still uses the pinned MCP plugin. The native fetch service retrieves
    public source content; it does not ask a language model to invent a page.
    """
    if public_source_url(url, domains) is None:
        raise DomainError("VALIDATION_ERROR", "网页地址不是允许的公开来源", 422)
    config = plugin_configuration(settings, domains)
    endpoint = config.get("deepseekBaseUrl", "https://api.deepseek.com") + "/v1/tools/fetch"
    with httpx.Client(timeout=settings.search_timeout_seconds, follow_redirects=False) as client:
        with client.stream(
            "POST",
            endpoint,
            headers={
                "Authorization": "Bearer " + config["deepseekApiKey"],
                "Idempotency-Key": request_id,
            },
            json={"url": url},
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1_000_000:
                    raise ValueError("Source response exceeded limit")
                chunks.append(chunk)
    payload = json.loads(b"".join(chunks))
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("DeepSeek source response has no original content")
    if payload.get("url", url) != url:
        raise ValueError("Source response does not match requested URL")
    return {"url": url, "text": content[:60000], "source_date": None}
