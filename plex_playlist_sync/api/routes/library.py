"""FastAPI router for native music library management.

Provides statistics and browsing CRUD for artists, albums, tracks, and files;
controls for filesystem scanning and Lidarr catalog migration;
interactive Manual Import scan and commit pipelines;
and Arr-grade token-template preview and batch-renaming engine.
"""

import logging
import os
from pathlib import Path
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

import httpx

from plex_playlist_sync.acquisition_coordinator import _to_quality_profile
from plex_playlist_sync.acquisition_worker import place_audio_file, safe_atomic_move
from plex_playlist_sync.api.dependencies import (
    get_config,
    get_db,
    get_lidarr_client,
    get_plex_client,
    require_admin,
    require_core_tier,
    require_user,
)
from plex_playlist_sync.clients.core_client import CoreClient
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.library_availability import get_item_availability
from plex_playlist_sync.library import (
    AUDIO_EXTENSIONS,
    inspect_audio_file,
    resolve_collision,
    write_audio_tags,
)
from plex_playlist_sync.library_scanner import library_scanner
from plex_playlist_sync.lidarr_migration import lidarr_migration_job
from plex_playlist_sync.naming import build_track_path
from plex_playlist_sync.quality import evaluate_release, parse_release_title
from plex_playlist_sync.storage import Database, clean_library_name

logger = logging.getLogger(__name__)

router = APIRouter()


# -------------------------------------------------------------------------
# Request Models
# -------------------------------------------------------------------------

class ArtistMonitoredRequest(BaseModel):
    monitored: bool
    cascade_children: bool = True


class AlbumMonitoredRequest(BaseModel):
    monitored: bool
    cascade_tracks: bool = True


class TrackMonitoredRequest(BaseModel):
    monitored: bool


class ScanRequest(BaseModel):
    root_folder: Optional[str] = None
    prune_missing: bool = False


class MigrateLidarrRequest(BaseModel):
    auto_switch_mode: bool = True


class ManualImportScanRequest(BaseModel):
    folder_path: Optional[str] = None


class ManualImportItem(BaseModel):
    source_path: Optional[str] = None
    file_path: Optional[str] = None
    artist_name: Optional[str] = None
    artist_id: Optional[str] = None
    album_title: Optional[str] = None
    album_id: Optional[str] = None
    track_title: Optional[str] = None
    track_id: Optional[str] = None
    track_number: Optional[int] = 1
    disc_number: Optional[int] = 1
    year: Optional[int] = None
    mode: str = "move"
    write_tags: bool = True


class ManualImportCommitRequest(BaseModel):
    items: list[ManualImportItem] = Field(default_factory=list)


class RenamePreviewRequest(BaseModel):
    artist_id: Optional[str] = None
    album_id: Optional[str] = None
    limit: int = 200


class RenameApplyRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------------
# Security & Path Traversal Defense
# -------------------------------------------------------------------------

def validate_media_path(path_str: str, db: Optional[Database] = None) -> Path:
    """Validates that a path is safe against directory traversal and resides in an approved directory.

    Approved bases include /music, /downloads, /data, /config, system temp directories (/tmp),
    current working directory, and paths configured in media management settings.
    """
    if not path_str or not isinstance(path_str, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path must be a non-empty string",
        )

    parts = path_str.replace("\\", "/").split("/")
    if ".." in parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal attempt detected",
        )

    resolved = Path(path_str).resolve()
    approved_bases = [
        Path("/music").resolve(),
        Path("/downloads").resolve(),
        Path("/data").resolve(),
        Path("/config").resolve(),
        Path("/tmp").resolve(),
        Path.cwd().resolve(),
    ]

    if db is not None:
        try:
            mm = db.get_media_management_settings()
            if mm.get("root_folder_path"):
                approved_bases.append(Path(mm["root_folder_path"]).resolve())
            if mm.get("staging_folder_path"):
                approved_bases.append(Path(mm["staging_folder_path"]).resolve())
        except Exception as exc:
            logger.warning("Could not query media management settings for path validation: %s", exc)

    is_approved = any(resolved == base or resolved.is_relative_to(base) for base in approved_bases)
    if not is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: path '{path_str}' is outside approved media mounts",
        )

    return resolved


