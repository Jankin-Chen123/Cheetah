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
    text_provider: Literal["bailian", "ark"] = "bailian"
    ark_api_key: SecretStr | None = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str = "doubao-seed-2-1-lite-260915"
    ark_embedding_model: str = "doubao-embedding-vision-251215"
    ark_embedding_api: Literal["multimodal", "text"] = "multimodal"
    retrieval_cache_dir: Path = PROJECT_ROOT / "work" / "embedding-cache"
    retrieval_min_similarity: float = 0.35
    dialogue_understanding_enabled: bool = False
    model_max_tokens: int = 2000
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
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
