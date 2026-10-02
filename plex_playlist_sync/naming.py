"""Arr-grade token template naming engine, conditional block evaluator,

cross-platform path sanitizer, and path builder for TrackSeerr.
"""

import re
from pathlib import Path
from typing import Any

# Supported token names
SUPPORTED_TOKENS: list[str] = [
    # Artist
    "Artist CleanName",
    "Artist Disambiguation",
    "Artist Name",
    # Album
    "Album CleanTitle",
    "Album Disambiguation",
    "Original Release Year",
    "Release Year",
    "Album Title",
    "Album Type",
    # Disc / Medium
    "Medium Format",
    "Medium Title",
    "medium:00",
    "medium:0",
    "disc:00",
    "disc:0",
    # Track
    "Track CleanTitle",
    "Track Title",
    "track:00",
    "track:0",
    # Audio / Quality / MediaInfo
    "Quality Full",
    "MediaInfo AudioCodec",
    "MediaInfo BitDepth",
    "MediaInfo Bitrate",
    "MediaInfo SampleRate",
]

# Preset templates
PRESETS: dict[str, dict[str, Any]] = {
    "Lidarr Standard": {
        "artist_folder_format": "{Artist Name}",
        "album_folder_format": "{Album Title} ({Release Year}){[ - Album Type]}",
        "standard_track_format": "{track:00} - {Track Title}{[ (Quality Full)]}",
        "compilation_track_format": "{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}",
        "multi_disc_folder_format": "{Medium Format} {medium:00}",
        "root_folder_path": "/music",
        "colon_replacement_format": " - ",
        "clean_artist_names": True,
    },
    "Clean Minimal": {
        "artist_folder_format": "{Artist CleanName}",
        "album_folder_format": "{Album CleanTitle} ({Release Year})",
        "standard_track_format": "{track:00} - {Track CleanTitle}",
        "compilation_track_format": "{track:00} - {Artist CleanName} - {Track CleanTitle}",
        "multi_disc_folder_format": "Disc {medium:0}",
        "root_folder_path": "/music",
        "colon_replacement_format": "_",
        "clean_artist_names": True,
    },
    "Audiophile / Detailed": {
        "artist_folder_format": "{Artist Name}",
        "album_folder_format": "{Album Title} ({Release Year}){[ - Album Type]}",
        "standard_track_format": "{track:00} - {Track Title} [{MediaInfo AudioCodec} {MediaInfo BitDepth} {MediaInfo SampleRate}]",
        "compilation_track_format": "{track:00} - {Artist Name} - {Track Title} [{MediaInfo AudioCodec} {MediaInfo BitDepth} {MediaInfo SampleRate}]",
        "multi_disc_folder_format": "{Medium Format} {medium:00}",
        "root_folder_path": "/music",
        "colon_replacement_format": " - ",
        "clean_artist_names": False,
    },
}


def strip_leading_articles(name: str | None) -> str:
    """Strips leading English grammatical articles (The, A, An) from a string."""
    if not name:
        return ""
    stripped = re.sub(r"^(?:the|a|an)\s+", "", str(name).strip(), flags=re.IGNORECASE)
    return stripped.strip()


