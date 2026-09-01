"""SQLModel table definitions and enums for Copywaste Notes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


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


class User(SQLModel, table=True):
    """One row per signed-in Google account (Phase 3: multi-user)."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    google_sub: str = Field(unique=True, index=True)  # Google's stable "sub" claim
    email: str = Field(index=True)
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Session(SQLModel, table=True):
    """An opaque app-issued bearer token, minted at the end of the Google
    OAuth callback and sent as `Authorization: Bearer <token>` from then on -
    replaces the old single shared API_TOKEN now that there are real users.
    No expiry: revoked only by explicit sign-out (POST /api/auth/logout).
    """

    token: str = Field(default_factory=lambda: uuid.uuid4().hex + uuid.uuid4().hex, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class PendingAuthState(SQLModel, table=True):
    """A short-lived CSRF token: created by GET /google/auth/start, consumed
    (and deleted) by GET /google/auth/callback. Not tied to a user yet -
    that's the whole point of a login flow.
    """

    state: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)


class GoogleCredential(SQLModel, table=True):
    """One row per user holding their linked Google Calendar tokens.

    Login and Calendar linking are the same OAuth flow (Phase 3) - this row
    is created/updated in the same callback that creates the User.
    """

    user_id: str = Field(foreign_key="user.id", primary_key=True)
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)


class Note(SQLModel, table=True):
    id: str = Field(default_factory=_new_id, primary_key=True)
    # Nullable: notes created before Phase 3 (multi-user) have no owner until
    # the first successful sign-in claims them - see google_auth.py.
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True)

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
