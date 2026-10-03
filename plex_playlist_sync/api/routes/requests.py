"""Requests REST API endpoints for user requests, approval workflows, and Lidarr dispatch."""

import logging
import os
import uuid
from typing import Any, Optional

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from plex_playlist_sync.acquisition_coordinator import acquisition_coordinator
from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_lidarr_client,
    has_permission,
    require_admin,
    require_user,
)
from plex_playlist_sync.clients.core_client import CoreClient
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.lidarr_queue import lidarr_worker
from plex_playlist_sync.models import (
    MusicRequest,
    NotificationEvent,
    RequestStatus,
    UserPermission,
)
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.request_submission import RequestRejected, submit_track_request, user_request_lock
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


class BatchCreateMusicRequestBody(BaseModel):
    requests: list[CreateMusicRequestBody] = Field(..., min_length=1)


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
    if not has_permission(current_user, UserPermission.REQUEST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires REQUEST",
        )

    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    if role == "gateway" and config.trackseerr_core_url:
        core_client = CoreClient(
            core_url=config.trackseerr_core_url,
            secret=config.internal_core_secret,
        )
        try:
            return core_client.forward_request(body.model_dump(), user_info=current_user)
        except httpx.HTTPStatusError as exc:
            try:
                err_detail = exc.response.json().get("detail", exc.response.text)
            except Exception:
                err_detail = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=err_detail) from exc
        except (httpx.RequestError, Exception) as exc:
            logger.error("Failed to forward request to Core at %s: %s", config.trackseerr_core_url, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to communicate with TrackSeerr Core engine",
            ) from exc

    clean_title = body.title.strip()
    clean_artist = body.artist.strip()
    clean_album = body.album.strip() if body.album else None

    try:
        submission = submit_track_request(
            db,
            config,
            current_user,
            clean_title,
            clean_artist,
            clean_album,
            source="api",
            item_type=body.item_type,
            cover_url=body.cover_url,
            release_date=body.release_date,
            foreign_id=body.foreign_id,
            preview_url=body.preview_url,
        )
    except RequestRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    created = submission.request
    req_id = created["id"]

    # Native grab already attempted by the shared submission; otherwise fall back to Lidarr
    if submission.status == RequestStatus.PROCESSING:
        grabbed = submission.grabbed

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


