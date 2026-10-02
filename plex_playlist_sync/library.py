"""Audio metadata inspector and library management pipeline for TrackSeerr.

Extracts tags, stream metrics, and codecs via Mutagen with cross-platform collision detection.
"""

import base64
import logging
import re
from pathlib import Path
from typing import Any

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPOS, TPE1, TPE2, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from plex_playlist_sync.naming import format_quality

logger = logging.getLogger(__name__)


def _parse_int(val: Any) -> int | None:
    """Safely parses an integer or returns None."""
    if val is None:
        return None
    try:
        # If float or string with decimals
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _parse_num_total(val: Any) -> tuple[int | None, int | None]:
    """Parses a track or disc field which can be '1/12', (1, 12), or 1."""
    if val is None:
        return None, None

    if isinstance(val, (list, tuple)):
        if len(val) >= 2:
            return _parse_int(val[0]), _parse_int(val[1])
        elif len(val) == 1:
            return _parse_num_total(val[0])
        return None, None

    s = str(val).strip()
    if "/" in s:
        parts = s.split("/", 1)
        return _parse_int(parts[0]), _parse_int(parts[1])
    return _parse_int(s), None


def _extract_year(date_val: Any) -> int | None:
    """Extracts 4-digit year from date strings like '2023-05-12' or '2023'."""
    if not date_val:
        return None
    m = re.search(r"\b(\d{4})\b", str(date_val))
    if m:
        return int(m.group(1))
    return None


