"""Per-user storage settings + the Drive folder-chooser's data (Phase 4).

Deliberately a JSON API rather than form posts: the web settings page drives
it from vanilla JS, and the Android app's own settings screen can adopt the
exact same endpoints later without any backend change (the requirement asks
for a section "in the settings", and both clients have one).

Every Drive call is blocking (googleapiclient), so each is pushed off the
event loop with run_in_threadpool.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session as DbSession

from ..auth import require_user
from ..db import get_session
from ..models import StorageLocation, User, utcnow
from ..schemas import (
    CreateDriveFolderRequest,
    DriveFolder,
    DriveFolderList,
    StorageSettings,
    UpdateStorageSettingsRequest,
)
from ..services import google_drive, note_storage, storage_migration

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


def _to_storage_settings(session: DbSession, user: User) -> StorageSettings:
    settings = note_storage.get_user_settings(session, user.id)
    return StorageSettings(
        drive_enabled=settings.drive_enabled,
        drive_folder_id=settings.drive_folder_id,
        drive_folder_name=settings.drive_folder_name,
        drive_linked=google_drive.is_linked(session, user.id),
        migration_status=settings.migration_status,
        migration_error=settings.migration_error,
        migration_total=settings.migration_total,
        migration_done=settings.migration_done,
    )


@router.get("/settings/storage", response_model=StorageSettings)
def get_storage_settings(
    user: User = Depends(require_user), session: DbSession = Depends(get_session)
) -> StorageSettings:
    return _to_storage_settings(session, user)


@router.put("/settings/storage", response_model=StorageSettings)
async def update_storage_settings(
    payload: UpdateStorageSettingsRequest,
    user: User = Depends(require_user),
    session: DbSession = Depends(get_session),
) -> StorageSettings:
    """Save the toggle + folder, then start moving the user's data.

    Turning the toggle on without naming a folder is explicitly allowed:
    that's the "we create a default `Copywaste Audionotes` folder" case.
    """
    settings = note_storage.get_user_settings(session, user.id)
    was_enabled = settings.drive_enabled
    previous_folder_id = settings.drive_folder_id

    if payload.drive_enabled:
        if not google_drive.is_linked(session, user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google Drive isn't linked yet - connect it before enabling this.",
            )

        if payload.drive_folder_id:
            folder = await run_in_threadpool(google_drive.get_folder, user.id, payload.drive_folder_id)
            if folder is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="That Drive folder doesn't exist any more.",
                )
        else:
            folder = await run_in_threadpool(google_drive.ensure_default_folder, user.id)

        settings.drive_enabled = True
        settings.drive_folder_id = folder["id"]
        settings.drive_folder_name = folder["name"]
    else:
        settings.drive_enabled = False

    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    session.refresh(settings)

    # Only actually shuffle files when the destination really changed -
    # re-saving the same settings shouldn't re-upload the whole archive.
    target = StorageLocation.drive if settings.drive_enabled else StorageLocation.local
    destination_changed = (settings.drive_enabled != was_enabled) or (
        settings.drive_enabled and settings.drive_folder_id != previous_folder_id
    )
    if destination_changed:
        storage_migration.start_migration(
            user.id, target, settings.drive_folder_id if settings.drive_enabled else None
        )
        session.refresh(settings)

    return _to_storage_settings(session, user)


@router.get("/drive/folders", response_model=DriveFolderList)
async def list_drive_folders(
    parent_id: str = google_drive.ROOT_FOLDER_ID,
    user: User = Depends(require_user),
    session: DbSession = Depends(get_session),
) -> DriveFolderList:
    """One level of the user's Drive folder tree, for the chooser."""
    _require_drive_linked(session, user)
    try:
        folders = await run_in_threadpool(google_drive.list_folders, user.id, parent_id)
        current = (
            None
            if parent_id == google_drive.ROOT_FOLDER_ID
            else await run_in_threadpool(google_drive.get_folder, user.id, parent_id)
        )
    except google_drive.DriveError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return DriveFolderList(
        parent_id=parent_id,
        parent_name=current["name"] if current else "My Drive",
        grandparent_id=current["parent_id"] if current else None,
        folders=[DriveFolder(**folder) for folder in folders],
    )


@router.post("/drive/folders", response_model=DriveFolder, status_code=status.HTTP_201_CREATED)
async def create_drive_folder(
    payload: CreateDriveFolderRequest,
    user: User = Depends(require_user),
    session: DbSession = Depends(get_session),
) -> DriveFolder:
    _require_drive_linked(session, user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A folder name is required.")
    try:
        created = await run_in_threadpool(
            google_drive.create_folder, user.id, name, payload.parent_id or google_drive.ROOT_FOLDER_ID
        )
    except google_drive.DriveError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return DriveFolder(**created)


def _require_drive_linked(session: DbSession, user: User) -> None:
    if not google_drive.is_linked(session, user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Drive isn't linked for this account.",
        )
