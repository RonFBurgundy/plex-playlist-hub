"""Background sync routes and SSE live log streaming."""

import asyncio
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_deezer_client,
    get_plex_client,
    get_spotify_client,
    require_admin,
)
from plex_playlist_sync.auth import get_or_create_secret_key, verify_session_token
from plex_playlist_sync.clients.deezer import DeezerClient
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.clients.spotify import SpotifyClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.models import Playlist, Track
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class BroadcastLogHandler(logging.Handler):
    """Logging handler that thread-safely broadcasts formatted log records to active asyncio queues."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.listeners: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        with self._lock:
            active_listeners = list(self.listeners)

        for loop, q in active_listeners:
            try:
                if loop.is_running():
                    loop.call_soon_threadsafe(self._safe_put, q, msg)
            except Exception:
                pass

    @staticmethod
    def _safe_put(q: asyncio.Queue, msg: str) -> None:
        try:
            q.put_nowait(msg)
        except (asyncio.QueueFull, Exception):
            pass

    def add_listener(self, loop: asyncio.AbstractEventLoop, q: asyncio.Queue) -> None:
        with self._lock:
            self.listeners.append((loop, q))

    def remove_listener(self, q: asyncio.Queue) -> None:
        with self._lock:
            self.listeners = [item for item in self.listeners if item[1] is not q]


class SyncState:
    """Manages active sync status, statistics, and log streaming."""

    def __init__(self) -> None:
        self.is_syncing: bool = False
        self.last_run_at: Optional[str] = None
        self.last_run_stats: dict[str, Any] = {
            "total_playlists": 0,
            "success_count": 0,
            "total_matched": 0,
            "total_missing": 0,
        }
        self.log_handler = BroadcastLogHandler()
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.log_handler.setFormatter(formatter)
        logging.getLogger("plex_playlist_sync").addHandler(self.log_handler)

    def execute_sync(
        self,
        db: Database,
        config: Config,
        plex_client: Optional[PlexClient],
        spotify_client: Optional[SpotifyClient],
        deezer_client: Optional[DeezerClient],
    ) -> dict[str, Any]:
        """Runs synchronization across all enabled database playlists."""
        if self.is_syncing:
            return {"status": "already_running"}

        self.is_syncing = True
        logger.info("Starting background playlist synchronization cycle")
        stats = {
            "total_playlists": 0,
            "success_count": 0,
            "total_matched": 0,
            "total_missing": 0,
        }

        try:
            playlists = db.list_playlists(enabled_only=True)
            stats["total_playlists"] = len(playlists)

            for pl in playlists:
                pl_id = pl["id"]
                target_uids = db.get_playlist_targets(pl_id)
                if not target_uids:
                    logger.info("Playlist '%s' has no target users assigned; skipping", pl["name"])
                    continue

                target_usernames: list[str] = []
                for uid in target_uids:
                    user_row = db.get_user(uid)
                    if user_row:
                        target_usernames.append(user_row["username"])

                if not target_usernames:
                    logger.info("No valid usernames found for playlist '%s' targets", pl["name"])
                    continue

                tracks: list[Track] = []
                service = pl.get("service", "spotify")
                try:
                    if pl_id.startswith("imp_") or pl.get("tracks_json"):
                        raw_tracks_json = pl.get("tracks_json")
                        if raw_tracks_json:
                            t_dicts = json.loads(raw_tracks_json)
                            tracks = [
                                Track(
                                    title=t.get("title", ""),
                                    artist=t.get("artist", ""),
                                    album=t.get("album", ""),
                                    url=t.get("url", ""),
                                )
                                for t in t_dicts
                                if t.get("title")
                            ]
                    elif service == "spotify" and spotify_client:
                        tracks = spotify_client.get_playlist_tracks(pl_id)
                    elif service == "deezer" and deezer_client:
                        tracks = deezer_client.get_playlist_tracks(pl_id)
                except Exception as e:
                    logger.error("Failed to fetch tracks for playlist '%s' (%s): %s", pl["name"], pl_id, e)
                    db.record_sync_result(pl_id, status="error")
                    continue

                model_playlist = Playlist(
                    id=pl_id,
                    name=pl["name"],
                    tracks=tracks,
                    description=pl.get("description", ""),
                    poster=pl.get("poster_url", ""),
                )

                if plex_client:
                    try:
                        results = plex_client.sync_playlist_to_users(
                            playlist=model_playlist,
                            target_usernames=target_usernames,
                            append=config.append_instead_of_sync,
                            add_description=config.add_playlist_description,
                            add_poster=config.add_playlist_poster,
                            write_missing_as_csv=config.write_missing_as_csv,
                            data_dir=config.data_dir,
                            threshold=config.search_similarity_threshold,
                        )
                        matched, missing = plex_client.match_playlist_tracks(
                            tracks, threshold=config.search_similarity_threshold
                        )
                        success = any(r.success for r in results) if results else False
                        db.record_sync_result(
                            playlist_id=pl_id,
                            status="success" if success else "failed",
                            missing_tracks=missing,
                        )
                        if success:
                            stats["success_count"] += 1
                        stats["total_matched"] += len(matched)
                        stats["total_missing"] += len(missing)
                    except Exception as e:
                        logger.error("Error syncing playlist '%s' to Plex: %s", pl["name"], e)
                        db.record_sync_result(playlist_id=pl_id, status="failed")
                else:
                    logger.warning("Plex client not available; recorded simulated sync for '%s'", pl["name"])
                    db.record_sync_result(playlist_id=pl_id, status="unconfigured")

            self.last_run_stats = stats
            self.last_run_at = datetime.now(timezone.utc).isoformat()
            logger.info(
                "Background sync complete: %d/%d succeeded, %d matched, %d missing",
                stats["success_count"],
                stats["total_playlists"],
                stats["total_matched"],
                stats["total_missing"],
            )
            return {"status": "success", "stats": stats}
        except Exception as e:
            logger.error("Unexpected error during sync cycle: %s", e)
            return {"status": "error", "error": str(e)}
        finally:
            self.is_syncing = False


# Shared sync state instance
sync_state = SyncState()


@router.post("")
def trigger_sync(
    background_tasks: BackgroundTasks,
    _current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    spotify_client: Optional[SpotifyClient] = Depends(get_spotify_client),
    deezer_client: Optional[DeezerClient] = Depends(get_deezer_client),
) -> dict[str, Any]:
    """Triggers sync in background task (runs async without blocking)."""
    if sync_state.is_syncing:
        return {
            "status": "already_running",
            "message": "Synchronization is already running in background",
        }

    background_tasks.add_task(
        sync_state.execute_sync,
        db=db,
        config=config,
        plex_client=plex_client,
        spotify_client=spotify_client,
        deezer_client=deezer_client,
    )

    return {
        "status": "started",
        "message": "Synchronization triggered successfully in background",
    }


@router.get("/status")
def get_sync_status(
    _current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Returns current sync status and last run stats."""
    return {
        "is_syncing": sync_state.is_syncing,
        "last_run_at": sync_state.last_run_at,
        "last_run_stats": sync_state.last_run_stats,
    }


