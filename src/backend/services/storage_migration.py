"""Moving a user's whole note archive between local disk and Drive (Phase 4).

Triggered when the user saves the storage section of their settings. This
can be hundreds of files and every one of them is a network round trip, so
it runs in the background and reports progress through UserSettings rather
than making the settings page wait on it.

Per-note moves are deliberately independent: one note that fails (a Drive
hiccup, a file that vanished from disk) records the error and stops the run,
but every note already moved stays correctly marked as moved. Re-saving the
settings simply resumes with whatever is still on the wrong side.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlmodel import select

from .. import db
from ..models import MigrationStatus, Note, StorageLocation, UserSettings, utcnow
from . import note_storage

logger = logging.getLogger(__name__)


def _notes_to_move(session, user_id: str, target: StorageLocation) -> list[Note]:
    return list(
        session.exec(
            select(Note).where(Note.user_id == user_id).where(Note.storage_location != target)
        ).all()
    )


def migrate_user_storage(user_id: str, target: StorageLocation, folder_id: Optional[str] = None) -> int:
    """Move every one of this user's notes to `target`. Returns how many moved.

    Synchronous and self-contained (its own sessions, its own error
    handling) so it can be run straight from a thread - or called directly
    by a test - without an event loop in sight.
    """
    if target == StorageLocation.drive and not folder_id:
        raise ValueError("A Drive folder is required to migrate notes to Drive.")

    with db.session_scope() as session:
        settings = note_storage.get_user_settings(session, user_id)
        pending = _notes_to_move(session, user_id, target)
        settings.migration_status = MigrationStatus.running
        settings.migration_error = None
        settings.migration_total = len(pending)
        settings.migration_done = 0
        settings.updated_at = utcnow()
        session.add(settings)
        session.commit()
        note_ids = [note.id for note in pending]

    moved = 0
    for note_id in note_ids:
        try:
            with db.session_scope() as session:
                note = session.get(Note, note_id)
                if note is None or note.storage_location == target:
                    continue
                if target == StorageLocation.drive:
                    note_storage.move_note_to_drive(session, note, folder_id)
                else:
                    note_storage.move_note_to_local(session, note)
            moved += 1
        except Exception as exc:  # noqa: BLE001 - recorded for the settings page
            logger.exception("Storage migration failed for note %s", note_id)
            _record_failure(user_id, moved, f"Note {note_id}: {exc}")
            return moved

        with db.session_scope() as session:
            settings = note_storage.get_user_settings(session, user_id)
            settings.migration_done = moved
            settings.updated_at = utcnow()
            session.add(settings)
            session.commit()

    with db.session_scope() as session:
        settings = note_storage.get_user_settings(session, user_id)
        settings.migration_status = MigrationStatus.done
        settings.migration_done = moved
        settings.migration_error = None
        settings.updated_at = utcnow()
        session.add(settings)
        session.commit()

    logger.info("Storage migration for user %s finished: %d note(s) moved to %s", user_id, moved, target.value)
    return moved


def _record_failure(user_id: str, moved: int, message: str) -> None:
    with db.session_scope() as session:
        settings = note_storage.get_user_settings(session, user_id)
        settings.migration_status = MigrationStatus.failed
        settings.migration_error = message[:500]
        settings.migration_done = moved
        settings.updated_at = utcnow()
        session.add(settings)
        session.commit()


# Holding a reference keeps the future from being garbage collected mid-run,
# and gives tests something to await.
_running: set[asyncio.Future] = set()


def start_migration(user_id: str, target: StorageLocation, folder_id: Optional[str] = None) -> asyncio.Future:
    """Kick the migration off in a worker thread and return immediately.

    Drive calls are blocking (googleapiclient), so this never belongs on the
    event loop itself - same reasoning as google_calendar's executor hop.
    """
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, migrate_user_storage, user_id, target, folder_id)
    _running.add(future)
    future.add_done_callback(_running.discard)
    return future
