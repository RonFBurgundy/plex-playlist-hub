"""Thread-safe recursive filesystem scanner and library ingestion engine.

Scans local audio storage non-destructively, extracts Mutagen metadata,
normalizes artists, albums, tracks, and files into SQLite catalog tables,
and evaluates quality profile cutoff compliance.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from plex_playlist_sync.acquisition_coordinator import _to_quality_profile
from plex_playlist_sync.library import AUDIO_EXTENSIONS, inspect_audio_file
from plex_playlist_sync.models import (
    LibraryAlbum,
    LibraryArtist,
    LibraryFile,
    LibraryTrack,
)
from plex_playlist_sync.quality import evaluate_release, parse_release_title
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)


class LibraryScanner:
    """Thread-safe media library filesystem scanner and ingestion engine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._status: dict[str, Any] = self._default_status()

    @staticmethod
    def _default_status() -> dict[str, Any]:
        return {
            "is_scanning": False,
            "total_files_found": 0,
            "processed_files": 0,
            "artists_created": 0,
            "albums_created": 0,
            "tracks_created": 0,
            "files_indexed": 0,
            "files_pruned": 0,
            "current_file": None,
            "status": "idle",  # "idle" | "scanning" | "completed" | "cancelled" | "failed" | "skipped"
            "error": None,
            "started_at": None,
            "completed_at": None,
        }

    def is_running(self) -> bool:
        """Returns True if a library scan is currently executing."""
        with self._lock:
            return bool(self._status.get("is_scanning", False))

    def get_status(self) -> dict[str, Any]:
        """Returns a snapshot copy of the current scanner status."""
        with self._lock:
            return dict(self._status)

    def cancel_scan(self) -> dict[str, Any]:
        """Signals the active scan to stop and returns the current status."""
        with self._lock:
            self._stop_event.set()
            if not self._status.get("is_scanning", False) and self._status.get("status") == "idle":
                self._status["status"] = "cancelled"
            return dict(self._status)

    def start_scan(
        self,
        db: Database,
        root_folder: Optional[str] = None,
        prune_missing: bool = False,
        plex_client: Optional[Any] = None,
    ) -> bool:
        """Starts a background scanning daemon thread if not already running."""
        with self._lock:
            if self._status.get("is_scanning", False):
                logger.warning("LibraryScanner: Scan already running, cannot start another.")
                return False

            self._stop_event.clear()
            self._status = self._default_status()
            self._status["is_scanning"] = True
            self._status["status"] = "scanning"
            self._status["started_at"] = datetime.now(timezone.utc).isoformat()

            self._thread = threading.Thread(
                target=self._run_background_scan,
                args=(db, root_folder, prune_missing, plex_client),
                daemon=True,
                name="LibraryScannerThread",
            )
            self._thread.start()
            return True

    def _run_background_scan(
        self,
        db: Database,
        root_folder: Optional[str],
        prune_missing: bool,
        plex_client: Optional[Any],
    ) -> None:
        """Entrypoint for background scanning thread."""
        try:
            self.scan(
                db=db,
                root_folder=root_folder,
                prune_missing=prune_missing,
                plex_client=plex_client,
                _is_background=True,
            )
        except Exception as exc:
            logger.exception("LibraryScanner: Unhandled exception in background scan thread: %s", exc)
            with self._lock:
                self._status["is_scanning"] = False
                self._status["status"] = "failed"
                self._status["error"] = str(exc)
                self._status["completed_at"] = datetime.now(timezone.utc).isoformat()

    def scan(
        self,
        db: Database,
        root_folder: Optional[str] = None,
        prune_missing: bool = False,
        plex_client: Optional[Any] = None,
        _is_background: bool = False,
    ) -> dict[str, Any]:
        """Synchronously scans media root folder, indexes audio files, and optionally prunes missing files."""
        if not _is_background:
            with self._lock:
                if self._status.get("is_scanning", False):
                    logger.warning("LibraryScanner: Scan already running, returning active status.")
                    return dict(self._status)
                if self._status.get("status") in ("completed", "failed", "skipped"):
                    self._stop_event.clear()
                self._status = self._default_status()
                self._status["is_scanning"] = True
                self._status["status"] = "scanning"
                self._status["started_at"] = datetime.now(timezone.utc).isoformat()

        try:
            # Check immediate cancellation
            if self._stop_event.is_set():
                logger.info("LibraryScanner: Stop flag set before start.")
                with self._lock:
                    self._status["status"] = "cancelled"
                    self._status["is_scanning"] = False
                    self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                    return dict(self._status)

            # Step a: Check library mode safeguard
            media_settings = db.get_media_management_settings()
            if media_settings.get("library_mode") == "lidarr":
                logger.warning(
                    "LibraryScanner: library_mode is 'lidarr'. Skipping filesystem scan to prevent conflicts."
                )
                with self._lock:
                    self._status["status"] = "skipped"
                    self._status["is_scanning"] = False
                    self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                    return dict(self._status)

            # Step b: Determine and validate root folder
            root_path_str = root_folder or media_settings.get("root_folder_path") or "/music"
            root = Path(root_path_str).resolve()
            if not root.exists():
                logger.error("LibraryScanner: Root folder does not exist: %s", root)
                with self._lock:
                    self._status["status"] = "failed"
                    self._status["error"] = "Root folder does not exist"
                    self._status["is_scanning"] = False
                    self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                    return dict(self._status)

            # Step c: Collect audio files
            audio_files: list[Path] = []
            try:
                for entry in root.rglob("*"):
                    if self._stop_event.is_set():
                        break
                    try:
                        if entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS:
                            audio_files.append(entry.resolve())
                    except OSError as oe:
                        logger.warning("LibraryScanner: Cannot access entry %s: %s", entry, oe)
            except OSError as oe:
                logger.warning("LibraryScanner: Directory walk error in %s: %s", root, oe)

            audio_files.sort()
            with self._lock:
                self._status["total_files_found"] = len(audio_files)

            if self._stop_event.is_set():
                with self._lock:
                    self._status["status"] = "cancelled"
                    self._status["is_scanning"] = False
                    self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                    return dict(self._status)

            # Step d: Process audio files
            for file_path in audio_files:
                if self._stop_event.is_set():
                    logger.info("LibraryScanner: Cancellation requested during indexing.")
                    break

                with self._lock:
                    self._status["current_file"] = str(file_path)

                # Fallback path metadata
                parent = file_path.parent
                fallback_album = parent.name if parent != root else "Unknown Album"
                grandparent = parent.parent
                fallback_artist = (
                    grandparent.name
                    if (parent != root and grandparent != root and grandparent != parent)
                    else "Unknown Artist"
                )
                fallback_title = file_path.stem
                fallback_track_number = 1

                try:
                    metadata = inspect_audio_file(file_path)
                except Exception as exc:
                    logger.warning(
                        "LibraryScanner: Mutagen extraction failed for %s: %s. Using path fallbacks.",
                        file_path,
                        exc,
                    )
                    metadata = {
                        "title": fallback_title,
                        "artist": fallback_artist,
                        "album": fallback_album,
                        "track_number": fallback_track_number,
                        "disc_number": 1,
                        "codec": file_path.suffix.lstrip(".").upper() or "UNKNOWN",
                        "bitrate": None,
                        "sample_rate": None,
                        "bits_per_sample": None,
                        "duration": 0.0,
                        "quality_full": file_path.suffix.lstrip(".").upper() or "UNKNOWN",
                        "file_path": str(file_path),
                    }

                artist_name = (
                    metadata.get("artist") or metadata.get("album_artist") or ""
                ).strip() or fallback_artist
                album_title = (metadata.get("album") or "").strip() or fallback_album
                track_title = (metadata.get("title") or "").strip() or fallback_title
                track_number = metadata.get("track_number") or fallback_track_number
                disc_number = metadata.get("disc_number") or 1
                duration_seconds = metadata.get("duration")
                year = metadata.get("year")
                total_tracks = metadata.get("total_tracks")

                # Resolve/Upsert Artist
                artist_row = db.get_library_artist_by_name(artist_name)
                if not artist_row:
                    artist_id = str(uuid.uuid4())
                    artist_path = (
                        str(parent.parent)
                        if (parent != root and grandparent != root and grandparent != parent)
                        else str(parent)
                    )
                    artist_row = db.upsert_library_artist(
                        LibraryArtist(
                            id=artist_id,
                            name=artist_name,
                            path=artist_path,
                            monitored=True,
                        )
                    )
                    with self._lock:
                        self._status["artists_created"] += 1
                artist_id = str(artist_row["id"])

                # Resolve/Upsert Album
                album_row = db.get_library_album_by_title(artist_id, album_title)
                if not album_row:
                    album_id = str(uuid.uuid4())
                    album_path = str(parent)
                    album_row = db.upsert_library_album(
                        LibraryAlbum(
                            id=album_id,
                            artist_id=artist_id,
                            title=album_title,
                            year=year,
                            path=album_path,
                            total_tracks=total_tracks,
                            monitored=True,
                        )
                    )
                    with self._lock:
                        self._status["albums_created"] += 1
                album_id = str(album_row["id"])

                # Resolve/Upsert Track
                track_row = db.get_library_track_by_title(album_id, track_title, track_number)
                if not track_row:
                    track_id = str(uuid.uuid4())
                    track_row = db.upsert_library_track(
                        LibraryTrack(
                            id=track_id,
                            album_id=album_id,
                            artist_id=artist_id,
                            title=track_title,
                            track_number=int(track_number),
                            disc_number=int(disc_number),
                            duration_seconds=duration_seconds,
                            monitored=True,
                        )
                    )
                    with self._lock:
                        self._status["tracks_created"] += 1
                track_id = str(track_row["id"])

                # Quality profile & Cutoff evaluation
                cutoff_met = True
                quality_name = str(metadata.get("quality_full") or metadata.get("codec") or "Unknown")
                try:
                    qp_id = artist_row.get("quality_profile_id")
                    profile_dict = db.get_quality_profile(qp_id) if qp_id else None
                    if not profile_dict:
                        profile_dict = db.get_default_quality_profile()
                    if profile_dict:
                        qp = _to_quality_profile(profile_dict)
                        quality_input = (
                            metadata.get("quality_full")
                            or metadata.get("codec")
                            or file_path.suffix.lstrip(".").upper()
                        )
                        parsed = parse_release_title(str(quality_input))
                        if parsed.quality == "Unknown" and quality_input:
                            parsed.quality = str(quality_input)
                        file_size = file_path.stat().st_size if file_path.exists() else 0
                        eval_result = evaluate_release(parsed, qp, size_bytes=file_size)
                        cutoff_met = bool(eval_result.meets_cutoff)
                        quality_name = eval_result.parsed_quality or str(quality_input)
                except Exception as exc:
                    logger.warning(
                        "LibraryScanner: Cutoff evaluation error for %s: %s. Defaulting cutoff_met=True.",
                        file_path,
                        exc,
                    )
                    cutoff_met = True

                # Upsert File
                file_size = file_path.stat().st_size if file_path.exists() else 0
                rel_path = str(file_path.relative_to(root))
                existing_file = db.get_library_file_by_path(str(file_path))
                file_id = str(existing_file["id"]) if existing_file else str(uuid.uuid4())

                db.upsert_library_file(
                    LibraryFile(
                        id=file_id,
                        track_id=track_id,
                        file_path=str(file_path),
                        relative_path=rel_path,
                        codec=str(metadata.get("codec") or file_path.suffix.lstrip(".").upper() or "UNKNOWN"),
                        bitrate=metadata.get("bitrate"),
                        sample_rate=metadata.get("sample_rate"),
                        bits_per_sample=metadata.get("bits_per_sample"),
                        quality_name=quality_name,
                        size_bytes=file_size,
                        cutoff_met=cutoff_met,
                    )
                )
                with self._lock:
                    self._status["files_indexed"] += 1
                    self._status["processed_files"] += 1

            # Step e: Prune missing files if enabled and scan was not cancelled
            if prune_missing and not self._stop_event.is_set():
                all_files = db.list_library_files(limit=10000)
                for row in all_files:
                    if self._stop_event.is_set():
                        break
                    fpath = row.get("file_path")
                    if fpath and not Path(fpath).exists():
                        db.delete_library_file(str(row["id"]))
                        with self._lock:
                            self._status["files_pruned"] += 1

            # Step f: Notify Plex client if available and scan was not cancelled
            if plex_client is not None and not self._stop_event.is_set():
                try:
                    if hasattr(plex_client, "refresh_music_library"):
                        plex_client.refresh_music_library()
                except Exception as exc:
                    logger.warning(
                        "LibraryScanner: Error invoking plex_client.refresh_music_library(): %s",
                        exc,
                    )

            # Step g: Conclude scan
            with self._lock:
                self._status["current_file"] = None
                self._status["is_scanning"] = False
                self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                if self._stop_event.is_set():
                    self._status["status"] = "cancelled"
                else:
                    self._status["status"] = "completed"
                return dict(self._status)

        except Exception as exc:
            logger.exception("LibraryScanner: Fatal error during scan execution: %s", exc)
            with self._lock:
                self._status["status"] = "failed"
                self._status["error"] = str(exc)
                self._status["is_scanning"] = False
                self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                return dict(self._status)
        finally:
            with self._lock:
                self._status["is_scanning"] = False
                self._status["current_file"] = None
                if self._status.get("completed_at") is None:
                    self._status["completed_at"] = datetime.now(timezone.utc).isoformat()
                if self._stop_event.is_set() and self._status.get("status") not in ("failed", "skipped"):
                    self._status["status"] = "cancelled"


# Expose module singleton instance
library_scanner = LibraryScanner()

__all__ = ["LibraryScanner", "library_scanner"]
