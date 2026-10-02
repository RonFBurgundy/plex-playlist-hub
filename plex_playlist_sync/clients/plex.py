import csv
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, List, Optional, Tuple

import requests
import urllib.parse
import urllib3
from plexapi.exceptions import BadRequest, NotFound
from plexapi.server import PlexServer

from ..models import Playlist, SyncResult, Track
from ..security import is_safe_image_url

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

    @property
    def machine_identifier(self) -> str:
        """Return the unique machine identifier of the Plex Media Server."""
        return str(getattr(self.server, "machineIdentifier", "") or "")

    def get_home_users(self) -> List[dict]:
        """Retrieve all Plex Home and managed users including the admin user.

        Queries self.server.myPlexAccount().users and includes the admin user
        (self.server.myPlexAccount().username). Handles non-PlexPass or non-PlexHome
        configurations gracefully.

        Returns:
            List of dicts: [{'id': ..., 'username': ..., 'email': ..., 'thumb': ..., 'is_admin': ...}, ...]
        """
        home_users: List[dict] = []
        try:
            account = self.server.myPlexAccount()
        except Exception as e:
            logger.warning("Could not access myPlexAccount (non-PlexPass or offline): %s", e)
            admin_name = str(getattr(self.server, "friendlyName", "Admin") or "Admin")
            return [
                {
                    "id": "admin",
                    "username": admin_name,
                    "email": "",
                    "thumb": "",
                    "is_admin": True,
                }
            ]

        # Admin user
        admin_username = str(getattr(account, "username", "") or "Admin")
        admin_id = str(getattr(account, "id", "") or "admin")
        admin_email = str(getattr(account, "email", "") or "")
        admin_thumb = str(getattr(account, "thumb", "") or "")
        home_users.append(
            {
                "id": admin_id,
                "username": admin_username,
                "email": admin_email,
                "thumb": admin_thumb,
                "is_admin": True,
            }
        )

        # Home / managed users
        try:
            users_attr = getattr(account, "users", None)
            if callable(users_attr):
                users_list = users_attr()
            elif isinstance(users_attr, (list, tuple)):
                users_list = list(users_attr)
            else:
                users_list = []

            for u in users_list:
                u_name = (
                    getattr(u, "username", None)
                    or getattr(u, "title", None)
                    or getattr(u, "name", "")
                )
                if not u_name:
                    continue
                # Skip duplicate admin entry if present in users
                if str(u_name).lower() == admin_username.lower():
                    continue
                u_id = str(getattr(u, "id", "") or u_name)
                u_email = str(getattr(u, "email", "") or "")
                u_thumb = str(getattr(u, "thumb", "") or "")
                home_users.append(
                    {
                        "id": u_id,
                        "username": str(u_name),
                        "email": u_email,
                        "thumb": u_thumb,
                        "is_admin": False,
                    }
                )
        except Exception as e:
            logger.warning("Could not retrieve home users from myPlexAccount: %s", e)

        return home_users

    def match_track(
        self, track: Track, threshold: float = 0.9, db: Optional[Any] = None
    ) -> Optional[object]:
        """Search Plex library for a matching track using match overrides or fuzzy title, artist, and album comparison."""
        # 1. Match Memory override check
        if db is not None:
            try:
                override = db.get_match_override(track.title, track.artist)
                if override and override.get("plex_rating_key"):
                    target_key = int(override["plex_rating_key"])
                    fetched = self.server.fetchItem(target_key)
                    if fetched:
                        logger.debug("Applied match memory override for '%s - %s'", track.artist, track.title)
                        return fetched
            except Exception as e:
                logger.debug("Failed match override fetch for '%s': %s", track.title, e)

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
        self, tracks: List[Track], threshold: float = 0.9, db: Optional[Any] = None
    ) -> Tuple[List[object], List[Track]]:
        """Match a list of tracks against the Plex library."""
        available_tracks = []
        missing_tracks = []

        for track in tracks:
            match = self.match_track(track, threshold=threshold, db=db)
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
        server: Optional[object] = None,
        admin_server: Optional[object] = None,
    ) -> object:
        """Create or update a playlist on Plex with given tracks and metadata."""
        srv = server if server is not None else self.server
        admin = admin_server if admin_server is not None else self.server

        try:
            plex_playlist = srv.playlist(name)
            logger.info("Found existing Plex playlist '%s'", name)
            if not append:
                plex_playlist.removeItems(plex_playlist.items())
            plex_playlist.addItems(tracks)
            logger.info("Updated tracks for playlist '%s'", name)
        except NotFound:
            logger.info("Creating new Plex playlist '%s'", name)
            srv.createPlaylist(title=name, items=tracks)
            plex_playlist = srv.playlist(name)

        if add_description and description:
            try:
                # Strip raw HTML tags if present in description
                clean_desc = re.sub(r"<[^>]+>", "", description).strip()
                plex_playlist.edit(summary=clean_desc)
                logger.debug("Updated summary for playlist '%s'", name)
            except Exception as e:
                logger.warning("Failed to update summary for '%s': %s", name, e)

        if add_poster and poster_url and is_safe_image_url(poster_url):
            try:
                plex_playlist.uploadPoster(url=poster_url)
                logger.debug("Updated poster for playlist '%s'", name)
            except Exception as e:
                logger.warning(
                    "Failed to upload poster for '%s' via user session: %s. Attempting admin fallback...",
                    name,
                    e,
                )
                # Injects poster using admin server session if user upload fails
                # (bypassing managed user 401 permission bug via admin /library/metadata/<ratingKey>/posters?url=...)
                rating_key = getattr(plex_playlist, "ratingKey", None)
                if rating_key and admin is not None:
                    try:
                        encoded_url = urllib.parse.quote_plus(poster_url)
                        key = f"/library/metadata/{rating_key}/posters?url={encoded_url}"
                        post_method = getattr(getattr(admin, "_session", requests), "post", requests.post)
                        admin.query(key, method=post_method)
                        logger.info("Successfully injected poster for playlist '%s' via admin session", name)
                    except Exception as admin_err:
                        logger.warning(
                            "Failed to inject poster for '%s' via admin fallback: %s",
                            name,
                            admin_err,
                        )

        return plex_playlist

    def write_missing_csv(self, missing_tracks: List[Track], playlist_name: str, data_dir: str = "/data") -> None:
        """Write missing tracks to CSV file in data directory with formula injection defense."""
        try:
            folder = Path(data_dir)
            folder.mkdir(parents=True, exist_ok=True)
            # Sanitize playlist name for filesystem
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", playlist_name)
            target = folder / f"{safe_name}.csv"

            def _clean(val: Any) -> str:
                s = str(val if val is not None else "")
                if s.startswith(("=", "+", "-", "@", "\t", "\r")):
                    return f"'{s}"
                return s

            with open(target, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["title", "artist", "album", "url"])
                for t in missing_tracks:
                    writer.writerow([_clean(t.title), _clean(t.artist), _clean(t.album), _clean(t.url)])
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

    def sync_playlist_to_users(
        self,
        playlist: Playlist,
        target_usernames: List[str],
        append: bool = False,
        add_description: bool = True,
        add_poster: bool = True,
        write_missing_as_csv: bool = False,
        data_dir: str = "/data",
        threshold: float = 0.9,
        db: Optional[Any] = None,
    ) -> List[SyncResult]:
        """Synchronize a playlist across multiple Plex user profiles.

        Matches tracks once against the server library.
        For each target user:
          - If admin username, syncs to admin.
          - If managed/home user, uses user_server = self.server.switchUser(username)
            and creates/updates playlist in that profile.
          - Injects poster using admin server session if user upload fails (bypassing
            managed user 401 permission bug via admin /library/metadata/<ratingKey>/posters?url=...).
        """
        if not target_usernames:
            logger.info("No target users specified for playlist '%s'", playlist.name)
            return []

        logger.info(
            "Syncing playlist '%s' (%d tracks) to %d user(s): %s",
            playlist.name,
            len(playlist.tracks),
            len(target_usernames),
            target_usernames,
        )

        matched, missing = self.match_playlist_tracks(playlist.tracks, threshold=threshold, db=db)

        if not matched:
            logger.warning(
                "No tracks in playlist '%s' could be matched in Plex library",
                playlist.name,
            )
            if write_missing_as_csv and missing:
                self.write_missing_csv(missing, playlist.name, data_dir=data_dir)

            return [
                SyncResult(
                    playlist_name=playlist.name,
                    total_tracks=len(playlist.tracks),
                    matched_tracks=0,
                    missing_tracks=len(missing),
                    success=False,
                    error="Zero tracks matched in Plex library",
                )
                for _ in target_usernames
            ]

        if write_missing_as_csv:
            if missing:
                self.write_missing_csv(missing, playlist.name, data_dir=data_dir)
            else:
                self.delete_missing_csv(playlist.name, data_dir=data_dir)

        admin_username = ""
        try:
            account = self.server.myPlexAccount()
            admin_username = str(getattr(account, "username", "") or "")
        except Exception as e:
            logger.debug("Could not determine admin username from myPlexAccount: %s", e)

        results: List[SyncResult] = []
        for username in target_usernames:
            is_admin = False
            if admin_username and username.lower() == admin_username.lower():
                is_admin = True
            elif not admin_username and username.lower() in (
                "admin",
                str(getattr(self.server, "friendlyName", "") or "").lower(),
            ):
                is_admin = True

            try:
                if is_admin:
                    user_server = self.server
                else:
                    user_server = self.server.switchUser(username)

                self.update_or_create_playlist(
                    name=playlist.name,
                    tracks=matched,
                    description=playlist.description,
                    poster_url=playlist.poster,
                    append=append,
                    add_description=add_description,
                    add_poster=add_poster,
                    server=user_server,
                    admin_server=self.server,
                )
                results.append(
                    SyncResult(
                        playlist_name=playlist.name,
                        total_tracks=len(playlist.tracks),
                        matched_tracks=len(matched),
                        missing_tracks=len(missing),
                        success=True,
                    )
                )
            except Exception as e:
                logger.error("Failed to sync playlist '%s' to user '%s': %s", playlist.name, username, e)
                results.append(
                    SyncResult(
                        playlist_name=playlist.name,
                        total_tracks=len(playlist.tracks),
                        matched_tracks=len(matched),
                        missing_tracks=len(missing),
                        success=False,
                        error=f"User {username}: {e}",
                    )
                )

        return results

    def search_library_tracks(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search tracks in Plex music library for manual matching."""
        if not query or not query.strip():
            return []
        clean_query = query.strip()
        try:
            results = self.server.search(clean_query, mediatype="track", limit=limit)
            tracks_out = []
            for item in results:
                artist_name = ""
                try:
                    cand_artist = item.artist()
                    if cand_artist:
                        artist_name = getattr(cand_artist, "title", "")
                except Exception:
                    artist_name = getattr(item, "grandparentTitle", "") or getattr(item, "originalTitle", "")

                album_name = ""
                try:
                    cand_album = item.album()
                    if cand_album:
                        album_name = getattr(cand_album, "title", "")
                except Exception:
                    album_name = getattr(item, "parentTitle", "")

                tracks_out.append(
                    {
                        "rating_key": str(getattr(item, "ratingKey", "")),
                        "title": getattr(item, "title", "Unknown"),
                        "artist": artist_name or "Unknown Artist",
                        "album": album_name or "",
                        "duration": getattr(item, "duration", 0),
                        "thumb": getattr(item, "thumb", ""),
                    }
                )
            return tracks_out
        except Exception as e:
            logger.error("Error searching Plex library tracks for '%s': %s", clean_query, e)
            return []

    def get_smart_mix_tracks(self, mix_type: str, limit: int = 50) -> list[dict[str, Any]]:
        """Extract smart mix track recommendations based on local Plex library statistics.

        Supported mix types:
        - 'heavy_rotation': Top played tracks
        - 'forgotten_favorites': High-rated / frequently-played tracks not listened to in 6+ months
        - 'deep_cuts': Unplayed tracks from your top artists
        """
        try:
            sections = getattr(self.server.library, "sections", lambda: [])()
            music_sections = [s for s in sections if getattr(s, "type", "") == "artist"]
            if music_sections:
                music_section = music_sections[0]
            else:
                music_section = self.server.library.section("Music")
        except Exception as e:
            logger.warning("Could not access music library section: %s", e)
            return []

        out: list[dict[str, Any]] = []

        try:
            if mix_type == "heavy_rotation":
                tracks = music_section.searchTracks(sort="viewCount:desc", limit=limit)
                for t in tracks:
                    if getattr(t, "viewCount", 0) and getattr(t, "viewCount", 0) > 0:
                        out.append(self._format_track_item(t))

            elif mix_type == "forgotten_favorites":
                import datetime

                cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=180)
                tracks = music_section.searchTracks(sort="lastViewedAt:asc", limit=limit * 3)
                for t in tracks:
                    last_played = getattr(t, "lastViewedAt", None)
                    views = getattr(t, "viewCount", 0) or 0
                    rating = getattr(t, "userRating", 0.0) or 0.0
                    if (views >= 3 or rating >= 7.0) and (
                        last_played is None or last_played.replace(tzinfo=datetime.timezone.utc) < cutoff
                    ):
                        out.append(self._format_track_item(t))
                        if len(out) >= limit:
                            break

            elif mix_type == "deep_cuts":
                artists = music_section.search(mediatype="artist", sort="viewCount:desc", limit=15)
                for a in artists:
                    try:
                        unplayed = a.tracks(filters={"viewCount": 0})
                        for ut in unplayed[:4]:
                            out.append(self._format_track_item(ut))
                            if len(out) >= limit:
                                break
                    except Exception:
                        continue
                    if len(out) >= limit:
                        break

            else:
                logger.warning("Unknown smart mix type: %s", mix_type)
        except Exception as e:
            logger.error("Error generating smart mix '%s': %s", mix_type, e)

        return out

    def _format_track_item(self, t: Any) -> dict[str, Any]:
        artist_name = getattr(t, "grandparentTitle", "") or getattr(t, "originalTitle", "")
        if not artist_name:
            try:
                a = t.artist()
                if a:
                    artist_name = getattr(a, "title", "")
            except Exception:
                pass

        album_name = getattr(t, "parentTitle", "")
        if not album_name:
            try:
                al = t.album()
                if al:
                    album_name = getattr(al, "title", "")
            except Exception:
                pass

        return {
            "rating_key": str(getattr(t, "ratingKey", "")),
            "title": getattr(t, "title", "Unknown"),
            "artist": artist_name or "Unknown Artist",
            "album": album_name or "",
            "view_count": getattr(t, "viewCount", 0) or 0,
            "last_viewed_at": str(getattr(t, "lastViewedAt", "")) if getattr(t, "lastViewedAt", None) else None,
        }

    def refresh_music_library(self, section_name: Optional[str] = None) -> bool:
        """Triggers a library section refresh on Plex Media Server."""
        sec_name = section_name or getattr(self, "music_section", "Music") or "Music"
        try:
            if hasattr(self.server, "library"):
                try:
                    sec = self.server.library.section(sec_name)
                    sec.update()
                    logger.info("Triggered Plex section update for '%s'", sec_name)
                    return True
                except Exception:
                    self.server.library.update()
                    logger.info("Triggered general Plex library update")
                    return True
        except Exception as e:
            logger.warning("Could not refresh Plex library '%s': %s", sec_name, e)
        return False

