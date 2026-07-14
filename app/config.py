"""Application settings, loaded from environment variables / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    # gpt-4o (not 4o-mini): 4o-mini would not reliably follow the "ask for
    # missing data, never assume a duration or invent a title" instruction, so
    # it silently booked 30-minute slots. gpt-4o obeys it. Override via env (D2).
    openai_model: str = "gpt-4o"
    # Dev-only default (>=32 bytes per RFC 7518 for HS256); override in production.
    jwt_secret: str = "dev-only-secret-change-me-in-production!"
    jwt_ttl_minutes: int = 8 * 60
    database_url: str = "sqlite:///data/roombooking.db"


settings = Settings()
