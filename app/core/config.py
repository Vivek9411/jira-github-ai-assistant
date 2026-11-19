import json
from functools import lru_cache
from typing import Any, Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Jira-GitHub AI Assistant"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    ALLOWED_ORIGINS: list[str] | str = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
    ]

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def assemble_origins(cls, v: list[str] | str) -> list[str]:
        """Support comma-delimited strings, JSON arrays, or native lists from .env."""
        if isinstance(v, str):
            clean = v.strip()
            if clean.startswith("[") and clean.endswith("]"):
                try:
                    return json.loads(clean)
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in clean.split(",") if origin.strip()]
        return v

    # Security & Encryption (Fernet AES-256 master key for third-party tokens)
    ENCRYPTION_KEY: str

    # JWT Authentication
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/jira_gh_db"

    # Passwordless Email & OTP
    EMAIL_DELIVERY_METHOD: Literal["console", "smtp"] = "console"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@jiraghassistant.local"
    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 3
    OTP_COOLDOWN_SECONDS: int = 60
    OTP_MAX_REQUESTS_PER_WINDOW: int = 5
    OTP_WINDOW_MINUTES: int = 15

    # Webhook Secrets
    GITHUB_WEBHOOK_SECRET: str = ""
    JIRA_WEBHOOK_SECRET: str = ""

    # OAuth Settings (Optional)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    JIRA_CLIENT_ID: str = ""
    JIRA_CLIENT_SECRET: str = ""

    # AI & Embeddings
    LLM_PROVIDER: Literal["gemini", "openai", "mock"] = "gemini"
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