# -------------------------------------------------------------------------
# 1. Library Statistics & Browsing Endpoints
# -------------------------------------------------------------------------

@router.get("/stats")
def get_library_stats(
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves aggregate statistics for the native library."""
    return db.get_library_stats()


@router.get("/artists")
def list_artists(
    monitored_only: bool = False,
    query: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(require_user),
) -> list[dict[str, Any]]:
    """Lists library artists with optional filtering, search query, and pagination, attaching album and track counts."""
    artists = db.list_library_artists(
        monitored_only=monitored_only, query=query, limit=limit, offset=offset
    )
    if not artists:
        return []

    artist_ids = [a["id"] for a in artists]
    placeholders = ",".join("?" for _ in artist_ids)
    with db._lock:
        album_cur = db.conn.execute(
            f"SELECT artist_id, COUNT(*) FROM library_albums WHERE artist_id IN ({placeholders}) GROUP BY artist_id",
            artist_ids,
        )
        album_counts = dict(album_cur.fetchall())
        track_cur = db.conn.execute(
            f"SELECT artist_id, COUNT(*) FROM library_tracks WHERE artist_id IN ({placeholders}) GROUP BY artist_id",
            artist_ids,
        )
        track_counts = dict(track_cur.fetchall())

    results: list[dict[str, Any]] = []
    for artist in artists:
        a_dict = dict(artist)
        a_dict["album_count"] = album_counts.get(artist["id"], 0)
        a_dict["track_count"] = track_counts.get(artist["id"], 0)
        results.append(a_dict)
    return results


@router.get("/artists/{artist_id}")
def get_artist(
    artist_id: str,
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves a single artist by ID, including its child albums."""
    artist = db.get_library_artist(artist_id)
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    result = dict(artist)
    result["albums"] = db.list_library_albums(artist_id=artist_id, limit=500)
    return result


@router.put("/artists/{artist_id}/monitored", dependencies=[Depends(require_core_tier)])
def set_artist_monitored(
    artist_id: str,
    body: ArtistMonitoredRequest,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Updates monitoring status for an artist, optionally cascading to albums and tracks."""
    artist = db.get_library_artist(artist_id)
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")

    db.set_artist_monitored(
        artist_id=artist_id,
        monitored=body.monitored,
        cascade_children=body.cascade_children,
    )
    updated = db.get_library_artist(artist_id)
    return updated or {}


@router.delete("/artists/{artist_id}", dependencies=[Depends(require_core_tier)])
def delete_artist(
    artist_id: str,
    delete_files: bool = Query(False),
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Deletes an artist and cascades to child albums, tracks, and files. Optionally unlinks files on disk."""
    artist = db.get_library_artist(artist_id)
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")

    if delete_files:
        tracks = db.list_library_tracks(artist_id=artist_id, limit=10000)
        for t in tracks:
            f = db.get_library_file_for_track(t["id"])
            if f and f.get("file_path"):
                try:
                    p = Path(f["file_path"])
                    if p.exists():
                        p.unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning("Failed to delete file %s from disk: %s", f.get("file_path"), exc)

    success = db.delete_library_artist(artist_id)
    return {"success": success}


@router.get("/albums")
def list_albums(
    artist_id: Optional[str] = None,
    monitored_only: bool = False,
    query: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(require_user),
) -> list[dict[str, Any]]:
    """Lists library albums with optional artist filtering, search query, and pagination, attaching artist name and track count."""
    albums = db.list_library_albums(
        artist_id=artist_id, monitored_only=monitored_only, query=query, limit=limit, offset=offset
    )
    if not albums:
        return []

    album_ids = [a["id"] for a in albums]
    placeholders = ",".join("?" for _ in album_ids)
    with db._lock:
        cur = db.conn.execute(
            f"SELECT album_id, COUNT(*) FROM library_tracks WHERE album_id IN ({placeholders}) GROUP BY album_id",
            album_ids,
        )
        track_counts = dict(cur.fetchall())

    results: list[dict[str, Any]] = []
    artist_cache: dict[str, str] = {}
    for album in albums:
        a_dict = dict(album)
        art_id = album.get("artist_id")
        if art_id not in artist_cache:
            art = db.get_library_artist(art_id) if art_id else None
            artist_cache[art_id] = art["name"] if art else "Unknown Artist"
        a_dict["artist_name"] = artist_cache[art_id]
        a_dict["track_count"] = track_counts.get(album["id"], 0)
        results.append(a_dict)
    return results


@router.get("/albums/{album_id}")
def get_album(
    album_id: str,
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves an album by ID, including its tracks and their linked library files."""
    album = db.get_library_album(album_id)
    if album is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")
    result = dict(album)
    tracks = db.list_library_tracks(album_id=album_id, limit=500)
    for t in tracks:
        file_info = db.get_library_file_for_track(t["id"])
        t["file"] = file_info
    result["tracks"] = tracks
    return result


@router.put("/albums/{album_id}/monitored", dependencies=[Depends(require_core_tier)])
def set_album_monitored(
    album_id: str,
    body: AlbumMonitoredRequest,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Updates monitoring status for an album and optionally cascades to child tracks."""
    album = db.get_library_album(album_id)
    if album is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")

    db.set_album_monitored(
        album_id=album_id,
        monitored=body.monitored,
        cascade_tracks=body.cascade_tracks,
    )
    updated = db.get_library_album(album_id)
    return updated or {}


@router.delete("/albums/{album_id}", dependencies=[Depends(require_core_tier)])
def delete_album(
    album_id: str,
    delete_files: bool = Query(False),
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Deletes an album and cascades to child tracks and files. Optionally unlinks files on disk."""
    album = db.get_library_album(album_id)
    if album is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found")

    if delete_files:
        tracks = db.list_library_tracks(album_id=album_id, limit=10000)
        for t in tracks:
            f = db.get_library_file_for_track(t["id"])
            if f and f.get("file_path"):
                try:
                    p = Path(f["file_path"])
                    if p.exists():
                        p.unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning("Failed to delete file %s from disk: %s", f.get("file_path"), exc)

    success = db.delete_library_album(album_id)
    return {"success": success}


@router.get("/tracks")
def list_tracks(
    album_id: Optional[str] = None,
    artist_id: Optional[str] = None,
    monitored_only: bool = False,
    query: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
    _user: dict[str, Any] = Depends(require_user),
) -> list[dict[str, Any]]:
    """Lists library tracks with optional filtering and joins linked library file details."""
    tracks = db.list_library_tracks(
        album_id=album_id,
        artist_id=artist_id,
        monitored_only=monitored_only,
        query=query,
        limit=limit,
        offset=offset,
    )
    artist_cache: dict[str, str] = {}
    album_cache: dict[str, str] = {}
    for t in tracks:
        art_id = t.get("artist_id")
        if art_id:
            if art_id not in artist_cache:
                art = db.get_library_artist(art_id)
                artist_cache[art_id] = art["name"] if art else "Unknown Artist"
            t["artist_name"] = artist_cache[art_id]
        else:
            t["artist_name"] = "Unknown Artist"

        alb_id = t.get("album_id")
        if alb_id:
            if alb_id not in album_cache:
                alb = db.get_library_album(alb_id)
                album_cache[alb_id] = alb["title"] if alb else "Unknown Album"
            t["album_title"] = album_cache[alb_id]
        else:
            t["album_title"] = "Unknown Album"

        t["file"] = db.get_library_file_for_track(t["id"])
    return tracks


@router.put("/tracks/{track_id}/monitored", dependencies=[Depends(require_core_tier)])
def set_track_monitored(
    track_id: str,
    body: TrackMonitoredRequest,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Updates monitoring status for a single track."""
    track = db.get_library_track(track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    db.set_track_monitored(track_id=track_id, monitored=body.monitored)
    updated = db.get_library_track(track_id)
    return updated or {}


@router.delete("/tracks/{track_id}", dependencies=[Depends(require_core_tier)])
def delete_track(
    track_id: str,
    delete_files: bool = Query(False),
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Deletes a library track and cascades to child files. Optionally unlinks files on disk."""
    track = db.get_library_track(track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    if delete_files:
        f = db.get_library_file_for_track(track_id)
        if f and f.get("file_path"):
            try:
                p = Path(f["file_path"])
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Failed to delete file %s from disk: %s", f.get("file_path"), exc)

    success = db.delete_library_track(track_id)
    return {"success": success}


@router.delete("/files/{file_id}", dependencies=[Depends(require_core_tier)])
def delete_file(
    file_id: str,
    delete_file_from_disk: bool = Query(True),
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Deletes a library file record and optionally unlinks the physical file from disk."""
    row = db.get_library_file(file_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if delete_file_from_disk and row.get("file_path"):
        try:
            p = Path(row["file_path"])
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Failed to unlink physical file %s: %s", row.get("file_path"), exc)

    success = db.delete_library_file(file_id)
    return {"success": success}


@router.get("/availability", summary="Get library availability")
def get_availability(
    artist_name: Optional[str] = Query(None),
    album_title: Optional[str] = Query(None),
    track_title: Optional[str] = Query(None),
    foreign_id: Optional[str] = Query(None),
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Resolves library presence and file availability. In gateway mode, forwards to Core."""
    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    if role == "gateway" and config.trackseerr_core_url:
        core_client = CoreClient(
            core_url=config.trackseerr_core_url,
            secret=config.internal_core_secret,
        )
        try:
            return core_client.get_availability(
                artist_name=artist_name,
                album_title=album_title,
                track_title=track_title,
                foreign_id=foreign_id,
            )
        except httpx.HTTPStatusError as exc:
            try:
                err_detail = exc.response.json().get("detail", exc.response.text)
            except Exception:
                err_detail = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=err_detail) from exc
        except (httpx.RequestError, Exception) as exc:
            logger.error("Failed to forward availability request to Core: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to communicate with TrackSeerr Core engine",
            ) from exc

    return get_item_availability(
        db,
        artist_name=artist_name,
        album_title=album_title,
        track_title=track_title,
        foreign_id=foreign_id,
    )


# -------------------------------------------------------------------------
# 2. Filesystem Scanner Controls
# -------------------------------------------------------------------------

@router.post("/scan", dependencies=[Depends(require_core_tier)])
def trigger_scan(
    body: Optional[ScanRequest] = None,
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Triggers an asynchronous background filesystem scan."""
    req = body or ScanRequest()
    if req.root_folder:
        validate_media_path(req.root_folder, db=db)

    library_scanner.start_scan(
        db=db,
        root_folder=req.root_folder,
        prune_missing=req.prune_missing,
        plex_client=plex_client,
    )
    return {"success": True, "status": library_scanner.get_status()}


@router.get("/scan/status")
def get_scan_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves current filesystem scanner status."""
    return library_scanner.get_status()


@router.post("/scan/cancel", dependencies=[Depends(require_core_tier)])
def cancel_scan(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Signals active scan to stop and returns current scanner status."""
    return library_scanner.cancel_scan()


# -------------------------------------------------------------------------
# 3. Lidarr Migration Controls
# -------------------------------------------------------------------------

@router.post("/migrate-lidarr", dependencies=[Depends(require_core_tier)])
def trigger_lidarr_migration(
    body: Optional[MigrateLidarrRequest] = None,
    db: Database = Depends(get_db),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Triggers an asynchronous background Lidarr migration job."""
    if lidarr_client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lidarr is not configured or settings are missing",
        )

    conn = lidarr_client.test_connection()
    if not conn.get("online"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lidarr is offline: {conn.get('error', 'connection failed')}",
        )

    req = body or MigrateLidarrRequest()
    success = lidarr_migration_job.start_migration(
        db=db,
        lidarr_client=lidarr_client,
        auto_switch_mode=req.auto_switch_mode,
    )
    return {"success": success, "status": lidarr_migration_job.get_status()}


@router.get("/migrate-lidarr/status")
def get_lidarr_migration_status(
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves current Lidarr migration job status."""
    return lidarr_migration_job.get_status()


@router.post("/migrate-lidarr/cancel", dependencies=[Depends(require_core_tier)])
def cancel_lidarr_migration(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Signals active Lidarr migration job to stop and returns status."""
    return lidarr_migration_job.cancel()


# -------------------------------------------------------------------------
# 4. Manual Import Pipeline
# -------------------------------------------------------------------------

@router.post("/manual-import/scan", dependencies=[Depends(require_core_tier)])
def manual_import_scan(
    body: Optional[ManualImportScanRequest] = None,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Scans a staging or download folder for audio files, inspects metadata, and calculates library match confidence."""
    req = body or ManualImportScanRequest()
    folder_path = req.folder_path
    if not folder_path:
        mm = db.get_media_management_settings()
        folder_path = mm.get("staging_folder_path") or "/downloads"

    validated_dir = validate_media_path(folder_path, db=db)
    if not validated_dir.exists() or not validated_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Directory does not exist or is not a directory: {folder_path}",
        )

    candidates: list[dict[str, Any]] = []
    for root, _, files in os.walk(str(validated_dir)):
        for f in sorted(files):
            p = Path(root) / f
            if p.suffix.lower() in AUDIO_EXTENSIONS:
                try:
                    inspected = inspect_audio_file(p)
                except Exception as exc:
                    logger.warning("Failed to inspect %s: %s", p, exc)
                    inspected = {
                        "title": p.stem,
                        "artist": None,
                        "album": None,
                        "year": None,
                        "track_number": 1,
                        "disc_number": 1,
                        "codec": p.suffix.lstrip(".").upper(),
                        "file_path": str(p),
                    }

                title = inspected.get("title")
                artist = inspected.get("artist")
                album = inspected.get("album")
                trkn = inspected.get("track_number")

                # Fuzzy/clean search against existing library catalog
                matched_artist = db.get_library_artist_by_name(artist) if artist else None
                matched_album = None
                matched_track = None
                confidence = 0.0

                if matched_artist:
                    confidence = 0.4
                    if album:
                        matched_album = db.get_library_album_by_title(matched_artist["id"], album)
                        if matched_album:
                            confidence = 0.7
                            if title:
                                matched_track = db.get_library_track_by_title(
                                    matched_album["id"], title, track_number=trkn
                                )
                                if matched_track:
                                    confidence = 1.0

                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0

                candidates.append({
                    "file_path": str(p),
                    "filename": p.name,
                    "size_bytes": size,
                    "tags": inspected,
                    "matched_artist_id": matched_artist["id"] if matched_artist else None,
                    "matched_artist_name": matched_artist["name"] if matched_artist else (artist or None),
                    "matched_album_id": matched_album["id"] if matched_album else None,
                    "matched_album_title": matched_album["title"] if matched_album else (album or None),
                    "matched_track_id": matched_track["id"] if matched_track else None,
                    "matched_track_title": matched_track["title"] if matched_track else (title or None),
                    "confidence": round(confidence, 2),
                })

    return candidates


@router.post("/manual-import/commit", dependencies=[Depends(require_core_tier)])
def manual_import_commit(
    body: ManualImportCommitRequest,
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Commits selected manual import items: resolves/creates catalog entities, moves/copies files to destination, tags them, and registers them in the library."""
    imported_count = 0
    failed_count = 0
    results: list[dict[str, Any]] = []

    media_settings = db.get_media_management_settings()
    root_folder_str = media_settings.get("root_folder_path") or "/music"
    root_dir = Path(root_folder_str).resolve()

    for item in body.items:
        source_str = item.source_path or item.file_path
        if not source_str:
            failed_count += 1
            results.append({"status": "failed", "error": "No source path provided"})
            continue

        try:
            source_path = validate_media_path(source_str, db=db)
            if not source_path.exists() or not source_path.is_file():
                failed_count += 1
                results.append({
                    "source_path": source_str,
                    "status": "failed",
                    "error": "Source file not found on disk",
                })
                continue

            try:
                inspected = inspect_audio_file(source_path)
            except Exception as exc:
                logger.warning("inspect_audio_file failed for %s, using fallback tags: %s", source_path, exc)
                inspected = {
                    "title": source_path.stem,
                    "artist": None,
                    "album": None,
                    "year": None,
                    "track_number": 1,
                    "disc_number": 1,
                    "codec": source_path.suffix.lstrip(".").upper(),
                    "file_path": str(source_path),
                }

            # 1. Resolve or Create Artist
            artist_id = item.artist_id
            artist = db.get_library_artist(artist_id) if artist_id else None
            if not artist:
                art_name = (item.artist_name or inspected.get("artist") or "Unknown Artist").strip()
                artist = db.get_library_artist_by_name(art_name)
                if not artist:
                    artist = db.upsert_library_artist({
                        "id": str(uuid.uuid4()),
                        "name": art_name,
                        "clean_name": clean_library_name(art_name),
                        "monitored": True,
                    })
            artist_id = artist["id"]

            # 2. Resolve or Create Album
            album_id = item.album_id
            album = db.get_library_album(album_id) if album_id else None
            if not album:
                alb_title = (item.album_title or inspected.get("album") or "Unknown Album").strip()
                album = db.get_library_album_by_title(artist_id, alb_title)
                if not album:
                    alb_year = item.year or inspected.get("year")
                    album = db.upsert_library_album({
                        "id": str(uuid.uuid4()),
                        "artist_id": artist_id,
                        "title": alb_title,
                        "clean_title": clean_library_name(alb_title),
                        "year": alb_year,
                        "monitored": True,
                    })
            album_id = album["id"]

            # 3. Resolve or Create Track
            track_id = item.track_id
            track = db.get_library_track(track_id) if track_id else None
            trkn = item.track_number or inspected.get("track_number") or 1
            disc = item.disc_number or inspected.get("disc_number") or 1
            if not track:
                trk_title = (item.track_title or inspected.get("title") or source_path.stem).strip()
                track = db.get_library_track_by_title(album_id, trk_title, track_number=trkn)
                if not track:
                    track = db.upsert_library_track({
                        "id": str(uuid.uuid4()),
                        "album_id": album_id,
                        "artist_id": artist_id,
                        "title": trk_title,
                        "clean_title": clean_library_name(trk_title),
                        "track_number": trkn,
                        "disc_number": disc,
                        "duration_seconds": inspected.get("duration"),
                        "monitored": True,
                    })
            track_id = track["id"]

            # 4. Resolve destination path
            meta = dict(inspected)
            meta["artist"] = artist["name"]
            meta["album_artist"] = artist["name"]
            meta["album"] = album["title"]
            meta["title"] = track["title"]
            meta["track_number"] = track["track_number"]
            meta["disc_number"] = track["disc_number"]
            if album.get("year"):
                meta["year"] = album["year"]
                meta["release_year"] = album["year"]
            meta["extension"] = source_path.suffix

            target_proposed = build_track_path(meta, media_settings)
            validate_media_path(target_proposed, db=db)
            target_dest = resolve_collision(target_proposed)

            # 5. Place file
            placed_file = place_audio_file(source_path, target_dest, mode=item.mode)

            # 6. Write audio tags if requested
            if item.write_tags:
                try:
                    write_audio_tags(placed_file, meta)
                except Exception as exc:
                    logger.warning("Error writing tags to %s: %s", placed_file, exc)

            # 7. Quality profile & Cutoff evaluation
            cutoff_met = True
            quality_name = str(meta.get("quality_full") or meta.get("codec") or "Unknown")
            try:
                qp_id = artist.get("quality_profile_id")
                profile_dict = db.get_quality_profile(qp_id) if qp_id else None
                if not profile_dict:
                    profile_dict = db.get_default_quality_profile()
                if profile_dict:
                    qp = _to_quality_profile(profile_dict)
                    quality_input = (
                        meta.get("quality_full")
                        or meta.get("codec")
                        or placed_file.suffix.lstrip(".").upper()
                    )
                    parsed = parse_release_title(str(quality_input))
                    if parsed.quality == "Unknown" and quality_input:
                        parsed.quality = str(quality_input)
                    fsize = placed_file.stat().st_size if placed_file.exists() else 0
                    eval_result = evaluate_release(parsed, qp, size_bytes=fsize)
                    cutoff_met = bool(eval_result.meets_cutoff)
                    quality_name = eval_result.parsed_quality or str(quality_input)
            except Exception as exc:
                logger.warning("Cutoff evaluation error during manual import for %s: %s", placed_file, exc)
                cutoff_met = True

            try:
                rel_path = str(placed_file.relative_to(root_dir))
            except ValueError:
                rel_path = placed_file.name

            existing_f = db.get_library_file_by_path(str(placed_file))
            file_id = str(existing_f["id"]) if existing_f else str(uuid.uuid4())
            db.upsert_library_file({
                "id": file_id,
                "track_id": track_id,
                "file_path": str(placed_file),
                "relative_path": rel_path,
                "codec": meta.get("codec") or placed_file.suffix.lstrip(".").upper(),
                "bitrate": meta.get("bitrate"),
                "sample_rate": meta.get("sample_rate"),
                "bits_per_sample": meta.get("bits_per_sample"),
                "quality_name": quality_name,
                "size_bytes": placed_file.stat().st_size if placed_file.exists() else 0,
                "cutoff_met": cutoff_met,
            })

            # Update album folder path if missing
            if not album.get("path"):
                db.upsert_library_album({
                    "id": album_id,
                    "artist_id": artist_id,
                    "title": album["title"],
                    "path": str(placed_file.parent),
                })

            imported_count += 1
            results.append({
                "source_path": source_str,
                "destination_path": str(placed_file),
                "artist_id": artist_id,
                "album_id": album_id,
                "track_id": track_id,
                "file_id": file_id,
                "status": "imported",
            })

        except Exception as exc:
            logger.exception("Failed to import %s: %s", source_str, exc)
            failed_count += 1
            results.append({
                "source_path": source_str,
                "status": "failed",
                "error": str(exc),
            })

    if plex_client and hasattr(plex_client, "refresh_music_library"):
        try:
            plex_client.refresh_music_library()
        except Exception as exc:
            logger.warning("Error invoking plex_client.refresh_music_library(): %s", exc)

    return {
        "imported_count": imported_count,
        "failed_count": failed_count,
        "results": results,
    }


# -------------------------------------------------------------------------
# 5. Preview & Batch Renamer
# -------------------------------------------------------------------------

@router.post("/rename/preview", dependencies=[Depends(require_core_tier)])
def rename_preview(
    body: Optional[RenamePreviewRequest] = None,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Previews proposed file path changes based on token naming templates and identifies files needing renaming."""
    req = body or RenamePreviewRequest()
    limit = req.limit or 200

    if req.album_id:
        tracks = db.list_library_tracks(album_id=req.album_id, limit=limit)
    elif req.artist_id:
        tracks = db.list_library_tracks(artist_id=req.artist_id, limit=limit)
    else:
        tracks = db.list_library_tracks(limit=limit)

    media_settings = db.get_media_management_settings()
    preview_diffs: list[dict[str, Any]] = []

    artist_cache: dict[str, dict[str, Any]] = {}
    album_cache: dict[str, dict[str, Any]] = {}

    for t in tracks:
        f = db.get_library_file_for_track(t["id"])
        if not f:
            continue
        current_path = f.get("file_path")
        if not current_path:
            continue

        art_id = t["artist_id"]
        if art_id not in artist_cache:
            art = db.get_library_artist(art_id)
            if art:
                artist_cache[art_id] = art
        artist = artist_cache.get(art_id)

        alb_id = t["album_id"]
        if alb_id not in album_cache:
            alb = db.get_library_album(alb_id)
            if alb:
                album_cache[alb_id] = alb
        album = album_cache.get(alb_id)

        if not artist or not album:
            continue

        meta = {
            "artist": artist["name"],
            "album_artist": artist["name"],
            "album": album["title"],
            "title": t["title"],
            "track_number": t["track_number"],
            "disc_number": t["disc_number"],
            "year": album.get("year"),
            "release_year": album.get("year"),
            "codec": f.get("codec"),
            "bitrate": f.get("bitrate"),
            "sample_rate": f.get("sample_rate"),
            "bits_per_sample": f.get("bits_per_sample"),
            "quality_full": f.get("quality_name"),
            "file_path": current_path,
            "extension": Path(current_path).suffix,
        }
        proposed_path = build_track_path(meta, media_settings)
        needs_rename = Path(current_path).resolve() != Path(proposed_path).resolve()
        preview_diffs.append({
            "file_id": f["id"],
            "track_id": t["id"],
            "current_path": current_path,
            "proposed_path": proposed_path,
            "needs_rename": needs_rename,
        })

    return preview_diffs


@router.post("/rename/apply", dependencies=[Depends(require_core_tier)])
def rename_apply(
    body: RenameApplyRequest,
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Applies batch renaming to specified library files, moving them to their template-rendered destinations and updating the catalog."""
    renamed_count = 0
    errors: list[str] = []

    media_settings = db.get_media_management_settings()
    root_folder_str = media_settings.get("root_folder_path") or "/music"
    root_dir = Path(root_folder_str).resolve()

    for fid in body.file_ids:
        f = db.get_library_file(fid)
        if not f:
            errors.append(f"Library file ID '{fid}' not found")
            continue

        current_path_str = f.get("file_path")
        if not current_path_str:
            errors.append(f"Library file '{fid}' has no recorded file path")
            continue

        try:
            current_path = validate_media_path(current_path_str, db=db)
            if not current_path.exists() or not current_path.is_file():
                errors.append(f"File '{current_path_str}' does not exist on disk")
                continue

            track = db.get_library_track(f["track_id"])
            if not track:
                errors.append(f"Track '{f['track_id']}' not found for file '{fid}'")
                continue

            album = db.get_library_album(track["album_id"])
            artist = db.get_library_artist(track["artist_id"])
            if not album or not artist:
                errors.append(f"Album or artist not found for track '{track['id']}'")
                continue

            meta = {
                "artist": artist["name"],
                "album_artist": artist["name"],
                "album": album["title"],
                "title": track["title"],
                "track_number": track["track_number"],
                "disc_number": track["disc_number"],
                "year": album.get("year"),
                "release_year": album.get("year"),
                "codec": f.get("codec"),
                "bitrate": f.get("bitrate"),
                "sample_rate": f.get("sample_rate"),
                "bits_per_sample": f.get("bits_per_sample"),
                "quality_full": f.get("quality_name"),
                "file_path": str(current_path),
                "extension": current_path.suffix,
            }
            proposed = build_track_path(meta, media_settings)
            validate_media_path(proposed, db=db)

            if current_path.resolve() == Path(proposed).resolve():
                continue  # Already matches target format

            target_path = resolve_collision(proposed)
            old_parent = current_path.parent
            new_path = safe_atomic_move(current_path, target_path)

            try:
                rel_path = str(new_path.relative_to(root_dir))
            except ValueError:
                rel_path = new_path.name

            db.upsert_library_file({
                "id": fid,
                "track_id": f["track_id"],
                "file_path": str(new_path),
                "relative_path": rel_path,
                "codec": f.get("codec"),
                "bitrate": f.get("bitrate"),
                "sample_rate": f.get("sample_rate"),
                "bits_per_sample": f.get("bits_per_sample"),
                "quality_name": f.get("quality_name"),
                "size_bytes": new_path.stat().st_size if new_path.exists() else f.get("size_bytes", 0),
                "cutoff_met": f.get("cutoff_met", True),
            })
            renamed_count += 1

            # Clean up empty parent folder if no other files remain
            try:
                if old_parent.exists() and not any(old_parent.iterdir()):
                    old_parent.rmdir()
            except OSError:
                pass

        except Exception as exc:
            logger.exception("Failed to rename file ID %s: %s", fid, exc)
            errors.append(f"Error renaming file '{fid}': {str(exc)}")

    if plex_client and hasattr(plex_client, "refresh_music_library"):
        try:
            plex_client.refresh_music_library()
        except Exception as exc:
            logger.warning("Error invoking plex_client.refresh_music_library(): %s", exc)

    return {"renamed_count": renamed_count, "errors": errors}
