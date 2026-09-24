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


class StorageLocation(str, Enum):
    """Where a note's audio + markdown actually live (Phase 4).

    Tracked per note, not just per user: a migration moves thousands of
    files one at a time, and a note that hasn't been moved yet must still be
    readable from wherever it currently is.
    """

    local = "local"
    drive = "drive"


class MigrationStatus(str, Enum):
    idle = "idle"
    running = "running"
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

    client records which surface started the flow ("mobile" or "web") since
    both share the same OAuth client/redirect URI (Phase 3.2) - the callback
    needs it to decide between a deep-link response (mobile) or a session
    cookie + redirect (web).
    """

    state: str = Field(primary_key=True)
    client: str = Field(default="mobile")
    # Where to send a web client once the callback succeeds. Phase 4 grants
    # the Drive scope from the settings page, which is where the user
    # expects to land again afterwards - not back at the notes list.
    return_to: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class GoogleCredential(SQLModel, table=True):
    """One row per user holding their linked Google tokens.

    Login and Calendar linking are the same OAuth flow (Phase 3) - this row
    is created/updated in the same callback that creates the User. Drive
    (Phase 4) is *not* part of that flow: it's granted later, on demand,
    from the settings page, which re-runs the same callback with the extra
    scope requested - hence `scopes`, which records what Google actually
    granted so we can tell "Drive is linked" from "only login + Calendar".
    """

    user_id: str = Field(foreign_key="user.id", primary_key=True)
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    # Space-separated, exactly as Google returns it in the token response.
    scopes: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)

    def granted_scopes(self) -> set[str]:
        return {scope for scope in (self.scopes or "").split() if scope}


class UserSettings(SQLModel, table=True):
    """Per-user, server-side settings (Phase 4: Save to Google Drive).

    Distinct from the Android app's own settings, which are client-side
    preferences (server URL, status filter) in SharedPreferences - these
    have to live on the server because the server is what acts on them.
    """

    user_id: str = Field(foreign_key="user.id", primary_key=True)

    # The feature toggle. When True, this user's notes live in Drive.
    drive_enabled: bool = Field(default=False)
    drive_folder_id: Optional[str] = None
    # Kept alongside the id purely so the settings page can name the folder
    # without a Drive round trip on every render.
    drive_folder_name: Optional[str] = None

    # Progress of the move triggered by the last settings save, so the
    # settings page can report "moving 12/40" instead of just hanging.
    migration_status: MigrationStatus = Field(default=MigrationStatus.idle)
    migration_error: Optional[str] = None
    migration_total: int = Field(default=0)
    migration_done: int = Field(default=0)

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

    # Phase 4: where this note's two files actually are. Notes always start
    # local (whisper needs a real file on disk to transcribe) and are moved
    # to Drive afterwards if the owner has the feature enabled.
    storage_location: StorageLocation = Field(default=StorageLocation.local)
    audio_drive_file_id: Optional[str] = None
    transcript_drive_file_id: Optional[str] = None
