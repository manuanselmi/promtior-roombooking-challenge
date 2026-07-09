"""Application settings, loaded from environment variables / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"  # cheap default; override via env (D2)
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 8 * 60
    database_url: str = "sqlite:///data/roombooking.db"


settings = Settings()