@router.post("/batch", status_code=status.HTTP_201_CREATED)
def create_batch_requests(
    body: BatchCreateMusicRequestBody,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    current_user: dict[str, Any] = Depends(require_user),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
) -> dict[str, Any]:
    """Creates multiple music requests in a single transaction within configured user quotas.

    Non-admin user requests are validated against remaining quota.
    Duplicates against active requests or within the batch are handled idempotently.
    Approved requests attempt native grab, falling back to Lidarr trickle worker.
    """
    if not has_permission(current_user, UserPermission.REQUEST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires REQUEST",
        )

    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    if role == "gateway" and config.trackseerr_core_url:
        core_client = CoreClient(
            core_url=config.trackseerr_core_url,
            secret=config.internal_core_secret,
        )
        try:
            return core_client.forward_batch_requests(body.model_dump(), user_info=current_user)
        except httpx.HTTPStatusError as exc:
            try:
                err_detail = exc.response.json().get("detail", exc.response.text)
            except Exception:
                err_detail = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=err_detail) from exc
        except (httpx.RequestError, Exception) as exc:
            logger.error("Failed to forward batch requests to Core at %s: %s", config.trackseerr_core_url, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to communicate with TrackSeerr Core engine",
            ) from exc

    # Hold the per-user lock across quota count + every insert so concurrent batches cannot exceed quota.
    # Network follow-ups (notifications, grabs) run after release.
    with user_request_lock(current_user["id"]):
        if not current_user.get("is_admin"):
            rolling_days = current_user.get("request_limit_days") if current_user.get("request_limit_days") is not None else 7
            quota_limit = current_user.get("request_limit_quota") or config.user_request_quota
            active_count = db.get_user_active_request_count(current_user["id"], days=rolling_days)
            remaining_quota = max(0, quota_limit - active_count)
            if len(body.requests) > remaining_quota:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Active request quota exceeded: batch size ({len(body.requests)}) exceeds remaining allowance ({remaining_quota} remaining of {quota_limit} allowed)",
                )
            existing_user_reqs = db.list_requests(user_id=current_user["id"])
            existing_active_keys = {
                ((r.get("artist") or "").lower().strip(), (r.get("title") or "").lower().strip())
                for r in existing_user_reqs
                if r.get("status") in ("pending", "processing", "approved")
            }
            existing_active_foreign_ids = {
                r.get("foreign_id")
                for r in existing_user_reqs
                if r.get("foreign_id") and r.get("status") in ("pending", "processing", "approved")
            }
        else:
            existing_active_keys = set()
            existing_active_foreign_ids = set()

        seen_keys: set[tuple[str, str]] = set()
        seen_fids: set[str] = set()

        is_auto_approved = bool(
            current_user.get("is_admin")
            or has_permission(current_user, UserPermission.AUTO_APPROVE)
            or config.auto_approve_requests
        )

        created_items: list[dict[str, Any]] = []

        for req_item in body.requests:
            clean_title = req_item.title.strip()
            clean_artist = req_item.artist.strip()
            clean_album = req_item.album.strip() if req_item.album else None
            item_key = (clean_artist.lower(), clean_title.lower())
            fid = req_item.foreign_id.strip() if req_item.foreign_id else None

            # Idempotent deduplication against existing active user requests
            if not current_user.get("is_admin"):
                if item_key in existing_active_keys or (fid and fid in existing_active_foreign_ids):
                    continue

            # Idempotent deduplication within the batch
            if item_key in seen_keys or (fid and fid in seen_fids):
                continue

            seen_keys.add(item_key)
            if fid:
                seen_fids.add(fid)

            item_auto_approved = is_auto_approved or (
                req_item.item_type == "album"
                and has_permission(current_user, UserPermission.AUTO_APPROVE_ALBUM)
            )
            item_status = RequestStatus.PROCESSING if item_auto_approved else RequestStatus.PENDING

            req_id = f"req-{uuid.uuid4().hex[:12]}"
            new_request = MusicRequest(
                id=req_id,
                user_id=current_user["id"],
                item_type=req_item.item_type,
                title=clean_title,
                artist=clean_artist,
                album=clean_album,
                cover_url=req_item.cover_url,
                status=item_status,
                release_date=req_item.release_date,
                foreign_id=fid,
                preview_url=req_item.preview_url,
            )

            created = db.create_request(new_request)
            created_items.append(created)

    for created in created_items:
        # Dispatch notification events
        notification_data = dict(created)
        if not notification_data.get("username"):
            notification_data["username"] = current_user.get("username")
        notification_dispatcher.dispatch(NotificationEvent.REQUEST_CREATED, data=notification_data, db=db)
        if created.get("status") in (RequestStatus.PROCESSING.value, "processing"):
            notification_dispatcher.dispatch(NotificationEvent.REQUEST_APPROVED, data=notification_data, db=db)

    # Dispatch to native acquisition coordinator if processing, otherwise fall back to Lidarr
    processing_items = [
        c for c in created_items if c.get("status") in (RequestStatus.PROCESSING.value, "processing")
    ]
    if processing_items:
        has_native_clients = any(
            c.get("enabled") for c in db.list_download_clients() if c.get("driver_type") != "lidarr"
        )
        has_indexers = any(i.get("enabled") for i in db.list_indexers()) or any(
            c.get("driver_type") == "slskd" and c.get("enabled") for c in db.list_download_clients()
        )

        lidarr_items: list[dict[str, Any]] = []

        for created in processing_items:
            req_id = created["id"]
            clean_artist = created["artist"]
            clean_title = created["title"]
            clean_album = created.get("album")
            item_type = created.get("item_type", "track")

            grabbed = False
            if has_native_clients and has_indexers:
                try:
                    grab_res = acquisition_coordinator.search_and_grab(
                        artist=clean_artist,
                        title=clean_title,
                        album=clean_album,
                        item_type=item_type,
                        request_id=req_id,
                        db=db,
                    )
                    if grab_res.get("success"):
                        grabbed = True
                        logger.info(
                            "Native acquisition grabbed batch request %s (%s - %s)",
                            req_id,
                            clean_artist,
                            clean_title,
                        )
                    else:
                        logger.info(
                            "Native acquisition found no match for batch request %s: %s",
                            req_id,
                            grab_res.get("message"),
                        )
                except Exception as e:
                    logger.error("Error in native acquisition for batch request %s: %s", req_id, e)

            if not grabbed:
                lidarr_items.append(
                    {
                        "id": req_id,
                        "artist": clean_artist,
                        "album": clean_album or clean_title,
                        "title": clean_title,
                        "is_request": True,
                    }
                )

        if lidarr_items and lidarr_client is not None:
            try:
                lidarr_worker.start_trickle(
                    items=lidarr_items,
                    client=lidarr_client,
                    db=db,
                    delay_seconds=config.lidarr_trickle_rate_seconds,
                    auto_search=config.lidarr_auto_search,
                )
                logger.info("Enqueued %d batch requests to Lidarr worker", len(lidarr_trickle_items))
            except Exception as e:
                logger.error("Failed to enqueue batch requests to Lidarr worker: %s", e)

    return {"created": created_items, "count": len(created_items)}


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

    res_req = updated or req
    notification_dispatcher.dispatch(NotificationEvent.REQUEST_APPROVED, data=res_req, db=db)
    return res_req


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
    res_req = updated or req
    notification_dispatcher.dispatch(NotificationEvent.REQUEST_REJECTED, data=res_req, db=db)
    return res_req


