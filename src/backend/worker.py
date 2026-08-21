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
from .models import Note, ProcessingStatus
from .services import summarization, transcription
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
        audio_file_path = storage.audio_path(note.id, note.audio_filename)
    finally:
        session.close()

    loop = asyncio.get_event_loop()

    # --- Transcription (fatal on failure) ---
    try:
        transcript_text = await loop.run_in_executor(
            None, transcription.transcribe_audio, str(audio_file_path)
        )
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
    finally:
        session.close()

    # --- Summarization (non-fatal on failure; falls back internally) ---
    try:
        title = await summarization.generate_title(transcript_text)
    except Exception:  # noqa: BLE001 - summarization must never fail the note
        logger.exception("Unexpected error generating title for note %s", note_id)
        words = transcript_text.strip().split()
        title = " ".join(words[:10]) if words else "Untitled note"

    markdown_content = build_markdown(
        title=title,
        note_id=note_id,
        original_filename=original_filename,
        transcript_text=transcript_text,
    )
    transcript_path = storage.write_markdown(note_id, markdown_content)

    session = session_factory()
    try:
        note = session.get(Note, note_id)
        if note is not None:
            note.title = title
            note.transcript_path = transcript_path
            note.processing_status = ProcessingStatus.done
            session.add(note)
            session.commit()
    finally:
        session.close()

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
