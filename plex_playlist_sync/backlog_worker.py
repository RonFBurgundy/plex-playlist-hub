"""Autonomous Wanted Backlog Search & Indexer RSS Sync Workers.

- WantedBacklogWorker: Periodically sweeps unfulfilled requests and missing playlist
  tracks against all enabled indexers with pacing delays to protect API rate limits.
- RSSSyncWorker: Periodically polls indexer recent release feeds (RSS/Torznab) and
  snatches releases that fulfill monitored requests.
"""

from difflib import SequenceMatcher
import logging
import threading
import time
from typing import Any, Optional
import uuid

from plex_playlist_sync.acquisition_coordinator import (
    acquisition_coordinator,
    _to_quality_profile,
)
from plex_playlist_sync.clients.acquisition import (
    get_acquisition_driver,
    get_indexer_driver,
)
from plex_playlist_sync.models import (
    AcquisitionSearchResult,
    ActiveDownload,
    DownloadStatus,
    NotificationEvent,
    RequestStatus,
)
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.quality import evaluate_release, parse_release_title
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)


def _matches_request(candidate: AcquisitionSearchResult, req: dict[str, Any]) -> bool:
    """Evaluates whether an indexer release matches a requested artist and title/album."""
    cand_raw = (candidate.title or "").lower()
    cand_artist = (candidate.artist or "").lower().strip()
    cand_album = (candidate.album or "").lower().strip()

    req_artist = (req.get("artist") or "").lower().strip()
    req_title = (req.get("title") or "").lower().strip()
    req_album = (req.get("album") or "").lower().strip()

    if not req_artist or not (req_title or req_album):
        return False

    # 1. Direct substring checks against raw candidate release title
    artist_match_raw = req_artist in cand_raw
    title_match_raw = (req_title in cand_raw) or (bool(req_album) and req_album in cand_raw)

    if artist_match_raw and title_match_raw:
        return True

    # 2. Parsed title matching and fuzzy matching via SequenceMatcher
    parsed = parse_release_title(candidate.title)
    p_artist = (parsed.artist or cand_artist).lower().strip()
    p_album = (parsed.album or cand_album).lower().strip()
    p_title = (parsed.title or candidate.title).lower().strip()

    artist_ok = False
    if p_artist and req_artist:
        if req_artist in p_artist or p_artist in req_artist:
            artist_ok = True
        elif SequenceMatcher(None, p_artist, req_artist).ratio() >= 0.8:
            artist_ok = True
    elif artist_match_raw:
        artist_ok = True

    if not artist_ok:
        return False

    title_ok = False
    for cand_text in (p_album, p_title, cand_album):
        if not cand_text:
            continue
        if req_title and (req_title in cand_text or cand_text in req_title):
            title_ok = True
            break
        if req_album and (req_album in cand_text or cand_text in req_album):
            title_ok = True
            break
        if req_title and SequenceMatcher(None, cand_text, req_title).ratio() >= 0.8:
            title_ok = True
            break
        if req_album and SequenceMatcher(None, cand_text, req_album).ratio() >= 0.8:
            title_ok = True
            break

    return artist_ok and (title_ok or title_match_raw)


