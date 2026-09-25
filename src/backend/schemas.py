"""Pydantic request/response schemas for the notes API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import MigrationStatus, NoteStatus, ProcessingStatus


class NoteListItem(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None
    status: NoteStatus
    processing_status: ProcessingStatus
    duration_seconds: Optional[float] = None
    audio_url: str
    scheduled_at: Optional[datetime] = None


class NoteDetail(NoteListItem):
    transcript_markdown: str = ""
    processing_error: Optional[str] = None
    audio_original_filename: Optional[str] = None
    audio_mime_type: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: NoteStatus


# --- Phase 4: Save to Google Drive ---------------------------------------
class StorageSettings(BaseModel):
    drive_enabled: bool = False
    drive_folder_id: Optional[str] = None
    drive_folder_name: Optional[str] = None
    # Whether the Drive *scope* has been granted, which is separate from
    # whether the feature is switched on.
    drive_linked: bool = False
    migration_status: MigrationStatus = MigrationStatus.idle
    migration_error: Optional[str] = None
    migration_total: int = 0
    migration_done: int = 0


class UpdateStorageSettingsRequest(BaseModel):
    drive_enabled: bool = False
    # Omitted/blank means "pick the default Copywaste Audionotes folder".
    drive_folder_id: Optional[str] = None


class DriveFolder(BaseModel):
    id: str
    name: str


class DriveFolderList(BaseModel):
    parent_id: str
    parent_name: str
    # None when already at the top of My Drive - the chooser hides "up" then.
    grandparent_id: Optional[str] = None
    folders: list[DriveFolder] = Field(default_factory=list)


class CreateDriveFolderRequest(BaseModel):
    name: str
    parent_id: Optional[str] = None
    
    
class UpdateTitleRequest(BaseModel):
    title: str = Field(default="")
    

class UpdateTranscriptRequest(BaseModel):
    markdown: str = Field(default="")

