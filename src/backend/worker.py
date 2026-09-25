"""Background job processing: transcription -> summarization -> markdown.

Runs as a single asyncio task started from the FastAPI lifespan, polling
SQLite for queued notes every POLL_INTERVAL_SECONDS. Survives process
restarts because state lives in the DB (see recover_stuck_jobs).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlmodel import Session, select

from . import storage
from .models import Note, ProcessingStatus, StorageLocation
from .services import date_recognition, google_calendar, note_storage, summarization, transcription
from .services.markdown_builder import build_markdown

logger = logging.getLogger(__name__)


def recover_stuck_jobs(session: Session) -> int:
    """On startup, reset any note stuck in transcribing/summarizing back to queued.

    Returns the number of notes reset.
    """
    stuck = session.exec(
        select(Note).where(
            Note.processing_status.in_([ProcessingStatus.transcribing, ProcessingStatus.summarizing])
        )
    ).all()
    for note in stuck:
        note.processing_status = ProcessingStatus.queued
        session.add(note)
    if stuck:
        session.commit()
    return len(stuck)


def _claim_next_queued_note(session: Session) -> Optional[Note]:
    """Atomically claim the oldest queued note by flipping it to 'transcribing'."""
    note = session.exec(
        select(Note).where(Note.processing_status == ProcessingStatus.queued).order_by(Note.created_at)
    ).first()
    if note is None:
        return None
    note.processing_status = ProcessingStatus.transcribing
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def _transcribe_note(note: Note) -> str:
    """Materialize the note's audio and transcribe it.

    Both halves are blocking and both belong in the same executor hop: for a
    Drive-resident note (Phase 4) the file has to be downloaded to a temp
    path first, since faster-whisper wants a real filename.
    """
    with note_storage.audio_file_path(note) as audio_file_path:
        return transcription.transcribe_audio(str(audio_file_path))


def _finalize_note(session_factory, note_id: str, title, scheduled_at, markdown_content: str) -> None:
    """Persist the finished note, then park it in the owner's chosen storage.

    Runs in an executor because both the markdown write and the move can hit
    the Drive API. A failed move is logged and left alone rather than
    failing the note: the transcript is already safely written locally at
    that point, and the next settings save will sweep it up.
    """
    session = session_factory()
    try:
        note = session.get(Note, note_id)
        if note is None:
            return
        note.title = title
        note.scheduled_at = scheduled_at
        note.processing_status = ProcessingStatus.done
        note_storage.write_markdown(session, note, markdown_content)
        session.add(note)
        session.commit()
        session.refresh(note)

        if note.user_id is None or note_storage.target_location(session, note.user_id) != StorageLocation.drive:
            return
        if note.storage_location == StorageLocation.drive:
            return
        settings = note_storage.get_user_settings(session, note.user_id)
        try:
            note_storage.move_note_to_drive(session, note, settings.drive_folder_id)
        except Exception:  # noqa: BLE001 - the note itself is already saved
            logger.exception("Couldn't move note %s to Drive; leaving it on local disk", note_id)
    finally:
        session.close()


async def process_next_note(session_factory) -> Optional[str]:
    """Claim and fully process a single queued note, if any exist.

    session_factory: a zero-arg callable returning a new sqlmodel Session.
    Returns the processed note's id, or None if there was nothing queued.
    """
    session = session_factory()
    try:
        note = _claim_next_queued_note(session)
        if note is None:
            return None
        note_id = note.id
    finally:
        session.close()

    loop = asyncio.get_event_loop()

    # --- Transcription (fatal on failure) ---
    try:
        transcript_text = await loop.run_in_executor(None, _transcribe_note, note)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Transcription failed for note %s", note_id)
        session = session_factory()
        try:
            note = session.get(Note, note_id)
            if note is not None:
                note.processing_status = ProcessingStatus.failed
                note.processing_error = f"Transcription failed: {exc}"
                session.add(note)
                session.commit()
        finally:
            session.close()
        return note_id

    # --- Mark summarizing ---
    session = session_factory()
    try:
        note = session.get(Note, note_id)
        if note is None:
            return note_id
        note.processing_status = ProcessingStatus.summarizing
        session.add(note)
        session.commit()
        original_filename = note.audio_original_filename or note.audio_filename
        created_at = note.created_at
        user_id = note.user_id
    finally:
        session.close()

    # --- Summarization (non-fatal on failure; falls back internally) ---
    try:
        title = await summarization.generate_title(transcript_text)
    except Exception:  # noqa: BLE001 - summarization must never fail the note
        logger.exception("Unexpected error generating title for note %s", note_id)
        words = transcript_text.strip().split()
        title = " ".join(words[:10]) if words else "Untitled note"

    # --- Date/time recognition (Phase 2/4, Duckling-based; non-fatal, runs
    # in a thread since it makes blocking HTTP calls) ---
    try:
        scheduled_at = await loop.run_in_executor(
            None, date_recognition.find_scheduled_at, transcript_text, created_at
        )
    except Exception:  # noqa: BLE001 - date recognition must never fail the note
        logger.exception("Date recognition failed for note %s", note_id)
        scheduled_at = None

    # --- Calendar event (Phase 2/3; non-fatal, and a silent no-op if not linked) ---
    if scheduled_at is not None and user_id is not None:
        try:
            await google_calendar.maybe_create_event(
                user_id=user_id, title=title, scheduled_at=scheduled_at, description=transcript_text[:500]
            )
        except Exception:  # noqa: BLE001 - a calendar failure must never fail the note
            logger.exception("Calendar event creation failed for note %s", note_id)

    markdown_content = build_markdown(
        title=title,
        note_id=note_id,
        original_filename=original_filename,
        transcript_text=transcript_text,
    )
    await loop.run_in_executor(
        None, _finalize_note, session_factory, note_id, title, scheduled_at, markdown_content
    )

    return note_id


async def run_worker_loop(
    session_factory,
    poll_interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """Poll forever until stop_event is set, processing one queued note per tick."""
    while not stop_event.is_set():
        try:
            processed_id = await process_next_note(session_factory)
        except Exception:  # noqa: BLE001 - the worker loop must never crash
            logger.exception("Unexpected error in worker loop")
            processed_id = None

        if processed_id is not None:
            # Immediately look for more queued work instead of waiting out the poll interval.
            continue

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except asyncio.TimeoutError:
            pass
