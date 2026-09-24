"""Where a given note's bytes live, and how to read/write them (Phase 4).

storage.py stays what it always was: the local filesystem layout.
google_drive.py is a thin Drive API wrapper. This module is the one place
that knows a note can be in either, dispatching on note.storage_location so
callers (the API, the worker, the web frontend) don't each grow their own
"if the user has Drive enabled..." branch.

The audio file is the asymmetric one: whisper and ffprobe both need a real
path on disk, so a Drive-resident note is materialized to a temp file for
the duration of an operation rather than being streamed through.
"""
from __future__ import annotations

import contextlib
import io
import logging
import tempfile
from pathlib import Path
from typing import Iterator, Optional

from sqlmodel import Session

from .. import storage
from ..models import Note, StorageLocation, UserSettings
from . import google_drive

logger = logging.getLogger(__name__)

MARKDOWN_MIME_TYPE = "text/markdown"


def get_user_settings(session: Session, user_id: str) -> UserSettings:
    """Fetch (or lazily create) this user's settings row."""
    settings = session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def target_location(session: Session, user_id: Optional[str]) -> StorageLocation:
    """Where a *new* note for this user should end up once it's processed."""
    if user_id is None:
        return StorageLocation.local
    settings = session.get(UserSettings, user_id)
    if settings is not None and settings.drive_enabled and settings.drive_folder_id:
        return StorageLocation.drive
    return StorageLocation.local


def markdown_filename(note: Note) -> str:
    return f"{note.id}.md"


# --- Markdown -------------------------------------------------------------


def read_markdown(note: Note) -> str:
    """The note's markdown, or "" if it has none yet.

    Never raises for a missing file - a note that hasn't been transcribed
    yet legitimately has no markdown, and the detail page renders an empty
    editor for it either way.
    """
    if note.storage_location != StorageLocation.drive:
        return storage.read_markdown(note.id)

    if not note.transcript_drive_file_id:
        return ""
    try:
        raw = google_drive.download_file(note.user_id, note.transcript_drive_file_id)
    except google_drive.DriveError:
        logger.exception("Couldn't read markdown for note %s from Drive", note.id)
        raise
    return raw.decode("utf-8")


def write_markdown(session: Session, note: Note, content: str) -> None:
    """Persist markdown wherever this note lives, updating the note row's
    location bookkeeping. Does not commit - the caller owns the transaction.
    """
    if note.storage_location != StorageLocation.drive:
        note.transcript_path = storage.write_markdown(note.id, content)
        return

    payload = io.BytesIO(content.encode("utf-8"))
    if note.transcript_drive_file_id:
        # We already know exactly which file this is - overwrite it in place
        # rather than looking it up by name in a folder it may since have
        # been moved out of.
        file_id = google_drive.update_file(
            note.user_id, note.transcript_drive_file_id, payload, MARKDOWN_MIME_TYPE
        )
    else:
        settings = get_user_settings(session, note.user_id)
        folder_id = settings.drive_folder_id
        if not folder_id:
            raise google_drive.DriveError("No Drive folder is configured for this account.")
        file_id = google_drive.upload_file(
            note.user_id, folder_id, markdown_filename(note), payload, MARKDOWN_MIME_TYPE
        )

    note.transcript_drive_file_id = file_id
    note.transcript_path = None


# --- Audio ----------------------------------------------------------------


def read_audio_bytes(note: Note) -> bytes:
    if note.storage_location != StorageLocation.drive:
        path = storage.audio_path(note.id, note.audio_filename)
        return path.read_bytes()
    if not note.audio_drive_file_id:
        raise FileNotFoundError(f"Note {note.id} has no audio on Drive")
    return google_drive.download_file(note.user_id, note.audio_drive_file_id)


def audio_exists(note: Note) -> bool:
    if not note.audio_filename:
        return False
    if note.storage_location != StorageLocation.drive:
        return storage.audio_path(note.id, note.audio_filename).exists()
    return bool(note.audio_drive_file_id)


@contextlib.contextmanager
def audio_file_path(note: Note) -> Iterator[Path]:
    """Yield a real on-disk path to this note's audio.

    For a local note that's just its permanent path. For a Drive note it's a
    temp file that's deleted on exit - ffprobe and faster-whisper both want
    a filename, not a stream.
    """
    if note.storage_location != StorageLocation.drive:
        yield storage.audio_path(note.id, note.audio_filename)
        return

    suffix = Path(note.audio_filename or "").suffix
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    temp_path = Path(handle.name)
    try:
        handle.write(read_audio_bytes(note))
        handle.close()
        yield temp_path
    finally:
        with contextlib.suppress(OSError):
            temp_path.unlink()


# --- Moving a single note between locations (used by the migration) -------


def move_note_to_drive(session: Session, note: Note, folder_id: str) -> None:
    """Upload this note's files to Drive, then remove the local copies.

    Deliberately ordered upload-then-delete, and the delete only happens
    once every upload has succeeded: a crash in the middle leaves a
    harmless duplicate on Drive rather than a note with no bytes anywhere.
    """
    if note.storage_location == StorageLocation.drive:
        return

    local_audio = storage.audio_path(note.id, note.audio_filename) if note.audio_filename else None
    local_markdown = storage.markdown_path(note.id)

    if local_audio is not None and local_audio.exists():
        with open(local_audio, "rb") as audio_file:
            note.audio_drive_file_id = google_drive.upload_file(
                note.user_id,
                folder_id,
                note.audio_filename,
                audio_file,
                note.audio_mime_type or "application/octet-stream",
            )

    if local_markdown.exists():
        note.transcript_drive_file_id = google_drive.upload_file(
            note.user_id,
            folder_id,
            markdown_filename(note),
            io.BytesIO(local_markdown.read_bytes()),
            MARKDOWN_MIME_TYPE,
        )

    note.storage_location = StorageLocation.drive
    note.transcript_path = None
    session.add(note)
    session.commit()

    # Only now that the DB agrees the note lives on Drive do the local
    # copies become redundant.
    for path in (local_audio, local_markdown):
        if path is not None and path.exists():
            with contextlib.suppress(OSError):
                path.unlink()


def move_note_to_local(session: Session, note: Note) -> None:
    """Download this note's files back to the server, then trash the Drive copies."""
    if note.storage_location != StorageLocation.drive:
        return

    audio_file_id = note.audio_drive_file_id
    transcript_file_id = note.transcript_drive_file_id

    if audio_file_id and note.audio_filename:
        audio_bytes = google_drive.download_file(note.user_id, audio_file_id)
        storage.audio_path(note.id, note.audio_filename).write_bytes(audio_bytes)

    if transcript_file_id:
        markdown = google_drive.download_file(note.user_id, transcript_file_id).decode("utf-8")
        note.transcript_path = storage.write_markdown(note.id, markdown)

    note.storage_location = StorageLocation.local
    note.audio_drive_file_id = None
    note.transcript_drive_file_id = None
    session.add(note)
    session.commit()

    for file_id in (audio_file_id, transcript_file_id):
        if file_id:
            google_drive.delete_file(note.user_id, file_id)