def format_quality(metadata: dict[str, Any]) -> str:
    """Builds a human-readable quality string (e.g. 'FLAC 24bit 96kHz' or 'MP3 320kbps')."""
    if metadata.get("quality_full"):
        return str(metadata["quality_full"]).strip()

    codec = str(metadata.get("codec") or metadata.get("audio_codec") or "").upper().strip()
    bit_depth = metadata.get("bits_per_sample") or metadata.get("bit_depth")
    sample_rate = metadata.get("sample_rate")
    bitrate = metadata.get("bitrate")

    sr_str: str | None = None
    if sample_rate:
        try:
            sr_val = float(sample_rate)
            if sr_val >= 1000:
                if sr_val % 1000 == 0:
                    sr_str = f"{int(sr_val // 1000)}kHz"
                else:
                    sr_str = f"{sr_val / 1000:.1f}kHz"
            else:
                sr_str = f"{sr_val}Hz"
        except (ValueError, TypeError):
            sr_str = str(sample_rate)

    br_str: str | None = None
    if bitrate:
        try:
            br_val = float(bitrate)
            kbps = round(br_val / 1000) if br_val > 1000 else round(br_val)
            br_str = f"{kbps}kbps"
        except (ValueError, TypeError):
            br_str = str(bitrate)
            if not br_str.endswith("kbps"):
                br_str = f"{br_str}kbps"

    depth_str: str | None = None
    if bit_depth:
        depth_val = str(bit_depth).lower().replace("bit", "").strip()
        depth_str = f"{depth_val}bit"

    if codec in ("FLAC", "ALAC", "WAV", "AIFF", "PCM"):
        parts = [codec]
        if depth_str:
            parts.append(depth_str)
        if sr_str:
            parts.append(sr_str)
        return " ".join(parts)
    elif codec:
        parts = [codec]
        if br_str:
            parts.append(br_str)
        elif depth_str and sr_str:
            parts.extend([depth_str, sr_str])
        return " ".join(parts)
    elif br_str:
        return br_str
    return ""


def truncate_utf8_bytes(s: str, max_bytes: int = 255) -> str:
    """Truncates a string to at most max_bytes when UTF-8 encoded without splitting multi-byte code points."""
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    truncated = encoded[:max_bytes]
    decoded = truncated.decode("utf-8", errors="ignore")
    return decoded.rstrip(" .")


def sanitize_component(name: str, colon_replacement: str = " - ") -> str:
    """Sanitizes a single directory or file path component across Windows, Linux, and macOS.

    - Replaces ':' with colon_replacement.
    - Strips directory traversal sequences ('..').
    - Strips illegal chars: < > " / \\ | ? * and ASCII control characters (0x00-0x1F).
    - Collapses redundant whitespace.
    - Truncates to max 255 bytes on clean UTF-8 code point boundaries.
    - Strips trailing spaces and dots (preventing SMB/CIFS and Windows filesystem errors).
    """
    if not name:
        return ""

    # Replace colons and any immediately following whitespace
    result = re.sub(r":\s*", colon_replacement, str(name))
    # Prevent directory traversal
    result = re.sub(r"\.{2,}", "", result)
    # Strip illegal cross-platform characters and ASCII controls
    result = re.sub(r'[<>"/\\|?*\x00-\x1f]', "", result)
    # Collapse redundant spaces
    result = re.sub(r"\s+", " ", result).strip()
    # Truncate to 255 bytes UTF-8 cleanly
    result = truncate_utf8_bytes(result, 255)
    # Strip trailing periods and spaces
    result = result.rstrip(" .")
    return result


