"""Download Monitor & Automated Library Organizer Worker.

Periodically inspects active downloads across configured download clients,
detects completed transfers, inspects audio tags, calculates destination
paths via the token template engine, performs atomic file moves with
collision resolution into /music, and triggers Plex library update pings.
"""

import json
import logging
import os
import shutil
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import httpx

from plex_playlist_sync.clients.acquisition import get_acquisition_driver
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.library import (
    embed_album_artwork,
    inspect_audio_file,
    resolve_collision,
    write_audio_tags,
)
from plex_playlist_sync.models import DownloadStatus, NotificationEvent, RequestStatus
from plex_playlist_sync.naming import build_track_path
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.security import is_safe_service_url
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff"}


def _is_safe_cover_url(url: Optional[str]) -> bool:
    """Validates that a cover artwork URL is safe against SSRF attacks."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        whitelisted_domains = (
            "mzstatic.com",
            "deezer.com",
            "dzcdn.net",
            "spotify.com",
            "scdn.co",
            "last.fm",
            "musicbrainz.org",
            "discogs.com",
        )
        if any(hostname == d or hostname.endswith("." + d) for d in whitelisted_domains):
            return True
        return is_safe_service_url(url, allow_lan=False)
    except Exception:
        return False


def safe_atomic_move(source_file: Path | str, target_file: Path | str) -> Path:
    """Atomically places source_file at target_file, safely handling cross-device mounts.

    If source and destination reside on the same filesystem, os.replace is used directly.
    Across different filesystems, writes to a temporary hidden file in the destination
    folder first, then atomically replaces to ensure Plex never indexes incomplete files.
    """
    src = Path(source_file).resolve()
    dst = Path(target_file).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.replace(str(src), str(dst))
        return dst
    except OSError:
        # Cross-device link: write temporary file in destination folder, then os.replace
        tmp_dst = dst.parent / f".tmp_{dst.name}_{os.getpid()}_{time.time_ns()}"
        shutil.copy2(str(src), str(tmp_dst))
        os.replace(str(tmp_dst), str(dst))
        try:
            src.unlink(missing_ok=True)
        except OSError:
            pass
        return dst


def place_audio_file(
    source_file: Path | str, target_file: Path | str, mode: str = "move"
) -> Path:
    """Places source_file at target_file using either atomic move or hardlink.

    - mode="hardlink": Target parent directories created, calls os.link(src, dst).
      If successful, returns dst (original src preserved untouched for seeding).
      If os.link fails (e.g. cross-device EXDEV), falls back to shutil.copy2 without unlinking src.
    - mode="move": Calls safe_atomic_move(source_file, target_file) (atomic replace, unlink source).
    """
    src = Path(source_file).resolve()
    dst = Path(target_file).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if mode == "hardlink":
        try:
            os.link(str(src), str(dst))
            logger.info("Successfully hardlinked '%s' -> '%s'", src, dst)
            return dst
        except OSError as e:
            logger.warning(
                "os.link failed (%s); falling back to shutil.copy2 for '%s' -> '%s'",
                e,
                src,
                dst,
            )
            shutil.copy2(str(src), str(dst))
            return dst
    else:
        return safe_atomic_move(source_file, target_file)


def translate_remote_path(
    remote_path: Optional[str], mappings: list[dict[str, str]]
) -> Optional[str]:
    """Translates remote download client file paths to local mount paths.

    If remote_path starts with a mapping's remote_path, replaces that prefix with local_path.
    Guards against directory traversal attacks.
    """
    if remote_path is None:
        return None

    # Defense against directory traversal attempts in remote path input
    parts = remote_path.replace("\\", "/").split("/")
    if ".." in parts:
        logger.warning("Path traversal attempt rejected in remote_path: %s", remote_path)
        return None

    if not mappings:
        return remote_path

    resolved = remote_path
    for m in mappings:
        if not isinstance(m, dict):
            continue
        r = m.get("remote_path")
        l = m.get("local_path")
        if not r or not l:
            continue
        r_clean = r.rstrip("/")
        l_clean = l.rstrip("/")
        if resolved == r_clean:
            resolved = l_clean
            break
        elif resolved.startswith(r_clean + "/"):
            resolved = l_clean + resolved[len(r_clean):]
            break
        elif resolved.startswith(r_clean + "\\"):
            resolved = l_clean + "/" + resolved[len(r_clean) + 1:].replace("\\", "/")
            break

    norm = os.path.normpath(resolved)
    if ".." in norm.replace("\\", "/").split("/"):
        logger.warning("Directory traversal detected in remote path mapping: %s", resolved)
        return None

    return norm


class AcquisitionWorker:
    """Thread-safe background runner monitoring active downloads and organizing media."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running: bool = False
        self.poll_interval: float = 5.0
        self.staging_dir: str = "/downloads"

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def start(
        self,
        db: Database,
        plex_client: Optional[PlexClient] = None,
        poll_interval: float = 5.0,
        staging_dir: Optional[str] = None,
    ) -> bool:
        """Starts background download monitor worker thread."""
        with self._lock:
            if self._is_running:
                logger.warning("AcquisitionWorker is already running")
                return False

            self.poll_interval = poll_interval
            if staging_dir:
                self.staging_dir = staging_dir

            self._stop_event.clear()
            self._is_running = True

            def _worker_loop() -> None:
                logger.info("AcquisitionWorker loop started (poll interval: %.1fs)", self.poll_interval)
                while not self._stop_event.is_set():
                    try:
                        self.poll_once(db=db, plex_client=plex_client, staging_dir=self.staging_dir)
                    except Exception as e:
                        logger.error("Unexpected error in AcquisitionWorker poll cycle: %s", e)

                    # Sleep with responsive stop checking
                    slept = 0.0
                    while slept < self.poll_interval and not self._stop_event.is_set():
                        time.sleep(min(0.5, self.poll_interval - slept))
                        slept += 0.5

                with self._lock:
                    self._is_running = False
                logger.info("AcquisitionWorker loop stopped cleanly")

            self._thread = threading.Thread(target=_worker_loop, daemon=True, name="AcquisitionWorkerThread")
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        """Signals background worker to stop and waits for completion."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._is_running = False

    def _find_audio_files(self, candidate_path: Optional[str | Path], search_term: str) -> list[Path]:
        """Locates downloaded audio files from source path or staging directory."""
        found: list[Path] = []
        staging_path = Path(self.staging_dir).resolve()

        if candidate_path:
            src_path = Path(candidate_path).resolve()
            if not src_path.is_relative_to(staging_path):
                logger.warning("Rejecting source path outside staging directory: %s", candidate_path)
            else:
                if src_path.is_file() and src_path.suffix.lower() in AUDIO_EXTENSIONS:
                    return [src_path]
                elif src_path.is_dir():
                    for root, _, files in os.walk(str(src_path)):
                        for f in files:
                            f_path = (Path(root) / f).resolve()
                            if f_path.is_relative_to(staging_path) and f_path.suffix.lower() in AUDIO_EXTENSIONS:
                                found.append(f_path)
                    if found:
                        return sorted(found)

        # Fallback: scan staging directory for files matching search term
        if staging_path.exists():
            clean_term = search_term.lower()
            for root, _, files in os.walk(str(staging_path)):
                for f in files:
                    f_path = (Path(root) / f).resolve()
                    if f_path.is_relative_to(staging_path) and f_path.suffix.lower() in AUDIO_EXTENSIONS:
                        if clean_term in f.lower() or clean_term in root.lower():
                            found.append(f_path)

        return sorted(found)

    def poll_once(
        self,
        db: Database,
        plex_client: Optional[PlexClient] = None,
        staging_dir: Optional[str] = None,
    ) -> dict[str, int]:
        media_settings = db.get_media_management_settings()
        import_mode = media_settings.get("import_mode", "move")
        write_tags = bool(media_settings.get("write_audio_tags", True))
        embed_art = bool(media_settings.get("embed_artwork", True))
        save_cover = bool(media_settings.get("save_cover_art_file", True))
        if staging_dir:
            self.staging_dir = staging_dir
        else:
            self.staging_dir = media_settings.get("staging_folder_path", self.staging_dir)

        stats = {"polled": 0, "completed": 0, "failed": 0, "imported": 0}
        active_items = db.list_active_downloads(
            statuses=[
                DownloadStatus.QUEUED.value,
                DownloadStatus.DOWNLOADING.value,
                DownloadStatus.IMPORTING.value,
                DownloadStatus.COMPLETED.value,
            ]
        )

        if not active_items:
            return stats

        for item in active_items:
            download_id = item["id"]
            client_id = item.get("client_id")
            stats["polled"] += 1

            def _notify_failed(err_text: str) -> None:
                try:
                    notification_dispatcher.dispatch(
                        NotificationEvent.DOWNLOAD_FAILED,
                        data={
                            "artist": item.get("artist"),
                            "title": item.get("title"),
                            "download_id": download_id,
                            "request_id": item.get("request_id"),
                            "error_message": err_text,
                        },
                        db=db,
                    )
                except Exception as ex:
                    logger.warning("Failed to dispatch DOWNLOAD_FAILED notification: %s", ex)

            client_config = db.get_download_client(client_id) if client_id else None
            if not client_config:
                logger.warning("Download client %s not found for active download %s", client_id, download_id)
                err_msg = f"Client '{client_id}' not found"
                db.update_download_status(
                    download_id,
                    status=DownloadStatus.FAILED.value,
                    error_message=err_msg,
                )
                _notify_failed(err_msg)
                stats["failed"] += 1
                continue

            try:
                driver = get_acquisition_driver(client_config)
            except Exception as e:
                logger.error("Could not instantiate driver for client %s: %s", client_id, e)
                err_msg = f"Driver error: {str(e)}"
                db.update_download_status(
                    download_id,
                    status=DownloadStatus.FAILED.value,
                    error_message=err_msg,
                )
                _notify_failed(err_msg)
                stats["failed"] += 1
                continue

            # Poll driver status
            target_lookup = item.get("download_hash") or download_id
            try:
                status_dict = driver.get_status(target_lookup)
            except Exception as e:
                logger.warning("Exception querying driver status for %s: %s", target_lookup, e)
                continue

            cur_status = status_dict.get("status", DownloadStatus.DOWNLOADING.value).lower()
            progress = float(status_dict.get("progress") or 0.0)
            size_bytes = status_dict.get("size_bytes")
            db.update_download_progress(download_id, progress, size_bytes)

            # If failed
            if cur_status == DownloadStatus.FAILED.value:
                err_msg = status_dict.get("error_message") or "Download failed"
                db.update_download_status(download_id, status=DownloadStatus.FAILED.value, error_message=err_msg)
                _notify_failed(err_msg)
                stats["failed"] += 1
                continue

            # If completed or ready to import
            is_ready = cur_status == DownloadStatus.COMPLETED.value or item.get("status") == DownloadStatus.COMPLETED.value
            if is_ready:
                stats["completed"] += 1
                db.update_download_status(download_id, status=DownloadStatus.IMPORTING.value)

                # Special case: Lidarr performs native file organization
                driver_type = str(client_config.get("driver_type", "")).lower()
                if driver_type == "lidarr":
                    db.update_download_status(download_id, status=DownloadStatus.IMPORTED.value)
                    req_row = None
                    if item.get("request_id"):
                        db.update_request_status(item["request_id"], RequestStatus.AVAILABLE.value)
                        req_row = db.get_request(item["request_id"])
                    stats["imported"] += 1
                    try:
                        notification_dispatcher.dispatch(
                            NotificationEvent.ITEM_AVAILABLE,
                            data={
                                "artist": item.get("artist"),
                                "title": item.get("title"),
                                "album": item.get("title") if item.get("item_type") == "album" else None,
                                "request_id": item.get("request_id"),
                                "download_id": download_id,
                                "cover_url": req_row.get("cover_url") if req_row else None,
                                "username": req_row.get("username") if req_row else None,
                            },
                            db=db,
                        )
                    except Exception as ex:
                        logger.warning("Failed to dispatch ITEM_AVAILABLE notification for Lidarr import: %s", ex)

                    if plex_client:
                        try:
                            plex_client.refresh_music_library()
                        except Exception as e:
                            logger.warning("Error refreshing Plex after Lidarr import: %s", e)
                    continue

                # Locate downloaded audio files with remote path translation
                mappings: list[dict[str, str]] = []
                extra_json = client_config.get("extra_settings_json")
                if extra_json:
                    try:
                        extra_data = json.loads(extra_json) if isinstance(extra_json, str) else extra_json
                        if isinstance(extra_data, dict):
                            mappings = extra_data.get("remote_path_mappings", [])
                    except (json.JSONDecodeError, TypeError):
                        mappings = []

                raw_src = status_dict.get("source_path") or item.get("source_path")
                candidate_src = translate_remote_path(raw_src, mappings) if raw_src else None
                if candidate_src:
                    src_path = Path(candidate_src).resolve()
                    staging_path = Path(self.staging_dir).resolve()
                    if not src_path.is_relative_to(staging_path):
                        logger.warning("Rejecting source path outside staging directory: %s", candidate_src)
                        candidate_src = None

                search_term = item.get("title") or item.get("artist") or ""
                audio_files = self._find_audio_files(candidate_src, search_term)

                if not audio_files:
                    logger.warning(
                        "Download %s marked completed but no audio files found at %s or staging %s",
                        download_id,
                        candidate_src,
                        self.staging_dir,
                    )
                    err_msg = "No audio files found for import in download staging"
                    db.update_download_status(
                        download_id,
                        status=DownloadStatus.FAILED.value,
                        error_message=err_msg,
                    )
                    _notify_failed(err_msg)
                    stats["failed"] += 1
                    continue

                # Organize and move each audio file
                imported_paths: list[str] = []
                root_folder = media_settings.get("root_folder_path") or "/music"
                root_path = Path(root_folder).resolve()

                # Fetch associated request and album cover art if available
                req = db.get_request(item["request_id"]) if item.get("request_id") else None
                cover_bytes: bytes | None = None
                if req and (embed_art or save_cover):
                    cover_url = req.get("cover_url")
                    if cover_url and _is_safe_cover_url(cover_url):
                        try:
                            resp = httpx.get(cover_url, timeout=10.0, follow_redirects=True)
                            if resp.status_code == 200 and resp.content:
                                cover_bytes = resp.content
                        except httpx.HTTPError as e:
                            logger.warning("HTTP error fetching cover art from %s: %s", cover_url, e)
                        except Exception as e:
                            logger.warning("Error fetching cover art from %s: %s", cover_url, e)
                    elif cover_url:
                        logger.warning("Cover art URL rejected by SSRF protection: %s", cover_url)

                for af in audio_files:
                    try:
                        metadata = inspect_audio_file(af)
                    except Exception as e:
                        logger.warning("Mutagen inspection failed for %s: %s; using item defaults", af, e)
                        metadata = {
                            "artist": item.get("artist", "Unknown Artist"),
                            "title": item.get("title", af.stem),
                            "album": item.get("title") if item.get("item_type") == "album" else "Unknown Album",
                            "file_path": str(af),
                            "extension": af.suffix.lower(),
                            "track_number": 1,
                            "disc_number": 1,
                            "total_discs": 1,
                        }

                    # Fallbacks for empty tags
                    if not metadata.get("artist"):
                        metadata["artist"] = item.get("artist") or "Unknown Artist"
                    if not metadata.get("title"):
                        metadata["title"] = item.get("title") or af.stem

                    target_str = build_track_path(metadata, media_settings)
                    final_target = resolve_collision(target_str)
                    target_path = Path(final_target).resolve()
                    if not target_path.is_relative_to(root_path):
                        logger.error("Destination %s escapes music root %s", target_path, root_path)
                        continue

                    placed_path = place_audio_file(af, target_path, mode=import_mode)
                    imported_paths.append(str(placed_path))
                    logger.info("Successfully imported '%s' -> '%s'", af.name, placed_path)

                    # Tag writing and artwork embedding
                    tags_to_write: dict[str, Any] = {
                        "artist": (req.get("artist") if req else None) or metadata.get("artist"),
                        "album": (req.get("album") or req.get("title") if req else None) or metadata.get("album"),
                        "title": metadata.get("title") if len(audio_files) > 1 else ((req.get("title") if req else None) or metadata.get("title")),
                        "date": (req.get("release_date") if req else None) or metadata.get("year"),
                        "tracknumber": metadata.get("track_number"),
                        "totaltracks": metadata.get("total_tracks"),
                        "discnumber": metadata.get("disc_number"),
                        "totaldiscs": metadata.get("total_discs"),
                    }

                    if write_tags:
                        art_to_embed = cover_bytes if embed_art else None
                        try:
                            write_audio_tags(placed_path, tags=tags_to_write, cover_art_bytes=art_to_embed)
                        except Exception as e:
                            logger.warning("Error writing audio tags to %s: %s", placed_path, e)
                    elif embed_art and cover_bytes:
                        try:
                            embed_album_artwork(placed_path, cover_bytes)
                        except Exception as e:
                            logger.warning("Error embedding artwork into %s: %s", placed_path, e)

                    if save_cover and cover_bytes:
                        cover_file = placed_path.parent / "cover.jpg"
                        if not cover_file.exists():
                            try:
                                cover_file.write_bytes(cover_bytes)
                                logger.info("Saved album cover to %s", cover_file)
                            except OSError as e:
                                logger.warning("Failed to save cover.jpg at %s: %s", cover_file, e)

                if not imported_paths:
                    logger.error("No audio files were successfully imported for download %s", download_id)
                    err_msg = "Destination escaped music root or placement failed"
                    db.update_download_status(
                        download_id,
                        status=DownloadStatus.FAILED.value,
                        error_message=err_msg,
                    )
                    _notify_failed(err_msg)
                    stats["failed"] += 1
                    continue

                # Update database records
                target_summary = imported_paths[0] if imported_paths else None
                db.update_download_status(
                    download_id,
                    status=DownloadStatus.IMPORTED.value,
                    target_path=target_summary,
                )
                if item.get("request_id"):
                    db.update_request_status(item["request_id"], RequestStatus.AVAILABLE.value)
                stats["imported"] += 1

                try:
                    notification_dispatcher.dispatch(
                        NotificationEvent.ITEM_AVAILABLE,
                        data={
                            "artist": item.get("artist"),
                            "title": item.get("title"),
                            "album": item.get("title") if item.get("item_type") == "album" else None,
                            "request_id": item.get("request_id"),
                            "download_id": download_id,
                            "target_path": target_summary,
                            "cover_url": req.get("cover_url") if req else None,
                            "username": req.get("username") if req else None,
                        },
                        db=db,
                    )
                except Exception as ex:
                    logger.warning("Failed to dispatch ITEM_AVAILABLE notification for native import: %s", ex)

                # Trigger Plex library refresh ping
                if plex_client:
                    try:
                        plex_client.refresh_music_library()
                    except Exception as e:
                        logger.warning("Error triggering Plex library refresh: %s", e)

            else:
                # Update progress and active status
                db.update_download_status(download_id, status=cur_status)

        return stats


# Global acquisition worker instance
acquisition_worker = AcquisitionWorker()
