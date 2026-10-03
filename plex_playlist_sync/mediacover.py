"""MediaCover local image caching service.

Provides high-speed local caching for artist posters, artist banners, and album covers
with SSRF protection, magic byte verification, atomic writes, and responsive fallbacks.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Union
import uuid

import requests

from plex_playlist_sync.security import is_safe_image_url

logger = logging.getLogger(__name__)

# Max image size allowed for caching: 10 Megabytes
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


class MediaCoverService:
    """Manages local filesystem caching for artist and album artwork."""

    def __init__(self, base_dir: Optional[Union[str, Path]] = None) -> None:
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            config_dir = os.getenv("CONFIG_DIR")
            if config_dir or os.path.isdir("/config"):
                self.base_dir = Path(config_dir or "/config").resolve()
            else:
                self.base_dir = Path(os.getenv("DATA_DIR", "/data")).resolve()

        self.artists_dir = self.base_dir / "mediacover" / "artists"
        self.albums_dir = self.base_dir / "mediacover" / "albums"

        try:
            self.artists_dir.mkdir(parents=True, exist_ok=True)
            self.albums_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("MediaCoverService: Failed to ensure cache directories: %s", exc)

    def get_artist_poster_path(self, artist_id: str) -> Path:
        """Returns the canonical filesystem path for an artist's poster image."""
        return self.artists_dir / f"{artist_id}_poster.jpg"

    def get_artist_banner_path(self, artist_id: str) -> Path:
        """Returns the canonical filesystem path for an artist's banner image."""
        return self.artists_dir / f"{artist_id}_banner.jpg"

    def get_album_cover_path(self, album_id: str) -> Path:
        """Returns the canonical filesystem path for an album's cover image."""
        return self.albums_dir / f"{album_id}_cover.jpg"

    def cache_image(
        self, target_path: Path, remote_url: str, timeout: float = 8.0
    ) -> bool:
        """Fetches and verifies remote image with magic byte check, writing atomically to target_path."""
        if not remote_url or not isinstance(remote_url, str):
            return False

        if not is_safe_image_url(remote_url):
            logger.warning("MediaCoverService: Blocked unsafe image URL: %s", remote_url)
            return False

        try:
            if target_path.is_file() and target_path.stat().st_size > 0:
                return True
        except OSError:
            pass

        try:
            headers = {
                "User-Agent": "Lidarr/2.0.0 (TrackSeerr; https://github.com/trackseerr)",
                "Accept": "image/webp,image/jpeg,image/png,image/*;q=0.8",
            }
            resp = requests.get(
                remote_url,
                timeout=float(timeout),
                stream=True,
                headers=headers,
            )
            if resp.status_code != 200:
                logger.debug(
                    "MediaCoverService: Remote image fetch failed (status=%d) for %s",
                    resp.status_code,
                    remote_url,
                )
                return False

            content = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    content.extend(chunk)
                    if len(content) > _MAX_IMAGE_BYTES:
                        logger.warning(
                            "MediaCoverService: Image from %s exceeded %d bytes limit",
                            remote_url,
                            _MAX_IMAGE_BYTES,
                        )
                        return False

            data = bytes(content)
            if len(data) < 12:
                logger.warning(
                    "MediaCoverService: Downloaded image from %s too short (%d bytes)",
                    remote_url,
                    len(data),
                )
                return False

            # Magic bytes validation
            is_jpeg = data.startswith(b"\xff\xd8\xff")
            is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
            is_webp = data.startswith(b"RIFF") and data[8:12] == b"WEBP"

            if not (is_jpeg or is_png or is_webp):
                logger.warning(
                    "MediaCoverService: Image from %s failed magic byte verification",
                    remote_url,
                )
                return False

            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target_path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
            tmp_path.write_bytes(data)
            tmp_path.replace(target_path)
            return True

        except (requests.RequestException, OSError) as exc:
            logger.warning(
                "MediaCoverService: Error downloading/saving image from %s: %s",
                remote_url,
                exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "MediaCoverService: Unexpected error caching image from %s: %s",
                remote_url,
                exc,
            )
            return False

    def ensure_artwork(
        self, category: str, item_id: str, remote_url: Optional[str]
    ) -> Optional[Path]:
        """Resolves target path for category, validates or caches artwork, returning path if valid."""
        if category == "artist_poster":
            target = self.get_artist_poster_path(item_id)
        elif category == "artist_banner":
            target = self.get_artist_banner_path(item_id)
        elif category == "album_cover":
            target = self.get_album_cover_path(item_id)
        else:
            return None

        try:
            if target.is_file() and target.stat().st_size > 0:
                return target
        except OSError:
            pass

        if remote_url and self.cache_image(target, remote_url):
            return target

        return None


# Module singleton
mediacover_service = MediaCoverService()

__all__ = ["MediaCoverService", "mediacover_service"]
