"""Configurable search adapters. No provider or credentials are selected by default."""

import ipaddress
import re
from collections.abc import Callable
from typing import Literal, Protocol
from urllib.parse import parse_qsl, urlsplit

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.errors import DomainError


class SearchAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    field: Literal["registered_name", "business", "founded_year", "project_description"]
    value: str = Field(min_length=1, max_length=1000)
    quote: str = Field(min_length=1, max_length=2000)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["1.0"] = "1.0"
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(ge=1, le=5)
    allowed_domains: list[str] = Field(
        default_factory=list,
        max_length=30,
        description=(
            "Empty means all public websites; a nonempty list restricts domains. "
            "Private/local addresses remain forbidden."
        ),
    )


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=3000)
    title: str = Field(min_length=1, max_length=300)
    snippet: str = Field(min_length=1, max_length=6000)
    published_at: AwareDatetime | None = None
    assertions: list[SearchAssertion] = Field(default_factory=list, max_length=10)


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[SearchHit] = Field(max_length=5)


class SearchAdapter(Protocol):
    source_mode: Literal["live", "mock"]

    def search(self, query: str, *, request_id: str) -> SearchResult: ...


def allowed_domains(settings: Settings) -> list[str]:
    domains = []
    for raw in settings.search_allowed_domains:
        host = raw.strip().lower().rstrip(".")
        if (
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or "." not in host
            or ".." in host
            or host.endswith((".local", ".internal", ".localhost"))
        ):
            raise DomainError("DEPENDENCY_NOT_READY", "研究来源域名配置不合法", 503)
        if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}", host):
            try:
                if not ipaddress.ip_address(host).is_global:
                    raise ValueError("private address")
            except ValueError:
                raise DomainError(
                    "DEPENDENCY_NOT_READY", "研究来源必须是规范公共地址", 503
                ) from None
        try:
            if not ipaddress.ip_address(host).is_global:
                raise DomainError("DEPENDENCY_NOT_READY", "研究来源不能使用私有地址", 503)
        except ValueError:
            pass
        domains.append(host)
    return sorted(set(domains))


def public_source_url(value: str, domains: list[str]) -> str | None:
    try:
        if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
            return None
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in {None, 80, 443}
            or not host
            or "%" in host
            or (
                domains
                and not any(host == domain or host.endswith("." + domain) for domain in domains)
            )
        ):
            return None
        if any(
            re.search(
                r"token|secret|credential|password|session|signature|api.?key|^sig$|^key$|^auth$|x-amz",
                key,
                re.I,
            )
            or "%" in key
            for key, _ in parse_qsl(parsed.query)
        ):
            return None
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global or address.is_multicast or address.is_reserved:
                return None
        except ValueError:
            if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}", host):
                return None
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError:
                return None
            labels = host.split(".")
            if (
                len(host) > 253
                or len(labels) < 2
                or any(
                    not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in labels
                )
                or labels[-1].isdigit()
                or host.endswith(
                    (
                        ".local",
                        ".internal",
                        ".localhost",
                        ".localdomain",
                        ".lan",
                        ".home",
                        ".test",
                        ".invalid",
                        ".onion",
                    )
                )
            ):
                return None
        return value
    except ValueError:
        return None


class HttpJsonSearch:
    """Normalized HTTP v1; a provider bridge must implement the documented wire contract."""

    source_mode: Literal["live"] = "live"

    def __init__(self, settings: Settings):
        endpoint = urlsplit(settings.search_endpoint or "")
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
        ):
            raise DomainError("DEPENDENCY_NOT_READY", "搜索接口需要不含凭据的 HTTPS 地址", 503)
        self.settings = settings

    def search(self, query: str, *, request_id: str) -> SearchResult:
        body = SearchRequest(
            query=query,
            limit=self.settings.search_result_limit,
            allowed_domains=allowed_domains(self.settings),
        )
        headers = {"Idempotency-Key": request_id}
        if self.settings.search_api_key:
            headers["Authorization"] = "Bearer " + self.settings.search_api_key.get_secret_value()
        with httpx.Client(
            timeout=self.settings.search_timeout_seconds, follow_redirects=False
        ) as client:
            with client.stream(
                "POST",
                self.settings.search_endpoint,
                headers=headers,
                json=body.model_dump(mode="json"),
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 1_000_000:
                        raise ValueError("Search response too large")
                    chunks.append(chunk)
                result = SearchResult.model_validate_json(b"".join(chunks))
        return result


FACTORIES: dict[str, Callable[[Settings], SearchAdapter]] = {"http_json": HttpJsonSearch}


def register_search_adapter(name: str, factory: Callable[[Settings], SearchAdapter]):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name) or name in {"disabled", *FACTORIES}:
        raise ValueError("Search adapter name is reserved or already registered")
    FACTORIES[name] = factory


def get_search_adapter(settings: Settings) -> SearchAdapter | None:
    if settings.search_provider == "disabled":
        return None
    if settings.search_provider not in FACTORIES:
        raise DomainError("DEPENDENCY_NOT_READY", "搜索适配器未注册", 503)
    adapter = FACTORIES[settings.search_provider](settings)
    if adapter.source_mode not in {"live", "mock"}:
        raise DomainError("DEPENDENCY_NOT_READY", "搜索适配器来源标识不合法", 503)
    return adapter
