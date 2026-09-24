"""Google Drive integration (Phase 4: Save to Google Drive).

Mirrors google_calendar.py's credential handling - same GoogleCredential
row, same "always refresh, then persist the new access token" approach -
but the contract is the opposite: Calendar is best-effort and silently does
nothing on failure, whereas Drive is where the user's notes actually *live*
once they turn the feature on. A failed Drive call here must surface, not be
swallowed, or a note would look saved while its bytes went nowhere.

Scope: the full `drive` scope rather than the narrower `drive.file`, because
the settings page lets the user browse their existing folders and pick one -
drive.file only ever grants access to files the app itself created.
"""
from __future__ import annotations

import io
import logging
from typing import BinaryIO, Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from sqlmodel import Session

from .. import db
from ..config import Settings, get_settings
from ..models import GoogleCredential

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DEFAULT_FOLDER_NAME = "Copywaste Audionotes"

# Drive's own name for "the top of My Drive" in parent queries.
ROOT_FOLDER_ID = "root"


class DriveError(RuntimeError):
    """A Drive call failed. Raised rather than swallowed - see module docstring."""


class DriveNotLinkedError(DriveError):
    """The user hasn't granted the Drive scope (or has revoked it)."""


def has_drive_scope(cred: Optional[GoogleCredential]) -> bool:
    if cred is None or not cred.refresh_token:
        return False
    return bool(set(SCOPES) & cred.granted_scopes())


def is_linked(session: Session, user_id: str) -> bool:
    return has_drive_scope(session.get(GoogleCredential, user_id))


