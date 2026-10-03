"""Shared request-submission policy: quota, duplicate check, auto-approval and native grab kick-off.

Used by the requests route and by tailored mixes so that every path that creates a ``music_requests`` row
applies the same rules. The caller supplies a user row (loaded from the DB for background work).
"""

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from plex_playlist_sync.acquisition_coordinator import acquisition_coordinator
from plex_playlist_sync.models import MusicRequest, NotificationEvent, RequestStatus, UserPermission
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

_locks_guard = threading.Lock()
_user_locks: dict[str, threading.RLock] = {}


def user_request_lock(user_id: str) -> threading.RLock:
    """Per-user lock serialising count-then-insert. Re-entrant so callers may hold it across submit_track_request."""
    key = str(user_id)
    with _locks_guard:
        lock = _user_locks.get(key)
        if lock is None:
            lock = _user_locks[key] = threading.RLock()
        return lock


class RequestRejected(Exception):
    """Policy refused the request. ``code`` is ``quota`` or ``duplicate``; ``status_code`` mirrors the HTTP mapping."""

    def __init__(self, code: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail


@dataclass
class RequestSubmission:
    request: dict[str, Any]
    status: RequestStatus
    grabbed: bool = False


def _has_permission(user: dict[str, Any], permission: UserPermission) -> bool:
    # Deferred import: dependencies pulls in the whole API layer.
    from plex_playlist_sync.api.dependencies import has_permission

    return has_permission(user, permission)


def effective_request_quota(user: dict[str, Any], config: Any) -> int:
    return int(user.get("request_limit_quota") or config.user_request_quota)


def submit_track_request(
    db: Database,
    config: Any,
    user: dict[str, Any],
    title: str,
    artist: str,
    album: Optional[str] = None,
    quality_profile_id: Optional[str] = None,
    source: str = "api",
    *,
    item_type: str = "track",
    cover_url: Optional[str] = None,
    release_date: Optional[str] = None,
    foreign_id: Optional[str] = None,
    preview_url: Optional[str] = None,
    defer_followups: bool = False,
) -> RequestSubmission:
    """Apply request policy and create the request. Raises ``RequestRejected`` on quota or duplicate.

    Non-admins cannot choose a quality profile: it is dropped. The per-user lock covers only the
    count-check plus insert. Notifications and the native grab (network I/O) run after it is released; a caller
    that holds the lock itself passes ``defer_followups=True`` and calls ``run_submission_followups`` once released.
    """
    clean_title = title.strip()
    clean_artist = artist.strip()
    clean_album = album.strip() if album else None
    is_admin = bool(user.get("is_admin"))
    if not is_admin:
        quality_profile_id = None

    with user_request_lock(user["id"]):
        if not is_admin:
            rolling_days = user.get("request_limit_days") if user.get("request_limit_days") is not None else 7
            quota_limit = effective_request_quota(user, config)
            if db.get_user_active_request_count(user["id"], days=rolling_days) >= quota_limit:
                raise RequestRejected(
                    "quota",
                    400,
                    f"Active request quota exceeded (maximum {quota_limit} requests allowed)",
                )
            for r in db.list_requests(user_id=user["id"]):
                if r.get("status") in ("pending", "processing", "approved") and (
                    r.get("artist", "").lower() == clean_artist.lower()
                    and r.get("title", "").lower() == clean_title.lower()
                ):
                    raise RequestRejected(
                        "duplicate", 409, "You have already submitted an active request for this item"
                    )

        is_auto_approved = bool(
            is_admin
            or _has_permission(user, UserPermission.AUTO_APPROVE)
            or (item_type == "album" and _has_permission(user, UserPermission.AUTO_APPROVE_ALBUM))
            or config.auto_approve_requests
        )
        initial_status = RequestStatus.PROCESSING if is_auto_approved else RequestStatus.PENDING

        req_id = f"req-{uuid.uuid4().hex[:12]}"
        created = db.create_request(
            MusicRequest(
                id=req_id,
                user_id=user["id"],
                item_type=item_type,
                title=clean_title,
                artist=clean_artist,
                album=clean_album,
                cover_url=cover_url,
                status=initial_status,
                release_date=release_date,
                foreign_id=foreign_id,
                preview_url=preview_url,
                quality_profile_id=quality_profile_id,
            )
        )

    submission = RequestSubmission(request=created, status=initial_status)
    if not defer_followups:
        run_submission_followups(db, user, submission, source=source)
    return submission


def run_submission_followups(
    db: Database, user: dict[str, Any], submission: RequestSubmission, source: str = "api"
) -> RequestSubmission:
    """Dispatch notifications and kick off the native grab. Must run without ``user_request_lock`` held."""
    created = submission.request
    initial_status = submission.status
    req_id = created["id"]
    clean_artist = created.get("artist") or ""
    clean_title = created.get("title") or ""
    clean_album = created.get("album")
    item_type = created.get("item_type") or "track"

    notification_data = dict(created)
    if not notification_data.get("username"):
        notification_data["username"] = user.get("username")
    notification_dispatcher.dispatch(NotificationEvent.REQUEST_CREATED, data=notification_data, db=db)
    if initial_status == RequestStatus.PROCESSING:
        notification_dispatcher.dispatch(NotificationEvent.REQUEST_APPROVED, data=notification_data, db=db)

    grabbed = False
    if initial_status == RequestStatus.PROCESSING:
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
                    request_id=req_id,
                    db=db,
                )
                if grab_res.get("success"):
                    grabbed = True
                    logger.info(
                        "Native acquisition grabbed request %s (%s - %s) [%s]", req_id, clean_artist, clean_title, source
                    )
                else:
                    logger.info("Native acquisition found no match for request %s: %s", req_id, grab_res.get("message"))
            except Exception as e:  # coordinator drivers raise heterogeneous errors; the request stays approved
                logger.error("Error in native acquisition for request %s (%s)", req_id, type(e).__name__)

    submission.grabbed = grabbed
    return submission
