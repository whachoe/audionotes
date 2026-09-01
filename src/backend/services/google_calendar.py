"""Google Calendar integration: per-user linked-account check + event creation.

Everything here is best-effort - a Calendar failure must never fail note
processing (worker.py wraps the call in its own try/except too). If a user
hasn't linked Calendar (no GoogleCredential row, or no refresh_token),
maybe_create_event() is a silent no-op for that user's notes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlmodel import Session

from .. import db
from ..config import Settings, get_settings
from ..models import GoogleCredential

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def get_credential(session: Session, user_id: str) -> Optional[GoogleCredential]:
    return session.get(GoogleCredential, user_id)


def is_linked(session: Session, user_id: str) -> bool:
    cred = get_credential(session, user_id)
    return cred is not None and bool(cred.refresh_token)


async def maybe_create_event(user_id: str, title: str, scheduled_at: datetime, description: str) -> None:
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return  # Google isn't configured on this server at all.

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _create_event_sync, user_id, title, scheduled_at, description, settings)


def _create_event_sync(
    user_id: str, title: str, scheduled_at: datetime, description: str, settings: Settings
) -> None:
    with db.session_scope() as session:
        cred = get_credential(session, user_id)
        if cred is None or not cred.refresh_token:
            return  # this user hasn't linked Calendar - nothing to do

        google_creds = Credentials(
            token=cred.access_token,
            refresh_token=cred.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=SCOPES,
        )
        # Always refresh: we don't persist the access token's expiry, and a
        # Calendar event is rare enough that one extra token-endpoint round
        # trip per note is a fine trade for not tracking expiry separately.
        google_creds.refresh(GoogleAuthRequest())
        cred.access_token = google_creds.token
        session.add(cred)
        session.commit()

        service = build("calendar", "v3", credentials=google_creds, cache_discovery=False)
        end = scheduled_at + timedelta(hours=1)
        event = {
            "summary": title,
            "description": description,
            # scheduled_at/end are already tz-aware (see summarization.py),
            # so isoformat() carries the correct UTC offset for whichever of
            # CET/CEST applies - timeZone is set too for Calendar UI display.
            "start": {"dateTime": scheduled_at.isoformat(), "timeZone": settings.LOCAL_TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": settings.LOCAL_TIMEZONE},
        }
        service.events().insert(calendarId=settings.GOOGLE_CALENDAR_ID, body=event).execute()