class WantedBacklogWorker:
    """Autonomous worker periodically re-searching unfulfilled requests and missing tracks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running: bool = False
        self.interval_seconds: int = 3600
        self.pace_delay: float = 2.5
        self.last_run_at: Optional[str] = None
        self.items_checked: int = 0
        self.items_grabbed: int = 0
        self.errors: int = 0

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._is_running,
                "interval_seconds": self.interval_seconds,
                "pace_delay": self.pace_delay,
                "last_run_at": self.last_run_at,
                "items_checked": self.items_checked,
                "items_grabbed": self.items_grabbed,
                "errors": self.errors,
            }

    def start(
        self,
        db: Database,
        interval_seconds: int = 3600,
        pace_delay: float = 2.5,
    ) -> bool:
        """Starts daemon thread executing periodic backlog sweeps."""
        with self._lock:
            if self._is_running:
                logger.warning("WantedBacklogWorker is already running")
                return False

            self.interval_seconds = interval_seconds
            self.pace_delay = pace_delay
            self._stop_event.clear()
            self._is_running = True

            def _worker_loop() -> None:
                logger.info(
                    "WantedBacklogWorker loop started (interval: %ds, pace: %.1fs)",
                    self.interval_seconds,
                    self.pace_delay,
                )
                while not self._stop_event.is_set():
                    try:
                        self.poll_once(db=db)
                    except Exception as e:
                        logger.exception("Unexpected error in WantedBacklogWorker poll cycle: %s", e)
                        with self._lock:
                            self.errors += 1

                    # Responsive sleep
                    slept = 0.0
                    while slept < float(self.interval_seconds) and not self._stop_event.is_set():
                        time.sleep(min(1.0, float(self.interval_seconds) - slept))
                        slept += 1.0

                with self._lock:
                    self._is_running = False
                logger.info("WantedBacklogWorker loop stopped cleanly")

            self._thread = threading.Thread(
                target=_worker_loop, daemon=True, name="WantedBacklogWorkerThread"
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        """Signals worker to stop and waits for completion."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._is_running = False

    def poll_once(self, db: Database) -> dict[str, int]:
        """Executes a single sweep over unfulfilled requests and missing tracks."""
        with self._lock:
            self.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        items_checked = 0
        items_grabbed = 0
        errors_count = 0

        # 1. Query active downloads to avoid duplicate searches
        try:
            active_dls = db.list_active_downloads(statuses=["queued", "downloading", "importing"])
        except Exception as e:
            logger.error("WantedBacklogWorker error querying active downloads: %s", e)
            active_dls = []
            errors_count += 1

        active_req_ids = {d["request_id"] for d in active_dls if d.get("request_id")}
        active_artist_titles = {
            ((d.get("artist") or "").strip().lower(), (d.get("title") or "").strip().lower())
            for d in active_dls
        }

        # 2. Query unfulfilled requests: status in ('processing', 'pending')
        try:
            requests = db.list_requests()
        except Exception as e:
            logger.error("WantedBacklogWorker error querying requests: %s", e)
            requests = []
            errors_count += 1

        unfulfilled_requests = [
            r
            for r in requests
            if r.get("status") in ("processing", "pending")
            and r.get("id") not in active_req_ids
            and (
                (r.get("artist") or "").strip().lower(),
                (r.get("title") or "").strip().lower(),
            )
            not in active_artist_titles
        ]

        # 3. Query unfulfilled missing tracks: lidarr_status != 'monitored'
        try:
            missing_tracks = db.get_missing_tracks()
        except Exception as e:
            logger.error("WantedBacklogWorker error querying missing tracks: %s", e)
            missing_tracks = []
            errors_count += 1

        unfulfilled_missing = [
            t
            for t in missing_tracks
            if t.get("lidarr_status") != "monitored"
            and (
                (t.get("artist") or "").strip().lower(),
                (t.get("title") or "").strip().lower(),
            )
            not in active_artist_titles
        ]

        # Items to search: (artist, title, album, item_type, request_id, missing_track_id)
        items_to_search: list[tuple[str, str, Optional[str], str, Optional[str], Optional[int]]] = []
        for r in unfulfilled_requests:
            items_to_search.append(
                (
                    r.get("artist", "").strip(),
                    r.get("title", "").strip(),
                    r.get("album", "").strip() if r.get("album") else None,
                    r.get("item_type", "track"),
                    r.get("id"),
                    None,
                )
            )

        for t in unfulfilled_missing:
            items_to_search.append(
                (
                    t.get("artist", "").strip(),
                    t.get("title", "").strip(),
                    t.get("album", "").strip() if t.get("album") else None,
                    "track",
                    None,
                    int(t["id"]),
                )
            )

        for artist, title, album, item_type, req_id, missing_id in items_to_search:
            if self._stop_event.is_set():
                logger.info("WantedBacklogWorker sweep interrupted by stop event")
                break

            if not artist or not title:
                continue

            items_checked += 1
            try:
                res = acquisition_coordinator.search_and_grab(
                    artist=artist,
                    title=title,
                    album=album,
                    item_type=item_type,
                    request_id=req_id,
                    db=db,
                )
                if res.get("success"):
                    items_grabbed += 1
                    logger.info(
                        "WantedBacklogWorker grabbed release for '%s - %s' (request_id=%s, missing_id=%s)",
                        artist,
                        title,
                        req_id,
                        missing_id,
                    )
                    if req_id:
                        db.update_request_status(req_id, RequestStatus.PROCESSING)
                    if missing_id:
                        db.update_missing_track_lidarr_status(missing_id, "grabbed")
            except Exception as e:
                logger.error("Error during search_and_grab for '%s - %s': %s", artist, title, e)
                errors_count += 1

            # Pacing delay between calls
            if self.pace_delay > 0 and not self._stop_event.is_set():
                slept = 0.0
                while slept < self.pace_delay and not self._stop_event.is_set():
                    time.sleep(min(0.2, self.pace_delay - slept))
                    slept += 0.2

        with self._lock:
            self.items_checked += items_checked
            self.items_grabbed += items_grabbed
            self.errors += errors_count

        return {
            "items_checked": items_checked,
            "items_grabbed": items_grabbed,
            "errors": errors_count,
        }


