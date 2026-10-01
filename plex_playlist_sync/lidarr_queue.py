"""Background trickle worker and queue manager for Lidarr onboarding.

Provides paced, rate-limited onboarding to prevent overloading Lidarr
and the MusicBrainz metadata backend.
"""

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)


class LidarrTrickleWorker:
    """Thread-safe background queue worker for trickling missing tracks to Lidarr."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._is_running: bool = False
        self._is_paused: bool = False

        # Queue tracking stats
        self._total_items: int = 0
        self._processed_items: int = 0
        self._successful_items: int = 0
        self._failed_items: int = 0
        self._current_artist: Optional[str] = None
        self._current_album: Optional[str] = None
        self._delay_seconds: float = 3.0
        self._auto_search: bool = True
        self._started_at: Optional[str] = None
        self._last_processed_at: Optional[str] = None
        self._rate_limited_until: float = 0.0
        self._message: str = "Idle"

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            cooldown_remaining = max(0, int(self._rate_limited_until - now)) if self._rate_limited_until > now else 0
            return {
                "is_running": self._is_running,
                "is_paused": self._is_paused,
                "total_items": self._total_items,
                "processed_items": self._processed_items,
                "remaining_items": max(0, self._total_items - self._processed_items),
                "successful_items": self._successful_items,
                "failed_items": self._failed_items,
                "current_artist": self._current_artist,
                "current_album": self._current_album,
                "delay_seconds": self._delay_seconds,
                "auto_search": self._auto_search,
                "started_at": self._started_at,
                "last_processed_at": self._last_processed_at,
                "is_rate_limited": cooldown_remaining > 0,
                "rate_limit_seconds_remaining": cooldown_remaining,
                "message": self._message,
            }

    def start_trickle(
        self,
        items: list[dict[str, Any]],
        client: LidarrClient,
        db: Database,
        delay_seconds: float = 3.0,
        auto_search: bool = True,
        batch_size: Optional[int] = None,
    ) -> dict[str, Any]:
        """Enqueues items and starts background trickle worker thread."""
        with self._lock:
            if self._is_running:
                return {
                    "status": "already_running",
                    "message": "Trickle worker is already running",
                    "queue": self.get_status(),
                }

            if batch_size and batch_size > 0:
                items = items[:batch_size]

            if not items:
                return {
                    "status": "empty",
                    "message": "No items to queue",
                    "queued_count": 0,
                }

            self._stop_event.clear()
            self._pause_event.clear()
            self._is_running = True
            self._is_paused = False
            self._total_items = len(items)
            self._processed_items = 0
            self._successful_items = 0
            self._failed_items = 0
            self._current_artist = None
            self._current_album = None
            self._delay_seconds = max(0.5, float(delay_seconds))
            self._auto_search = bool(auto_search)
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._last_processed_at = None
            self._rate_limited_until = 0.0
            self._message = f"Enqueued {len(items)} tracks. Starting artist-first trickle..."

            # Group tracks by artist to consolidate API queries
            artist_groups: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                artist_key = (item.get("artist") or "").strip().lower()
                if not artist_key:
                    continue
                if artist_key not in artist_groups:
                    artist_groups[artist_key] = []
                artist_groups[artist_key].append(item)

            self._thread = threading.Thread(
                target=self._worker_loop,
                args=(artist_groups, client, db),
                name="LidarrTrickleWorkerThread",
                daemon=True,
            )
            self._thread.start()

            return {
                "status": "started",
                "message": f"Started Lidarr trickle worker for {len(items)} tracks ({len(artist_groups)} unique artists)",
                "queued_count": len(items),
                "artist_count": len(artist_groups),
                "delay_seconds": self._delay_seconds,
                "auto_search": self._auto_search,
            }

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if not self._is_running:
                return {"status": "not_running", "message": "Worker is not currently active"}
            self._is_paused = True
            self._pause_event.set()
            self._message = "Paused"
            logger.info("Lidarr trickle worker paused by user")
            return {"status": "paused", "message": "Worker paused"}

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if not self._is_running:
                return {"status": "not_running", "message": "Worker is not currently active"}
            self._is_paused = False
            self._pause_event.clear()
            self._message = "Resumed"
            logger.info("Lidarr trickle worker resumed by user")
            return {"status": "resumed", "message": "Worker resumed"}

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            if not self._is_running:
                return {"status": "not_running", "message": "Worker is not currently active"}
            self._stop_event.set()
            self._is_paused = False
            self._pause_event.clear()
            self._message = "Canceled by user"
            logger.info("Lidarr trickle worker cancellation requested")
            return {"status": "canceling", "message": "Worker is stopping"}

    def _worker_loop(
        self,
        artist_groups: dict[str, list[dict[str, Any]]],
        client: LidarrClient,
        db: Database,
    ) -> None:
        logger.info(
            "Lidarr trickle worker started for %d artists (pacing: %.1fs, auto_search=%s)",
            len(artist_groups),
            self._delay_seconds,
            self._auto_search,
        )

        try:
            for artist_key, group in artist_groups.items():
                if self._stop_event.is_set():
                    logger.info("Lidarr trickle worker received stop signal")
                    break

                # Handle pause
                while self._is_paused and not self._stop_event.is_set():
                    time.sleep(0.5)

                if self._stop_event.is_set():
                    break

                # Handle rate-limit cooldown
                now = time.time()
                if self._rate_limited_until > now:
                    wait_time = self._rate_limited_until - now
                    logger.warning("Lidarr trickle cooling down for %.1fs due to rate limits...", wait_time)
                    with self._lock:
                        self._message = f"Rate limited: cooling down for {int(wait_time)}s"
                    while time.time() < self._rate_limited_until and not self._stop_event.is_set():
                        time.sleep(1.0)
                    if self._stop_event.is_set():
                        break

                first_item = group[0]
                artist_display = first_item.get("artist", "").strip()
                albums = list(dict.fromkeys(
                    (it.get("album") or "").strip()
                    for it in group
                    if (it.get("album") or "").strip()
                ))

                with self._lock:
                    self._current_artist = artist_display
                    self._current_album = albums[0] if albums else None
                    self._message = f"Processing artist: {artist_display} ({len(group)} track(s))"

                # Attempt add and monitor with Lidarr
                res = client.add_artist_and_albums(
                    artist_name=artist_display,
                    album_names=albums,
                    auto_search=self._auto_search,
                    monitor_mode="specific",
                )

                # Check if rate-limited
                if res.get("status") == "rate_limited":
                    retry_after = res.get("retry_after", 60)
                    logger.warning(
                        "Rate limited by Lidarr/MusicBrainz for artist '%s'. Pausing for %ds",
                        artist_display,
                        retry_after,
                    )
                    with self._lock:
                        self._rate_limited_until = time.time() + retry_after
                        self._message = f"Rate limited on '{artist_display}' - cooling down for {retry_after}s"

                    # Sleep through cooldown
                    while time.time() < self._rate_limited_until and not self._stop_event.is_set():
                        time.sleep(1.0)

                    if self._stop_event.is_set():
                        break

                    # Retry once after cooldown
                    res = client.add_artist_and_albums(
                        artist_name=artist_display,
                        album_names=albums,
                        auto_search=self._auto_search,
                        monitor_mode="specific",
                    )

                # Update database statuses for tracks in this group
                track_ids = [it.get("id") for it in group if it.get("id")]
                if res.get("status") == "success":
                    db.update_missing_tracks_lidarr_status_bulk(track_ids, "monitored")
                    with self._lock:
                        self._successful_items += len(group)
                    logger.info("Monitored %d tracks for artist '%s' in Lidarr", len(group), artist_display)
                elif res.get("status") == "not_found":
                    db.update_missing_tracks_lidarr_status_bulk(track_ids, "not_found")
                    with self._lock:
                        self._failed_items += len(group)
                    logger.warning("Artist '%s' not found in Lidarr/MusicBrainz", artist_display)
                else:
                    db.update_missing_tracks_lidarr_status_bulk(track_ids, "error")
                    with self._lock:
                        self._failed_items += len(group)
                    logger.error("Error queueing artist '%s': %s", artist_display, res.get("message"))

                with self._lock:
                    self._processed_items += len(group)
                    self._last_processed_at = datetime.now(timezone.utc).isoformat()

                # Pacing delay with gentle jitter to prevent lockstep API hammering
                jitter = random.uniform(0.1, 0.4)
                sleep_duration = self._delay_seconds + jitter
                time.sleep(sleep_duration)

        except Exception as e:
            logger.exception("Unexpected error in Lidarr trickle worker loop: %s", e)
            with self._lock:
                self._message = f"Error: {e}"
        finally:
            with self._lock:
                self._is_running = False
                self._is_paused = False
                self._current_artist = None
                self._current_album = None
                if self._stop_event.is_set():
                    self._message = f"Canceled ({self._processed_items}/{self._total_items} processed)"
                else:
                    self._message = f"Completed ({self._successful_items} monitored, {self._failed_items} failed/missing)"
            logger.info("Lidarr trickle worker finished. %s", self._message)


# Global singleton worker instance
lidarr_worker = LidarrTrickleWorker()
