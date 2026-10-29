from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Small, fail-closed application settings for the backend foundation."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="ENVIRONMENT"
    )
    token_hash_pepper: SecretStr | None = Field(
        default=None, validation_alias="TOKEN_HASH_PEPPER"
    )
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_service_key: SecretStr | None = Field(
        default=None, validation_alias="SUPABASE_SERVICE_KEY"
    )
    allowed_origins: list[str] = Field(
        default_factory=list, validation_alias="ALLOWED_ORIGINS"
    )
    nebius_api_key: SecretStr | None = Field(
        default=None, validation_alias="NEBIUS_API_KEY"
    )
    nebius_base_url: str = Field(
        default="https://api.tokenfactory.nebius.com/v1",
        validation_alias="NEBIUS_BASE_URL",
    )
    nebius_model: str = Field(
        default="nvidia/Nemotron-3_5-Lightning",
        validation_alias=AliasChoices("NEBIUS_MODEL", "MODEL_SUPER"),
    )
    nebius_timeout_seconds: float = Field(
        default=15.0,
        validation_alias="NEBIUS_TIMEOUT_SECONDS",
    )
    nebius_coaching_timeout_seconds: float = Field(
        default=5.0,
        validation_alias="NEBIUS_COACHING_TIMEOUT_SECONDS",
    )
    groq_api_key: SecretStr | None = Field(
        default=None, validation_alias="GROQ_API_KEY"
    )
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        validation_alias="GROQ_BASE_URL",
    )
    stt_provider: str = Field(
        default="groq",
        validation_alias="STT_PROVIDER",
    )
    stt_model: str = Field(
        default="whisper-large-v3",
        validation_alias=AliasChoices("STT_MODEL", "GROQ_MODEL"),
    )
    groq_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("GROQ_TIMEOUT_SECONDS", "STT_TIMEOUT_SECONDS"),
    )
    tts_enabled: bool = Field(default=True, validation_alias="TTS_ENABLED")
    tts_model: str = Field(
        default="canopylabs/orpheus-v1-english",
        validation_alias="TTS_MODEL",
    )
    tts_voice: str = Field(default="autumn", validation_alias="TTS_VOICE")
    tts_timeout_seconds: float = Field(
        default=10.0,
        validation_alias="TTS_TIMEOUT_SECONDS",
    )
    tts_ai_api_key: SecretStr | None = Field(
        default=None, validation_alias="TTS_AI_API_KEY"
    )
    tts_ai_base_url: str = Field(
        default="https://api.tts.ai/v1/",
        validation_alias="TTS_AI_BASE_URL",
    )
    tts_ai_model: str = Field(
        default="kokoro",
        validation_alias="TTS_AI_MODEL",
    )
    tts_ai_voice: str = Field(
        default="af_heart",
        validation_alias="TTS_AI_VOICE",
    )
    tts_ai_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="TTS_AI_TIMEOUT_SECONDS",
    )
    tts_ai_download_timeout_seconds: float = Field(
        default=10.0,
        validation_alias="TTS_AI_DOWNLOAD_TIMEOUT_SECONDS",
    )
    tts_ai_use_stream: bool = Field(
        default=True,
        validation_alias="TTS_AI_USE_STREAM",
    )




    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("[") and value.endswith("]"):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except (json.JSONDecodeError, ValueError):
                    pass
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        return []

    @model_validator(mode="after")
    def require_production_pepper(self) -> "Settings":
        if self.environment == "production":
            pepper = self.token_hash_pepper.get_secret_value() if self.token_hash_pepper else ""
            if len(pepper) < 32:
                raise ValueError(
                    "TOKEN_HASH_PEPPER must be set to at least 32 characters in production"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
