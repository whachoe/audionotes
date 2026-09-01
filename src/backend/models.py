"""SQLModel table definitions and enums for cjpa's Notes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoteStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    todo = "todo"
    closed = "closed"


class ProcessingStatus(str, Enum):
    queued = "queued"
    transcribing = "transcribing"
    summarizing = "summarizing"
    done = "done"
    failed = "failed"


class Note(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    title: Optional[str] = None
    status: NoteStatus = Field(default=NoteStatus.open)
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.queued)
    processing_error: Optional[str] = None

    duration_seconds: Optional[float] = None

    audio_filename: str
    audio_original_filename: Optional[str] = None
    audio_mime_type: Optional[str] = None

    transcript_path: Optional[str] = None

    # Set when the LLM recognizes a date/time in the transcript (Phase 2).
    scheduled_at: Optional[datetime] = None


class GoogleCredential(SQLModel, table=True):
    """Singleton row (id=1) holding this single-user app's linked Google account.

    pending_state is a short-lived CSRF token set by GET /google/auth/start
    and consumed by GET /google/auth/callback.
    """

    id: int = Field(default=1, primary_key=True)
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    pending_state: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)
