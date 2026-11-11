from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).parents[1] / ".env", extra="ignore")
    database_url: str
    source_database_url: str | None = None
    jwt_secret: str = Field(min_length=32)
    environment: str = "development"
    source_dump: str = "Unspecified database"
    source_snapshot: str = "Unknown"
    allowed_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    cookie_secure: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_models: list[str] = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
    ai_query_timeout_ms: int = Field(default=8000, ge=1000, le=30000)
    ai_max_rows: int = Field(default=200, ge=10, le=1000)

    @model_validator(mode="after")
    def production_security(self):
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("Production requires COOKIE_SECURE=true and HTTPS")
        if self.environment == "production" and any(
            not origin.startswith("https://") for origin in self.allowed_origins
        ):
            raise ValueError("Production requires explicit HTTPS origins")
        if "*" in self.allowed_origins:
            raise ValueError("Explicit origins are required")
        return self


@lru_cache
def settings():
    return Settings()
