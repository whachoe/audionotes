"""Session-token auth: resolves either a Bearer header (mobile) or a
SESSION_COOKIE_NAME cookie (web frontend, Phase 3.2) to its User - one
Session table, two delivery mechanisms.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session as DbSession

from .db import get_session
from .models import Session, User

bearer_scheme = HTTPBearer(auto_error=False)

SESSION_COOKIE_NAME = "session_token"


class RequireLoginRedirect(Exception):
    """Raised by require_web_user when there's no valid session - caught by
    an exception handler (see main.py) that sends the browser to /login,
    instead of the raw 401 JSON a Bearer-header API caller would get.
    """


def resolve_user_from_token(token: Optional[str], db: DbSession) -> Optional[User]:
    if not token:
        return None
    session_row = db.get(Session, token)
    if session_row is None:
        return None
    return db.get(User, session_row.user_id)


def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: DbSession = Depends(get_session),
) -> User:
    token = credentials.credentials if credentials and credentials.credentials else session_cookie
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token or session cookie")

    user = resolve_user_from_token(token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    return user


def require_web_user(
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: DbSession = Depends(get_session),
) -> User:
    user = resolve_user_from_token(session_cookie, db)
    if user is None:
        raise RequireLoginRedirect()
    return user