class RSSSyncWorker:
    """Autonomous worker periodically polling indexer recent release feeds."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running: bool = False
        self.interval_seconds: int = 900
        self.last_run_at: Optional[str] = None
        self.releases_scanned: int = 0
        self.grabs_triggered: int = 0
        self.errors: int = 0

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._is_running,
                "interval_seconds": self.interval_seconds,
                "last_run_at": self.last_run_at,
                "releases_scanned": self.releases_scanned,
                "grabs_triggered": self.grabs_triggered,
                "errors": self.errors,
            }

    def start(self, db: Database, interval_seconds: int = 900) -> bool:
        """Starts daemon thread executing periodic RSS polling."""
        with self._lock:
            if self._is_running:
                logger.warning("RSSSyncWorker is already running")
                return False

            self.interval_seconds = interval_seconds
            self._stop_event.clear()
            self._is_running = True

            def _worker_loop() -> None:
                logger.info("RSSSyncWorker loop started (interval: %ds)", self.interval_seconds)
                while not self._stop_event.is_set():
                    try:
                        self.poll_once(db=db)
                    except Exception as e:
                        logger.exception("Unexpected error in RSSSyncWorker poll cycle: %s", e)
                        with self._lock:
                            self.errors += 1

                    # Responsive sleep
                    slept = 0.0
                    while slept < float(self.interval_seconds) and not self._stop_event.is_set():
                        time.sleep(min(1.0, float(self.interval_seconds) - slept))
                        slept += 1.0

                with self._lock:
                    self._is_running = False
                logger.info("RSSSyncWorker loop stopped cleanly")

            self._thread = threading.Thread(
                target=_worker_loop, daemon=True, name="RSSSyncWorkerThread"
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        """Signals worker to stop and waits for completion."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._is_running = False

    def poll_once(self, db: Database) -> dict[str, int]:
        """Polls indexer recent feeds and triggers grabs for matching requests."""
        with self._lock:
            self.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        releases_scanned = 0
        grabs_triggered = 0
        errors_count = 0

        # 1. Retrieve enabled indexers
        try:
            indexers = db.list_indexers(enabled_only=True)
        except Exception as e:
            logger.error("RSSSyncWorker error listing enabled indexers: %s", e)
            indexers = []
            errors_count += 1

        # 2. Gather wanted requests without active transfers
        try:
            active_dls = db.list_active_downloads(statuses=["queued", "downloading", "importing"])
        except Exception as e:
            logger.error("RSSSyncWorker error querying active downloads: %s", e)
            active_dls = []
            errors_count += 1

        active_req_ids = {d["request_id"] for d in active_dls if d.get("request_id")}
        try:
            all_requests = db.list_requests()
        except Exception as e:
            logger.error("RSSSyncWorker error querying requests: %s", e)
            all_requests = []
            errors_count += 1

        wanted_requests = [
            r
            for r in all_requests
            if r.get("status") in ("processing", "pending")
            and r.get("id") not in active_req_ids
        ]

        if not indexers or not wanted_requests:
            with self._lock:
                self.releases_scanned += releases_scanned
                self.grabs_triggered += grabs_triggered
                self.errors += errors_count
            return {
                "releases_scanned": releases_scanned,
                "grabs_triggered": grabs_triggered,
                "errors": errors_count,
            }

        # 3. Retrieve default quality profile
        try:
            profile_dict = db.get_default_quality_profile()
            profile = _to_quality_profile(profile_dict)
        except Exception as e:
            logger.warning("RSSSyncWorker failed to load default quality profile: %s", e)
            profile = None

        # 4. Iterate over indexers and recent releases
        for idx_cfg in indexers:
            if self._stop_event.is_set():
                break

            try:
                driver = get_indexer_driver(idx_cfg)
                if hasattr(driver, "fetch_recent"):
                    recent_releases = driver.fetch_recent(limit=100)
                else:
                    logger.debug("Indexer driver '%s' does not implement fetch_recent", idx_cfg.get("name"))
                    continue
            except Exception as e:
                logger.warning("Error fetching recent releases from indexer '%s': %s", idx_cfg.get("name"), e)
                errors_count += 1
                continue

            for candidate in recent_releases:
                if self._stop_event.is_set():
                    break

                releases_scanned += 1

                # Check if release matches any wanted request
                matched_req = None
                for req in wanted_requests:
                    if req["id"] in active_req_ids:
                        continue
                    if _matches_request(candidate, req):
                        matched_req = req
                        break

                if not matched_req:
                    continue

                # Evaluate candidate against quality profile
                eval_res = None
                if profile:
                    parsed = parse_release_title(candidate.title)
                    eval_res = evaluate_release(
                        release=parsed,
                        profile=profile,
                        size_bytes=candidate.size_bytes if candidate.size_bytes > 0 else None,
                    )
                    if not eval_res.is_acceptable:
                        logger.debug(
                            "RSS candidate '%s' rejected by profile for request %s (%s)",
                            candidate.title,
                            matched_req["id"],
                            eval_res.rejection_reasons,
                        )
                        continue

                # Find download client for protocol
                client = acquisition_coordinator.find_client_for_protocol(
                    protocol=candidate.protocol, db=db
                )
                if not client:
                    logger.warning(
                        "RSS matched '%s' for request %s but no client available for protocol %s",
                        candidate.title,
                        matched_req["id"],
                        candidate.protocol,
                    )
                    continue

                # Dispatch download to client
                try:
                    client_driver = get_acquisition_driver(client)
                    download_hash = client_driver.download(candidate)
                except Exception as e:
                    logger.error(
                        "Dispatch download failed on client '%s' for '%s': %s",
                        client.get("name"),
                        candidate.title,
                        e,
                    )
                    errors_count += 1
                    continue

                # Record active download in database
                download_id = f"dl-{uuid.uuid4().hex[:12]}"
                active_dl = ActiveDownload(
                    id=download_id,
                    request_id=matched_req["id"],
                    client_id=str(client["id"]),
                    download_hash=download_hash,
                    title=candidate.title,
                    artist=matched_req.get("artist", candidate.artist),
                    item_type=matched_req.get("item_type", "track"),
                    status=DownloadStatus.QUEUED.value,
                    progress=0.0,
                    size_bytes=candidate.size_bytes,
                    source_path=None,
                    target_path=None,
                )
                try:
                    db.create_active_download(active_dl)
                    db.update_request_status(matched_req["id"], RequestStatus.PROCESSING)
                    active_req_ids.add(matched_req["id"])
                    grabs_triggered += 1
                    try:
                        notification_dispatcher.dispatch(
                            NotificationEvent.DOWNLOAD_STARTED,
                            data={
                                "artist": active_dl.artist,
                                "title": active_dl.title,
                                "release": candidate.title,
                                "client": client.get("name"),
                                "request_id": matched_req["id"],
                                "download_id": download_id,
                                "size_bytes": candidate.size_bytes,
                            },
                            db=db,
                        )
                    except Exception as ex:
                        logger.warning("Failed to dispatch RSS DOWNLOAD_STARTED notification: %s", ex)

                    logger.info(
                        "RSSSyncWorker grabbed '%s' for request %s via %s (score=%s)",
                        candidate.title,
                        matched_req["id"],
                        client.get("name"),
                        eval_res.score if eval_res else "N/A",
                    )
                except Exception as e:
                    logger.error("Error creating active download for '%s': %s", candidate.title, e)
                    errors_count += 1

        with self._lock:
            self.releases_scanned += releases_scanned
            self.grabs_triggered += grabs_triggered
            self.errors += errors_count

        return {
            "releases_scanned": releases_scanned,
            "grabs_triggered": grabs_triggered,
            "errors": errors_count,
        }


# Singletons
backlog_worker = WantedBacklogWorker()
rss_worker = RSSSyncWorker()

__all__ = [
    "WantedBacklogWorker",
    "RSSSyncWorker",
    "backlog_worker",
    "rss_worker",
    "_matches_request",
]
