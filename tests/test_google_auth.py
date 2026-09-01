from __future__ import annotations

import pytest

from backend.config import reset_settings_cache


def test_status_defaults_to_not_linked(client, auth_headers):
    response = client.get("/api/google/auth/status", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"linked": False}


def test_start_rejects_missing_token(client):
    response = client.get("/api/google/auth/start", follow_redirects=False)
    assert response.status_code == 422  # token is a required query param


def test_start_rejects_wrong_token(client):
    response = client.get("/api/google/auth/start?token=wrong", follow_redirects=False)
    assert response.status_code == 401


def test_start_is_503_when_google_not_configured(client, auth_headers):
    # env_setup (conftest) never sets GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI,
    # so the feature is disabled by default - exactly like a real deployment
    # that hasn't filled those env vars in yet.
    response = client.get("/api/google/auth/start?token=test-token", follow_redirects=False)
    assert response.status_code == 503


def test_callback_reports_google_error(client):
    response = client.get("/api/google/auth/callback?error=access_denied")
    assert response.status_code == 200
    assert "access_denied" in response.text


@pytest.fixture
def google_configured(env_setup, monkeypatch):
    """Fill in the Google OAuth env vars a real deployment would set, so the
    /start -> /callback flow can be exercised past the "not configured" gate.
    """
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://notes.example.com/api/google/auth/callback")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_start_redirects_to_google_and_sets_pending_state(client, auth_headers, google_configured):
    response = client.get("/api/google/auth/start?token=test-token", follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in location
    assert "state=" in location


def test_callback_rejects_missing_or_wrong_state(client, google_configured):
    response = client.get("/api/google/auth/callback?code=abc123&state=whatever-not-set")
    assert response.status_code == 200
    assert "failed" in response.text.lower()
