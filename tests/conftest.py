from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.config import reset_settings_cache
from backend.main import create_app
from backend.services import summarization, transcription

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_WAV = FIXTURES_DIR / "sample.wav"

FAKE_TRANSCRIPT = "this is a fake transcript used only for automated testing purposes today"
FAKE_TITLE = "Fake Generated Title"


@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
    """Never hit a real whisper model or a real Ollama server in tests."""

    def fake_transcribe(path: str) -> str:
        return FAKE_TRANSCRIPT

    async def fake_generate_title_and_schedule(
        transcript: str, reference_time: datetime
    ) -> Tuple[str, Optional[datetime]]:
        return FAKE_TITLE, None

    monkeypatch.setattr(transcription, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(summarization, "generate_title_and_schedule", fake_generate_title_and_schedule)


@pytest.fixture
def env_setup(tmp_path, monkeypatch):
    """Point the app at a throwaway DATA_DIR + sqlite db, with a known API token.

    POLL_INTERVAL_SECONDS is set very high so the background worker (started by
    the app's lifespan) does not race API-level assertions about a note being
    freshly "queued".
    """
    data_dir = tmp_path / "data"
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "tiny")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")

    reset_settings_cache()
    db.reset_engine()

    yield data_dir

    db.reset_engine()
    reset_settings_cache()


@pytest.fixture
def client(env_setup):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def sample_wav_bytes():
    return SAMPLE_WAV.read_bytes()