def inspect_audio_file(file_path: str | Path) -> dict[str, Any]:
    """Inspects an audio file using Mutagen to extract tags and stream properties.

    Supports FLAC, MP3 (ID3), M4A/AAC (MP4), and Ogg/Opus.
    Returns:
        title, artist, album, album_artist, year, track_number, total_tracks,
        disc_number, total_discs, codec, bitrate, sample_rate, bits_per_sample,
        duration, quality_full, extension, file_path.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    audio = mutagen.File(str(path))
    if audio is None:
        raise ValueError(f"Unsupported audio file format or corrupted file: {path}")

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    track_number: int | None = None
    total_tracks: int | None = None
    disc_number: int | None = None
    total_discs: int | None = None
    codec = "UNKNOWN"
    bitrate: int | None = None
    sample_rate: int | None = None
    bits_per_sample: int | None = None
    duration: float = 0.0

    tags = getattr(audio, "tags", None)
    info = getattr(audio, "info", None)

    if info is not None:
        duration = float(getattr(info, "length", 0.0))
        sample_rate = _parse_int(getattr(info, "sample_rate", None))
        bitrate = _parse_int(getattr(info, "bitrate", None))
        bits_per_sample = _parse_int(getattr(info, "bits_per_sample", None))

    # 1. FLAC
    if isinstance(audio, FLAC):
        codec = "FLAC"
        if tags:
            title = tags.get("title", [None])[0]
            artist = tags.get("artist", [None])[0]
            album = tags.get("album", [None])[0]
            album_artist = tags.get("albumartist", [None])[0] or tags.get("album_artist", [None])[0]
            year = _extract_year(tags.get("date", [None])[0])
            track_number, total_tracks = _parse_num_total(tags.get("tracknumber", [None])[0])
            if total_tracks is None:
                total_tracks = _parse_int(tags.get("tracktotal", [None])[0] or tags.get("totaltracks", [None])[0])
            disc_number, total_discs = _parse_num_total(tags.get("discnumber", [None])[0])
            if total_discs is None:
                total_discs = _parse_int(tags.get("disctotal", [None])[0] or tags.get("totaldiscs", [None])[0])

    # 2. MP3 (ID3)
    elif isinstance(audio, MP3):
        codec = "MP3"
        if bits_per_sample is None:
            bits_per_sample = 16
        if tags:
            def id3_val(key: str) -> str | None:
                frame = tags.get(key)
                if frame and hasattr(frame, "text") and frame.text:
                    return str(frame.text[0])
                return None

            title = id3_val("TIT2")
            artist = id3_val("TPE1")
            album = id3_val("TALB")
            album_artist = id3_val("TPE2")
            year = _extract_year(id3_val("TDRC") or id3_val("TYER"))
            track_number, total_tracks = _parse_num_total(id3_val("TRCK"))
            disc_number, total_discs = _parse_num_total(id3_val("TPOS"))

    # 3. MP4 / M4A / AAC / ALAC
    elif isinstance(audio, MP4):
        codec = "ALAC" if getattr(info, "codec", "").lower() == "alac" else "AAC"
        if tags:
            def mp4_val(key: str) -> str | None:
                v = tags.get(key)
                if v and isinstance(v, list) and v:
                    return str(v[0])
                return None

            title = mp4_val("\xa9nam")
            artist = mp4_val("\xa9ART")
            album = mp4_val("\xa9alb")
            album_artist = mp4_val("aART")
            year = _extract_year(mp4_val("\xa9day"))

            trkn = tags.get("trkn")
            if trkn and isinstance(trkn, list) and trkn:
                track_number, total_tracks = _parse_num_total(trkn[0])

            disk = tags.get("disk")
            if disk and isinstance(disk, list) and disk:
                disc_number, total_discs = _parse_num_total(disk[0])

    # 4. Ogg Opus or Ogg Vorbis
    elif isinstance(audio, (OggOpus, OggVorbis)):
        codec = "Opus" if isinstance(audio, OggOpus) else "Vorbis"
        if tags:
            title = tags.get("title", [None])[0]
            artist = tags.get("artist", [None])[0]
            album = tags.get("album", [None])[0]
            album_artist = tags.get("albumartist", [None])[0] or tags.get("album_artist", [None])[0]
            year = _extract_year(tags.get("date", [None])[0])
            track_number, total_tracks = _parse_num_total(tags.get("tracknumber", [None])[0])
            disc_number, total_discs = _parse_num_total(tags.get("discnumber", [None])[0])

    # 5. Generic Mutagen File fallback
    else:
        suffix = path.suffix.lower()
        if suffix in (".flac",):
            codec = "FLAC"
        elif suffix in (".mp3",):
            codec = "MP3"
        elif suffix in (".m4a", ".aac"):
            codec = "AAC"
        elif suffix in (".opus",):
            codec = "Opus"
        elif suffix in (".ogg",):
            codec = "Vorbis"
        elif suffix in (".wav",):
            codec = "WAV"

        if tags:
            title = str(tags.get("title", [""])[0]) or None
            artist = str(tags.get("artist", [""])[0]) or None
            album = str(tags.get("album", [""])[0]) or None
            album_artist = str(tags.get("albumartist", [""])[0]) or None
            year = _extract_year(tags.get("date", [""])[0])
            track_number, total_tracks = _parse_num_total(tags.get("tracknumber", [""])[0])
            disc_number, total_discs = _parse_num_total(tags.get("discnumber", [""])[0])

    metadata: dict[str, Any] = {
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": album_artist,
        "year": year,
        "release_year": year,
        "track_number": track_number or 1,
        "total_tracks": total_tracks,
        "disc_number": disc_number or 1,
        "total_discs": total_discs or 1,
        "codec": codec,
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "bits_per_sample": bits_per_sample,
        "duration": round(duration, 2),
        "extension": path.suffix.lower(),
        "file_path": str(path),
    }

    metadata["quality_full"] = format_quality(metadata)
    return metadata


def detect_path_collision(
    destination_path: str | Path,
    existing_paths: set[str] | None = None,
) -> bool:
    """Checks if destination_path already exists on the filesystem or in an in-memory set."""
    p_str = str(destination_path)
    if existing_paths and p_str in existing_paths:
        return True
    try:
        return Path(p_str).exists()
    except (OSError, ValueError):
        return False


def resolve_collision(
    destination_path: str | Path,
    existing_paths: set[str] | None = None,
) -> Path:
    """Appends an incrementing counter (e.g. 'Song (1).flac') if a collision is detected."""
    dest = Path(destination_path)
    if not detect_path_collision(dest, existing_paths):
        return dest

    parent = dest.parent
    stem = dest.stem
    suffix = dest.suffix

    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not detect_path_collision(candidate, existing_paths):
            return candidate
        counter += 1


def write_audio_tags(
    file_path: str | Path,
    tags: dict[str, Any],
    cover_art_bytes: bytes | None = None,
) -> bool:
    """Writes normalized audio metadata tags and optional cover artwork to an audio file.

    Supports FLAC, MP3 (ID3v2.4), M4A/AAC/MP4, and Ogg/Opus containers.
    Returns True on success, or False if the file is invalid or tagging encounters an error.
    """
    try:
        path = Path(file_path).resolve()
        if not path.is_file():
            logger.warning("Tag writing target is not a regular file: %s", file_path)
            return False

        suffix = path.suffix.lower()

        # Extract normalized tag values with sensible aliases
        t_title = tags.get("title")
        t_artist = tags.get("artist")
        t_album = tags.get("album")
        t_album_artist = tags.get("albumartist") or tags.get("album_artist") or tags.get("artist")
        t_date = tags.get("date") or tags.get("release_date") or tags.get("year")
        t_track = tags.get("tracknumber") or tags.get("track_number")
        t_total_tracks = tags.get("totaltracks") or tags.get("total_tracks")
        t_disc = tags.get("discnumber") or tags.get("disc_number")
        t_total_discs = tags.get("totaldiscs") or tags.get("total_discs")

        # 1. FLAC
        if suffix == ".flac":
            audio = FLAC(str(path))
            if audio.tags is None:
                audio.add_tags()

            if t_title is not None:
                audio["title"] = [str(t_title)]
            if t_artist is not None:
                audio["artist"] = [str(t_artist)]
            if t_album is not None:
                audio["album"] = [str(t_album)]
            if t_album_artist is not None:
                audio["albumartist"] = [str(t_album_artist)]
            if t_date is not None:
                audio["date"] = [str(t_date)]
            if t_track is not None:
                audio["tracknumber"] = [str(t_track)]
            if t_total_tracks is not None:
                audio["totaltracks"] = [str(t_total_tracks)]
            if t_disc is not None:
                audio["discnumber"] = [str(t_disc)]
            if t_total_discs is not None:
                audio["totaldiscs"] = [str(t_total_discs)]

            if cover_art_bytes:
                pic = Picture()
                pic.type = 3  # Cover (front)
                pic.mime = "image/png" if cover_art_bytes.startswith(b"\x89PNG") else "image/jpeg"
                pic.data = cover_art_bytes
                audio.clear_pictures()
                audio.add_picture(pic)

            audio.save()
            return True

        # 2. MP3
        elif suffix == ".mp3":
            audio = MP3(str(path))
            if audio.tags is None:
                audio.add_tags()

            if t_title is not None:
                audio.tags.setall("TIT2", [TIT2(encoding=3, text=[str(t_title)])])
            if t_artist is not None:
                audio.tags.setall("TPE1", [TPE1(encoding=3, text=[str(t_artist)])])
            if t_album is not None:
                audio.tags.setall("TALB", [TALB(encoding=3, text=[str(t_album)])])
            if t_album_artist is not None:
                audio.tags.setall("TPE2", [TPE2(encoding=3, text=[str(t_album_artist)])])
            if t_date is not None:
                audio.tags.setall("TDRC", [TDRC(encoding=3, text=[str(t_date)])])
            if t_track is not None:
                track_val = f"{t_track}/{t_total_tracks}" if t_total_tracks else str(t_track)
                audio.tags.setall("TRCK", [TRCK(encoding=3, text=[track_val])])
            if t_disc is not None:
                disc_val = f"{t_disc}/{t_total_discs}" if t_total_discs else str(t_disc)
                audio.tags.setall("TPOS", [TPOS(encoding=3, text=[disc_val])])

            if cover_art_bytes:
                mime = "image/png" if cover_art_bytes.startswith(b"\x89PNG") else "image/jpeg"
                audio.tags.setall(
                    "APIC",
                    [APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_art_bytes)],
                )

            audio.save(v2_version=4)
            return True

        # 3. MP4 / M4A / AAC
        elif suffix in (".m4a", ".aac", ".mp4"):
            audio = MP4(str(path))
            if audio.tags is None:
                audio.add_tags()

            if t_title is not None:
                audio["\xa9nam"] = [str(t_title)]
            if t_artist is not None:
                audio["\xa9ART"] = [str(t_artist)]
            if t_album is not None:
                audio["\xa9alb"] = [str(t_album)]
            if t_album_artist is not None:
                audio["aART"] = [str(t_album_artist)]
            if t_date is not None:
                audio["\xa9day"] = [str(t_date)]

            if t_track is not None:
                try:
                    trkn_num = int(t_track)
                    trkn_total = int(t_total_tracks) if t_total_tracks else 0
                    audio["trkn"] = [(trkn_num, trkn_total)]
                except (ValueError, TypeError):
                    pass

            if t_disc is not None:
                try:
                    disc_num = int(t_disc)
                    disc_total = int(t_total_discs) if t_total_discs else 0
                    audio["disk"] = [(disc_num, disc_total)]
                except (ValueError, TypeError):
                    pass

            if cover_art_bytes:
                img_fmt = (
                    MP4Cover.FORMAT_PNG
                    if cover_art_bytes.startswith(b"\x89PNG")
                    else MP4Cover.FORMAT_JPEG
                )
                audio["covr"] = [MP4Cover(cover_art_bytes, imageformat=img_fmt)]

            audio.save()
            return True

        # 4. Ogg Vorbis or Ogg Opus
        elif suffix in (".ogg", ".opus"):
            if suffix == ".opus":
                audio = OggOpus(str(path))
            else:
                audio = OggVorbis(str(path))

            if audio.tags is None:
                audio.add_tags()

            if t_title is not None:
                audio["title"] = [str(t_title)]
            if t_artist is not None:
                audio["artist"] = [str(t_artist)]
            if t_album is not None:
                audio["album"] = [str(t_album)]
            if t_album_artist is not None:
                audio["albumartist"] = [str(t_album_artist)]
            if t_date is not None:
                audio["date"] = [str(t_date)]
            if t_track is not None:
                audio["tracknumber"] = [str(t_track)]
            if t_total_tracks is not None:
                audio["totaltracks"] = [str(t_total_tracks)]
            if t_disc is not None:
                audio["discnumber"] = [str(t_disc)]
            if t_total_discs is not None:
                audio["totaldiscs"] = [str(t_total_discs)]

            if cover_art_bytes:
                pic = Picture()
                pic.type = 3
                pic.mime = "image/png" if cover_art_bytes.startswith(b"\x89PNG") else "image/jpeg"
                pic.data = cover_art_bytes
                audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]

            audio.save()
            return True

        else:
            logger.warning("Unsupported audio container for tag writing: %s", suffix)
            return False

    except (mutagen.MutagenError, OSError) as e:
        logger.warning("Error writing audio tags to %s: %s", file_path, e)
        return False
    except Exception as e:
        logger.warning("Unexpected error writing audio tags to %s: %s", file_path, e)
        return False


def embed_album_artwork(file_path: str | Path, image_data: bytes) -> bool:
    """Embeds cover artwork directly into an audio file without changing existing tags.

    Supports FLAC, MP3, M4A/AAC/MP4, and Ogg/Opus containers.
    Returns True on success, or False if embedding encounters an error.
    """
    if not image_data:
        logger.warning("Cannot embed empty image data into %s", file_path)
        return False
    return write_audio_tags(file_path=file_path, tags={}, cover_art_bytes=image_data)

