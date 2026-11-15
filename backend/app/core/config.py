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
    model_timeout_seconds: int = Field(default=90, ge=1, le=90)
    model_thinking: Literal["enabled", "disabled"] | None = None
    model_max_output_tokens: int = Field(default=16000, ge=100, le=64000)
    job_model_call_limit: int = Field(default=30, ge=1, le=1000)
    talent_model_call_limit: int = Field(default=2, ge=1, le=3)
    file_asr_provider: Literal["disabled", "volcengine"] = "disabled"
    volc_file_asr_resource_id: str = "volc.bigasr.auc_turbo"
    volc_file_asr_standard_resource_id: str = "volc.seedasr.auc"
    file_asr_byte_limit: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    file_asr_timeout_seconds: int = Field(default=180, ge=10, le=300)
    file_asr_daily_limit: int = Field(default=20, ge=1, le=100)
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
    task_lease_seconds: int = Field(default=300, ge=100, le=600)
    task_attempt_limit: int = Field(default=3, ge=1, le=5)
    batch_limit: int = Field(default=10, ge=1, le=10)
    file_byte_limit: int = Field(default=5242880, ge=1, le=5242880)
    text_char_limit: int = Field(default=30000, ge=1, le=30000)

    bailian_api_key: SecretStr | None = None
    bailian_base_url: str | None = None
    bailian_model: str | None = None
    bailian_region: str | None = None
    text_provider: Literal["bailian", "ark", "configured"] = "bailian"
    ark_api_key: SecretStr | None = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str = "doubao-seed-2-1-lite-260915"
    ark_embedding_model: str = "doubao-embedding-vision-251215"
    ark_embedding_api: Literal["multimodal", "text"] = "multimodal"
    retrieval_cache_dir: Path = PROJECT_ROOT / "work" / "embedding-cache"
    retrieval_min_similarity: float = 0.35
    dialogue_understanding_enabled: bool = False
    model_max_tokens: int = 2000
    extraction_max_tokens: int = Field(default=4000, ge=128, le=4000)
    model_max_requests_per_case: int = 100
    voice_provider: Literal["bailian", "volcengine"] = "bailian"
    volc_speech_api_key: SecretStr | None = None
    volc_asr_resource_id: str = "volc.seedasr.sauc.duration"
    volc_tts_resource_id: str = "seed-tts-2.0"
    volc_custom_voice_resource_id: str = "seed-icl-2.0"
    tts_custom_voice_id: str | None = None
    tts_custom_voice_label: str = "自定义音色"
    tts_model: str = "qwen-audio-3.1-tts-flash"
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_sender: str | None = None
    evaluation_template_path: Path | None = None
    report_template_path: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
