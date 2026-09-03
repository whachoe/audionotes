from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.config import reset_settings_cache
from backend.main import create_app
from backend.models import Session as AppSession
from backend.models import User
from backend.services import summarization, transcription

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_WAV = FIXTURES_DIR / "sample.wav"

# Deliberately has no date/time-shaped words in it, so date_recognition
# (which runs for real in tests - it's local and deterministic, no server to
# mock) naturally finds nothing and scheduled_at stays None by default.
FAKE_TRANSCRIPT = "this is a fake transcript used only for automated testing purposes please"
FAKE_TITLE = "Fake Generated Title"


@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
    """Never hit a real whisper model or a real Ollama server in tests.

    date_recognition isn't mocked here - it's local/deterministic (no
    network, no server), so it's safe (and more meaningful) to let it run
    for real; tests that care about a specific scheduled_at either craft a
    transcript that contains one or monkeypatch it explicitly.
    """

    def fake_transcribe(path: str) -> str:
        return FAKE_TRANSCRIPT

    async def fake_generate_title(transcript: str) -> str:
        return FAKE_TITLE

    monkeypatch.setattr(transcription, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(summarization, "generate_title", fake_generate_title)


@pytest.fixture
def env_setup(tmp_path, monkeypatch):
    """Point the app at a throwaway DATA_DIR + sqlite db.

    POLL_INTERVAL_SECONDS is set very high so the background worker (started by
    the app's lifespan) does not race API-level assertions about a note being
    freshly "queued".
    """
    data_dir = tmp_path / "data"
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
def test_user(client) -> User:
    """A signed-in user for tests to act as (Phase 3: multi-user)."""
    with db.session_scope() as session:
        user = User(google_sub="test-google-sub", email="test@example.com", name="Test User")
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


@pytest.fixture
def auth_headers(test_user):
    with db.session_scope() as session:
        app_session = AppSession(user_id=test_user.id)
        session.add(app_session)
        session.commit()
        session.refresh(app_session)
        return {"Authorization": f"Bearer {app_session.token}"}


@pytest.fixture
def sample_wav_bytes():
    return SAMPLE_WAV.read_bytes()