def _credentials_for(session: Session, user_id: str, settings: Settings) -> Credentials:
    """Build refreshed google-auth Credentials for this user, persisting the
    newly minted access token back onto their GoogleCredential row.
    """
    cred = session.get(GoogleCredential, user_id)
    if not has_drive_scope(cred):
        raise DriveNotLinkedError("Google Drive isn't linked for this account.")

    google_creds = Credentials(
        token=cred.access_token,
        refresh_token=cred.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    try:
        # We never persist the access token's expiry, so - as with Calendar -
        # we just always refresh and eat one extra token round trip.
        google_creds.refresh(GoogleAuthRequest())
    except Exception as exc:  # noqa: BLE001 - refresh failure means "re-link"
        raise DriveNotLinkedError(f"Couldn't refresh Google credentials: {exc}") from exc

    cred.access_token = google_creds.token
    session.add(cred)
    session.commit()
    return google_creds


def _service_for(session: Session, user_id: str):
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise DriveNotLinkedError("Google isn't configured on this server.")
    google_creds = _credentials_for(session, user_id, settings)
    return build("drive", "v3", credentials=google_creds, cache_discovery=False)


def _escape_query_value(value: str) -> str:
    """Drive query strings are single-quoted; escape backslashes and quotes."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


# --- Folder browsing / creation (the settings page's folder-chooser) -------


def list_folders(user_id: str, parent_id: str = ROOT_FOLDER_ID) -> list[dict]:
    """Folders directly inside parent_id, alphabetically. Shared drives are
    out of scope here - this browses the user's own My Drive only.
    """
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        query = (
            f"'{_escape_query_value(parent_id)}' in parents"
            f" and mimeType = '{FOLDER_MIME_TYPE}'"
            " and trashed = false"
        )
        try:
            response = (
                service.files()
                .list(
                    q=query,
                    fields="files(id, name)",
                    orderBy="name",
                    pageSize=200,
                    spaces="drive",
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(f"Couldn't list Drive folders: {exc}") from exc
        return [{"id": f["id"], "name": f["name"]} for f in response.get("files", [])]


def get_folder(user_id: str, folder_id: str) -> Optional[dict]:
    """Look up one folder's id/name/parent, or None if it's gone or not a folder."""
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        try:
            found = (
                service.files()
                .get(fileId=folder_id, fields="id, name, mimeType, parents, trashed")
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status == 404:
                return None
            raise DriveError(f"Couldn't read Drive folder: {exc}") from exc
        if found.get("mimeType") != FOLDER_MIME_TYPE or found.get("trashed"):
            return None
        parents = found.get("parents") or []
        return {"id": found["id"], "name": found["name"], "parent_id": parents[0] if parents else None}


def create_folder(user_id: str, name: str, parent_id: str = ROOT_FOLDER_ID) -> dict:
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        body = {"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]}
        try:
            created = service.files().create(body=body, fields="id, name").execute()
        except HttpError as exc:
            raise DriveError(f"Couldn't create Drive folder: {exc}") from exc
        return {"id": created["id"], "name": created["name"]}


def ensure_default_folder(user_id: str) -> dict:
    """Find-or-create the "Copywaste Audionotes" folder at the top of My
    Drive - what a user gets when they enable the feature without picking a
    folder themselves.
    """
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        query = (
            f"name = '{_escape_query_value(DEFAULT_FOLDER_NAME)}'"
            f" and '{ROOT_FOLDER_ID}' in parents"
            f" and mimeType = '{FOLDER_MIME_TYPE}'"
            " and trashed = false"
        )
        try:
            response = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
        except HttpError as exc:
            raise DriveError(f"Couldn't look for the default Drive folder: {exc}") from exc
        existing = response.get("files", [])
        if existing:
            return {"id": existing[0]["id"], "name": existing[0]["name"]}
    return create_folder(user_id, DEFAULT_FOLDER_NAME, ROOT_FOLDER_ID)


# --- File upload / download / delete (where notes actually go) -------------


def upload_file(
    user_id: str,
    folder_id: str,
    filename: str,
    content: BinaryIO,
    mime_type: str = "application/octet-stream",
) -> str:
    """Upload (or replace) a file in folder_id. Returns its Drive file id.

    Replaces rather than duplicates: a note's markdown gets rewritten every
    time the user edits it, and Drive would otherwise happily accumulate a
    dozen files all called "<id>.md" in the same folder.
    """
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        media = MediaIoBaseUpload(content, mimetype=mime_type, resumable=False)
        existing_id = _find_file_id(service, folder_id, filename)
        try:
            if existing_id is not None:
                updated = service.files().update(fileId=existing_id, media_body=media, fields="id").execute()
                return updated["id"]
            created = (
                service.files()
                .create(
                    body={"name": filename, "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(f"Couldn't upload {filename} to Drive: {exc}") from exc
        return created["id"]


def _find_file_id(service, folder_id: str, filename: str) -> Optional[str]:
    query = (
        f"name = '{_escape_query_value(filename)}'"
        f" and '{_escape_query_value(folder_id)}' in parents"
        " and trashed = false"
    )
    try:
        response = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    except HttpError as exc:
        raise DriveError(f"Couldn't look up {filename} on Drive: {exc}") from exc
    files = response.get("files", [])
    return files[0]["id"] if files else None


def update_file(
    user_id: str,
    file_id: str,
    content: BinaryIO,
    mime_type: str = "application/octet-stream",
) -> str:
    """Overwrite a file we already know the id of.

    Preferred over upload_file() whenever the note already records a Drive
    file id: it's one request instead of a lookup plus a write, and it keeps
    working even if the user has since moved the file elsewhere in Drive.
    """
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        media = MediaIoBaseUpload(content, mimetype=mime_type, resumable=False)
        try:
            updated = service.files().update(fileId=file_id, media_body=media, fields="id").execute()
        except HttpError as exc:
            raise DriveError(f"Couldn't update file {file_id} on Drive: {exc}") from exc
        return updated["id"]


def download_file(user_id: str, file_id: str) -> bytes:
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        buffer = io.BytesIO()
        try:
            downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=file_id))
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except HttpError as exc:
            raise DriveError(f"Couldn't download file {file_id} from Drive: {exc}") from exc
        return buffer.getvalue()


def delete_file(user_id: str, file_id: str) -> None:
    """Trash a file (recoverable for 30 days) rather than destroying it.

    The settings flow calls this as the second half of a move, and a move
    that silently vaporizes the only copy of someone's recording on a bad
    day is not a move worth having.
    """
    with db.session_scope() as session:
        service = _service_for(session, user_id)
        try:
            service.files().update(fileId=file_id, body={"trashed": True}).execute()
        except HttpError as exc:
            if exc.resp.status == 404:
                logger.info("Drive file %s already gone; nothing to trash", file_id)
                return
            raise DriveError(f"Couldn't remove file {file_id} from Drive: {exc}") from exc
