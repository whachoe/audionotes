from __future__ import annotations

import shutil
from datetime import datetime, timezone

import pytest

from backend import db, storage, worker
from backend.models import Note, ProcessingStatus
from backend.services import google_calendar, summarization, transcription

from tests.conftest import FAKE_TITLE, FAKE_TRANSCRIPT, SAMPLE_WAV


@pytest.fixture
def worker_db(env_setup):
    """A configured db engine + on-disk layout, independent of the FastAPI app/lifespan."""
    db.configure_engine(str(env_setup))
    db.init_db()
    yield env_setup


def _seed_queued_note(data_dir) -> Note:
    note = Note(
        audio_filename="note.wav",
        audio_original_filename="note.wav",
        audio_mime_type="audio/wav",
        processing_status=ProcessingStatus.queued,
    )
    with db.session_scope() as session:
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

    audio_dir = data_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLE_WAV, audio_dir / "note.wav")

    with db.session_scope() as session:
        return session.get(Note, note_id)


@pytest.mark.asyncio
async def test_happy_path_queued_to_done(worker_db):
    note = _seed_queued_note(worker_db)

    processed_id = await worker.process_next_note(db.session_scope)
    assert processed_id == note.id

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.processing_status == ProcessingStatus.done
        assert refreshed.processing_error is None
        assert refreshed.title == FAKE_TITLE
        assert refreshed.scheduled_at is None
        assert refreshed.transcript_path == f"notes/{note.id}.md"

    markdown = storage.read_markdown(note.id)
    assert FAKE_TITLE in markdown
    assert FAKE_TRANSCRIPT in markdown
    assert f"/api/notes/{note.id}/audio" in markdown


@pytest.mark.asyncio
async def test_no_queued_notes_returns_none(worker_db):
    result = await worker.process_next_note(db.session_scope)
    assert result is None


@pytest.mark.asyncio
async def test_transcription_failure_marks_failed(worker_db, monkeypatch):
    note = _seed_queued_note(worker_db)

    def boom(path: str) -> str:
        raise RuntimeError("whisper exploded")

    monkeypatch.setattr(transcription, "transcribe_audio", boom)

    processed_id = await worker.process_next_note(db.session_scope)
    assert processed_id == note.id

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.processing_status == ProcessingStatus.failed
        assert refreshed.processing_error is not None
        assert "whisper exploded" in refreshed.processing_error
        # Transcription failure must not silently mark the note done.
        assert refreshed.title is None


@pytest.mark.asyncio
async def test_summarization_failure_still_marks_done_with_fallback_title(worker_db, monkeypatch):
    note = _seed_queued_note(worker_db)

    async def boom(transcript: str, reference_time: datetime):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(summarization, "generate_title_and_schedule", boom)

    processed_id = await worker.process_next_note(db.session_scope)
    assert processed_id == note.id

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.processing_status == ProcessingStatus.done
        assert refreshed.processing_error is None
        expected_fallback = " ".join(FAKE_TRANSCRIPT.split()[:10])
        assert refreshed.title == expected_fallback
        assert refreshed.scheduled_at is None


@pytest.mark.asyncio
async def test_recognized_schedule_is_saved_on_the_note(worker_db, monkeypatch):
    note = _seed_queued_note(worker_db)
    scheduled = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)

    async def fake_with_schedule(transcript: str, reference_time: datetime):
        return FAKE_TITLE, scheduled

    monkeypatch.setattr(summarization, "generate_title_and_schedule", fake_with_schedule)

    processed_id = await worker.process_next_note(db.session_scope)
    assert processed_id == note.id

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        # SQLite/SQLAlchemy strips tzinfo on round-trip for every datetime
        # column here (created_at/updated_at included) - not specific to this
        # feature, so compare naive-to-naive like the rest of this suite would.
        assert refreshed.scheduled_at == scheduled.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_calendar_failure_does_not_fail_the_note(worker_db, monkeypatch):
    """A recognized schedule with no Google account linked (or a Calendar API
    error) must still leave the note done, not failed - worker.py wraps the
    calendar call defensively."""
    note = _seed_queued_note(worker_db)
    scheduled = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)

    async def fake_with_schedule(transcript: str, reference_time: datetime):
        return FAKE_TITLE, scheduled

    async def boom_calendar(*args, **kwargs):
        raise RuntimeError("calendar API exploded")

    monkeypatch.setattr(summarization, "generate_title_and_schedule", fake_with_schedule)
    monkeypatch.setattr(google_calendar, "maybe_create_event", boom_calendar)

    processed_id = await worker.process_next_note(db.session_scope)
    assert processed_id == note.id

    with db.session_scope() as session:
        refreshed = session.get(Note, note.id)
        assert refreshed.processing_status == ProcessingStatus.done
        assert refreshed.scheduled_at == scheduled.replace(tzinfo=None)


def test_recover_stuck_jobs_resets_to_queued(worker_db):
    note = Note(
        audio_filename="stuck.wav",
        processing_status=ProcessingStatus.transcribing,
    )
    with db.session_scope() as session:
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

        reset_count = worker.recover_stuck_jobs(session)
        assert reset_count == 1

        refreshed = session.get(Note, note_id)
        assert refreshed.processing_status == ProcessingStatus.queued
