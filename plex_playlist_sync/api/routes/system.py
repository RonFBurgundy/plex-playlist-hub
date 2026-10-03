"""System diagnostics and telemetry API routes for TrackSeerr."""

import asyncio
import collections
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import threading
import time
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_plex_client,
    require_admin,
)
from plex_playlist_sync.auth import get_or_create_secret_key, verify_session_token
from plex_playlist_sync.clients.acquisition import (
    get_acquisition_driver,
    get_indexer_driver,
)
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.models import DownloadClientConfig, IndexerConfig
from plex_playlist_sync.security import is_safe_service_url
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

# Track application start timestamp at module import
_APP_START_TIME = time.time()

router = APIRouter()


class LogRingBuffer(logging.Handler):
    """Thread-safe circular in-memory log buffer supporting SSE broadcasting."""

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=maxlen)
        self.listeners: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            entry = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "message": msg,
            }
            with self._lock:
                self.buffer.append(entry)
                listeners = list(self.listeners)

            for loop, q in listeners:
                try:
                    if loop.is_running():
                        loop.call_soon_threadsafe(self._safe_put, q, entry)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)

    @staticmethod
    def _safe_put(q: asyncio.Queue, item: dict[str, Any]) -> None:
        try:
            q.put_nowait(item)
        except (asyncio.QueueFull, Exception):
            pass

    def add_listener(self, loop: asyncio.AbstractEventLoop, q: asyncio.Queue) -> None:
        with self._lock:
            self.listeners.append((loop, q))

    def remove_listener(self, q: asyncio.Queue) -> None:
        with self._lock:
            self.listeners = [item for item in self.listeners if item[1] is not q]

    def get_logs(
        self,
        level: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.buffer)

        if level and level.lower() != "all":
            lvl = level.strip().upper()
            items = [i for i in items if i["level"].upper() == lvl]

        if search:
            s = search.strip().lower()
            items = [
                i for i in items
                if s in i["message"].lower() or s in i["name"].lower()
            ]

        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self.buffer.clear()


log_ring_buffer = LogRingBuffer(maxlen=1000)

# Attach log_ring_buffer to root logger so all events are captured
_root_logger = logging.getLogger()
if log_ring_buffer not in _root_logger.handlers:
    _root_logger.addHandler(log_ring_buffer)


def get_log_file_path(config: Optional[Config] = None, log_dir: Optional[str] = None) -> Path:
    """Resolves the active trackseerr.log file destination path."""
    if log_dir:
        target_dir = Path(log_dir)
    elif config and getattr(config, "config_dir", None) and os.path.exists(config.config_dir):
        target_dir = Path(config.config_dir)
    elif config and getattr(config, "data_dir", None) and os.path.exists(config.data_dir):
        target_dir = Path(config.data_dir)
    elif os.path.exists("/config"):
        target_dir = Path("/config")
    elif os.path.exists("/data"):
        target_dir = Path("/data")
    else:
        target_dir = Path(os.environ.get("DATA_DIR", "/tmp"))

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        target_dir = Path("/tmp")

    return target_dir / "trackseerr.log"


class DiskUsageItem(BaseModel):
    path: str
    label: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float


class DatabaseStatus(BaseModel):
    path: str
    size_bytes: int
    sqlite_version: str
    table_counts: dict[str, int]


class ServicePingResult(BaseModel):
    id: str
    name: str
    service_type: str
    host_url: str
    enabled: bool
    online: bool
    latency_ms: Optional[float] = None
    message: str


class PlexStatus(BaseModel):
    configured: bool
    url: Optional[str] = None
    music_section: Optional[str] = None
    online: bool
    latency_ms: Optional[float] = None
    user_count: int = 0
    playlist_count: int = 0
    message: str


class WorkerStatus(BaseModel):
    acquisition_worker: dict[str, Any]
    lidarr_worker: dict[str, Any]
    sync_coordinator: dict[str, Any]
    backlog_worker: Optional[dict[str, Any]] = None
    rss_worker: Optional[dict[str, Any]] = None


class EnvironmentStatus(BaseModel):
    version: str = "1.0.0"
    python_version: str
    platform: str
    role: str
    uptime_seconds: float