def resolve_token(token: str, metadata: dict[str, Any], clean_artist_names: bool = False) -> str | None:
    """Resolves a token identifier against metadata."""
    t = token.strip()

    # Artist
    if t == "Artist CleanName":
        val = metadata.get("artist") or metadata.get("artist_name") or metadata.get("album_artist") or ""
        return strip_leading_articles(str(val)) or None
    if t == "Artist Name":
        val = metadata.get("artist") or metadata.get("artist_name") or metadata.get("album_artist") or ""
        return str(val) or None
    if t == "Artist Disambiguation":
        val = metadata.get("artist_disambiguation")
        return str(val).strip() if val else None

    # Album
    if t == "Album CleanTitle":
        val = metadata.get("album") or metadata.get("album_title") or ""
        return strip_leading_articles(str(val)) or None
    if t == "Album Title":
        val = metadata.get("album") or metadata.get("album_title") or ""
        return str(val).strip() or None
    if t == "Release Year":
        year = metadata.get("release_year") or metadata.get("year")
        if not year and metadata.get("release_date"):
            m = re.search(r"\b(\d{4})\b", str(metadata["release_date"]))
            if m:
                year = m.group(1)
        return str(year).strip() if year else None
    if t == "Original Release Year":
        year = metadata.get("original_release_year") or metadata.get("original_year")
        if not year:
            year = metadata.get("release_year") or metadata.get("year")
        if not year and metadata.get("release_date"):
            m = re.search(r"\b(\d{4})\b", str(metadata["release_date"]))
            if m:
                year = m.group(1)
        return str(year).strip() if year else None
    if t == "Album Disambiguation":
        val = metadata.get("album_disambiguation")
        return str(val).strip() if val else None
    if t == "Album Type":
        val = metadata.get("album_type")
        return str(val).strip() if val else None

    # Disc / Medium
    if t in ("medium:00", "disc:00"):
        num = metadata.get("disc_number") or metadata.get("medium_number") or metadata.get("disc") or 1
        try:
            return f"{int(num):02d}"
        except (ValueError, TypeError):
            return "01"
    if t in ("medium:0", "disc:0"):
        num = metadata.get("disc_number") or metadata.get("medium_number") or metadata.get("disc") or 1
        try:
            return f"{int(num):d}"
        except (ValueError, TypeError):
            return "1"
    if t == "Medium Format":
        val = metadata.get("medium_format") or metadata.get("media_format") or "CD"
        return str(val).strip()
    if t == "Medium Title":
        val = metadata.get("medium_title") or metadata.get("disc_title")
        return str(val).strip() if val else None

    # Track
    if t == "track:00":
        num = metadata.get("track_number") or metadata.get("track") or 1
        try:
            return f"{int(num):02d}"
        except (ValueError, TypeError):
            return "01"
    if t == "track:0":
        num = metadata.get("track_number") or metadata.get("track") or 1
        try:
            return f"{int(num):d}"
        except (ValueError, TypeError):
            return "1"
    if t == "Track Title":
        val = metadata.get("title") or metadata.get("track_title")
        return str(val).strip() if val else None
    if t == "Track CleanTitle":
        val = metadata.get("title") or metadata.get("track_title") or ""
        return strip_leading_articles(str(val)) or None

    # Audio / Quality / MediaInfo
    if t == "Quality Full":
        q = format_quality(metadata)
        return q or None
    if t == "MediaInfo AudioCodec":
        codec = metadata.get("codec") or metadata.get("audio_codec")
        return str(codec).upper().strip() if codec else None
    if t == "MediaInfo Bitrate":
        br = metadata.get("bitrate")
        if br:
            try:
                br_val = float(br)
                kbps = round(br_val / 1000) if br_val > 1000 else round(br_val)
                return f"{kbps}kbps"
            except (ValueError, TypeError):
                s = str(br).strip()
                return s if s.endswith("kbps") else f"{s}kbps"
        return None
    if t == "MediaInfo SampleRate":
        sr = metadata.get("sample_rate")
        if sr:
            try:
                sr_val = float(sr)
                if sr_val >= 1000:
                    if sr_val % 1000 == 0:
                        return f"{int(sr_val // 1000)}kHz"
                    return f"{sr_val / 1000:.1f}kHz"
                return f"{sr_val}Hz"
            except (ValueError, TypeError):
                return str(sr).strip()
        return None
    if t == "MediaInfo BitDepth":
        bd = metadata.get("bits_per_sample") or metadata.get("bit_depth")
        if bd:
            bd_str = str(bd).lower().replace("bit", "").strip()
            return f"{bd_str}bit"
        return None

    # Fallback to direct key in metadata
    val_direct = metadata.get(t)
    if val_direct is not None:
        return str(val_direct).strip() or None
    return None


