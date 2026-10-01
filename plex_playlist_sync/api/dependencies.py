"""FastAPI dependencies for plex-playlist-sync."""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import Depends, HTTPException, Request, status

from plex_playlist_sync.auth import get_or_create_secret_key, verify_session_token
from plex_playlist_sync.clients.deezer import DeezerClient
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.clients.spotify import SpotifyClient
from plex_playlist_sync.clients.spotify_scraper import SpotifyWebScraper
from plex_playlist_sync.config import Config
from plex_playlist_sync.security import safe_data_path
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

_db_lock = threading.Lock()
_db_instances: dict[str, Database] = {}


def get_config() -> Config:
    """Dependency to retrieve system configuration from environment."""
    return Config.from_env()


def get_db() -> Database:
    """Dependency providing a Database instance from /data/sync_db.sqlite or config."""
    config = get_config()
    db_env = os.getenv("DATABASE_PATH")
    if db_env:
        if db_env == ":memory:":
            db_path = ":memory:"
        else:
            db_path = str(Path(db_env).resolve())
    else:
        # Default to /data/sync_db.sqlite, resolved securely within data_dir
        base_dir = os.getenv("DATA_DIR", config.data_dir)
        db_path = str(safe_data_path("sync_db.sqlite", base_dir=base_dir))

    with _db_lock:
        if db_path not in _db_instances:
            _db_instances[db_path] = Database(db_path)
        return _db_instances[db_path]


def get_plex_client(config: Config = Depends(get_config)) -> Optional[PlexClient]:
    """Dependency providing PlexClient instance if configured."""
    if not config.plex_url or not config.plex_token:
        return None
    try:
        return PlexClient(
            base_url=config.plex_url,
            token=config.plex_token,
            verify_ssl=config.plex_verify_ssl,
        )
    except Exception as e:
        logger.error("Failed to initialize PlexClient: %s", e)
        return None


def get_spotify_client(
    config: Config = Depends(get_config),
) -> Union[SpotifyClient, SpotifyWebScraper, None]:
    """Dependency providing SpotifyClient if credentials exist, falling back to keyless SpotifyWebScraper."""
    if config.spotify_client_id and config.spotify_client_secret:
        try:
            return SpotifyClient(
                client_id=config.spotify_client_id,
                client_secret=config.spotify_client_secret,
            )
        except Exception as e:
            logger.error("Failed to initialize SpotifyClient: %s. Falling back to web scraper.", e)

    try:
        return SpotifyWebScraper()
    except Exception as e:
        logger.error("Failed to initialize SpotifyWebScraper: %s", e)
        return None


def get_deezer_client() -> Optional[DeezerClient]:
    """Dependency providing DeezerClient instance."""
    try:
        return DeezerClient()
    except Exception as e:
        logger.error("Failed to initialize DeezerClient: %s", e)
        return None


def get_current_user(
    request: Request,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> dict[str, Any]:
    """Reads signed HttpOnly session cookie 'session_token' or Authorization Bearer header,

    validates signature and expiration, retrieves user from DB. Raises 401 if invalid or expired.
    """
    token: Optional[str] = None

    # 1. Read from HttpOnly cookie
    cookie_token = request.cookies.get("session_token")
    if cookie_token:
        token = cookie_token

    # 2. Or from Authorization Bearer header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: No active session or token provided",
        )

    # 3. Validate signature and expiration
    secret_key = get_or_create_secret_key(data_dir=config.data_dir)
    payload = verify_session_token(token, secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    # 4. Validate session exists in database
    session_row = db.get_session(token)
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or was revoked",
        )

    # 5. Retrieve user from DB
    user = db.get_user(payload["user_id"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def require_user(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Enforces active user session."""
    return current_user


def require_admin(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Enforces is_admin=True, raises 403 otherwise."""
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user


def get_lidarr_client(config: Config = Depends(get_config)) -> Optional[LidarrClient]:
    """Dependency providing LidarrClient if configured."""
    if not config.has_lidarr:
        return None
    try:
        return LidarrClient(
            base_url=config.lidarr_url,  # type: ignore[arg-type]
            api_key=config.lidarr_api_key,  # type: ignore[arg-type]
            verify_ssl=config.plex_verify_ssl,
            auto_search=config.lidarr_auto_search,
            root_folder=config.lidarr_root_folder,
            quality_profile_id=config.lidarr_quality_profile_id,
            metadata_profile_id=config.lidarr_metadata_profile_id,
        )
    except Exception as e:
        logger.error("Failed to initialize LidarrClient: %s", e)
        return None


def verify_feed_access(
    request: Request,
    token: Optional[str] = None,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> Optional[dict[str, Any]]:
    """Validates access for RSS / Lidarr feeds.

    If FEED_TOKEN is configured in environment, token or header is enforced.
    Otherwise, if session cookie / bearer token exists, uses user context.
    If no FEED_TOKEN is configured and no session is provided, allows read-only feed.
    """
    if config.feed_token:
        provided = (
            token
            or request.headers.get("X-Api-Key")
            or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        )
        if provided != config.feed_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid feed token",
            )
        return {"id": "feed_token_user", "username": "feed_subscriber", "is_admin": True}

    cookie_token = request.cookies.get("session_token")
    auth_header = request.headers.get("Authorization", "")
    sess_token = cookie_token or (auth_header[7:].strip() if auth_header.startswith("Bearer ") else None) or token

    if sess_token:
        try:
            secret_key = get_or_create_secret_key(data_dir=config.data_dir)
            payload = verify_session_token(sess_token, secret_key)
            if payload and db.get_session(sess_token):
                user = db.get_user(payload["user_id"])
                if user:
                    return user
        except Exception:
            pass

    return {"id": "lan_reader", "username": "lan_reader", "is_admin": False}
