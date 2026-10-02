"""REST API endpoints for managing outbound notification channels and live testing."""

import logging
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import get_db, require_admin
from plex_playlist_sync.models import (
    NotificationChannel,
    NotificationChannelType,
    NotificationEvent,
)
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.security import is_safe_service_url, mask_channel_config
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class NotificationChannelItem(BaseModel):
    id: str
    name: str
    channel_type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class NotificationChannelPayload(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=120)
    channel_type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    events: Optional[list[str]] = None


class TestNotificationPayload(BaseModel):
    channel_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    channel_id: Optional[str] = None


class TestNotificationResponse(BaseModel):
    success: bool
    message: str


def _mask_channel_dict(channel: dict[str, Any]) -> dict[str, Any]:
    c = dict(channel)
    c["config"] = mask_channel_config(c.get("channel_type", ""), c.get("config", {}))
    return c


@router.get(
    "",
    response_model=list[NotificationChannelItem],
    summary="List notification channels",
)
@router.get(
    "/",
    response_model=list[NotificationChannelItem],
    include_in_schema=False,
)
def list_notification_channels(
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Admin-only endpoint listing all notification channels with masked secrets."""
    channels = db.list_notification_channels()
    return [_mask_channel_dict(c) for c in channels]


@router.post(
    "",
    response_model=NotificationChannelItem,
    status_code=status.HTTP_201_CREATED,
    summary="Create notification channel",
)
@router.post(
    "/",
    response_model=NotificationChannelItem,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_notification_channel(
    payload: NotificationChannelPayload,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only endpoint to create a new notification channel."""
    valid_types = {t.value for t in NotificationChannelType}
    clean_type = payload.channel_type.strip().lower()
    if clean_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel type '{payload.channel_type}'. Supported: {', '.join(sorted(valid_types))}",
        )

    # Validate webhook URLs against SSRF
    cfg = dict(payload.config)
    if "webhook_url" in cfg and cfg["webhook_url"]:
        clean_url = str(cfg["webhook_url"]).strip()
        if not is_safe_service_url(clean_url, allow_lan=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prohibited or invalid webhook URL (SSRF protection)",
            )

    # Validate events
    all_events = [e.value for e in NotificationEvent]
    valid_event_set = set(all_events)
    if payload.events is not None:
        for ev in payload.events:
            if ev not in valid_event_set:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid notification event '{ev}'. Supported: {', '.join(sorted(valid_event_set))}",
                )
        events = payload.events
    else:
        events = all_events

    channel_id = (
        payload.id.strip()
        if payload.id and payload.id.strip()
        else f"chan-{uuid.uuid4().hex[:12]}"
    )

    channel = NotificationChannel(
        id=channel_id,
        name=payload.name.strip(),
        channel_type=clean_type,
        enabled=payload.enabled,
        config=cfg,
        events=events,
    )

    saved = db.create_notification_channel(channel)
    return _mask_channel_dict(saved)


@router.put(
    "/{channel_id}",
    response_model=NotificationChannelItem,
    summary="Update notification channel",
)
def update_notification_channel(
    channel_id: str,
    payload: NotificationChannelPayload,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only endpoint to update an existing channel, preserving masked secrets."""
    existing = db.get_notification_channel(channel_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification channel '{channel_id}' not found",
        )

    valid_types = {t.value for t in NotificationChannelType}
    clean_type = payload.channel_type.strip().lower()
    if clean_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel type '{payload.channel_type}'. Supported: {', '.join(sorted(valid_types))}",
        )

    # Merge credentials to preserve existing secrets if payload value is masked
    new_cfg = dict(payload.config)
    existing_cfg = existing.get("config") or {}
    for k, v in existing_cfg.items():
        if k not in new_cfg:
            new_cfg[k] = v
        elif isinstance(new_cfg[k], str) and "•••" in new_cfg[k]:
            new_cfg[k] = v

    # Validate webhook URLs against SSRF
    if "webhook_url" in new_cfg and new_cfg["webhook_url"]:
        clean_url = str(new_cfg["webhook_url"]).strip()
        if not is_safe_service_url(clean_url, allow_lan=True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prohibited or invalid webhook URL (SSRF protection)",
            )

    all_events = [e.value for e in NotificationEvent]
    valid_event_set = set(all_events)
    if payload.events is not None:
        for ev in payload.events:
            if ev not in valid_event_set:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid notification event '{ev}'. Supported: {', '.join(sorted(valid_event_set))}",
                )
        events = payload.events
    else:
        events = existing.get("events") or all_events

    updated = db.update_notification_channel(
        channel_id,
        {
            "name": payload.name.strip(),
            "channel_type": clean_type,
            "enabled": payload.enabled,
            "config": new_cfg,
            "events": events,
        },
    )
    return _mask_channel_dict(updated)


@router.delete(
    "/{channel_id}",
    summary="Delete notification channel",
)
def delete_notification_channel(
    channel_id: str,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only endpoint to delete a notification channel."""
    deleted = db.delete_notification_channel(channel_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification channel '{channel_id}' not found",
        )
    return {"status": "deleted", "id": channel_id}


@router.post(
    "/test",
    response_model=TestNotificationResponse,
    summary="Test notification channel",
)
def test_notification_channel(
    payload: TestNotificationPayload,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> TestNotificationResponse:
    """Admin-only endpoint to test a notification channel configuration."""
    test_cfg = dict(payload.config)

    # If channel_id provided, merge unmasked credentials from stored channel
    if payload.channel_id:
        existing = db.get_notification_channel(payload.channel_id)
        if existing:
            existing_cfg = existing.get("config") or {}
            for k, v in existing_cfg.items():
                if k not in test_cfg:
                    test_cfg[k] = v
                elif isinstance(test_cfg[k], str) and "•••" in test_cfg[k]:
                    test_cfg[k] = v

    if "webhook_url" in test_cfg and test_cfg["webhook_url"]:
        clean_url = str(test_cfg["webhook_url"]).strip()
        if not is_safe_service_url(clean_url, allow_lan=True):
            return TestNotificationResponse(
                success=False,
                message="Prohibited or invalid webhook URL (SSRF protection)",
            )

    success, message = notification_dispatcher.test_channel(
        channel_type=payload.channel_type.strip().lower(),
        config=test_cfg,
    )
    return TestNotificationResponse(success=success, message=message)
