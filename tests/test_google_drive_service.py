"""Exercises the REAL google_drive module - only Google's HTTP layer is faked.

tests/test_drive_storage.py monkeypatches the whole google_drive module, which
is right for testing *our* storage logic but means `_credentials_for`,
`_service_for`, `_find_file_id`, the upload/update/download/delete bodies and
the HttpError classifier never actually execute. A credential-state bug lived
in that blind spot long enough to reach production (a plain sign-in silently
un-linking Drive), so these tests drive the module itself and stub only
`build()` and the token refresh.
"""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from backend import db
from backend.config import reset_settings_cache
from backend.models import GoogleCredential, User
from backend.services import google_drive


@pytest.fixture
def google_configured(env_setup, monkeypatch):
    # env_setup points DATA_DIR at a tmp dir and resets the engine, but it's
    # the `client` fixture that normally creates the schema via create_app();
    # these tests drive the service directly, so do it here.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    reset_settings_cache()
    db.init_db()
    yield
    reset_settings_cache()


def _user(scopes: str | None = None, refresh_token: str | None = "rt") -> str:
    with db.session_scope() as session:
        user = User(google_sub="drive-sub", email="whachoe@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(
            GoogleCredential(
                user_id=user.id,
                access_token="at",
                refresh_token=refresh_token,
                scopes=scopes if scopes is not None else " ".join(google_drive.SCOPES),
            )
        )
        session.commit()
        return user.id


class _Files:
    """Records the Drive calls our code makes, and answers them."""

    def __init__(self, log, list_result=None, raises=None):
        self.log = log
        self.list_result = list_result if list_result is not None else {"files": []}
        self.raises = raises

    def _resp(self, value):
        m = MagicMock()
        if self.raises is not None:
            m.execute.side_effect = self.raises
        else:
            m.execute.return_value = value
        return m

    def list(self, **kw):
        self.log.append(("list", kw))
        return self._resp(self.list_result)

    def create(self, **kw):
        self.log.append(("create", kw))
        return self._resp({"id": "created-id", "name": kw.get("body", {}).get("name", "n")})

    def update(self, **kw):
        self.log.append(("update", kw))
        return self._resp({"id": kw.get("fileId", "updated-id")})

    def get(self, **kw):
        self.log.append(("get", kw))
        return self._resp(
            {"id": "folder-x", "name": "Folder X", "mimeType": google_drive.FOLDER_MIME_TYPE, "parents": ["root"]}
        )


def _service(log, **kwargs):
    svc = MagicMock()
    svc.files.return_value = _Files(log, **kwargs)
    return svc


def _http_error(status_code: int, reason: str, message: str = "boom") -> HttpError:
    content = json.dumps(
        {"error": {"code": status_code, "message": message, "errors": [{"message": message, "reason": reason}]}}
    ).encode()
    return HttpError(SimpleNamespace(status=status_code, reason=reason), content, uri="https://drive/x")


# --- Credential handling (the part that was never covered) -----------------


def test_a_credential_without_the_drive_scope_is_refused_before_any_call(google_configured):
    """has_drive_scope is the gate; reaching Google with a login-only grant
    would just waste a round trip to be told the same thing."""
    user_id = _user(scopes="openid email https://www.googleapis.com/auth/calendar.events")
    with pytest.raises(google_drive.DriveNotLinkedError):
        google_drive.list_folders(user_id)


def test_a_credential_without_a_refresh_token_is_refused(google_configured):
    user_id = _user(refresh_token=None)
    with pytest.raises(google_drive.DriveNotLinkedError):
        google_drive.list_folders(user_id)


def test_a_failing_token_refresh_reads_as_not_linked(google_configured):
    user_id = _user()
    with patch("google.oauth2.credentials.Credentials.refresh", side_effect=Exception("invalid_grant")):
        with pytest.raises(google_drive.DriveNotLinkedError) as exc:
            google_drive.list_folders(user_id)
    assert "invalid_grant" in str(exc.value)


def test_a_successful_call_persists_the_refreshed_access_token(google_configured):
    """Every Drive call refreshes and writes the new token back - through a
    second DB session nested inside whatever session the caller holds."""
    user_id = _user()
    log = []

    def fake_refresh(self, request):
        self.token = "refreshed-token"

    with patch("backend.services.google_drive.build", return_value=_service(log)), patch(
        "google.oauth2.credentials.Credentials.refresh", fake_refresh
    ):
        google_drive.list_folders(user_id)

    with db.session_scope() as session:
        assert session.get(GoogleCredential, user_id).access_token == "refreshed-token"