class SystemStatusResponse(BaseModel):
    environment: EnvironmentStatus
    storage: list[DiskUsageItem]
    database: DatabaseStatus
    plex: PlexStatus
    download_clients: list[ServicePingResult]
    indexers: list[ServicePingResult]
    workers: WorkerStatus


def _get_disk_metrics(config: Config, db: Database) -> list[DiskUsageItem]:
    """Collects disk usage metrics for key system mount paths."""
    candidates: list[tuple[str, str]] = [
        ("/", "System Root (/)"),
        (config.data_dir or "/data", f"Data Directory ({config.data_dir or '/data'})"),
    ]

    if os.path.exists("/config"):
        candidates.append(("/config", "Config Directory (/config)"))

    try:
        mm = db.get_media_management_settings()
        root_folder = mm.get("root_folder_path")
        if root_folder:
            candidates.append((str(root_folder), "Music Library Storage"))
        staging_folder = mm.get("staging_folder_path")
        if staging_folder:
            candidates.append((str(staging_folder), "Download Staging Storage"))
    except Exception as e:
        logger.warning("Failed to retrieve media management paths for disk usage: %s", e)

    results: list[DiskUsageItem] = []
    seen_usages: set[tuple[int, int]] = set()

    for path, label in candidates:
        if not path:
            continue
        try:
            usage = shutil.disk_usage(path)
            usage_key = (usage.total, usage.used)
            if usage_key in seen_usages:
                continue
            seen_usages.add(usage_key)

            total_bytes = int(usage.total)
            used_bytes = int(usage.used)
            free_bytes = int(usage.free)
            percent_used = (
                round((used_bytes / total_bytes) * 100.0, 1)
                if total_bytes > 0
                else 0.0
            )

            results.append(
                DiskUsageItem(
                    path=path,
                    label=label,
                    total_bytes=total_bytes,
                    used_bytes=used_bytes,
                    free_bytes=free_bytes,
                    percent_used=percent_used,
                )
            )
        except (OSError, ValueError, TypeError) as e:
            logger.debug("Disk usage probe skipped for path %s: %s", path, e)

    return results


def _get_db_metrics(db: Database) -> DatabaseStatus:
    """Collects database size, sqlite engine version, and table row counts."""
    db_path_str = str(db.db_path)
    size_bytes = 0
    if db_path_str != ":memory:" and os.path.exists(db_path_str):
        try:
            size_bytes = os.path.getsize(db_path_str)
        except OSError as e:
            logger.warning("Could not read database file size at %s: %s", db_path_str, e)
            size_bytes = 0

    table_counts: dict[str, int] = {}
    try:
        table_counts["users"] = len(db.list_users())
    except Exception as e:
        logger.warning("Failed to count users: %s", e)
        table_counts["users"] = 0

    try:
        table_counts["playlists"] = len(db.list_playlists())
    except Exception as e:
        logger.warning("Failed to count playlists: %s", e)
        table_counts["playlists"] = 0

    try:
        table_counts["requests"] = len(db.list_requests())
    except Exception as e:
        logger.warning("Failed to count requests: %s", e)
        table_counts["requests"] = 0

    try:
        table_counts["missing_tracks"] = len(db.get_missing_tracks())
    except Exception as e:
        logger.warning("Failed to count missing_tracks: %s", e)
        table_counts["missing_tracks"] = 0

    try:
        table_counts["download_clients"] = len(db.list_download_clients())
    except Exception as e:
        logger.warning("Failed to count download_clients: %s", e)
        table_counts["download_clients"] = 0

    try:
        table_counts["indexers"] = len(db.list_indexers())
    except Exception as e:
        logger.warning("Failed to count indexers: %s", e)
        table_counts["indexers"] = 0

    try:
        table_counts["active_downloads"] = len(db.list_active_downloads())
    except Exception as e:
        logger.warning("Failed to count active_downloads: %s", e)
        table_counts["active_downloads"] = 0

    try:
        table_counts["system_events"] = db.list_events(limit=1)[1]
    except Exception as e:
        logger.warning("Failed to count system_events: %s", e)
        table_counts["system_events"] = 0

    return DatabaseStatus(
        path=db_path_str,
        size_bytes=size_bytes,
        sqlite_version=sqlite3.sqlite_version,
        table_counts=table_counts,
    )


