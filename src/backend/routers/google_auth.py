"""Google sign-in + Calendar linking - one combined OAuth flow (Phase 3).

/start and /callback are opened in the phone's system browser (not called
through Retrofit), and /start is itself how you log in - there's no prior
session to check yet, so it's intentionally public. Access control happens
at /callback: only an email on ALLOWED_GOOGLE_EMAILS gets a User created and
a session token issued. Google only ever redirects to /callback for the
exact redirect_uri registered on our OAuth client, carrying the single-use
`state` /start generated.

On success, /callback hands the app a session token via a deep link
(copywastenotes://auth?token=...) that the app's manifest is registered to
receive, so the phone lands back in the app already signed in.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from sqlmodel import Session as DbSession
from sqlmodel import select

from .. import auth
from ..config import Settings, get_settings
from ..db import get_session
from ..models import GoogleCredential, Note, PendingAuthState, Session, User, utcnow
from ..services import google_calendar

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/google/auth", tags=["google"])

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Signing in and linking Calendar are the same consent screen.
LOGIN_SCOPES = ["openid", "email", "profile", *google_calendar.SCOPES]

APP_AUTH_DEEP_LINK = "copywastenotes://auth"


def _require_google_configured(settings: Settings) -> None:
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI):
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in isn't configured on this server yet.",
        )


@router.get("/start")
def start(
    settings: Settings = Depends(get_settings),
    session: DbSession = Depends(get_session),
):
    """Public by design - this IS the login entrypoint. See module docstring."""
    _require_google_configured(settings)

    state = secrets.token_urlsafe(24)
    session.add(PendingAuthState(state=state))
    session.commit()

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(LOGIN_SCOPES),
        "access_type": "offline",
        # Forces Google to hand back a refresh_token every time, including
        # on a re-link, not just the very first authorization.
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(f"{_AUTH_ENDPOINT}?{urlencode(params)}")


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    settings: Settings = Depends(get_settings),
    session: DbSession = Depends(get_session),
) -> HTMLResponse:
    if error:
        return _failure_page(f"Sign-in failed: {error}")

    _require_google_configured(settings)

    pending = session.get(PendingAuthState, state)
    if pending is None:
        return _failure_page("Sign-in failed: invalid or expired request. Please try again from the app.")
    session.delete(pending)
    session.commit()

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(
            _TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if token_response.status_code != 200:
        logger.error("Google token exchange failed (%s): %s", token_response.status_code, token_response.text)
        return _failure_page("Sign-in failed: couldn't exchange the authorization code.")

    payload = token_response.json()
    id_token_jwt = payload.get("id_token")
    if not id_token_jwt:
        return _failure_page("Sign-in failed: Google didn't return an identity token.")

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_jwt, google_auth_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError:
        logger.exception("Google ID token verification failed")
        return _failure_page("Sign-in failed: couldn't verify your Google identity.")

    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified"):
        return _failure_page("Sign-in failed: your Google account has no verified email.")

    if email not in settings.allowed_google_emails():
        return _failure_page(
            f"Sign-in failed: {email} isn't authorized to use this server."
        )

    google_sub = claims["sub"]
    name = claims.get("name")

    user = session.exec(select(User).where(User.google_sub == google_sub)).first()
    is_first_user_ever = session.exec(select(User)).first() is None
    if user is None:
        user = User(google_sub=google_sub, email=email, name=name)
    else:
        user.email = email
        user.name = name
    session.add(user)
    session.commit()
    session.refresh(user)

    if is_first_user_ever:
        # One-time bootstrap: claim every pre-Phase-3 note (created before
        # user accounts existed) for whoever signs in first.
        orphaned_notes = session.exec(select(Note).where(Note.user_id == None)).all()  # noqa: E711
        for note in orphaned_notes:
            note.user_id = user.id
            session.add(note)
        if orphaned_notes:
            session.commit()
            logger.info("Claimed %d pre-existing note(s) for first user %s", len(orphaned_notes), email)

    cred = session.get(GoogleCredential, user.id) or GoogleCredential(user_id=user.id)
    cred.access_token = payload.get("access_token")
    # Google only returns refresh_token when prompt=consent forced re-consent
    # (always, per /start above) - keep the old one as a fallback just in case.
    cred.refresh_token = payload.get("refresh_token") or cred.refresh_token
    cred.updated_at = utcnow()
    session.add(cred)

    app_session = Session(user_id=user.id)
    session.add(app_session)
    session.commit()

    return _success_page(app_session.token)


@router.get("/status")
def get_status(user: User = Depends(auth.require_user), session: DbSession = Depends(get_session)) -> dict:
    return {
        "email": user.email,
        "name": user.name,
        "calendar_linked": google_calendar.is_linked(session, user.id),
    }


@router.post("/logout", status_code=http_status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(auth.bearer_scheme),
    user: User = Depends(auth.require_user),
    session: DbSession = Depends(get_session),
) -> None:
    session_row = session.get(Session, credentials.credentials)
    if session_row is not None:
        session.delete(session_row)
        session.commit()


def _success_page(token: str) -> HTMLResponse:
    deep_link = f"{APP_AUTH_DEEP_LINK}?token={token}"
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem;text-align:center;'>"
        "<p>Signed in. Returning you to Copywaste Notes&hellip;</p>"
        f"<p><a href=\"{deep_link}\">Tap here if it doesn't open automatically</a></p>"
        f"<script>window.location.replace({deep_link!r});</script>"
        "</body></html>"
    )


def _failure_page(message: str) -> HTMLResponse:
    return HTMLResponse(
        f"<html><body style='font-family:sans-serif;padding:2rem;'><p>{message}</p></body></html>"
    )
