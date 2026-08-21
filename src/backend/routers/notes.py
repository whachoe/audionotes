"""Notes API: upload, list, detail, status update, transcript update, audio streaming."""
from __future__ import annotations

import re
from enum import Enum

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from .. import storage
from ..auth import require_bearer_token
from ..db import get_session
from ..models import Note, NoteStatus, ProcessingStatus, utcnow
from ..schemas import NoteDetail, NoteListItem, UpdateStatusRequest, UpdateTranscriptRequest

router = APIRouter(prefix="/notes", tags=["notes"], dependencies=[Depends(require_bearer_token)])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK_SIZE = 64 * 1024


class SortBy(str, Enum):
    created_at = "created_at"
    duration_seconds = "duration_seconds"
    status = "status"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


def _audio_url(note_id: str) -> str:
    return f"/api/notes/{note_id}/audio"


def _to_list_item(note: Note) -> NoteListItem:
    return NoteListItem(
        id=note.id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        title=note.title,
        status=note.status,
        processing_status=note.processing_status,
        duration_seconds=note.duration_seconds,
        audio_url=_audio_url(note.id),
    )


def _to_detail(note: Note) -> NoteDetail:
    transcript_markdown = storage.read_markdown(note.id)
    return NoteDetail(
        id=note.id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        title=note.title,
        status=note.status,
        processing_status=note.processing_status,
        duration_seconds=note.duration_seconds,
        audio_url=_audio_url(note.id),
        transcript_markdown=transcript_markdown,
        processing_error=note.processing_error,
        audio_original_filename=note.audio_original_filename,
        audio_mime_type=note.audio_mime_type,
    )


def _get_note_or_404(session: Session, note_id: str) -> Note:
    note = session.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@router.post("", response_model=NoteDetail, status_code=status.HTTP_201_CREATED)
async def create_note(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> NoteDetail:
    note = Note(
        audio_filename="",  # filled in below, once we know the id
        audio_original_filename=file.filename,
        audio_mime_type=file.content_type,
        processing_status=ProcessingStatus.queued,
        status=NoteStatus.open,
    )

    stored_filename = storage.save_upload_to_disk(note.id, file.filename, file.file)
    note.audio_filename = stored_filename

    audio_file_path = storage.audio_path(note.id, stored_filename)
    note.duration_seconds = storage.ffprobe_duration_seconds(audio_file_path)

    session.add(note)
    session.commit()
    session.refresh(note)

    return _to_detail(note)


@router.get("", response_model=list[NoteListItem])
async def list_notes(
    sort_by: SortBy = SortBy.created_at,
    order: SortOrder = SortOrder.desc,
    session: Session = Depends(get_session),
) -> list[NoteListItem]:
    column = {
        SortBy.created_at: Note.created_at,
        SortBy.duration_seconds: Note.duration_seconds,
        SortBy.status: Note.status,
    }[sort_by]

    statement = select(Note)
    statement = statement.order_by(column.asc() if order == SortOrder.asc else column.desc())

    notes = session.exec(statement).all()
    return [_to_list_item(note) for note in notes]


@router.get("/{note_id}", response_model=NoteDetail)
async def get_note(note_id: str, session: Session = Depends(get_session)) -> NoteDetail:
    note = _get_note_or_404(session, note_id)
    return _to_detail(note)


@router.patch("/{note_id}/status", response_model=NoteDetail)
async def update_status(
    note_id: str,
    payload: UpdateStatusRequest,
    session: Session = Depends(get_session),
) -> NoteDetail:
    note = _get_note_or_404(session, note_id)
    note.status = payload.status
    note.updated_at = utcnow()
    session.add(note)
    session.commit()
    session.refresh(note)
    return _to_detail(note)


@router.put("/{note_id}/transcript", response_model=NoteDetail)
async def update_transcript(
    note_id: str,
    payload: UpdateTranscriptRequest,
    session: Session = Depends(get_session),
) -> NoteDetail:
    note = _get_note_or_404(session, note_id)
    transcript_path = storage.write_markdown(note_id, payload.markdown)
    note.transcript_path = transcript_path
    note.updated_at = utcnow()
    session.add(note)
    session.commit()
    session.refresh(note)
    return _to_detail(note)


def _iter_file_range(path, start: int, length: int):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _iter_file_full(path):
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


@router.get("/{note_id}/audio")
async def get_audio(
    note_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    note = _get_note_or_404(session, note_id)
    file_path = storage.audio_path(note.id, note.audio_filename)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file missing")

    media_type = note.audio_mime_type or "application/octet-stream"
    filename = note.audio_original_filename or note.audio_filename
    file_size = file_path.stat().st_size

    range_header = request.headers.get("range")
    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
    }

    if not range_header:
        headers = {**base_headers, "Content-Length": str(file_size)}
        return StreamingResponse(_iter_file_full(file_path), media_type=media_type, headers=headers)

    match = _RANGE_RE.match(range_header)
    if not match or (match.group(1) == "" and match.group(2) == ""):
        raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE, detail="Invalid Range header")

    start_str, end_str = match.groups()
    if start_str == "":
        suffix_length = int(end_str)
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str != "" else file_size - 1

    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="Requested range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    length = end - start + 1
    headers = {
        **base_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(length),
    }
    return StreamingResponse(
        _iter_file_range(file_path, start, length),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )
