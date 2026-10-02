"""Download Monitor & Automated Library Organizer Worker.

Periodically inspects active downloads across configured download clients,
detects completed transfers, inspects audio tags, calculates destination
paths via the token template engine, performs atomic file moves with
collision resolution into /music, and triggers Plex library update pings.
"""

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

from plex_playlist_sync.clients.acquisition import get_acquisition_driver
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.library import inspect_audio_file, resolve_collision
from plex_playlist_sync.models import DownloadStatus, RequestStatus
from plex_playlist_sync.naming import build_track_path
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff"}


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
        """Executes a single poll cycle across all active downloads."""
        if staging_dir:
            self.staging_dir = staging_dir

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

        media_settings = db.get_media_management_settings()

        for item in active_items:
            download_id = item["id"]
            client_id = item.get("client_id")
            stats["polled"] += 1

            client_config = db.get_download_client(client_id) if client_id else None
            if not client_config:
                logger.warning("Download client %s not found for active download %s", client_id, download_id)
                db.update_download_status(
                    download_id,
                    status=DownloadStatus.FAILED.value,
                    error_message=f"Client '{client_id}' not found",
                )
                stats["failed"] += 1
                continue

            try:
                driver = get_acquisition_driver(client_config)
            except Exception as e:
                logger.error("Could not instantiate driver for client %s: %s", client_id, e)
                db.update_download_status(
                    download_id,
                    status=DownloadStatus.FAILED.value,
                    error_message=f"Driver error: {str(e)}",
                )
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
                    if item.get("request_id"):
                        db.update_request_status(item["request_id"], RequestStatus.AVAILABLE.value)
                    stats["imported"] += 1
                    if plex_client:
                        try:
                            plex_client.refresh_music_library()
                        except Exception as e:
                            logger.warning("Error refreshing Plex after Lidarr import: %s", e)
                    continue

                # Locate downloaded audio files
                candidate_src = status_dict.get("source_path") or item.get("source_path")
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
                    db.update_download_status(
                        download_id,
                        status=DownloadStatus.FAILED.value,
                        error_message="No audio files found for import in download staging",
                    )
                    stats["failed"] += 1
                    continue

                # Organize and move each audio file
                imported_paths: list[str] = []
                root_folder = media_settings.get("root_folder_path") or "/music"
                root_path = Path(root_folder).resolve()

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

                    placed_path = safe_atomic_move(af, target_path)
                    imported_paths.append(str(placed_path))
                    logger.info("Successfully imported '%s' -> '%s'", af.name, placed_path)

                if not imported_paths:
                    logger.error("No audio files were successfully imported for download %s", download_id)
                    db.update_download_status(
                        download_id,
                        status=DownloadStatus.FAILED.value,
                        error_message="Destination escaped music root or placement failed",
                    )
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
