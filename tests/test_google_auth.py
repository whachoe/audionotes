from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest
from sqlmodel import select

from backend import db
from backend.config import reset_settings_cache
from backend.models import GoogleCredential, Note, ProcessingStatus, Session, User
from backend.routers import google_auth as google_auth_module


@pytest.fixture
def google_configured(env_setup, monkeypatch):
    """Fill in the Google OAuth env vars a real deployment would set, and
    allow-list one test email, so the /start -> /callback flow can be
    exercised past the "not configured" gate.
    """
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://notes.example.com/api/google/auth/callback")
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "allowed@example.com")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_start_is_503_when_google_not_configured(client):
    response = client.get("/api/google/auth/start", follow_redirects=False)
    assert response.status_code == 503


def test_start_redirects_to_google_and_requests_combined_scopes(client, google_configured):
    response = client.get("/api/google/auth/start", follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = parse_qs(urlparse(location).query)
    assert query["client_id"] == ["test-client-id"]
    assert "state" in query
    scopes = query["scope"][0].split()
    assert {"openid", "email", "profile", "https://www.googleapis.com/auth/calendar.events"} <= set(scopes)


def test_callback_reports_google_error(client):
    response = client.get("/api/google/auth/callback?error=access_denied")
    assert response.status_code == 200
    assert "access_denied" in response.text


def test_callback_rejects_missing_or_unknown_state(client, google_configured):
    response = client.get("/api/google/auth/callback?code=abc123&state=never-issued")
    assert response.status_code == 200
    assert "failed" in response.text.lower()


class _FakeTokenResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self._json = json_body
        self.text = str(json_body)

    def json(self) -> dict:
        return self._json


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient's token-exchange POST in tests -
    nothing here should ever hit the real network."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url, data=None, **kwargs) -> _FakeTokenResponse:
        return _FakeTokenResponse(
            200,
            {
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "id_token": "fake-id-token",
            },
        )


def _start_and_get_state(client) -> str:
    response = client.get("/api/google/auth/start", follow_redirects=False)
    location = response.headers["location"]
    return parse_qs(urlparse(location).query)["state"][0]


def _patch_google_verification(monkeypatch, email: str, sub: str = "google-sub-123", name: str = "Test User"):
    def fake_verify(token, request, audience):
        return {"sub": sub, "email": email, "email_verified": True, "name": name}

    monkeypatch.setattr(google_auth_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(google_auth_module.google_id_token, "verify_oauth2_token", fake_verify)


def _extract_token(html: str) -> str:
    match = re.search(r"token=([\w-]+)", html)
    assert match is not None, html
    return match.group(1)


def test_callback_rejects_email_not_on_allowlist(client, google_configured, monkeypatch):
    state = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="stranger@example.com")

    response = client.get(f"/api/google/auth/callback?code=abc123&state={state}")
    assert response.status_code == 200
    assert "isn't authorized" in response.text.lower()

    with db.session_scope() as session:
        assert session.exec(select(User)).first() is None


def test_callback_creates_user_credential_and_session_for_allowed_email(client, google_configured, monkeypatch):
    state = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="allowed@example.com")

    response = client.get(f"/api/google/auth/callback?code=abc123&state={state}")
    assert response.status_code == 200
    assert "copywastenotes://auth?token=" in response.text

    with db.session_scope() as session:
        user = session.exec(select(User).where(User.email == "allowed@example.com")).first()
        assert user is not None
        assert user.name == "Test User"

        cred = session.get(GoogleCredential, user.id)
        assert cred is not None
        assert cred.refresh_token == "fake-refresh-token"

        sessions = session.exec(select(Session).where(Session.user_id == user.id)).all()
        assert len(sessions) == 1
        assert sessions[0].token == _extract_token(response.text)


def test_repeat_signin_reuses_the_same_user(client, google_configured, monkeypatch):
    state1 = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="allowed@example.com", sub="same-sub")
    client.get(f"/api/google/auth/callback?code=abc123&state={state1}")

    state2 = _start_and_get_state(client)
    client.get(f"/api/google/auth/callback?code=abc456&state={state2}")

    with db.session_scope() as session:
        users = session.exec(select(User).where(User.email == "allowed@example.com")).all()
        assert len(users) == 1
        # Both sign-ins issued their own session (multiple devices allowed).
        sessions = session.exec(select(Session).where(Session.user_id == users[0].id)).all()
        assert len(sessions) == 2


def test_first_signin_claims_pre_existing_orphaned_notes(client, google_configured, monkeypatch):
    # Simulate a note recorded before Phase 3 (multi-user) existed.
    with db.session_scope() as session:
        note = Note(audio_filename="old.wav", processing_status=ProcessingStatus.done)
        session.add(note)
        session.commit()
        note_id = note.id

    state = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="allowed@example.com")
    client.get(f"/api/google/auth/callback?code=abc123&state={state}")

    with db.session_scope() as session:
        user = session.exec(select(User).where(User.email == "allowed@example.com")).first()
        refreshed_note = session.get(Note, note_id)
        assert refreshed_note.user_id == user.id


def test_second_signin_does_not_claim_notes_owned_by_the_first_user(client, google_configured, monkeypatch):
    with db.session_scope() as session:
        note = Note(audio_filename="old.wav", processing_status=ProcessingStatus.done)
        session.add(note)
        session.commit()
        note_id = note.id

    # First sign-in claims the orphaned note.
    state1 = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="allowed@example.com", sub="first-user-sub")
    client.get(f"/api/google/auth/callback?code=abc123&state={state1}")

    # A second (differently allow-listed) account signs in afterward.
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "allowed@example.com,second@example.com")
    reset_settings_cache()
    state2 = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="second@example.com", sub="second-user-sub")
    client.get(f"/api/google/auth/callback?code=def456&state={state2}")

    with db.session_scope() as session:
        first_user = session.exec(select(User).where(User.email == "allowed@example.com")).first()
        refreshed_note = session.get(Note, note_id)
        assert refreshed_note.user_id == first_user.id  # untouched by the second sign-in


def test_status_reports_identity_and_calendar_link(client, google_configured, monkeypatch):
    state = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="allowed@example.com")
    callback_response = client.get(f"/api/google/auth/callback?code=abc123&state={state}")
    token = _extract_token(callback_response.text)

    response = client.get("/api/google/auth/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "allowed@example.com"
    assert body["calendar_linked"] is True


def test_logout_revokes_the_session(client, google_configured, monkeypatch):
    state = _start_and_get_state(client)
    _patch_google_verification(monkeypatch, email="allowed@example.com")
    callback_response = client.get(f"/api/google/auth/callback?code=abc123&state={state}")
    headers = {"Authorization": f"Bearer {_extract_token(callback_response.text)}"}

    logout_response = client.post("/api/google/auth/logout", headers=headers)
    assert logout_response.status_code == 204

    status_after_logout = client.get("/api/google/auth/status", headers=headers)
    assert status_after_logout.status_code == 401
