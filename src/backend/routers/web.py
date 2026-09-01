"""HTML frontend (Phase 3.2): server-rendered pages using the same Google
sign-in as the mobile app, but via a session cookie instead of a bearer
header - see auth.py's require_web_user. HTMX is used only where a partial
update is genuinely worth it (the inline status dropdown); sorting and
filtering are plain full-page navigations - simpler, and just as fast for a
personal note list.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Cookie, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import false as sa_false
from sqlmodel import Session as DbSession
from sqlmodel import select

from .. import storage
from ..auth import SESSION_COOKIE_NAME, require_web_user, resolve_user_from_token
from ..db import get_session
from ..models import Note, NoteStatus, ProcessingStatus
from ..models import Session as AppSession
from ..models import User, utcnow
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

    transcript_markdown = storage.read_markdown(note.id)
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

    transcript_path = storage.write_markdown(note_id, markdown)
    note.transcript_path = transcript_path
    note.updated_at = utcnow()
    db.add(note)
    db.commit()

    return RedirectResponse(url=f"/notes/{note_id}", status_code=303)
