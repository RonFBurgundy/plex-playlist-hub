"""FastAPI dependencies for plex-playlist-sync."""

import logging
import hmac
import os
import threading
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import Depends, HTTPException, Request, status

from plex_playlist_sync.auth import get_or_create_secret_key, verify_session_token
from plex_playlist_sync.clients.deezer import DeezerClient
from plex_playlist_sync.clients.discovery import DiscoveryClient
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.clients.mbid_enricher import MbidEnricherClient
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.clients.spotify import SpotifyClient
from plex_playlist_sync.clients.spotify_scraper import SpotifyWebScraper
from plex_playlist_sync.config import Config
from plex_playlist_sync.internal_auth import (
    HEADER_SIGNATURE,
    InvalidAssertion,
    verify_assertion,
)
from plex_playlist_sync.models import UserPermission
from plex_playlist_sync.security import safe_data_path
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

_db_lock = threading.Lock()
_db_instances: dict[str, Database] = {}
_discovery_lock = threading.Lock()
_discovery_client_instance: Optional[DiscoveryClient] = None
_mbid_enricher_lock = threading.Lock()
_mbid_enricher_instance: Optional[MbidEnricherClient] = None


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
        # Resolve base directory prioritizing CONFIG_DIR, then /config if a dir, then DATA_DIR / config.data_dir
        if os.getenv("CONFIG_DIR"):
            base_dir = str(os.getenv("CONFIG_DIR")).strip()
        elif os.path.isdir("/config"):
            base_dir = "/config"
        else:
            base_dir = os.getenv("DATA_DIR", config.data_dir).strip()
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


def get_discovery_client() -> DiscoveryClient:
    """Dependency providing singleton DiscoveryClient instance."""
    global _discovery_client_instance
    with _discovery_lock:
        if _discovery_client_instance is None:
            _discovery_client_instance = DiscoveryClient()
        return _discovery_client_instance


def get_mbid_enricher() -> MbidEnricherClient:
    """Dependency providing singleton MbidEnricherClient instance."""
    global _mbid_enricher_instance
    with _mbid_enricher_lock:
        if _mbid_enricher_instance is None:
            _mbid_enricher_instance = MbidEnricherClient()
        return _mbid_enricher_instance


GATEWAY_SERVICE_ID = "gateway_service"


def tier_of(config: Config) -> str:
    """Deployment tier reported to the UI: "gateway", "core" or "all-in-one"."""
    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    return role if role in ("gateway", "core") else "all-in-one"


def _forwarded_principal(user: dict[str, Any]) -> dict[str, Any]:
    """Returns a copy of ``user`` that can never be admin: flag forced off, ADMIN bit stripped."""
    principal = dict(user)
    perms = principal.get("permissions")
    perms = int(UserPermission.DEFAULT) if perms is None else int(perms)
    principal["permissions"] = perms & ~int(UserPermission.ADMIN)
    principal["is_admin"] = False
    principal["forwarded"] = True
    return principal


