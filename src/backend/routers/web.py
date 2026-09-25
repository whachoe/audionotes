"""HTML frontend (Phase 3.2): server-rendered pages using the same Google
sign-in as the mobile app, but via a session cookie instead of a bearer
header - see auth.py's require_web_user. HTMX is used only where a partial
update is genuinely worth it (the inline status dropdown); sorting and
filtering are plain full-page navigations - simpler, and just as fast for a
personal note list.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Cookie, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import false as sa_false
from sqlmodel import Session as DbSession
from sqlmodel import select

from ..auth import SESSION_COOKIE_NAME, require_web_user, resolve_user_from_token
from ..db import get_session
from ..models import Note, NoteStatus, ProcessingStatus
from ..models import Session as AppSession
from ..models import User, utcnow
from ..services import google_drive, note_storage
from .notes import SortBy, SortOrder

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

STATUS_FILTER_COOKIE = "status_filter"
DEFAULT_ENABLED_STATUSES = {"open", "in_progress", "todo"}
ALL_STATUSES = [(s.value, s.value.replace("_", " ").title()) for s in NoteStatus]


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _format_datetime(value) -> str:
    if value is None:
        return ""
    return value.strftime("%b %d, %H:%M")


def _row_context(note: Note) -> dict:
    if note.title:
        title_display = note.title
    elif note.processing_status == ProcessingStatus.failed:
        title_display = "(processing failed)"
    elif note.processing_status != ProcessingStatus.done:
        title_display = "(untitled — processing…)"
    else:
        title_display = "(untitled)"
    return {
        "id": note.id,
        "status": note.status.value,
        "created_display": _format_datetime(note.created_at),
        "title_display": title_display,
        "duration_display": _format_duration(note.duration_seconds),
    }


def _query_notes(db: DbSession, user: User, sort_by: SortBy, order: SortOrder, statuses: set[str]) -> List[Note]:
    column = {
        SortBy.created_at: Note.created_at,
        SortBy.duration_seconds: Note.duration_seconds,
        SortBy.status: Note.status,
    }[sort_by]
    statement = select(Note).where(Note.user_id == user.id)
    if statuses:
        statement = statement.where(Note.status.in_(statuses))  # type: ignore[attr-defined]
    else:
        # An explicitly empty filter means "show nothing", not "no filter".
        statement = statement.where(sa_false())
    statement = statement.order_by(column.asc() if order == SortOrder.asc else column.desc())
    return list(db.exec(statement).all())


def _filter_query_string(statuses: set[str]) -> str:
    return "&".join(f"status={value}" for value in statuses)


_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*#*$")


def _derive_title_from_markdown(markdown: str) -> Optional[str]:
    """Titles for markdown-only notes (Phase 4.2) have no recording to
    summarize, so instead of running the transcript through the LLM
    summarizer, the title just tracks the first non-blank line of the note
    (its heading, if it has one) - simple, instant, and it's exactly what a
    Markdown editor's own first line already looks like.
    """
    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _HEADING_RE.match(line)
        text = match.group(1) if match else line
        return text[:200] or None
    return None


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: DbSession = Depends(get_session),
):
    if resolve_user_from_token(session_cookie, db) is not None:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/logout")
def logout_web(
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: DbSession = Depends(get_session),
):
    if session_cookie:
        session_row = db.get(AppSession, session_cookie)
        if session_row is not None:
            db.delete(session_row)
            db.commit()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/", response_class=HTMLResponse)
def notes_list_page(
    request: Request,
    sort_by: SortBy = SortBy.created_at,
    order: SortOrder = SortOrder.desc,
    status: Optional[List[str]] = Query(default=None),
    filter_submitted: Optional[str] = None,
    status_filter_cookie: Optional[str] = Cookie(default=None, alias=STATUS_FILTER_COOKIE),
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    if filter_submitted is not None:
        enabled_statuses = set(status or [])
    elif status_filter_cookie is not None:
        enabled_statuses = {s for s in status_filter_cookie.split(",") if s}
    else:
        enabled_statuses = set(DEFAULT_ENABLED_STATUSES)

    notes = _query_notes(db, user, sort_by, order, enabled_statuses)

    response = templates.TemplateResponse(
        request,
        "notes_list.html",
        {
            "user": user,
            "sort_by": sort_by.value,
            "order": order.value,
            "all_statuses": ALL_STATUSES,
            "enabled_statuses": enabled_statuses,
            "filter_qs": _filter_query_string(enabled_statuses),
            "rows": [_row_context(n) for n in notes],
        },
    )
    if filter_submitted is not None:
        response.set_cookie(
            key=STATUS_FILTER_COOKIE,
            value=",".join(sorted(enabled_statuses)),
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            max_age=60 * 60 * 24 * 365,
        )
    return response


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    """Phase 4: the Save to Google Drive section.

    Rendered server-side with the current state; the folder-chooser and the
    save itself talk to the JSON API in routers/settings.py, so the Android
    settings screen can reuse exactly the same endpoints.
    """
    storage_settings = note_storage.get_user_settings(db, user.id)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "settings": storage_settings,
            "drive_linked": google_drive.is_linked(db, user.id),
            "default_folder_name": google_drive.DEFAULT_FOLDER_NAME,
        },
    )


@router.patch("/partials/notes/{note_id}/status", response_class=HTMLResponse)
def update_status_partial(
    request: Request,
    note_id: str,
    status: str = Form(...),
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        return HTMLResponse("Note not found", status_code=404)

    try:
        note.status = NoteStatus(status)
    except ValueError:
        return HTMLResponse("Invalid status", status_code=422)

    note.updated_at = utcnow()
    db.add(note)
    db.commit()
    db.refresh(note)

    return templates.TemplateResponse(
        request,
        "partials/note_row.html",
        {"note": _row_context(note), "all_statuses": ALL_STATUSES},
    )


@router.post("/notes/new")
def create_markdown_note_web(
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    """Phase 4.2: start a new note with no recording - just an empty
    transcript the user types straight into. Skips the audio/transcription
    pipeline entirely (processing_status=done, audio_filename="") so the
    background worker never picks it up and tries to "transcribe" nothing.

    Because it skips the worker it also skips worker._finalize_note, which
    is what normally parks a finished note in the owner's Drive folder - so
    the storage location has to be decided here instead, at birth. There
    are no files to move yet, so it costs nothing to start in the right
    place; getting this wrong would quietly strand every typed note on
    local disk for a user who has Drive switched on.
    """
    note = Note(
        user_id=user.id,
        audio_filename="",
        status=NoteStatus.open,
        processing_status=ProcessingStatus.done,
        storage_location=note_storage.target_location(db, user.id),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return RedirectResponse(url=f"/notes/{note.id}", status_code=303)


@router.get("/notes/{note_id}", response_class=HTMLResponse)
def note_detail_page(
    request: Request,
    note_id: str,
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        return HTMLResponse("Note not found", status_code=404)

    transcript_markdown = note_storage.read_markdown(note)
    return templates.TemplateResponse(
        request,
        "note_detail.html",
        {
            "note": note,
            "row": _row_context(note),
            "transcript_markdown": transcript_markdown,
            "all_statuses": ALL_STATUSES,
            "audio_url": f"/api/notes/{note.id}/audio",
        },
    )


@router.post("/notes/{note_id}/status")
def update_status_web(
    note_id: str,
    status: str = Form(...),
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        return HTMLResponse("Note not found", status_code=404)

    try:
        note.status = NoteStatus(status)
    except ValueError:
        return HTMLResponse("Invalid status", status_code=422)

    note.updated_at = utcnow()
    db.add(note)
    db.commit()

    return RedirectResponse(url=f"/notes/{note_id}", status_code=303)


def _save_transcript(note: Note, markdown: str, db: DbSession) -> None:
    """Shared by the explicit Save button and the background autosave
    endpoint below - both need to write the markdown, keep a
    still-titleless markdown-only note's title in sync, and bump
    updated_at, just with a different response shape around it.

    The write goes through note_storage so it lands wherever this note
    actually lives (Phase 4: local disk or the owner's Drive folder). That
    helper deliberately leaves the transaction to its caller, so the commit
    at the bottom is what persists the note's location bookkeeping - the
    Drive file id in particular, without which a note whose markdown was
    just uploaded reads back empty.
    """
    note_storage.write_markdown(db, note, markdown)
    if not note.audio_filename and not note.title:
        # Markdown-only note (Phase 4.2) that's never had a title yet: seed
        # it from the transcript's first heading/line so it isn't stuck
        # showing "(untitled)" until the user separately fills in the title
        # field. Only when it's still empty, though - once there's a title
        # (from this, or typed into the title field below), further
        # transcript saves must leave it alone rather than stomping on an
        # edit the user made on purpose.
        note.title = _derive_title_from_markdown(markdown)
    note.updated_at = utcnow()
    db.add(note)
    db.commit()
    db.refresh(note)


@router.post("/notes/{note_id}/transcript")
def update_transcript_web(
    note_id: str,
    markdown: str = Form(...),
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        return HTMLResponse("Note not found", status_code=404)

    _save_transcript(note, markdown, db)
<<<<<<< HEAD

=======
>>>>>>> 3273313 (fixes for the merge conflicts)
    return RedirectResponse(url=f"/notes/{note_id}", status_code=303)


@router.post("/notes/{note_id}/transcript/autosave")
def autosave_transcript_web(
    note_id: str,
    markdown: str = Form(...),
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    """Background autosave (Phase 4.3): the editor's JS calls this a couple
    seconds after the user stops typing, so the note is actually persisted
    as they write rather than only on an explicit click. Does the exact same
    write as the Save button, but answers with a small JSON ack instead of a
    redirect - a fetch() call every couple seconds shouldn't reload the page
    out from under whatever the user is doing next.
    """
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        return JSONResponse({"error": "Note not found"}, status_code=404)

    _save_transcript(note, markdown, db)

    return JSONResponse({"title": note.title, "saved_at": note.updated_at.isoformat()})


@router.post("/notes/{note_id}/title")
def update_title_web(
    note_id: str,
    title: str = Form(""),
    user: User = Depends(require_web_user),
    db: DbSession = Depends(get_session),
):
    note = db.get(Note, note_id)
    if note is None or note.user_id != user.id:
        return HTMLResponse("Note not found", status_code=404)

    note.title = title.strip()[:200] or None
    note.updated_at = utcnow()
    db.add(note)
    db.commit()

    return RedirectResponse(url=f"/notes/{note_id}", status_code=303)
