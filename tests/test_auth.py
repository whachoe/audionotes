from __future__ import annotations

import pytest

from tests.conftest import SAMPLE_WAV


def test_health_requires_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


PROTECTED_ROUTES = [
    ("GET", "/api/notes"),
    ("GET", "/api/notes/some-id"),
    ("PATCH", "/api/notes/some-id/status"),
    ("PUT", "/api/notes/some-id/transcript"),
    ("GET", "/api/notes/some-id/audio"),
    ("GET", "/api/google/auth/status"),
    ("POST", "/api/google/auth/logout"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_protected_routes_require_auth_missing_token(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_protected_routes_reject_wrong_token(client, method, path):
    response = client.request(method, path, headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_upload_requires_auth_missing_token(client):
    with open(SAMPLE_WAV, "rb") as f:
        response = client.post("/api/notes", files={"file": ("sample.wav", f, "audio/wav")})
    assert response.status_code == 401


def test_upload_requires_auth_wrong_token(client):
    with open(SAMPLE_WAV, "rb") as f:
        response = client.post(
            "/api/notes",
            files={"file": ("sample.wav", f, "audio/wav")},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert response.status_code == 401


def test_correct_token_is_accepted(client, auth_headers):
    response = client.get("/api/notes", headers=auth_headers)
    assert response.status_code == 200
