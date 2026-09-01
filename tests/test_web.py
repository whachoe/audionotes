from __future__ import annotations

from backend import db
from backend.auth import SESSION_COOKIE_NAME
from backend.models import Note, ProcessingStatus
from backend.models import Session as AppSession
from backend.models import User

from tests.conftest import SAMPLE_WAV


def _seed_session(user: User) -> str:
    with db.session_scope() as session:
        app_session = AppSession(user_id=user.id)
        session.add(app_session)
        session.commit()
        session.refresh(app_session)
        return app_session.token


def _seed_note(user_id: str, **overrides) -> Note:
    defaults = dict(
        user_id=user_id,
        audio_filename="x.wav",
        audio_original_filename="x.wav",
        audio_mime_type="audio/wav",
        processing_status=ProcessingStatus.done,
        title="A test note",
    )
    defaults.update(overrides)
    with db.session_scope() as session:
        note = Note(**defaults)
        session.add(note)
        session.commit()
        session.refresh(note)
        return note


def test_root_redirects_to_login_when_signed_out(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/login"


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in with Google" in response.text


def test_login_page_redirects_to_root_when_already_signed_in(client, test_user):
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/"


def test_root_page_lists_the_signed_in_users_notes(client, test_user):
    _seed_note(test_user.id, title="My recorded note")
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.get("/")
    assert response.status_code == 200
    assert "My recorded note" in response.text
    assert test_user.email in response.text


def test_root_page_never_shows_another_users_note(client, test_user):
    with db.session_scope() as session:
        other = User(google_sub="other-sub", email="other@example.com")
        session.add(other)
        session.commit()
        session.refresh(other)
    _seed_note(other.id, title="Someone else's note")

    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get("/")
    assert "Someone else's note" not in response.text


def test_unchecking_every_status_filter_shows_no_notes(client, test_user):
    _seed_note(test_user.id, title="Visible note")
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # filter_submitted present, no `status` values at all = explicitly none selected.
    response = client.get("/?filter_submitted=1&sort_by=created_at&order=desc")
    assert response.status_code == 200
    assert "Visible note" not in response.text
    assert "No notes match" in response.text


def test_filter_selection_persists_via_cookie(client, test_user):
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    submit = client.get("/?filter_submitted=1&sort_by=created_at&order=desc&status=closed")
    assert submit.status_code == 200
    assert "status_filter" in submit.cookies

    # A plain navigation (no filter_submitted, no status params) should now
    # honor the persisted cookie rather than resetting to the hardcoded default.
    _seed_note(test_user.id, title="Open note")
    followup = client.get("/")
    assert "Open note" not in followup.text  # cookie says only "closed" is enabled


def test_status_update_partial_changes_status_and_is_scoped_to_owner(client, test_user):
    note = _seed_note(test_user.id)
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.patch(f"/partials/notes/{note.id}/status", data={"status": "in_progress"})
    assert response.status_code == 200
    assert "in_progress" in response.text

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.status.value == "in_progress"


def test_status_update_rejects_someone_elses_note(client, test_user):
    with db.session_scope() as session:
        other = User(google_sub="other-sub-2", email="other2@example.com")
        session.add(other)
        session.commit()
        session.refresh(other)
    note = _seed_note(other.id)

    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.patch(f"/partials/notes/{note.id}/status", data={"status": "closed"})
    assert response.status_code == 404


def test_note_detail_page_renders_transcript(client, test_user, env_setup):
    note = _seed_note(test_user.id)
    from backend import storage

    storage.write_markdown(note.id, "# Hello\n\nSome transcript text.\n")

    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    response = client.get(f"/notes/{note.id}")
    assert response.status_code == 200
    assert "Some transcript text." in response.text


def test_transcript_update_web_persists(client, test_user, env_setup):
    note = _seed_note(test_user.id)
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    new_markdown = "# Edited\n\nHand-edited via the web frontend.\n"
    response = client.post(f"/notes/{note.id}/transcript", data={"markdown": new_markdown}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/notes/{note.id}"

    from backend import storage

    assert storage.read_markdown(note.id) == new_markdown


def test_logout_clears_session_and_cookie(client, test_user):
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    with db.session_scope() as session:
        assert session.get(AppSession, token) is None

    # The cookie jar's session_token cookie should now be gone (or invalid).
    followup = client.get("/", follow_redirects=False)
    assert followup.status_code in (302, 307)
    assert followup.headers["location"] == "/login"


def test_upload_via_cookie_auth_works_for_the_browser_recorder(client, test_user):
    """The web frontend's JS uploads straight to POST /api/notes with only a
    cookie (no Authorization header) - confirms require_user's cookie
    fallback actually covers the JSON API too, not just the HTML routes."""
    token = _seed_session(test_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    with open(SAMPLE_WAV, "rb") as f:
        response = client.post("/api/notes", files={"file": ("recording.webm", f, "audio/webm")})
    assert response.status_code == 201
    assert response.json()["status"] == "open"

    with db.session_scope() as session:
        note = session.get(Note, response.json()["id"])
        assert note.user_id == test_user.id
