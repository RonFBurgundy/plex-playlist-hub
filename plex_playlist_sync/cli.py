import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from typing import Optional

import uvicorn

from .api.app import create_app
from .api.routes.sync import sync_state
from .clients.deezer import DeezerClient
from .clients.plex import PlexClient
from .clients.spotify import SpotifyClient
from .clients.spotify_scraper import SpotifyWebScraper
from .config import Config
from .security import safe_data_path
from .storage import Database
from .sync import SyncCoordinator

logger = logging.getLogger("plex_playlist_sync")
_shutdown_requested = False


def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Received termination signal (%d). Shutting down cleanly...", signum)
    _shutdown_requested = True


def setup_logging(level_name: str) -> None:
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        stream=sys.stdout,
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    config = Config.from_env()
    setup_logging(config.log_level)

    logger.info("Initializing Plex Playlist Hub v1.0.0")

    if not config.plex_url or not config.plex_token:
        logger.error("Missing mandatory environment variables: PLEX_URL and PLEX_TOKEN must be specified.")
        return 1

    plex_client = None
    try:
        plex_client = PlexClient(
            base_url=config.plex_url,
            token=config.plex_token,
            verify_ssl=config.plex_verify_ssl,
        )
    except Exception as e:
        if config.run_once or config.headless:
            logger.error("Failed to connect to Plex Media Server: %s", e)
            return 1
        logger.warning(
            "Could not connect to Plex Server at %s on startup: %s. "
            "Starting Web Server; connection will be retried during sync.",
            config.plex_url,
            e,
        )

    spotify_client = None
    if config.has_spotify:
        try:
            spotify_client = SpotifyClient(
                client_id=config.spotify_client_id,  # type: ignore
                client_secret=config.spotify_client_secret,  # type: ignore
            )
        except Exception as e:
            logger.error("Failed to initialize Spotify client: %s. Falling back to web scraper.", e)
            spotify_client = SpotifyWebScraper()
    else:
        logger.info("No Spotify API credentials configured; activating keyless SpotifyWebScraper")
        spotify_client = SpotifyWebScraper()

    deezer_client = None
    if config.has_deezer:
        try:
            deezer_client = DeezerClient()
        except Exception as e:
            logger.error("Failed to initialize Deezer client: %s. Skipping Deezer sync.", e)

    coordinator = SyncCoordinator(
        config=config,
        plex_client=plex_client,
        spotify_client=spotify_client,
        deezer_client=deezer_client,
    )

    # 1. Run-once / CLI mode
    if config.run_once:
        logger.info("RUN_ONCE enabled; running single sync cycle and exiting.")
        coordinator.run_sync_cycle()
        logger.info("Plex Playlist Hub run-once completed cleanly.")
        return 0

    # 2. Headless mode (no web UI)
    if config.headless:
        logger.info("Running in HEADLESS loop mode.")
        while not _shutdown_requested:
            try:
                coordinator.run_sync_cycle()
            except Exception as e:
                logger.exception("Unexpected error occurred during sync cycle: %s", e)
            slept = 0
            while slept < config.wait_seconds and not _shutdown_requested:
                time.sleep(min(1, config.wait_seconds - slept))
                slept += 1
        logger.info("Plex Playlist Hub terminated cleanly.")
        return 0

    # 3. Web UI & REST Server Mode (Default)
    logger.info("Starting Plex Playlist Hub Web Server on %s:%d", config.host, config.port)
    db_path = str(safe_data_path("sync_db.sqlite", base_dir=config.data_dir))
    try:
        db = Database(db_path)
    except (PermissionError, sqlite3.OperationalError) as e:
        logger.critical(
            "Failed to initialize SQLite database at '%s': %s. "
            "Please verify file and directory permissions on '%s' (e.g. Unraid PUID/PGID).",
            db_path,
            e,
            config.data_dir,
        )
        return 1

    # Auto-discover Plex Home users and populate database
    if plex_client is not None:
        try:
            home_users = plex_client.get_home_users()
            for u in home_users:
                uname = u.get("username") or u.get("name") or "Unknown"
                admin_flag = bool(u.get("is_admin", u.get("admin", False)))
                db.upsert_user(
                    user_id=str(u["id"]),
                    username=str(uname),
                    email=u.get("email"),
                    is_admin=admin_flag,
                )
            logger.info("Successfully discovered %d Plex Home users", len(home_users))
        except Exception as e:
            logger.warning("Could not auto-discover Plex Home users on startup: %s", e)

    # Sync legacy config playlist IDs to DB if any
    for sp_id in config.spotify_playlist_ids:
        if not db.get_playlist(sp_id):
            db.upsert_playlist(sp_id, f"Spotify Playlist {sp_id}", service="spotify")
    for dz_id in config.deezer_playlist_ids:
        if not db.get_playlist(dz_id):
            db.upsert_playlist(dz_id, f"Deezer Playlist {dz_id}", service="deezer")

    # Start periodic background sync worker thread if wait_seconds > 0
    if config.wait_seconds > 0:
        def background_sync_worker():
            logger.info("Background sync scheduler started (interval: %d seconds)", config.wait_seconds)
            while not _shutdown_requested:
                slept = 0
                while slept < config.wait_seconds and not _shutdown_requested:
                    time.sleep(min(1, config.wait_seconds - slept))
                    slept += 1
                if _shutdown_requested:
                    break
                try:
                    logger.info("Triggering scheduled background synchronization...")
                    sync_state.execute_sync(
                        db=db,
                        config=config,
                        plex_client=plex_client,
                        spotify_client=spotify_client,
                        deezer_client=deezer_client,
                    )
                except Exception as e:
                    logger.exception("Error in scheduled background sync: %s", e)

        bg_thread = threading.Thread(
            target=background_sync_worker, daemon=True, name="ScheduledSyncWorker"
        )
        bg_thread.start()

    # Start periodic Lidarr auto-trickle worker thread if configured
    if config.has_lidarr and config.lidarr_auto_trickle:
        from plex_playlist_sync.clients.lidarr import LidarrClient
        from plex_playlist_sync.lidarr_queue import lidarr_worker

        def background_lidarr_trickle_worker():
            interval_sec = max(60, config.lidarr_auto_trickle_interval_minutes * 60)
            logger.info(
                "Lidarr auto-trickle scheduler started (interval: %d min, batch: %d, pacing: %.1fs)",
                config.lidarr_auto_trickle_interval_minutes,
                config.lidarr_trickle_batch_size,
                config.lidarr_trickle_rate_seconds,
            )
            lidarr_cli = LidarrClient(
                base_url=config.lidarr_url,
                api_key=config.lidarr_api_key,
                verify_ssl=config.plex_verify_ssl,
                auto_search=config.lidarr_auto_search,
                root_folder=config.lidarr_root_folder,
                quality_profile_id=config.lidarr_quality_profile_id,
                metadata_profile_id=config.lidarr_metadata_profile_id,
            )
            while not _shutdown_requested:
                slept = 0
                while slept < interval_sec and not _shutdown_requested:
                    time.sleep(min(1, interval_sec - slept))
                    slept += 1
                if _shutdown_requested:
                    break
                try:
                    if not lidarr_worker.is_running():
                        all_missing = db.get_missing_tracks()
                        unmonitored = [t for t in all_missing if t.get("lidarr_status") != "monitored"]
                        if unmonitored:
                            logger.info(
                                "Auto-trickle: enqueuing %d unmonitored tracks into Lidarr",
                                min(len(unmonitored), config.lidarr_trickle_batch_size),
                            )
                            lidarr_worker.start_trickle(
                                items=unmonitored,
                                client=lidarr_cli,
                                db=db,
                                delay_seconds=config.lidarr_trickle_rate_seconds,
                                auto_search=config.lidarr_auto_search,
                                batch_size=config.lidarr_trickle_batch_size,
                            )
                except Exception as e:
                    logger.exception("Error in scheduled Lidarr auto-trickle: %s", e)

        lidarr_bg_thread = threading.Thread(
            target=background_lidarr_trickle_worker, daemon=True, name="ScheduledLidarrTrickleWorker"
        )
        lidarr_bg_thread.start()

    app = create_app(db=db, config=config)

    uvicorn_config = uvicorn.Config(
        app=app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    try:
        server.run()
    except Exception as e:
        logger.exception("Web server error: %s", e)
        return 1
    finally:
        db.close()

    logger.info("Plex Playlist Hub server terminated cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
