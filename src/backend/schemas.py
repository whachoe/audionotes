"""Pydantic request/response schemas for the notes API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import NoteStatus, ProcessingStatus


class NoteListItem(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None
    status: NoteStatus
    processing_status: ProcessingStatus
    duration_seconds: Optional[float] = None
    audio_url: str


class NoteDetail(NoteListItem):
    transcript_markdown: str = ""
    processing_error: Optional[str] = None
    audio_original_filename: Optional[str] = None
    audio_mime_type: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: NoteStatus


class UpdateTranscriptRequest(BaseModel):
    markdown: str = Field(default="")