def _evaluate_conditional_block(block_content: str, metadata: dict[str, Any], clean_artist_names: bool = False) -> str:
    """Evaluates the inner content of a conditional block.

    If all resolved tokens are non-empty, replaces tokens and keeps prefixes/suffixes.
    If the tokens resolve to empty/None, returns empty string.
    """
    found_tokens: list[str] = []
    # Identify known tokens inside block_content
    for token_name in SUPPORTED_TOKENS:
        # Match bare token name or wrapped {token_name}
        pattern = re.compile(rf"(\{{?\b{re.escape(token_name)}\}}?)")
        if pattern.search(block_content):
            found_tokens.append(token_name)

    if not found_tokens:
        # Check for any {key} token
        generic_tokens = re.findall(r"\{([A-Za-z0-9_:]+)\}", block_content)
        found_tokens.extend(generic_tokens)

    if not found_tokens:
        return ""

    # Verify that all tokens in the conditional block resolve to non-empty values
    resolved_values: dict[str, str] = {}
    for tok in found_tokens:
        val = resolve_token(tok, metadata, clean_artist_names=clean_artist_names)
        if not val:
            return ""
        resolved_values[tok] = val

    # Strip any internal delimiter brackets, e.g. [Disambiguation: ] -> Disambiguation:
    result = re.sub(r"\[(.*?)\]", r"\1", block_content)
    for tok, val in resolved_values.items():
        # Replace {tok} or bare tok
        result = result.replace(f"{{{tok}}}", val)
        result = re.sub(rf"\b{re.escape(tok)}\b", val, result)
    return result


def render_template(
    template: str,
    metadata: dict[str, Any],
    clean_artist_names: bool = False,
    colon_replacement: str = " - ",
) -> str:
    """Renders a token naming template with conditional block evaluation and token replacement."""
    if not template:
        return ""

    result = template

    # 1. Evaluate {[prefix]Token[suffix]} conditional blocks
    def replace_bracket_conditional(match: re.Match[str]) -> str:
        inner = match.group(1)
        return _evaluate_conditional_block(inner, metadata, clean_artist_names=clean_artist_names)

    result = re.sub(r"\{\[(.*?)\]\}", replace_bracket_conditional, result)

    # 2. Evaluate {(Token)} conditional blocks
    def replace_paren_conditional(match: re.Match[str]) -> str:
        inner = match.group(1)
        eval_res = _evaluate_conditional_block(inner, metadata, clean_artist_names=clean_artist_names)
        return f"({eval_res})" if eval_res else ""

    result = re.sub(r"\{\((.*?)\)\}", replace_paren_conditional, result)

    # 3. Evaluate standard tokens {Token}
    def replace_standard_token(match: re.Match[str]) -> str:
        token_name = match.group(1)
        val = resolve_token(token_name, metadata, clean_artist_names=clean_artist_names)
        return val if val is not None else ""

    result = re.sub(r"\{([A-Za-z0-9_:\s]+)\}", replace_standard_token, result)

    # 4. Clean up any remaining double spaces or dangling formatting artifacts
    result = re.sub(r" +", " ", result).strip()
    return result