def resolve_signed_principal(
    request: Request,
    db: Database,
    config: Config,
) -> dict[str, Any]:
    """Authenticates a gateway-signed call (X-TS-* headers) and returns its non-admin principal.

    Raises 401 on any verification failure. Unknown asserted users are created as
    non-admin; an existing row (admin or not) is never modified.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid gateway assertion",
    )
    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    if role == "gateway":
        # A gateway is never a verification endpoint.
        raise unauthorized
    body_hash = getattr(request.state, "ts_body_sha256", None)
    if not isinstance(body_hash, str):
        # Body hash is computed by SignedBodyMiddleware; without it nothing can be verified.
        logger.warning("Gateway assertion rejected: request body hash unavailable")
        raise unauthorized
    raw_path = request.scope.get("raw_path")
    path = raw_path.decode("latin-1") if raw_path else request.url.path
    query = request.scope.get("query_string", b"").decode("latin-1")
    target = f"{path}?{query}" if query else path
    try:
        asserted = verify_assertion(
            config.internal_core_secret,
            request.method,
            target,
            request.headers,
            body_hash,
            nonce_store=db,
        )
    except InvalidAssertion as exc:
        logger.warning("Gateway assertion rejected: %s", exc)
        raise unauthorized from exc

    if not asserted.user_id:
        return {
            "id": GATEWAY_SERVICE_ID,
            "username": GATEWAY_SERVICE_ID,
            "is_admin": False,
            "permissions": 0,
            "forwarded": True,
        }
    # Admins never act through the gateway, even at user level.
    known = db.get_user(asserted.user_id)
    if known is not None and (
        known.get("is_admin") or int(known.get("permissions") or 0) & int(UserPermission.ADMIN)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts must use the TrackSeerr Core admin interface",
        )
    try:
        # ensure_user returns the stored row, so the asserted name never renames an existing user.
        user = db.ensure_user(asserted.user_id, asserted.user_name)
    except PermissionError as exc:
        logger.warning("Gateway assertion rejected: %s", exc)
        raise unauthorized from exc
    return _forwarded_principal(user)


def get_current_user(
    request: Request,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> dict[str, Any]:
    """Reads signed HttpOnly session cookie 'session_token' or Authorization Bearer header,

    validates signature and expiration, retrieves user from DB. Raises 401 if invalid or expired.
    """
    if request.headers.get(HEADER_SIGNATURE) is not None:
        return resolve_signed_principal(request, db, config)

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

    # Ensure permissions and is_admin are synchronized
    if user.get("permissions") is None:
        user["permissions"] = int(UserPermission.ADMIN if user.get("is_admin") else UserPermission.DEFAULT)
    elif int(user["permissions"]) & int(UserPermission.ADMIN):
        user["is_admin"] = True

    return user


def get_current_user_or_api_key(
    request: Request,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> dict[str, Any]:
    """Authenticates via a gateway-signed assertion, X-Api-Key / query param, or a user session."""
    # 0. Gateway-signed assertion: forced non-admin, never falls through to other methods
    if request.headers.get(HEADER_SIGNATURE) is not None:
        return resolve_signed_principal(request, db, config)

    # 1. Check X-Api-Key header or query parameter apikey / api_key
    api_key = (
        request.headers.get("X-Api-Key")
        or request.query_params.get("apikey")
        or request.query_params.get("api_key")
    )
    if api_key is not None:
        if db.validate_api_key(api_key):
            return {
                "id": "api_key_user",
                "username": "api_key",
                "is_admin": True,
                "permissions": int(UserPermission.ADMIN),
            }
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # 2. Fall back to standard session token validation
    return get_current_user(request=request, db=db, config=config)


def require_user(current_user: dict[str, Any] = Depends(get_current_user_or_api_key)) -> dict[str, Any]:
    """Enforces active user session or valid machine authentication."""
    return current_user


def has_permission(user: dict[str, Any], permission: UserPermission) -> bool:
    """Checks whether a user holds the given permission bitflag.

    Admins (is_admin=True or UserPermission.ADMIN) hold all permissions.
    """
    if user.get("forwarded"):
        # Gateway-asserted principals never hold admin, nor any permission implied by it.
        user_perms = user.get("permissions")
        user_perms = 0 if user_perms is None else int(user_perms)
        return bool(user_perms & ~int(UserPermission.ADMIN) & int(permission))
    if user.get("is_admin"):
        return True
    user_perms = user.get("permissions")
    if user_perms is None:
        user_perms = int(UserPermission.DEFAULT)
    else:
        user_perms = int(user_perms)
    if user_perms & int(UserPermission.ADMIN):
        return True
    return bool(user_perms & int(permission))


def require_permission(permission: UserPermission):
    """FastAPI dependency factory enforcing that current user holds the specified permission."""
    def _dependency(current_user: dict[str, Any] = Depends(get_current_user_or_api_key)) -> dict[str, Any]:
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires {permission.name}",
            )
        return current_user
    return _dependency


def require_admin(current_user: dict[str, Any] = Depends(get_current_user_or_api_key)) -> dict[str, Any]:
    """Enforces is_admin=True or UserPermission.ADMIN, raises 403 otherwise."""
    if current_user.get("forwarded"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    user_perms = int(current_user.get("permissions") if current_user.get("permissions") is not None else 0)
    if not (current_user.get("is_admin") or (user_perms & int(UserPermission.ADMIN))):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user


def require_core_tier(config: Config = Depends(get_config)) -> None:
    """Enforces that endpoint is running on TrackSeerr Core tier; blocks execution in gateway mode."""
    role = (config.role or os.getenv("ROLE", "all-in-one")).lower().strip()
    if role == "gateway":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Library management is restricted to TrackSeerr Core tier. Gateway tier cannot execute library mutations.",
        )


def get_lidarr_client(
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> Optional[LidarrClient]:
    """Dependency providing LidarrClient using DB-backed settings with env fallback."""
    lidarr_settings = db.get_lidarr_settings()
    url = lidarr_settings.get("url")
    api_key = lidarr_settings.get("api_key")
    auto_search = lidarr_settings.get("auto_search", True)
    root_folder = lidarr_settings.get("root_folder")
    quality_profile_id = lidarr_settings.get("quality_profile_id")
    metadata_profile_id = lidarr_settings.get("metadata_profile_id")

    if not (url and api_key):
        if config.has_lidarr:
            url = config.lidarr_url
            api_key = config.lidarr_api_key
            auto_search = config.lidarr_auto_search
            root_folder = config.lidarr_root_folder
            quality_profile_id = config.lidarr_quality_profile_id
            metadata_profile_id = config.lidarr_metadata_profile_id
            # Seed the DB so subsequent requests use DB
            try:
                db.update_lidarr_settings(
                    {
                        "url": url,
                        "api_key": api_key,
                        "auto_search": auto_search,
                        "root_folder": root_folder,
                        "quality_profile_id": quality_profile_id,
                        "metadata_profile_id": metadata_profile_id,
                        "trickle_rate_seconds": config.lidarr_trickle_rate_seconds,
                        "trickle_batch_size": config.lidarr_trickle_batch_size,
                        "auto_trickle": config.lidarr_auto_trickle,
                        "auto_trickle_interval_minutes": config.lidarr_auto_trickle_interval_minutes,
                    }
                )
            except Exception as e:
                logger.warning("Failed to seed Lidarr settings to DB: %s", e)
        else:
            return None

    try:
        return LidarrClient(
            base_url=str(url),
            api_key=str(api_key),
            verify_ssl=config.plex_verify_ssl,
            auto_search=bool(auto_search),
            root_folder=root_folder,
            quality_profile_id=quality_profile_id,
            metadata_profile_id=metadata_profile_id,
        )
    except Exception as e:
        logger.error("Failed to initialize LidarrClient: %s", e)
        return None


def verify_feed_access(
    request: Request,
    token: Optional[str] = None,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> dict[str, Any]:
    """Validates access for the missing-track RSS / text feeds (Lidarr and RSS clients).

    Accepted credentials, all of which are administrative:
    * the configured ``FEED_TOKEN`` (query ``token``, ``X-Api-Key`` or Bearer),
    * a valid API key,
    * an admin session.

    A plain (non-admin) user, a gateway-forwarded principal and anonymous callers are refused.
    """
    if request.headers.get(HEADER_SIGNATURE) is None and config.feed_token:
        provided = (
            token
            or request.headers.get("X-Api-Key")
            or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        )
        if provided and hmac.compare_digest(
            str(provided).encode("utf-8"), str(config.feed_token).encode("utf-8")
        ):
            return {"id": "feed_token_user", "username": "feed_subscriber", "is_admin": True}

    principal = get_current_user_or_api_key(request=request, db=db, config=config)
    return require_admin(principal)
