"""Requests REST API endpoints for user requests, approval workflows, and Lidarr dispatch."""

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from plex_playlist_sync.acquisition_coordinator import acquisition_coordinator
from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_lidarr_client,
    require_admin,
    require_user,
)
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.lidarr_queue import lidarr_worker
from plex_playlist_sync.models import MusicRequest, RequestStatus
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateMusicRequestBody(BaseModel):
    item_type: str = Field(default="album", pattern="^(album|track)$")
    title: str = Field(..., min_length=1)
    artist: str = Field(..., min_length=1)
    album: Optional[str] = None
    cover_url: Optional[str] = None
    release_date: Optional[str] = None
    foreign_id: Optional[str] = None
    preview_url: Optional[str] = None


@router.get("")
def list_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Lists requests. Non-admins see only their own requests; admins see all."""
    user_id = None if current_user.get("is_admin") else current_user["id"]
    requests = db.list_requests(user_id=user_id, status=status_filter)
    return {"requests": requests, "count": len(requests)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(
    body: CreateMusicRequestBody,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    current_user: dict[str, Any] = Depends(require_user),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
) -> dict[str, Any]:
    """Creates a new music request.

    If the user is admin or auto_approve_requests is enabled, transitions immediately
    to processing and dispatches to lidarr_worker (if Lidarr is configured).
    Otherwise, sets status to pending.
    """
    clean_title = body.title.strip()
    clean_artist = body.artist.strip()
    clean_album = body.album.strip() if body.album else None

    # Quota check for non-admin users
    if not current_user.get("is_admin"):
        existing_user_reqs = db.list_requests(user_id=current_user["id"])
        active_count = sum(
            1 for r in existing_user_reqs if r.get("status") in ("pending", "processing", "approved")
        )
        if active_count >= config.user_request_quota:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Active request quota exceeded (maximum {config.user_request_quota} requests allowed)",
            )

        # Duplicate check for the same item
        for r in existing_user_reqs:
            if r.get("status") in ("pending", "processing", "approved"):
                if (
                    r.get("artist", "").lower() == clean_artist.lower()
                    and r.get("title", "").lower() == clean_title.lower()
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="You have already submitted an active request for this item",
                    )

    # Determine status & auto-approval
    is_auto_approved = bool(current_user.get("is_admin") or config.auto_approve_requests)
    initial_status = RequestStatus.PROCESSING if is_auto_approved else RequestStatus.PENDING

    req_id = f"req-{uuid.uuid4().hex[:12]}"
    new_request = MusicRequest(
        id=req_id,
        user_id=current_user["id"],
        item_type=body.item_type,
        title=clean_title,
        artist=clean_artist,
        album=clean_album,
        cover_url=body.cover_url,
        status=initial_status,
        release_date=body.release_date,
        foreign_id=body.foreign_id,
        preview_url=body.preview_url,
    )

    created = db.create_request(new_request)

    # Dispatch to native acquisition coordinator if processing, otherwise fall back to Lidarr
    if initial_status == RequestStatus.PROCESSING:
        grabbed = False
        has_native_clients = any(
            c.get("enabled") for c in db.list_download_clients() if c.get("driver_type") != "lidarr"
        )
        has_indexers = any(i.get("enabled") for i in db.list_indexers()) or any(
            c.get("driver_type") == "slskd" and c.get("enabled") for c in db.list_download_clients()
        )

        if has_native_clients and has_indexers:
            try:
                grab_res = acquisition_coordinator.search_and_grab(
                    artist=clean_artist,
                    title=clean_title,
                    album=clean_album,
                    item_type=body.item_type,
                    request_id=req_id,
                    db=db,
                )
                if grab_res.get("success"):
                    grabbed = True
                    logger.info("Native acquisition grabbed request %s (%s - %s)", req_id, clean_artist, clean_title)
                else:
                    logger.info("Native acquisition found no match for request %s: %s", req_id, grab_res.get("message"))
            except Exception as e:
                logger.error("Error in native acquisition for request %s: %s", req_id, e)

        if not grabbed and lidarr_client is not None:
            try:
                lidarr_worker.start_trickle(
                    items=[
                        {
                            "id": req_id,
                            "artist": clean_artist,
                            "album": clean_album or clean_title,
                            "title": clean_title,
                            "is_request": True,
                        }
                    ],
                    client=lidarr_client,
                    db=db,
                    delay_seconds=config.lidarr_trickle_rate_seconds,
                    auto_search=config.lidarr_auto_search,
                )
                logger.info("Enqueued request %s (%s - %s) to Lidarr worker", req_id, clean_artist, clean_title)
            except Exception as e:
                logger.error("Failed to enqueue request %s to Lidarr worker: %s", req_id, e)

    return created


@router.post("/{request_id}/approve")
def approve_request(
    request_id: str,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    _admin: dict[str, Any] = Depends(require_admin),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
) -> dict[str, Any]:
    """Admin-only endpoint to approve a request, updating status to processing and dispatching to Lidarr."""
    req = db.get_request(request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    db.update_request_status(request_id, RequestStatus.PROCESSING)
    updated = db.get_request(request_id)

    grabbed = False
    has_native_clients = any(
        c.get("enabled") for c in db.list_download_clients() if c.get("driver_type") != "lidarr"
    )
    has_indexers = any(i.get("enabled") for i in db.list_indexers()) or any(
        c.get("driver_type") == "slskd" and c.get("enabled") for c in db.list_download_clients()
    )

    if has_native_clients and has_indexers:
        try:
            grab_res = acquisition_coordinator.search_and_grab(
                artist=req["artist"],
                title=req["title"],
                album=req.get("album"),
                item_type=req.get("item_type", "track"),
                request_id=request_id,
                db=db,
            )
            if grab_res.get("success"):
                grabbed = True
                logger.info("Native acquisition grabbed approved request %s (%s - %s)", request_id, req["artist"], req["title"])
            else:
                logger.info("Native acquisition found no match for approved request %s: %s", request_id, grab_res.get("message"))
        except Exception as e:
            logger.error("Error in native acquisition for approved request %s: %s", request_id, e)

    if not grabbed and lidarr_client is not None:
        try:
            lidarr_worker.start_trickle(
                items=[
                    {
                        "id": request_id,
                        "artist": req["artist"],
                        "album": req.get("album") or req["title"],
                        "title": req["title"],
                        "is_request": True,
                    }
                ],
                client=lidarr_client,
                db=db,
                delay_seconds=config.lidarr_trickle_rate_seconds,
                auto_search=config.lidarr_auto_search,
            )
            logger.info("Approved request %s enqueued to Lidarr worker", request_id)
        except Exception as e:
            logger.error("Error enqueuing approved request %s to Lidarr: %s", request_id, e)

    return updated or req


@router.post("/{request_id}/reject")
def reject_request(
    request_id: str,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only endpoint to reject a request."""
    req = db.get_request(request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    db.update_request_status(request_id, RequestStatus.REJECTED)
    updated = db.get_request(request_id)
    return updated or req


@router.delete("/{request_id}")
def delete_request(
    request_id: str,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Deletes a request. Requesters can delete pending requests; admins can delete any."""
    req = db.get_request(request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    is_admin = bool(current_user.get("is_admin"))
    is_owner = str(req["user_id"]) == str(current_user["id"])

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this request",
        )

    if not is_admin and req["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending requests may be canceled by standard users",
        )

    deleted = db.delete_request(request_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete request",
        )

    return {"status": "deleted", "id": request_id}
