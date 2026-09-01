"""Application configuration via environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Single static bearer token protecting every route except /health.
    API_TOKEN: str = "changeme"

    # Root directory for persisted data (sqlite db, audio files, markdown notes).
    DATA_DIR: str = "./data"

    # faster-whisper configuration.
    WHISPER_MODEL_SIZE: str = "small"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # Ollama configuration for title summarization.
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"

    # Background worker poll interval, in seconds.
    POLL_INTERVAL_SECONDS: float = 2.0

    # Google Calendar linking (Phase 2). Leave blank to disable the feature
    # entirely - GOOGLE_REDIRECT_URI must exactly match a redirect URI
    # registered on the OAuth client in Google Cloud Console, e.g.
    # "https://notes.example.com/api/google/auth/callback".
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_CALENDAR_ID: str = "primary"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests to force Settings to be re-read after changing env vars."""
    get_settings.cache_clear()
