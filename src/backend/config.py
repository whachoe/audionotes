"""Application configuration via environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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

    # Google sign-in + Calendar linking (Phase 3: one combined OAuth flow is
    # both login and Calendar authorization). Leave blank to disable the
    # feature entirely - GOOGLE_REDIRECT_URI must exactly match a redirect
    # URI registered on the OAuth client in Google Cloud Console, e.g.
    # "https://notes.example.com/api/google/auth/callback".
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_CALENDAR_ID: str = "primary"

    # Comma-separated Google account emails allowed to sign in. Anyone else's
    # Google sign-in is rejected at the OAuth callback. Leave blank to allow
    # no one (safe default) - fill this in before relying on the feature.
    ALLOWED_GOOGLE_EMAILS: str = ""

    # IANA zone recognized date/times are interpreted in and scheduled
    # against on Google Calendar (handles CET/CEST DST automatically).
    LOCAL_TIMEZONE: str = "Europe/Brussels"

    def allowed_google_emails(self) -> set[str]:
        return {email.strip().lower() for email in self.ALLOWED_GOOGLE_EMAILS.split(",") if email.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests to force Settings to be re-read after changing env vars."""
    get_settings.cache_clear()