def build_track_path(metadata: dict[str, Any], settings: dict[str, Any]) -> str:
    """Builds a fully sanitized, cross-platform media track path.

    - Omission of multi-disc folder when total_discs <= 1.
    - Handling of compilation / Various Artists vs standard artist.
    - Path sanitization per component preventing directory traversal.
    - Extension preservation.
    """
    root_folder = str(settings.get("root_folder_path") or "/music").rstrip("/\\")
    colon_replacement = str(settings.get("colon_replacement_format") or " - ")
    clean_artist_names = bool(settings.get("clean_artist_names", True))

    artist_format = str(settings.get("artist_folder_format") or "{Artist Name}")
    album_format = str(settings.get("album_folder_format") or "{Album Title} ({Release Year}){[ - Album Type]}")
    standard_track_format = str(settings.get("standard_track_format") or "{track:00} - {Track Title}{[ (Quality Full)]}")
    compilation_track_format = str(
        settings.get("compilation_track_format") or "{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}"
    )
    multi_disc_format = str(settings.get("multi_disc_folder_format") or "{Medium Format} {medium:00}")

    meta = dict(metadata)

    # Detect Compilation / Various Artists
    album_artist = str(meta.get("album_artist") or "").strip()
    is_compilation = (
        meta.get("is_compilation") is True
        or meta.get("compilation") is True
        or album_artist.lower() in ("various artists", "various")
        or str(meta.get("album_type", "")).strip().lower() == "compilation"
    )

    # Determine Artist Folder
    if is_compilation:
        comp_meta = dict(meta)
        if not comp_meta.get("artist") or album_artist.lower() in ("various artists", "various"):
            comp_meta["artist"] = album_artist or "Various Artists"
        artist_raw = render_template(
            artist_format,
            comp_meta,
            clean_artist_names=clean_artist_names,
            colon_replacement=colon_replacement,
        )
        if not artist_raw:
            artist_raw = "Various Artists"
    else:
        artist_raw = render_template(
            artist_format,
            meta,
            clean_artist_names=clean_artist_names,
            colon_replacement=colon_replacement,
        )
        if not artist_raw:
            artist_raw = "Unknown Artist"

    artist_component = sanitize_component(artist_raw, colon_replacement=colon_replacement)

    # Determine Album Folder
    album_raw = render_template(
        album_format,
        meta,
        clean_artist_names=clean_artist_names,
        colon_replacement=colon_replacement,
    )
    if not album_raw:
        album_raw = "Unknown Album"
    album_component = sanitize_component(album_raw, colon_replacement=colon_replacement)

    # Detect Multi-Disc
    total_discs = meta.get("total_discs") or meta.get("disc_total") or meta.get("total_mediums")
    disc_number = meta.get("disc_number") or meta.get("medium_number") or meta.get("disc")

    is_multi_disc = False
    if total_discs is not None:
        try:
            is_multi_disc = int(total_discs) > 1
        except (ValueError, TypeError):
            is_multi_disc = False
    elif disc_number is not None:
        try:
            is_multi_disc = int(disc_number) > 1
        except (ValueError, TypeError):
            is_multi_disc = False

    disc_component: str | None = None
    if is_multi_disc:
        disc_raw = render_template(
            multi_disc_format,
            meta,
            clean_artist_names=clean_artist_names,
            colon_replacement=colon_replacement,
        )
        disc_component = sanitize_component(disc_raw, colon_replacement=colon_replacement)

    # Determine Track Filename
    track_format = compilation_track_format if is_compilation else standard_track_format
    track_raw = render_template(
        track_format,
        meta,
        clean_artist_names=clean_artist_names,
        colon_replacement=colon_replacement,
    )
    if not track_raw:
        track_raw = "Track"

    track_component = sanitize_component(track_raw, colon_replacement=colon_replacement)

    # Extract / Append Extension
    ext = meta.get("extension") or meta.get("ext")
    if not ext and meta.get("file_path"):
        ext = Path(str(meta["file_path"])).suffix
    if not ext and meta.get("filename"):
        ext = Path(str(meta["filename"])).suffix
    if not ext and meta.get("codec"):
        codec_ext_map = {
            "FLAC": ".flac",
            "MP3": ".mp3",
            "AAC": ".m4a",
            "ALAC": ".m4a",
            "M4A": ".m4a",
            "OPUS": ".opus",
            "OGG": ".ogg",
            "VORBIS": ".ogg",
            "WAV": ".wav",
            "AIFF": ".aiff",
        }
        ext = codec_ext_map.get(str(meta["codec"]).upper().strip(), "")

    if ext:
        ext_clean = str(ext).strip()
        if not ext_clean.startswith("."):
            ext_clean = f".{ext_clean}"
        if not track_component.lower().endswith(ext_clean.lower()):
            track_component = f"{track_component}{ext_clean}"

    # Assemble components
    components: list[str] = []
    if artist_component:
        components.append(artist_component)
    if album_component:
        components.append(album_component)
    if disc_component:
        components.append(disc_component)
    if track_component:
        components.append(track_component)

    rel_path = "/".join(components)
    if root_folder:
        return f"{root_folder}/{rel_path}"
    return rel_path
