import csv
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Tuple

import requests
import urllib3
from plexapi.exceptions import BadRequest, NotFound
from plexapi.server import PlexServer

from ..models import Playlist, SyncResult, Track

logger = logging.getLogger(__name__)


def clean_title(title: str) -> str:
    """Strip remaster info, feature tags, and bracketed metadata for fallback search."""
    # Remove text in parentheses or brackets mentioning remaster, live, bonus, feat, etc.
    cleaned = re.sub(
        r"[\(\[](.*?)(remaster|remix|feat|ft\.|live|deluxe|version|edition|mono|stereo|anniversary)(.*?)[\)\]]",
        "",
        title,
        flags=re.IGNORECASE,
    )
    # Remove trailing ' - Remastered...' or ' - Live...'
    cleaned = re.sub(
        r"\s*-\s*(remastered|remaster|live|deluxe|radio edit|mono|stereo).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # If title has parentheses without tags, also strip for clean fallback
    cleaned = re.sub(r"[\(\[].*?[\)\]]", "", cleaned)
    return cleaned.strip()


class PlexClient:
    """Manages interactions with the Plex Media Server."""

    def __init__(self, base_url: str, token: str, verify_ssl: bool = True, timeout: int = 30):
        self.base_url = base_url
        self.token = token
        self.verify_ssl = verify_ssl

        session = requests.Session()
        if not verify_ssl:
            session.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning("Plex SSL verification disabled (verify=False)")

        try:
            self.server = PlexServer(base_url, token, session=session, timeout=timeout)
            logger.info("Successfully connected to Plex Server: %s", getattr(self.server, "friendlyName", base_url))
        except Exception as e:
            logger.error("Failed to connect to Plex Server at %s: %s", base_url, e)
            raise

    def match_track(self, track: Track, threshold: float = 0.9) -> Optional[object]:
        """Search Plex library for a matching track using fuzzy title, artist, and album comparison."""
        candidates = []
        try:
            candidates = self.server.search(track.title, mediatype="track", limit=10)
        except BadRequest as e:
            logger.debug("BadRequest searching for %s: %s", track.title, e)

        # Check initial search results
        matched = self._eval_candidates(candidates, track, threshold)
        if matched:
            return matched

        # Fallback: clean title if it contained qualifiers/remaster text
        stripped_title = clean_title(track.title)
        if stripped_title and stripped_title.lower() != track.title.lower():
            logger.debug("Retrying search with sanitized title: '%s' -> '%s'", track.title, stripped_title)
            try:
                fallback_candidates = self.server.search(stripped_title, mediatype="track", limit=10)
                matched = self._eval_candidates(fallback_candidates, track, threshold)
                if matched:
                    return matched
            except BadRequest as e:
                logger.debug("BadRequest searching for sanitized title %s: %s", stripped_title, e)

        return None

    def _eval_candidates(self, candidates: List[object], track: Track, threshold: float) -> Optional[object]:
        target_artist = track.artist.lower().strip()
        target_album = track.album.lower().strip()

        for candidate in candidates:
            try:
                cand_artist = candidate.artist().title.lower().strip() if candidate.artist() else ""
                artist_ratio = SequenceMatcher(None, cand_artist, target_artist).quick_ratio()
                if artist_ratio >= threshold:
                    return candidate

                cand_album = candidate.album().title.lower().strip() if candidate.album() else ""
                album_ratio = SequenceMatcher(None, cand_album, target_album).quick_ratio()
                if album_ratio >= threshold:
                    return candidate
            except (AttributeError, IndexError, Exception) as e:
                logger.debug("Candidate comparison error for track '%s': %s", track.title, e)
                continue

        return None

    def match_playlist_tracks(
        self, tracks: List[Track], threshold: float = 0.9
    ) -> Tuple[List[object], List[Track]]:
        """Match a list of tracks against the Plex library."""
        available_tracks = []
        missing_tracks = []

        for track in tracks:
            match = self.match_track(track, threshold=threshold)
            if match is not None:
                available_tracks.append(match)
            else:
                missing_tracks.append(track)

        return available_tracks, missing_tracks

    def update_or_create_playlist(
        self,
        name: str,
        tracks: List[object],
        description: str = "",
        poster_url: str = "",
        append: bool = False,
        add_description: bool = True,
        add_poster: bool = True,
    ) -> object:
        """Create or update a playlist on Plex with given tracks and metadata."""
        try:
            plex_playlist = self.server.playlist(name)
            logger.info("Found existing Plex playlist '%s'", name)
            if not append:
                plex_playlist.removeItems(plex_playlist.items())
            plex_playlist.addItems(tracks)
            logger.info("Updated tracks for playlist '%s'", name)
        except NotFound:
            logger.info("Creating new Plex playlist '%s'", name)
            self.server.createPlaylist(title=name, items=tracks)
            plex_playlist = self.server.playlist(name)

        if add_description and description:
            try:
                # Strip raw HTML tags if present in description
                clean_desc = re.sub(r"<[^>]+>", "", description).strip()
                plex_playlist.edit(summary=clean_desc)
                logger.debug("Updated summary for playlist '%s'", name)
            except Exception as e:
                logger.warning("Failed to update summary for '%s': %s", name, e)

        if add_poster and poster_url:
            try:
                plex_playlist.uploadPoster(url=poster_url)
                logger.debug("Updated poster for playlist '%s'", name)
            except Exception as e:
                logger.warning("Failed to upload poster for '%s': %s", name, e)

        return plex_playlist

    def write_missing_csv(self, missing_tracks: List[Track], playlist_name: str, data_dir: str = "/data") -> None:
        """Write missing tracks to CSV file in data directory."""
        try:
            folder = Path(data_dir)
            folder.mkdir(parents=True, exist_ok=True)
            # Sanitize playlist name for filesystem
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", playlist_name)
            target = folder / f"{safe_name}.csv"
            with open(target, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["title", "artist", "album", "url"])
                for t in missing_tracks:
                    writer.writerow([t.title, t.artist, t.album, t.url])
            logger.info("Wrote %d missing track(s) to %s", len(missing_tracks), target)
        except Exception as e:
            logger.warning("Failed to write missing tracks CSV for '%s': %s", playlist_name, e)

    def delete_missing_csv(self, playlist_name: str, data_dir: str = "/data") -> None:
        """Delete previously written missing CSV if all tracks now match."""
        try:
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", playlist_name)
            target = Path(data_dir) / f"{safe_name}.csv"
            if target.exists():
                target.unlink()
                logger.info("Cleaned up obsolete missing CSV: %s", target)
        except Exception as e:
            logger.debug("Could not delete missing CSV for '%s': %s", playlist_name, e)

    def sync_playlist(
        self,
        playlist: Playlist,
        append: bool = False,
        add_description: bool = True,
        add_poster: bool = True,
        write_missing_as_csv: bool = False,
        data_dir: str = "/data",
        threshold: float = 0.9,
    ) -> SyncResult:
        """Execute full match and sync for a single playlist."""
        logger.info("Syncing playlist '%s' (%d tracks)", playlist.name, len(playlist.tracks))
        matched, missing = self.match_playlist_tracks(playlist.tracks, threshold=threshold)

        if not matched:
            logger.warning("No tracks in playlist '%s' could be matched in Plex library", playlist.name)
            if write_missing_as_csv and missing:
                self.write_missing_csv(missing, playlist.name, data_dir=data_dir)
            return SyncResult(
                playlist_name=playlist.name,
                total_tracks=len(playlist.tracks),
                matched_tracks=0,
                missing_tracks=len(missing),
                success=False,
                error="Zero tracks matched in Plex library",
            )

        try:
            self.update_or_create_playlist(
                name=playlist.name,
                tracks=matched,
                description=playlist.description,
                poster_url=playlist.poster,
                append=append,
                add_description=add_description,
                add_poster=add_poster,
            )

            if write_missing_as_csv:
                if missing:
                    self.write_missing_csv(missing, playlist.name, data_dir=data_dir)
                else:
                    self.delete_missing_csv(playlist.name, data_dir=data_dir)

            return SyncResult(
                playlist_name=playlist.name,
                total_tracks=len(playlist.tracks),
                matched_tracks=len(matched),
                missing_tracks=len(missing),
                success=True,
            )
        except Exception as e:
            logger.error("Error creating/updating playlist '%s': %s", playlist.name, e)
            return SyncResult(
                playlist_name=playlist.name,
                total_tracks=len(playlist.tracks),
                matched_tracks=len(matched),
                missing_tracks=len(missing),
                success=False,
                error=str(e),
            )
