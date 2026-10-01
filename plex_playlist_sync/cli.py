import logging
import signal
import sys
import time

from .clients.deezer import DeezerClient
from .clients.plex import PlexClient
from .clients.spotify import SpotifyClient
from .config import Config
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

    logger.info("Initializing Plex Playlist Sync v1.0.0")

    if not config.plex_url or not config.plex_token:
        logger.error("Missing mandatory environment variables: PLEX_URL and PLEX_TOKEN must be specified.")
        return 1

    try:
        plex_client = PlexClient(
            base_url=config.plex_url,
            token=config.plex_token,
            verify_ssl=config.plex_verify_ssl,
        )
    except Exception as e:
        logger.error("Failed to connect to Plex Media Server: %s", e)
        return 1

    spotify_client = None
    if config.has_spotify:
        try:
            spotify_client = SpotifyClient(
                client_id=config.spotify_client_id,  # type: ignore
                client_secret=config.spotify_client_secret,  # type: ignore
            )
        except Exception as e:
            logger.error("Failed to initialize Spotify client: %s. Skipping Spotify sync.", e)

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

    while not _shutdown_requested:
        try:
            coordinator.run_sync_cycle()
        except Exception as e:
            logger.exception("Unexpected error occurred during sync cycle: %s", e)

        if config.run_once:
            logger.info("RUN_ONCE/CRON enabled; sync complete. Exiting.")
            break

        logger.info("Sleeping for %d seconds until next sync cycle...", config.wait_seconds)
        # Sleep in small increments to respond quickly to shutdown signals
        slept = 0
        while slept < config.wait_seconds and not _shutdown_requested:
            time.sleep(min(1, config.wait_seconds - slept))
            slept += 1

    logger.info("Plex Playlist Sync terminated cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