def _ping_download_clients(db: Database) -> list[ServicePingResult]:
    """Pings all configured download clients and measures response latency."""
    results: list[ServicePingResult] = []
    try:
        clients = db.list_download_clients()
    except Exception as e:
        logger.warning("Failed to list download clients: %s", e)
        return results

    for client in clients:
        c_id = str(client.get("id", ""))
        c_name = str(client.get("name", "Unknown Client"))
        driver_type = str(client.get("driver_type", "unknown"))
        host_url = str(client.get("host_url", ""))
        enabled = bool(client.get("enabled", True))

        if not enabled:
            results.append(
                ServicePingResult(
                    id=c_id,
                    name=c_name,
                    service_type=driver_type,
                    host_url=host_url,
                    enabled=False,
                    online=False,
                    latency_ms=None,
                    message="Disabled in settings",
                )
            )
            continue

        if not is_safe_service_url(host_url):
            results.append(
                ServicePingResult(
                    id=c_id,
                    name=c_name,
                    service_type=driver_type,
                    host_url=host_url,
                    enabled=True,
                    online=False,
                    latency_ms=None,
                    message="Prohibited or invalid host URL (SSRF defense)",
                )
            )
            continue

        t0 = time.perf_counter()
        try:
            cfg = DownloadClientConfig(
                id=c_id,
                name=c_name,
                driver_type=driver_type,
                host_url=host_url,
                api_key=client.get("api_key"),
                username=client.get("username"),
                password=client.get("password"),
                enabled=enabled,
                priority=int(client.get("priority", 1)),
                extra_settings_json=client.get("extra_settings_json"),
                created_at=client.get("created_at"),
                updated_at=client.get("updated_at"),
            )
            driver = get_acquisition_driver(cfg)
            success, msg = driver.test_connection()
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            results.append(
                ServicePingResult(
                    id=c_id,
                    name=c_name,
                    service_type=driver_type,
                    host_url=host_url,
                    enabled=True,
                    online=bool(success),
                    latency_ms=latency_ms if success else None,
                    message=str(msg),
                )
            )
        except Exception as e:
            logger.warning("Error testing connection to download client %s: %s", c_name, e)
            results.append(
                ServicePingResult(
                    id=c_id,
                    name=c_name,
                    service_type=driver_type,
                    host_url=host_url,
                    enabled=True,
                    online=False,
                    latency_ms=None,
                    message=str(e),
                )
            )

    return results


def _ping_indexers(db: Database) -> list[ServicePingResult]:
    """Pings all configured indexers and measures response latency."""
    results: list[ServicePingResult] = []
    try:
        indexers = db.list_indexers()
    except Exception as e:
        logger.warning("Failed to list indexers: %s", e)
        return results

    for idx in indexers:
        i_id = str(idx.get("id", ""))
        i_name = str(idx.get("name", "Unknown Indexer"))
        indexer_type = str(idx.get("indexer_type", "torznab"))
        host_url = str(idx.get("host_url", ""))
        enabled = bool(idx.get("enabled", True))

        if not enabled:
            results.append(
                ServicePingResult(
                    id=i_id,
                    name=i_name,
                    service_type=indexer_type,
                    host_url=host_url,
                    enabled=False,
                    online=False,
                    latency_ms=None,
                    message="Disabled in settings",
                )
            )
            continue

        if not is_safe_service_url(host_url):
            results.append(
                ServicePingResult(
                    id=i_id,
                    name=i_name,
                    service_type=indexer_type,
                    host_url=host_url,
                    enabled=True,
                    online=False,
                    latency_ms=None,
                    message="Prohibited or invalid host URL (SSRF defense)",
                )
            )
            continue

        t0 = time.perf_counter()
        try:
            cfg = IndexerConfig(
                id=i_id,
                name=i_name,
                indexer_type=indexer_type,
                host_url=host_url,
                api_key=idx.get("api_key"),
                categories=str(idx.get("categories") or "3000,3010,3020,3030,3040"),
                enabled=enabled,
                priority=int(idx.get("priority", 1)),
                created_at=idx.get("created_at"),
                updated_at=idx.get("updated_at"),
            )
            driver = get_indexer_driver(cfg)
            success, msg = driver.test_connection()
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            results.append(
                ServicePingResult(
                    id=i_id,
                    name=i_name,
                    service_type=indexer_type,
                    host_url=host_url,
                    enabled=True,
                    online=bool(success),
                    latency_ms=latency_ms if success else None,
                    message=str(msg),
                )
            )
        except Exception as e:
            logger.warning("Error testing connection to indexer %s: %s", i_name, e)
            results.append(
                ServicePingResult(
                    id=i_id,
                    name=i_name,
                    service_type=indexer_type,
                    host_url=host_url,
                    enabled=True,
                    online=False,
                    latency_ms=None,
                    message=str(e),
                )
            )

    return results


