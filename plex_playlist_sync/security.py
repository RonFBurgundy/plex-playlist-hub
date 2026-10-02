"""Security and input sanitization utilities for plex-playlist-sync."""

import os
import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Optional

# Strict regex matching for 22-char alphanumeric Spotify ID
_SPOTIFY_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
_SPOTIFY_URI_RE = re.compile(r"^spotify:playlist:([A-Za-z0-9]{22})$")
_SPOTIFY_PATH_RE = re.compile(
    r"^(?:/intl-[a-z]{2}(?:-[a-z]{2})?)?(?:/user/[A-Za-z0-9_.-]+)?/playlist/([A-Za-z0-9]{22})/?$"
)

# Strict regex matching for 5-15 digit Deezer ID
_DEEZER_ID_RE = re.compile(r"^[0-9]{5,15}$")
_DEEZER_PATH_RE = re.compile(
    r"^(?:/[a-zA-Z]{2}(?:-[a-zA-Z]{2})?)?/playlist/([0-9]{5,15})/?$"
)

_HTML_TAG_RE = re.compile(r"<[^>]*>", flags=re.DOTALL)


def extract_spotify_id(input_str: Optional[str]) -> Optional[str]:
    """Strictly validate and extract a 22-character Spotify playlist ID.

    Accepts:
    - Raw 22-character alphanumeric Spotify ID
    - Spotify playlist URI (spotify:playlist:...)
    - Spotify playlist URL (https://open.spotify.com/playlist/...)

    Rejects all invalid or malicious URLs to prevent SSRF.
    """
    if not isinstance(input_str, str):
        return None
    val = input_str.strip()
    if not val:
        return None

    # 1. Raw ID match
    if _SPOTIFY_ID_RE.fullmatch(val):
        return val

    # 2. Spotify URI match
    uri_match = _SPOTIFY_URI_RE.fullmatch(val)
    if uri_match:
        return uri_match.group(1)

    # 3. Spotify URL match with SSRF prevention
    try:
        parsed = urllib.parse.urlparse(val)
    except ValueError:
        return None

    if parsed.scheme in ("http", "https"):
        # Enforce exact hostname, prevent userinfo bypass or non-standard ports
        if (
            parsed.hostname == "open.spotify.com"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 80, 443)
        ):
            path_match = _SPOTIFY_PATH_RE.fullmatch(parsed.path)
            if path_match:
                return path_match.group(1)

    return None


def extract_deezer_id(input_str: Optional[str]) -> Optional[str]:
    """Strictly validate and extract a 5-15 digit Deezer playlist ID.

    Accepts:
    - Raw 5-15 digit numeric ID
    - Deezer playlist URL (https://www.deezer.com/.../playlist/...)

    Rejects all invalid or malicious URLs to prevent SSRF.
    """
    if not isinstance(input_str, str):
        return None
    val = input_str.strip()
    if not val:
        return None

    # 1. Raw numeric ID match
    if _DEEZER_ID_RE.fullmatch(val):
        return val

    # 2. Deezer URL match with SSRF prevention
    try:
        parsed = urllib.parse.urlparse(val)
    except ValueError:
        return None

    if parsed.scheme in ("http", "https"):
        # Enforce exact hostname, prevent userinfo bypass or non-standard ports
        if (
            parsed.hostname in ("deezer.com", "www.deezer.com")
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 80, 443)
        ):
            path_match = _DEEZER_PATH_RE.fullmatch(parsed.path)
            if path_match:
                return path_match.group(1)

    return None


def sanitize_text(text: Optional[str]) -> str:
    """Strips HTML tags and control characters from text."""
    if not isinstance(text, str):
        return ""
    # Strip HTML tags
    cleaned = _HTML_TAG_RE.sub("", text)
    # Strip control characters (Unicode category C: Cc, Cf, Cs, Co, Cn)
    return "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != "C")


