import os
import re
from typing import Any, Optional

from .security import sanitize_text

# Regex for #EXTINF:<seconds> [attributes],<title / artist - title>
_EXTINF_PATTERN = re.compile(
    r"^#EXTINF:\s*(-?\d+)?(?:\s+([^\,]*))?\,(.*)$", re.IGNORECASE
)
# Pattern for attributes like artist="Foo", tvg-name="Bar", or tvg-artist="Baz"
_ATTR_PATTERN = re.compile(r'([\w\-]+)=["\']([^"\']*)["\']')

# Audio file extensions to strip from path-based entries
_AUDIO_EXTENSIONS = (
    ".mp3",
    ".flac",
    ".m4a",
    ".alac",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".wma",
    ".aiff",
    ".ape",
)


def parse_m3u(content: str) -> list[dict[str, Any]]:
    """Safely parses an M3U or M3U8 playlist content string into a list of tracks.

    Returns:
        list of dicts with keys: 'title', 'artist', 'album'
    """
    if not isinstance(content, str):
        return []

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    tracks: list[dict[str, Any]] = []

    pending_title: Optional[str] = None
    pending_artist: Optional[str] = None
    pending_album: Optional[str] = None

    for line in lines:
        if line.startswith("#EXTM3U") or line.startswith("#PLAYLIST:"):
            continue

        if line.startswith("#EXTINF:"):
            m = _EXTINF_PATTERN.match(line)
            if m:
                _duration_str, attr_str, display_name = m.groups()
                display_name = sanitize_text(display_name or "").strip()

                artist: Optional[str] = None
                title: Optional[str] = None
                album: Optional[str] = None

                # Check for explicit artist="..." or title="..." attributes
                if attr_str:
                    for k, v in _ATTR_PATTERN.findall(attr_str):
                        k_lower = k.lower()
                        if k_lower in ("artist", "tvg-artist"):
                            artist = sanitize_text(v)
                        elif k_lower in ("title", "tvg-name", "tvg-title"):
                            title = sanitize_text(v)
                        elif k_lower in ("album", "tvg-album"):
                            album = sanitize_text(v)

                # Parse display name if artist or title not already resolved from attributes
                if display_name:
                    if " - " in display_name:
                        parts = display_name.split(" - ", 1)
                        if not artist:
                            artist = parts[0].strip()
                        if not title:
                            title = parts[1].strip()
                    else:
                        if not title:
                            title = display_name

                pending_title = title
                pending_artist = artist
                pending_album = album
            continue

        # Ignore comments or directives
        if line.startswith("#"):
            continue

        # This line is a file path, URI, or title
        raw_path = line

        # If we had an #EXTINF preceding this line, use those metadata values
        if pending_title:
            t = pending_title
            a = pending_artist or "Unknown Artist"
            al = pending_album or ""
            tracks.append({"title": t, "artist": a, "album": al})
            pending_title = None
            pending_artist = None
            pending_album = None
            continue

        # Otherwise, parse the raw path or title line directly
        # Strip trailing audio extension
        clean_entry = raw_path
        for ext in _AUDIO_EXTENSIONS:
            if clean_entry.lower().endswith(ext):
                clean_entry = clean_entry[: -len(ext)]
                break

        # Remove path separators (extract filename and potential parent directory)
        norm_path = clean_entry.replace("\\", "/")
        path_parts = [p.strip() for p in norm_path.split("/") if p.strip()]

        if not path_parts:
            continue

        filename = path_parts[-1]

        # Strip track numbers like "01 - " or "1. "
        stripped_filename = re.sub(r"^\d+[\s\.\-_]+", "", filename).strip()

        artist = "Unknown Artist"
        title = stripped_filename
        album = ""

        if " - " in stripped_filename:
            parts = stripped_filename.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
        elif len(path_parts) >= 2:
            # Fall back to parent folder as artist if format is Artist/Song
            possible_artist = path_parts[-2]
            if len(path_parts) >= 3:
                # Structure: Artist/Album/Track
                artist = path_parts[-3]
                album = path_parts[-2]
            else:
                artist = possible_artist

        tracks.append(
            {
                "title": sanitize_text(title),
                "artist": sanitize_text(artist),
                "album": sanitize_text(album),
            }
        )

    # If file ended with pending #EXTINF line
    if pending_title:
        tracks.append(
            {
                "title": pending_title,
                "artist": pending_artist or "Unknown Artist",
                "album": pending_album or "",
            }
        )

    return tracks
