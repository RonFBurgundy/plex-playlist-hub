"""Plex Home users management routes."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from plex_playlist_sync.api.dependencies import (
    get_current_user,
    get_db,
    get_plex_client,
    require_admin,
)
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
def list_users(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Returns discovered Plex Home users (admin sees all; regular user sees self)."""
    if current_user.get("is_admin"):
        return db.list_users()
    return [current_user]


@router.post("/refresh")
def refresh_users(
    _admin: dict[str, Any] = Depends(require_admin),
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
) -> list[dict[str, Any]]:
    """Discovers users from Plex server and upserts them to DB (admin only)."""
    if not plex_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plex client is not configured on hub",
        )

    try:
        discovered_users = plex_client.get_home_users()
    except Exception as e:
        logger.error("Failed to discover Plex Home users: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query Plex users: {e}",
        )

    for u in discovered_users:
        db.upsert_user(
            user_id=str(u["id"]),
            username=str(u["username"]),
            email=u.get("email") or None,
            is_admin=bool(u.get("is_admin", False)),
        )

    return db.list_users()