@router.delete("/{request_id}")
def delete_request(
    request_id: str,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    current_user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Deletes a request. Requesters can delete pending requests; admins can delete any."""
    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    if role == "gateway" and config.trackseerr_core_url:
        core_client = CoreClient(
            core_url=config.trackseerr_core_url,
            secret=config.internal_core_secret,
        )
        try:
            ok = core_client.forward_delete_request(request_id, user_info=current_user)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete request on TrackSeerr Core",
                )
            return {"status": "deleted", "id": request_id}
        except HTTPException:
            raise
        except (httpx.RequestError, Exception) as exc:
            logger.error("Failed to forward delete request to Core at %s: %s", config.trackseerr_core_url, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to communicate with TrackSeerr Core engine",
            ) from exc

    req = db.get_request(request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    is_admin = bool(current_user.get("is_admin"))
    is_owner = str(req["user_id"]) == str(current_user["id"])

    if not is_admin and not is_owner:
        # 404, not 403: do not reveal that another user's request exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

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


@router.post("/{request_id}/retry")
def retry_request(
    request_id: str,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    _admin: dict[str, Any] = Depends(require_admin),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
) -> dict[str, Any]:
    """Admin-only: forces re-search and grab for an existing request."""
    req = db.get_request(request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if req.get("status") == "available":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request is already fulfilled and available",
        )

    db.update_request_status(request_id, RequestStatus.PROCESSING)

    clean_artist = req.get("artist", "").strip()
    clean_title = req.get("title", "").strip()
    clean_album = req.get("album", "").strip() if req.get("album") else None
    item_type = req.get("item_type", "track")

    grabbed = False
    download_id: Optional[str] = None
    msg = "Acquisition initiated"

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
                item_type=item_type,
                request_id=request_id,
                db=db,
            )
            if grab_res.get("success"):
                grabbed = True
                download_id = grab_res.get("download_id")
                msg = f"Grabbed release: {grab_res.get('release')}"
                logger.info(
                    "Native acquisition grabbed retried request %s (%s - %s)",
                    request_id,
                    clean_artist,
                    clean_title,
                )
            else:
                msg = grab_res.get("message") or "No matching release found on indexers"
                logger.info(
                    "Native acquisition found no match for retried request %s: %s",
                    request_id,
                    msg,
                )
        except Exception as e:
            logger.error("Error in native acquisition for retried request %s: %s", request_id, e)
            msg = f"Acquisition error: {str(e)}"

    if not grabbed and lidarr_client is not None:
        try:
            lidarr_worker.start_trickle(
                items=[
                    {
                        "id": request_id,
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
            logger.info("Enqueued retried request %s (%s - %s) to Lidarr worker", request_id, clean_artist, clean_title)
            msg = "Enqueued to Lidarr for search"
        except Exception as e:
            logger.error("Failed to enqueue retried request %s to Lidarr worker: %s", request_id, e)

    return {
        "success": grabbed or (lidarr_client is not None),
        "status": "processing",
        "message": msg,
        "download_id": download_id,
    }
