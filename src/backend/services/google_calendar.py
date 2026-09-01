"""Google Calendar integration: linked-account check + event creation.

Everything here is best-effort - a Calendar failure must never fail note
processing (worker.py wraps the call in its own try/except too). If no
Google account is linked yet, maybe_create_event() is a silent no-op.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlmodel import Session

from .. import db
from ..config import Settings, get_settings
from ..models import GoogleCredential

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Single-user app: one fixed row holds the (at most one) linked Google account.
SINGLETON_ID = 1


def get_credential(session: Session) -> GoogleCredential | None:
    return session.get(GoogleCredential, SINGLETON_ID)


def is_linked(session: Session) -> bool:
    cred = get_credential(session)
    return cred is not None and bool(cred.refresh_token)


async def maybe_create_event(title: str, scheduled_at: datetime, description: str) -> None:
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return  # Google Calendar isn't configured on this server at all.

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _create_event_sync, title, scheduled_at, description, settings)


def _create_event_sync(title: str, scheduled_at: datetime, description: str, settings: Settings) -> None:
    with db.session_scope() as session:
        cred = get_credential(session)
        if cred is None or not cred.refresh_token:
            return  # not linked yet - nothing to do

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