@router.get("/stream")
async def stream_sync_logs(
    request: Request,
    limit: Optional[int] = None,
    _admin: dict[str, Any] = Depends(require_admin),
) -> StreamingResponse:
    """Server-Sent Events (SSE) streaming live log lines (administrators only)."""

    async def event_generator():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        sync_state.log_handler.add_listener(loop, q)
        count = 0
        try:
            yield "data: Connected to live sync log stream\n\n"
            count += 1
            if limit is not None and count >= limit:
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {line}\n\n"
                    count += 1
                    if limit is not None and count >= limit:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sync_state.log_handler.remove_listener(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/webhook")
async def handle_sync_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    token: Optional[str] = None,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    spotify_client: Optional[SpotifyClient] = Depends(get_spotify_client),
    deezer_client: Optional[DeezerClient] = Depends(get_deezer_client),
) -> dict[str, Any]:
    """Webhook endpoint for Lidarr, Plex, or external automation triggers.

    When Lidarr completes a track download/import or Plex completes a library scan,
    they can ping this endpoint to trigger immediate playlist sync and re-evaluation.
    Requires FEED_TOKEN if configured, or a valid admin session.
    """
    provided = (
        token
        or request.headers.get("X-Api-Key")
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    )
    if config.feed_token:
        if provided != config.feed_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook token",
            )
    else:
        # FEED_TOKEN is not set; require an explicit admin session token
        cookie_token = request.cookies.get("session_token")
        sess_token = cookie_token or (provided if provided else None)
        is_admin_session = False
        if sess_token:
            try:
                secret_key = get_or_create_secret_key(data_dir=config.data_dir)
                payload = verify_session_token(sess_token, secret_key)
                if payload and payload.get("is_admin") and db.get_session(sess_token):
                    is_admin_session = True
            except Exception:
                pass
        if not is_admin_session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="FEED_TOKEN must be configured or admin authentication provided to trigger webhooks",
            )

    body_preview = ""
    try:
        raw_body = await request.body()
        if raw_body:
            body_preview = raw_body[:200].decode("utf-8", errors="ignore")
    except Exception:
        pass

    logger.info("Sync webhook received (triggering background sync): %s", body_preview)

    if sync_state.is_syncing:
        return {"status": "already_running", "message": "Synchronization is already in progress"}

    background_tasks.add_task(
        sync_state.execute_sync,
        db=db,
        config=config,
        plex_client=plex_client,
        spotify_client=spotify_client,
        deezer_client=deezer_client,
    )
    return {"status": "triggered", "message": "Background synchronization triggered via webhook"}
