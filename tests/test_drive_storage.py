"""Phase 4 (Save to Google Drive): settings API, folder chooser, migration.

Drive itself is faked - these tests are about our own logic (which location
a note is read from, what a migration does to the rows and the files on
disk), not about googleapiclient. The fake stands in for a Drive folder as a
plain dict of file id -> bytes, which is all our code actually needs it to be.
"""
from __future__ import annotations

import pytest

from backend import db, storage
from backend.models import (
    GoogleCredential,
    MigrationStatus,
    Note,
    ProcessingStatus,
    StorageLocation,
    User,
    UserSettings,
)
from backend.services import google_drive, note_storage, storage_migration

from tests.conftest import SAMPLE_WAV


class FakeDrive:
    """A stand-in Drive: folders, files, and the handful of calls we make."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.names: dict[str, str] = {}
        self.parents: dict[str, str] = {}
        self.folders: dict[str, str] = {"root": "My Drive"}
        self.trashed: list[str] = []
        self._next = 0

    def _new_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next}"

    # --- the google_drive module's surface ---

    def list_folders(self, user_id, parent_id="root"):
        return [
            {"id": fid, "name": name}
            for fid, name in self.folders.items()
            if fid != "root" and self.parents.get(fid) == parent_id
        ]

    def get_folder(self, user_id, folder_id):
        if folder_id not in self.folders:
            return None
        return {
            "id": folder_id,
            "name": self.folders[folder_id],
            "parent_id": self.parents.get(folder_id),
        }

    def create_folder(self, user_id, name, parent_id="root"):
        folder_id = self._new_id("folder")
        self.folders[folder_id] = name
        self.parents[folder_id] = parent_id
        return {"id": folder_id, "name": name}

    def ensure_default_folder(self, user_id):
        for fid, name in self.folders.items():
            if name == google_drive.DEFAULT_FOLDER_NAME:
                return {"id": fid, "name": name}
        return self.create_folder(user_id, google_drive.DEFAULT_FOLDER_NAME)

    def upload_file(self, user_id, folder_id, filename, content, mime_type="application/octet-stream"):
        data = content.read() if hasattr(content, "read") else bytes(content)
        for fid, name in self.names.items():
            if name == filename and self.parents.get(fid) == folder_id:
                self.files[fid] = data
                return fid
        file_id = self._new_id("file")
        self.files[file_id] = data
        self.names[file_id] = filename
        self.parents[file_id] = folder_id
        return file_id

    def update_file(self, user_id, file_id, content, mime_type="application/octet-stream"):
        data = content.read() if hasattr(content, "read") else bytes(content)
        if file_id not in self.files:
            raise google_drive.DriveError(f"no such file {file_id}")
        self.files[file_id] = data
        return file_id

    def download_file(self, user_id, file_id):
        if file_id not in self.files:
            raise google_drive.DriveError(f"no such file {file_id}")
        return self.files[file_id]

    def delete_file(self, user_id, file_id):
        self.trashed.append(file_id)
        self.files.pop(file_id, None)


@pytest.fixture
def fake_drive(monkeypatch):
    fake = FakeDrive()
    for name in (
        "list_folders",
        "get_folder",
        "create_folder",
        "ensure_default_folder",
        "upload_file",
        "update_file",
        "download_file",
        "delete_file",
    ):
        monkeypatch.setattr(google_drive, name, getattr(fake, name))
    # is_linked is what gates the whole feature; pretend the scope is granted.
    monkeypatch.setattr(google_drive, "is_linked", lambda session, user_id: True)
    return fake


def _link_drive(user: User) -> None:
    with db.session_scope() as session:
        cred = GoogleCredential(
            user_id=user.id,
            access_token="access",
            refresh_token="refresh",
            scopes=" ".join(google_drive.SCOPES),
        )
        session.add(cred)
        session.commit()


def _seed_local_note(user_id: str, markdown: str = "# Local note\n") -> Note:
    with db.session_scope() as session:
        note = Note(
            user_id=user_id,
            audio_filename="sample.wav",
            audio_original_filename="sample.wav",
            audio_mime_type="audio/wav",
            processing_status=ProcessingStatus.done,
            title="A local note",
        )
        session.add(note)
        session.commit()
        session.refresh(note)

    storage.audio_path(note.id, note.audio_filename).write_bytes(SAMPLE_WAV.read_bytes())
    storage.write_markdown(note.id, markdown)
    return note


# --- Scope / linking -------------------------------------------------------


def test_drive_is_not_linked_by_a_plain_login(client, test_user):
    """Login asks for Calendar, never Drive - the Drive scope is granted
    separately from the settings page, so a fresh account must read as
    unlinked even though it has a GoogleCredential row."""
    with db.session_scope() as session:
        session.add(
            GoogleCredential(
                user_id=test_user.id,
                access_token="a",
                refresh_token="r",
                scopes="openid email https://www.googleapis.com/auth/calendar.events",
            )
        )
        session.commit()
        assert google_drive.is_linked(session, test_user.id) is False


def test_drive_counts_as_linked_once_the_scope_is_granted(client, test_user):
    _link_drive(test_user)
    with db.session_scope() as session:
        assert google_drive.is_linked(session, test_user.id) is True


# --- Settings API ----------------------------------------------------------


def test_enabling_drive_without_a_folder_creates_the_default_one(
    client, auth_headers, test_user, fake_drive, env_setup
):
    _link_drive(test_user)
    response = client.put("/api/settings/storage", json={"drive_enabled": True}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["drive_enabled"] is True
    assert body["drive_folder_name"] == google_drive.DEFAULT_FOLDER_NAME
    assert body["drive_folder_id"]


def test_enabling_drive_is_refused_when_the_scope_was_never_granted(client, auth_headers, test_user):
    response = client.put("/api/settings/storage", json={"drive_enabled": True}, headers=auth_headers)
    assert response.status_code == 400
    assert "isn't linked" in response.json()["detail"]


def test_choosing_a_folder_that_no_longer_exists_is_refused(
    client, auth_headers, test_user, fake_drive, env_setup
):
    _link_drive(test_user)
    response = client.put(
        "/api/settings/storage",
        json={"drive_enabled": True, "drive_folder_id": "folder-that-vanished"},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_folder_listing_and_creation_drive_the_chooser(client, auth_headers, test_user, fake_drive):
    _link_drive(test_user)
    created = client.post("/api/drive/folders", json={"name": "Voice notes"}, headers=auth_headers)
    assert created.status_code == 201
    folder_id = created.json()["id"]

    listing = client.get("/api/drive/folders", headers=auth_headers)
    assert listing.status_code == 200
    assert {"id": folder_id, "name": "Voice notes"} in listing.json()["folders"]

    # Descending into it reports where "up" goes, so the chooser can offer it.
    inside = client.get(f"/api/drive/folders?parent_id={folder_id}", headers=auth_headers)
    assert inside.json()["parent_name"] == "Voice notes"
    assert inside.json()["grandparent_id"] == "root"


def test_folder_endpoints_require_the_drive_scope(client, auth_headers, test_user):
    assert client.get("/api/drive/folders", headers=auth_headers).status_code == 400
    assert client.post("/api/drive/folders", json={"name": "x"}, headers=auth_headers).status_code == 400


# --- Migration -------------------------------------------------------------


def test_migrating_to_drive_uploads_both_files_and_clears_local_disk(
    client, test_user, fake_drive, env_setup
):
    _link_drive(test_user)
    note = _seed_local_note(test_user.id, "# Shopping\n\n- milk\n")
    folder = fake_drive.create_folder(test_user.id, "Notes folder")

    moved = storage_migration.migrate_user_storage(test_user.id, StorageLocation.drive, folder["id"])
    assert moved == 1

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.storage_location == StorageLocation.drive
        assert refreshed.audio_drive_file_id
        assert refreshed.transcript_drive_file_id
        # The markdown is readable through the indirection, from Drive.
        assert note_storage.read_markdown(refreshed) == "# Shopping\n\n- milk\n"

    assert not storage.audio_path(note.id, "sample.wav").exists()
    assert not storage.markdown_path(note.id).exists()


def test_migrating_back_to_local_downloads_the_files_and_trashes_the_drive_copies(
    client, test_user, fake_drive, env_setup
):
    _link_drive(test_user)
    note = _seed_local_note(test_user.id, "# Round trip\n")
    folder = fake_drive.create_folder(test_user.id, "Notes folder")
    storage_migration.migrate_user_storage(test_user.id, StorageLocation.drive, folder["id"])

    with db.session_scope() as session:
        drive_ids = {
            session.get(Note, note.id).audio_drive_file_id,
            session.get(Note, note.id).transcript_drive_file_id,
        }

    moved_back = storage_migration.migrate_user_storage(test_user.id, StorageLocation.local)
    assert moved_back == 1

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.storage_location == StorageLocation.local
        assert refreshed.audio_drive_file_id is None
        assert refreshed.transcript_drive_file_id is None

    assert storage.markdown_path(note.id).read_text(encoding="utf-8") == "# Round trip\n"
    assert storage.audio_path(note.id, "sample.wav").read_bytes() == SAMPLE_WAV.read_bytes()
    # "Move", not "copy": the Drive copies were trashed on the way back.
    assert drive_ids.issubset(set(fake_drive.trashed))


def test_migration_records_progress_and_failure_without_losing_moved_notes(
    client, test_user, fake_drive, env_setup, monkeypatch
):
    _link_drive(test_user)
    first = _seed_local_note(test_user.id, "# One\n")
    second = _seed_local_note(test_user.id, "# Two\n")
    folder = fake_drive.create_folder(test_user.id, "Notes folder")

    real_upload = fake_drive.upload_file
    calls = {"n": 0}

    def flaky_upload(*args, **kwargs):
        calls["n"] += 1
        # Fail partway through the *second* note (3rd upload: audio+md, then audio).
        if calls["n"] == 3:
            raise google_drive.DriveError("drive is having a day")
        return real_upload(*args, **kwargs)

    monkeypatch.setattr(google_drive, "upload_file", flaky_upload)

    moved = storage_migration.migrate_user_storage(test_user.id, StorageLocation.drive, folder["id"])
    assert moved == 1

    with db.session_scope() as session:
        settings = session.get(UserSettings, test_user.id)
        assert settings.migration_status == MigrationStatus.failed
        assert "drive is having a day" in settings.migration_error

        # The note that did make it is correctly marked as living on Drive,
        # and the one that didn't is untouched - so re-saving resumes.
        locations = {
            session.get(Note, first.id).storage_location,
            session.get(Note, second.id).storage_location,
        }
        assert locations == {StorageLocation.drive, StorageLocation.local}


# --- Reading a Drive-resident note through the normal API ------------------


def test_note_detail_and_audio_are_served_from_drive(
    client, auth_headers, test_user, fake_drive, env_setup
):
    _link_drive(test_user)
    note = _seed_local_note(test_user.id, "# From Drive\n")
    folder = fake_drive.create_folder(test_user.id, "Notes folder")
    storage_migration.migrate_user_storage(test_user.id, StorageLocation.drive, folder["id"])

    detail = client.get(f"/api/notes/{note.id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["transcript_markdown"] == "# From Drive\n"

    audio = client.get(f"/api/notes/{note.id}/audio", headers=auth_headers)
    assert audio.status_code == 200
    assert audio.content == SAMPLE_WAV.read_bytes()

    # Range requests still work when the bytes come from Drive.
    ranged = client.get(f"/api/notes/{note.id}/audio", headers={**auth_headers, "Range": "bytes=0-9"})
    assert ranged.status_code == 206
    assert ranged.content == SAMPLE_WAV.read_bytes()[0:10]


def test_editing_a_drive_notes_transcript_writes_back_to_drive(
    client, auth_headers, test_user, fake_drive, env_setup
):
    _link_drive(test_user)
    note = _seed_local_note(test_user.id, "# Before\n")
    folder = fake_drive.create_folder(test_user.id, "Notes folder")
    storage_migration.migrate_user_storage(test_user.id, StorageLocation.drive, folder["id"])

    response = client.put(
        f"/api/notes/{note.id}/transcript", json={"markdown": "# After\n"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["transcript_markdown"] == "# After\n"

    # Written to Drive, not quietly resurrected on local disk.
    assert not storage.markdown_path(note.id).exists()
    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert fake_drive.files[refreshed.transcript_drive_file_id].decode() == "# After\n"
