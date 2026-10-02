"""Plex Home users management routes."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from pydantic import BaseModel

from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_plex_client,
    require_admin,
    require_user,
)
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.models import UserPermission
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class UpdateUserGovernanceBody(BaseModel):
    permissions: Optional[int] = None
    request_limit_quota: Optional[int] = None
    request_limit_days: Optional[int] = None
    is_admin: Optional[bool] = None


@router.get("/me")
def get_current_user_profile(
    current_user: dict[str, Any] = Depends(require_user),
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> dict[str, Any]:
    """Returns current user profile, permissions bitmask, and rolling request quota telemetry."""
    user_id = str(current_user["id"])
    user = db.get_user(user_id) or current_user

    permissions = int(user.get("permissions") if user.get("permissions") is not None else UserPermission.DEFAULT)
    quota_limit = user.get("request_limit_quota") or config.user_request_quota
    rolling_days = user.get("request_limit_days") if user.get("request_limit_days") is not None else 7

    active_requests = db.get_user_active_request_count(user_id, days=rolling_days)
    remaining_quota = max(0, quota_limit - active_requests)

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email"),
        "is_admin": bool(user.get("is_admin")),
        "permissions": permissions,
        "request_limit_quota": user.get("request_limit_quota"),
        "quota_limit": quota_limit,
        "request_limit_days": rolling_days,
        "rolling_days": rolling_days,
        "active_requests": active_requests,
        "active_request_count": active_requests,
        "remaining_quota": remaining_quota,
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }


@router.get("")
def list_users(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Returns discovered Plex Home users (admin sees all; regular user sees self)."""
    if current_user.get("is_admin") or (int(current_user.get("permissions") or 0) & int(UserPermission.ADMIN)):
        return db.list_users()
    return [current_user]


@router.put("/{user_id}")
def update_user_governance_route(
    user_id: str,
    body: UpdateUserGovernanceBody,
    _admin: dict[str, Any] = Depends(require_admin),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Updates user governance, permissions, and request quotas (admin only)."""
    existing = db.get_user(user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    fields_set = getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))
    clear_quota = "request_limit_quota" in fields_set and body.request_limit_quota is None

    try:
        updated = db.update_user_governance(
            user_id=user_id,
            permissions=body.permissions if "permissions" in fields_set else None,
            request_limit_quota=body.request_limit_quota if ("request_limit_quota" in fields_set and not clear_quota) else None,
            request_limit_days=body.request_limit_days if "request_limit_days" in fields_set else None,
            is_admin=body.is_admin if "is_admin" in fields_set else None,
            clear_quota=clear_quota,
        )
        return updated
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    except Exception as e:
        logger.error("Failed to update user %s governance: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {e}",
        )


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
