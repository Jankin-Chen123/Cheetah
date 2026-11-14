from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
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
    local_username: str = "local-reviewer"
    local_password: SecretStr | None = None
    bailian_api_key: SecretStr | None = None
    bailian_base_url: str | None = None
    bailian_model: str | None = None
    bailian_region: str | None = None
    model_max_tokens: int = 2000
    model_max_requests_per_case: int = 24
    evaluation_template_path: Path | None = None
    report_template_path: Path | None = None
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