def safe_data_path(filename: str, base_dir: str = "/data") -> Path:
    """Validate that filename resides strictly inside base_dir.

    Strips dangerous characters, resolves relative segments,
    and asserts that the final resolved path is strictly within base_dir.
    Raises ValueError on path traversal attempts or invalid targets.
    """
    if not isinstance(filename, str):
        raise ValueError("Filename must be a string")

    # Strip control characters and whitespace
    cleaned = "".join(ch for ch in filename if unicodedata.category(ch)[0] != "C").strip()
    if not cleaned:
        raise ValueError("Filename is empty or invalid")

    base = Path(base_dir).resolve()
    if os.path.isabs(cleaned):
        target = Path(cleaned).resolve()
    else:
        target = (base / cleaned).resolve()

    if not target.is_relative_to(base) or target == base:
        raise ValueError(f"Path traversal detected or invalid target: '{filename}'")

    return target


def mask_secret(secret: Optional[str], visible_chars: int = 4) -> str:
    """Return masked string revealing only the trailing visible_chars (e.g. ••••••••••••abcd)."""
    if not secret:
        return ""
    mask_char = "•"
    if visible_chars <= 0:
        return mask_char * len(secret)
    if len(secret) <= visible_chars:
        return mask_char * len(secret)
    return (mask_char * (len(secret) - visible_chars)) + secret[-visible_chars:]


_ALLOWED_IMAGE_HOSTS = {
    "i.scdn.co",
    "mosaic.scdn.co",
    "image-cdn-ak.spotifycdn.com",
    "image-cdn-fa.spotifycdn.com",
    "blend-playlist-covers.spotifycdn.com",
    "wrapped-images.spotifycdn.com",
    "e-cdns-images.dzcdn.net",
    "cdns-images.dzcdn.net",
}

_ALLOWED_IMAGE_SUFFIXES = (
    ".scdn.co",
    ".spotifycdn.com",
    ".dzcdn.net",
)


def is_safe_image_url(url: Optional[str]) -> bool:
    """Validates that an image URL is strictly HTTPS and originates from a trusted CDN or public domain.

    Rejects private, loopback, link-local, or cloud metadata IP addresses to prevent SSRF.
    """
    import ipaddress

    if not isinstance(url, str):
        return False
    val = url.strip()
    if not val:
        return False

    try:
        parsed = urllib.parse.urlparse(val)
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False

    if not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False

    hostname = parsed.hostname.lower()

    # Reject localhost or internal domain names (.local, .internal, .lan, etc.)
    if hostname in ("localhost", "127.0.0.1", "::1") or hostname.endswith((".local", ".internal", ".lan", ".home")):
        return False

    # Check if hostname is an IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        return True
    except ValueError:
        # Not a raw IP, it's a domain name
        pass

    if hostname in _ALLOWED_IMAGE_HOSTS:
        return True

    for suffix in _ALLOWED_IMAGE_SUFFIXES:
        if hostname.endswith(suffix):
            return True

    if "." in hostname and not hostname.startswith(".") and not hostname.endswith("."):
        return True

    return False


def is_safe_service_url(url: Optional[str]) -> bool:
    """Validates that a service host URL (download client or indexer) is safe against SSRF.

    Accepts HTTP and HTTPS schemes on homelab LAN IPs (private, loopback, docker container names)
    and valid public domains.
    Strictly blocks:
    - Dangerous schemes (file://, ftp://, gopher://, etc.)
    - Link-local and cloud metadata addresses (169.254.169.254, 169.254.0.0/16, fd00:ec2::254)
    - Cloud metadata hostnames (metadata.google.internal, instance-data)
    - Userinfo URL components (embedded username/password)
    - Malformed or illegal hostname characters
    """
    import ipaddress

    if not isinstance(url, str):
        return False
    val = url.strip()
    if not val:
        return False

    try:
        parsed = urllib.parse.urlparse(val)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    if not parsed.hostname or parsed.username or parsed.password:
        return False

    hostname = parsed.hostname.lower()

    # Reject cloud metadata hostnames
    if hostname in ("metadata.google.internal", "instance-data", "metadata"):
        return False

    # Check IP addresses
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
        return True
    except ValueError:
        pass

    # Hostname syntax validation
    if hostname == "localhost":
        return True

    if not re.fullmatch(r"^[a-z0-9][a-z0-9_\.-]*[a-z0-9]$", hostname):
        return False

    return True