def test_google_not_configured_on_this_server_is_refused(env_setup, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    reset_settings_cache()
    db.init_db()
    user_id = _user()
    with pytest.raises(google_drive.DriveNotLinkedError):
        google_drive.list_folders(user_id)
    reset_settings_cache()


# --- Query building and the upload replace-vs-create decision --------------


@pytest.fixture
def refreshed():
    with patch("google.oauth2.credentials.Credentials.refresh", return_value=None):
        yield


def test_folder_names_with_quotes_cannot_break_out_of_the_query(google_configured, refreshed):
    """Drive queries are single-quoted strings; an apostrophe in a folder
    name must be escaped or the query is malformed (or worse, injected)."""
    user_id = _user()
    log = []
    with patch("backend.services.google_drive.build", return_value=_service(log)):
        google_drive.create_folder(user_id, "Jo's notes", "root")
        google_drive.list_folders(user_id, "it's-a-folder-id")

    list_query = [kw["q"] for name, kw in log if name == "list"][0]
    assert "\\'" in list_query, list_query


def test_upload_replaces_an_existing_file_rather_than_duplicating_it(google_configured, refreshed):
    """A note's markdown is rewritten on every edit - without the lookup,
    Drive would happily accumulate a dozen files all called <id>.md."""
    user_id = _user()
    log = []
    existing = {"files": [{"id": "already-there"}]}
    with patch("backend.services.google_drive.build", return_value=_service(log, list_result=existing)):
        file_id = google_drive.upload_file(user_id, "folder-1", "note.md", io.BytesIO(b"x"), "text/markdown")

    assert file_id == "already-there"
    assert [name for name, _ in log] == ["list", "update"]  # not "create"


def test_upload_creates_when_nothing_is_there(google_configured, refreshed):
    user_id = _user()
    log = []
    with patch("backend.services.google_drive.build", return_value=_service(log)):
        file_id = google_drive.upload_file(user_id, "folder-1", "note.md", io.BytesIO(b"x"), "text/markdown")

    assert file_id == "created-id"
    assert [name for name, _ in log] == ["list", "create"]


def test_delete_trashes_rather_than_destroying(google_configured, refreshed):
    """A move's second half. Trashing is recoverable for 30 days; a move
    that vaporizes the only copy of a recording is not a move worth having."""
    user_id = _user()
    log = []
    with patch("backend.services.google_drive.build", return_value=_service(log)):
        google_drive.delete_file(user_id, "file-9")

    name, kw = log[0]
    assert name == "update"
    assert kw["body"] == {"trashed": True}


def test_a_folder_that_is_gone_reads_as_none_not_an_error(google_configured, refreshed):
    user_id = _user()
    log = []
    with patch(
        "backend.services.google_drive.build",
        return_value=_service(log, raises=_http_error(404, "notFound")),
    ):
        assert google_drive.get_folder(user_id, "missing") is None


# --- The HttpError classifier ---------------------------------------------


def test_the_drive_api_being_disabled_is_classified_as_a_setup_problem():
    """The real first-deployment failure: enabling the Calendar API doesn't
    enable Drive, so Google answers 403 accessNotConfigured."""
    real_message = (
        "Google Drive API has not been used in project 398709281802 before or it is disabled. "
        "Enable it by visiting https://console.developers.google.com/apis/api/drive.googleapis.com/"
        "overview?project=398709281802 then retry."
    )
    wrapped = google_drive._wrap_http_error(
        _http_error(403, "accessNotConfigured", real_message), "Couldn't look for the default Drive folder"
    )
    assert isinstance(wrapped, google_drive.DriveNotEnabledError)
    assert "isn't enabled" in str(wrapped)
    assert "Library" in str(wrapped)  # says where to go, not just that it broke


def test_missing_scopes_are_classified_as_needing_a_reconnect():
    """Same status code as above, different reason, different remedy - this
    one the user fixes themselves by re-consenting."""
    wrapped = google_drive._wrap_http_error(
        _http_error(403, "insufficientPermissions", "Insufficient Permission"), "Couldn't list Drive folders"
    )
    assert isinstance(wrapped, google_drive.DriveNotLinkedError)
    assert "Reconnect" in str(wrapped)


def test_an_unrecognized_failure_keeps_its_original_detail():
    wrapped = google_drive._wrap_http_error(_http_error(500, "backendError"), "Couldn't list Drive folders")
    assert type(wrapped) is google_drive.DriveError
    assert "Couldn't list Drive folders" in str(wrapped)


def test_a_non_json_error_body_does_not_itself_explode():
    exc = HttpError(SimpleNamespace(status=500, reason="x"), b"<html>gateway timeout</html>", uri="u")
    wrapped = google_drive._wrap_http_error(exc, "Couldn't list Drive folders")
    assert type(wrapped) is google_drive.DriveError
