from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHEETA_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr | None = None
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]
    session_hours: int = Field(default=8, ge=1, le=24)
    login_attempt_limit: int = Field(default=10, ge=3, le=100)
    registration_enabled: bool = True
    registration_attempt_limit: int = Field(default=5, ge=1, le=100)
    idempotency_hours: int = Field(default=24, ge=24, le=168)
    allow_mock: bool = False
    model_endpoint: str | None = None
    model_api_key: SecretStr | None = None
    model_name: str | None = None
    model_timeout_seconds: int = Field(default=30, ge=1, le=90)
    model_max_output_tokens: int = Field(default=16000, ge=100, le=64000)
    job_model_call_limit: int = Field(default=30, ge=1, le=1000)
    job_model_token_limit: int = Field(default=300000, ge=1)
    search_provider: str = Field(default="disabled", pattern=r"^[a-z][a-z0-9_]{0,39}$")
    search_endpoint: str | None = None
    search_api_key: SecretStr | None = None
    search_allowed_domains: list[str] = Field(
        default_factory=list,
        max_length=30,
        description=(
            "Empty means all public websites; a nonempty list optionally limits source domains"
        ),
    )
    search_timeout_seconds: int = Field(default=20, ge=1, le=30)
    search_result_limit: int = Field(default=5, ge=1, le=5)
    research_query_limit: int = Field(default=2, ge=0, le=2)
    job_search_call_limit: int = Field(default=20, ge=0, le=1000)
    a03_web_backend: Literal["disabled", "normalized", "pi_web_access"] = "disabled"
    a03_plugin_provider: str = "brave"
    a03_plugin_api_key: SecretStr | None = None
    a03_plugin_base_url: str | None = None
    a03_fetch_endpoint: str | None = None
    a03_node_binary: str = "node"
    a03_max_turns: int = Field(default=16, ge=1, le=40)
    a03_max_searches: int = Field(default=12, ge=0, le=50)
    a03_max_pages: int = Field(default=12, ge=0, le=50)
    a03_per_object_searches: int = Field(default=3, ge=1, le=8)
    a03_max_seconds: int = Field(default=300, ge=30, le=900)
    a03_no_progress_limit: int = Field(default=2, ge=1, le=5)
    task_lease_seconds: int = Field(default=120, ge=100, le=600)
    task_attempt_limit: int = Field(default=3, ge=1, le=5)
    batch_limit: int = Field(default=10, ge=1, le=10)
    file_byte_limit: int = Field(default=5242880, ge=1, le=5242880)
    text_char_limit: int = Field(default=30000, ge=1, le=30000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