def _ping_plex(
    plex_client: Optional[PlexClient],
    config: Config,
    db: Database,
) -> PlexStatus:
    sec = getattr(config, "plex_music_section", None)
    if not isinstance(sec, str):
        client_sec = getattr(plex_client, "music_section", None) if plex_client else None
        sec = client_sec if isinstance(client_sec, str) else "Music"
    music_sec: Optional[str] = sec if isinstance(sec, str) else "Music"

    if plex_client is None:
        return PlexStatus(
            configured=False,
            url=config.plex_url,
            music_section=music_sec,
            online=False,
            latency_ms=None,
            user_count=0,
            playlist_count=0,
            message="Plex not configured",
        )

    t0 = time.perf_counter()
    try:
        if hasattr(plex_client, "test_connection"):
            res = plex_client.test_connection()
            if isinstance(res, tuple):
                online = bool(res[0])
                msg = str(res[1])
            elif isinstance(res, bool):
                online = res
                msg = "Connected to Plex" if online else "Plex unreachable"
            elif isinstance(res, dict):
                online = bool(res.get("online", False))
                msg = str(
                    res.get("message")
                    or res.get("error")
                    or ("Connected to Plex" if online else "Plex unreachable")
                )
            else:
                online = bool(res)
                msg = "Connected to Plex" if online else "Plex unreachable"
        else:
            online = True
            msg = "Connected to Plex"
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2) if online else None
    except Exception as e:
        logger.warning("Error testing connection to Plex: %s", e)
        online = False
        latency_ms = None
        msg = str(e)

    try:
        user_count = len(db.list_users())
    except Exception:
        user_count = 0

    try:
        playlist_count = len(db.list_playlists())
    except Exception:
        playlist_count = 0

    return PlexStatus(
        configured=True,
        url=config.plex_url,
        music_section=music_sec,
        online=online,
        latency_ms=latency_ms,
        user_count=user_count,
        playlist_count=playlist_count,
        message=msg,
    )


def _get_worker_statuses() -> WorkerStatus:
    """Collects live heartbeat metrics from background workers."""
    # 1. Acquisition worker status
    try:
        from plex_playlist_sync.acquisition_worker import acquisition_worker

        acq_status = {"running": acquisition_worker.is_running()}
    except Exception as e:
        logger.warning("Failed to query acquisition worker: %s", e)
        acq_status = {"running": False, "error": str(e)}

    # 2. Lidarr trickle worker status
    try:
        from plex_playlist_sync.lidarr_queue import lidarr_worker

        lidarr_status = lidarr_worker.get_status()
    except Exception as e:
        logger.warning("Failed to query lidarr worker: %s", e)
        lidarr_status = {"running": False, "error": str(e)}

    # 3. Sync coordinator status
    try:
        from plex_playlist_sync.api.routes.sync import sync_state

        sync_status = {
            "is_syncing": sync_state.is_syncing,
            "last_run_at": sync_state.last_run_at,
            "last_run_stats": sync_state.last_run_stats,
        }
    except Exception as e:
        logger.warning("Failed to query sync state: %s", e)
        sync_status = {"is_syncing": False, "error": str(e)}

    # 4. Wanted backlog worker status
    try:
        from plex_playlist_sync.backlog_worker import backlog_worker

        backlog_status = backlog_worker.get_status()
    except Exception as e:
        logger.warning("Failed to query backlog worker: %s", e)
        backlog_status = {"running": False, "error": str(e)}

    # 5. RSS sync worker status
    try:
        from plex_playlist_sync.backlog_worker import rss_worker

        rss_status = rss_worker.get_status()
    except Exception as e:
        logger.warning("Failed to query rss worker: %s", e)
        rss_status = {"running": False, "error": str(e)}

    return WorkerStatus(
        acquisition_worker=acq_status,
        lidarr_worker=lidarr_status,
        sync_coordinator=sync_status,
        backlog_worker=backlog_status,
        rss_worker=rss_status,
    )


