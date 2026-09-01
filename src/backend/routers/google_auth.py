"""Google Calendar OAuth linking flow.

/start and /callback are opened in the phone's system browser (not called
through Retrofit), so they can't carry an Authorization header like the rest
of the API. /start is instead gated by the same API token passed as a query
param; /callback needs no auth of its own - it only completes anything if it
carries the single-use `state` /start generated, and Google only ever
redirects there for the exact redirect_uri registered on our OAuth client.
/status is a normal bearer-token-protected route, used by the app to show
whether a Google account is linked.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..auth import require_bearer_token
from ..config import Settings, get_settings
from ..db import get_session
from ..models import GoogleCredential
from ..services.google_calendar import SCOPES, get_credential, is_linked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/google/auth", tags=["google"])

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

_SINGLETON_ID = 1


def _require_google_configured(settings: Settings) -> None:
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI):
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar isn't configured on this server yet.",
        )


@router.get("/start")
def start(
    token: str = Query(...),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if not secrets.compare_digest(token, settings.API_TOKEN):
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    _require_google_configured(settings)

    state = secrets.token_urlsafe(24)
    cred = get_credential(session) or GoogleCredential(id=_SINGLETON_ID)
    cred.pending_state = state
    session.add(cred)
    session.commit()

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
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
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if error:
        return _result_page(f"Linking failed: {error}")

    _require_google_configured(settings)
    cred = get_credential(session)
    if cred is None or not cred.pending_state or not secrets.compare_digest(state, cred.pending_state):
        return _result_page("Linking failed: invalid or expired request. Please try again from the app.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        logger.error("Google token exchange failed (%s): %s", response.status_code, response.text)
        return _result_page("Linking failed: couldn't exchange the authorization code.")

    payload = response.json()
    cred.access_token = payload.get("access_token")
    # Google only returns refresh_token when prompt=consent forced re-consent
    # (always, per /start above) - but keep the old one as a fallback just in case.
    cred.refresh_token = payload.get("refresh_token") or cred.refresh_token
    cred.pending_state = None
    session.add(cred)
    session.commit()

    return _result_page("Google Calendar linked. You can close this and return to the app.")


@router.get("/status", dependencies=[Depends(require_bearer_token)])
def get_status(session: Session = Depends(get_session)) -> dict:
    return {"linked": is_linked(session)}


def _result_page(message: str) -> HTMLResponse:
    return HTMLResponse(
        f"<html><body style='font-family:sans-serif;padding:2rem;'><p>{message}</p></body></html>"
    )
