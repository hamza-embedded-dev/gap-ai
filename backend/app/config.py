from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