@router.get("/status", response_model=SystemStatusResponse, summary="Get system status and diagnostics")
@router.get("", response_model=SystemStatusResponse, include_in_schema=False)
def get_system_status(
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    admin: dict[str, Any] = Depends(require_admin),
) -> SystemStatusResponse:
    """Returns comprehensive system telemetry, storage, service connectivity, and worker heartbeats."""
    env_status = EnvironmentStatus(
        version="1.0.0",
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        role=os.getenv("ROLE", "all-in-one").lower().strip(),
        uptime_seconds=round(time.time() - _APP_START_TIME, 1),
    )

    storage = _get_disk_metrics(config, db)
    database = _get_db_metrics(db)
    plex = _ping_plex(plex_client, config, db)
    download_clients = _ping_download_clients(db)
    indexers = _ping_indexers(db)
    workers = _get_worker_statuses()

    return SystemStatusResponse(
        environment=env_status,
        storage=storage,
        database=database,
        plex=plex,
        download_clients=download_clients,
        indexers=indexers,
        workers=workers,
    )


# -----------------------------------------------------------------------------
# System Events & Logging Routes
# -----------------------------------------------------------------------------

@router.get("/events", summary="List system lifecycle events")
def get_system_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Returns paginated and filtered system lifecycle events."""
    limit = page_size
    offset = (page - 1) * limit
    items, total = db.list_events(
        limit=limit,
        offset=offset,
        event_type=event_type,
        severity=severity,
        search=search,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.delete("/events", summary="Clear system lifecycle events")
def clear_system_events(
    db: Database = Depends(get_db),
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Clears all system lifecycle events from database (admin required)."""
    db.clear_events()
    return {"success": True}


@router.get("/logs", summary="Get recent in-memory system logs")
def get_system_logs(
    level: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Returns filtered entries from the circular in-memory log buffer."""
    return log_ring_buffer.get_logs(level=level, search=search, limit=limit)


@router.get("/logs/stream", summary="Live SSE stream of system logs")
async def stream_system_logs(
    request: Request,
    token: Optional[str] = None,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
):
    """Server-Sent Events endpoint streaming real-time log records."""
    secret = get_or_create_secret_key(data_dir=config.data_dir)
    auth_token = None

    cookie_token = request.cookies.get("session_token")
    if cookie_token:
        auth_token = cookie_token
    elif token:
        auth_token = token
    else:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            auth_token = auth_header[7:].strip()

    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    session = verify_session_token(auth_token, secret)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )

    user = db.get_user(session["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    log_ring_buffer.add_listener(loop, q)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            log_ring_buffer.remove_listener(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/logs", summary="Clear in-memory log buffer")
def clear_system_logs(
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Clears all buffered log entries from memory (admin required)."""
    log_ring_buffer.clear()
    return {"success": True}


@router.get("/logs/download", summary="Download rotated disk log file")
def download_system_logs(
    config: Config = Depends(get_config),
    admin: dict[str, Any] = Depends(require_admin),
):
    """Returns active trackseerr.log file for download (admin required)."""
    log_path = get_log_file_path(config)
    if not log_path.exists():
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logs = log_ring_buffer.get_logs(limit=1000)
            with open(log_path, "w", encoding="utf-8") as f:
                for l in logs:
                    f.write(f"{l.get('timestamp')} [{l.get('level')}] {l.get('name')}: {l.get('message')}\n")
        except Exception as ex:
            logger.warning("Could not generate disk log file: %s", ex)
            raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(
        path=str(log_path),
        filename="trackseerr.log",
        media_type="text/plain",
    )
