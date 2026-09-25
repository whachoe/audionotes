from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.config import get_settings, reset_settings_cache
from backend.main import create_app
from backend.models import Session as AppSession
from backend.models import User
from backend.services import summarization, transcription

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_WAV = FIXTURES_DIR / "sample.wav"

# Deliberately has no date/time-shaped words in it, so date_recognition
# naturally finds nothing and scheduled_at stays None by default, regardless
# of whether Duckling is reachable.
FAKE_TRANSCRIPT = "this is a fake transcript used only for automated testing purposes please"
FAKE_TITLE = "Fake Generated Title"


@lru_cache
def duckling_reachable() -> bool:
    """Used to skip tests that exercise date_recognition for real (Phase 4:
    it calls out to a Duckling HTTP service, unlike the old dateparser
    implementation which was local/deterministic with nothing to reach).
    """
    try:
        httpx.get(get_settings().DUCKLING_BASE_URL, timeout=1.0)
        return True
    except httpx.HTTPError:
        return False


@lru_cache
def ollama_reachable() -> bool:
    """Used to skip tests that exercise summarization.generate_title for
    real against Ollama. Only confirms the server itself is up - not that
    OLLAMA_MODEL has actually been pulled there (see
    test_summarization_integration.py, which surfaces that case as an
    assertion failure with a pointer to `ollama pull`, rather than a skip).
    """
    try:
        httpx.get(get_settings().OLLAMA_BASE_URL, timeout=1.0)
        return True
    except httpx.HTTPError:
        return False


# deploy/docker-compose.test.yml spins up real Ollama/Duckling instances for
# tests that want them (see the two _reachable() helpers above) with ports
# published on config.py's defaults - see that file for the run command.


@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
    """Never hit a real whisper model or a real Ollama server in tests.

    date_recognition isn't mocked here either - if Duckling isn't running,
    it fails closed (returns None, see its own "must never raise" contract)
    same as if it just found nothing, so it's safe to leave real for tests
    that don't care about a specific scheduled_at. Tests that do either craft
    a transcript and require Duckling (see duckling_reachable()) or
    monkeypatch find_scheduled_at directly.
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
