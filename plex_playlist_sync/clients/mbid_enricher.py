"""MusicBrainz (MBID) and BrainzMash metadata enrichment client with in-memory TTL caching."""

import logging
import re
import threading
import time
from typing import Any, Optional
import urllib.parse

import requests

logger = logging.getLogger(__name__)


def _sanitize_lucene_query(text: str) -> str:
    """Removes or escapes characters that disrupt Lucene query parsing."""
    if not text:
        return ""
    # Strip double quotes, backslashes, and control characters
    return re.sub(r'["\\/]', " ", text).strip()


class MbidEnricherClient:
    """High-speed cached MBID resolver querying BrainzMash or MusicBrainz REST mirrors and Cover Art Archive."""

    def __init__(
        self,
        base_url: str = "https://api.brainzmash.org",
        timeout: float = 3.0,
        cache_ttl: float = 3600.0,
    ) -> None:
        self.base_url = (base_url or "https://api.brainzmash.org").rstrip("/")
        self.timeout = float(timeout)
        self.cache_ttl = float(cache_ttl)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "TrackSeerr/1.0.0 (https://github.com/trackseerr)",
                "Accept": "application/json",
            }
        )

    def _get_cached(self, key: str) -> tuple[bool, Any]:
        with self._lock:
            if key in self._cache:
                timestamp, data = self._cache[key]
                if time.time() - timestamp < self.cache_ttl:
                    return True, data
                del self._cache[key]
            return False, None

    def _set_cached(self, key: str, data: Any) -> None:
        with self._lock:
            self._cache[key] = (time.time(), data)

    def lookup_track_mbids(
        self,
        artist: str,
        album: str,
        title: str,
        isrc: Optional[str] = None,
    ) -> Optional[dict[str, Optional[str]]]:
        """Looks up recording, artist, album, and release group MBIDs by ISRC or title/artist/album."""
        clean_artist = _sanitize_lucene_query(artist)
        clean_album = _sanitize_lucene_query(album)
        clean_title = _sanitize_lucene_query(title)
        clean_isrc = (isrc or "").strip().upper()

        cache_key = f"track:{clean_artist.lower()}:{clean_album.lower()}:{clean_title.lower()}:{clean_isrc}"
        hit, cached_data = self._get_cached(cache_key)
        if hit:
            return cached_data

        try:
            # 1. Try ISRC lookup first if present
            recordings = []
            if clean_isrc:
                url = f"{self.base_url}/ws/2/recording"
                params = {"query": f"isrc:{clean_isrc}", "fmt": "json"}
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    recordings = data.get("recordings") or []

            # 2. If no ISRC match, search by recording, artist, and release
            if not recordings and clean_title:
                url = f"{self.base_url}/ws/2/recording"
                query_parts = [f'recording:"{clean_title}"']
                if clean_artist:
                    query_parts.append(f'artist:"{clean_artist}"')
                if clean_album:
                    query_parts.append(f'release:"{clean_album}"')
                query_str = " AND ".join(query_parts)
                params = {"query": query_str, "fmt": "json"}
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    recordings = data.get("recordings") or []

            if not recordings:
                self._set_cached(cache_key, None)
                return None

            rec = recordings[0]
            musicbrainz_trackid = rec.get("id")

            musicbrainz_artistid: Optional[str] = None
            artist_credit = rec.get("artist-credit") or []
            if artist_credit and isinstance(artist_credit, list):
                ac0 = artist_credit[0]
                if isinstance(ac0, dict):
                    art = ac0.get("artist")
                    if isinstance(art, dict):
                        musicbrainz_artistid = art.get("id")
                    elif "id" in ac0:
                        musicbrainz_artistid = ac0.get("id")

            musicbrainz_albumid: Optional[str] = None
            musicbrainz_releasegroupid: Optional[str] = None
            releases = rec.get("releases") or []
            if releases and isinstance(releases, list):
                rel0 = releases[0]
                if isinstance(rel0, dict):
                    musicbrainz_albumid = rel0.get("id")
                    rg = rel0.get("release-group")
                    if isinstance(rg, dict):
                        musicbrainz_releasegroupid = rg.get("id")

            result = {
                "musicbrainz_artistid": musicbrainz_artistid,
                "musicbrainz_albumid": musicbrainz_albumid,
                "musicbrainz_releasegroupid": musicbrainz_releasegroupid,
                "musicbrainz_trackid": musicbrainz_trackid,
            }
            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning("MbidEnricherClient: lookup_track_mbids failed for '%s - %s': %s", artist, title, exc)
            return None

    def lookup_artist_mbid(self, artist_name: str) -> Optional[str]:
        """Queries the mirror for the canonical artist MBID."""
        clean_name = _sanitize_lucene_query(artist_name)
        if not clean_name:
            return None

        cache_key = f"artist:{clean_name.lower()}"
        hit, cached_data = self._get_cached(cache_key)
        if hit:
            return cached_data

        try:
            url = f"{self.base_url}/ws/2/artist"
            params = {"query": f'artist:"{clean_name}"', "fmt": "json"}
            resp = self._session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                self._set_cached(cache_key, None)
                return None

            data = resp.json()
            artists = data.get("artists") or []
            if not artists:
                self._set_cached(cache_key, None)
                return None

            mbid = artists[0].get("id")
            self._set_cached(cache_key, mbid)
            return mbid

        except Exception as exc:
            logger.warning("MbidEnricherClient: lookup_artist_mbid failed for '%s': %s", artist_name, exc)
            return None

    def lookup_album_mbids(
        self, artist_name: str, album_title: str
    ) -> Optional[dict[str, Optional[str]]]:
        """Queries the mirror for release group and artist MBIDs."""
        clean_artist = _sanitize_lucene_query(artist_name)
        clean_album = _sanitize_lucene_query(album_title)
        if not clean_album:
            return None

        cache_key = f"album:{clean_artist.lower()}:{clean_album.lower()}"
        hit, cached_data = self._get_cached(cache_key)
        if hit:
            return cached_data

        try:
            url = f"{self.base_url}/ws/2/release-group"
            query_parts = [f'releasegroup:"{clean_album}"']
            if clean_artist:
                query_parts.append(f'artist:"{clean_artist}"')
            params = {"query": " AND ".join(query_parts), "fmt": "json"}
            resp = self._session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                self._set_cached(cache_key, None)
                return None

            data = resp.json()
            release_groups = data.get("release-groups") or []
            if not release_groups:
                self._set_cached(cache_key, None)
                return None

            rg0 = release_groups[0]
            rg_id = rg0.get("id")

            art_id: Optional[str] = None
            artist_credit = rg0.get("artist-credit") or []
            if artist_credit and isinstance(artist_credit, list):
                ac0 = artist_credit[0]
                if isinstance(ac0, dict):
                    art = ac0.get("artist")
                    if isinstance(art, dict):
                        art_id = art.get("id")
                    elif "id" in ac0:
                        art_id = ac0.get("id")

            result = {
                "mb_release_group_id": rg_id,
                "mb_artist_id": art_id,
            }
            self._set_cached(cache_key, result)
            return result

        except Exception as exc:
            logger.warning(
                "MbidEnricherClient: lookup_album_mbids failed for '%s - %s': %s",
                artist_name,
                album_title,
                exc,
            )
            return None

    def get_cover_art_url(
        self, release_group_id: Optional[str] = None, release_id: Optional[str] = None
    ) -> Optional[str]:
        """Resolves high-resolution 500px front cover URL from Cover Art Archive."""
        if release_group_id:
            return f"https://coverartarchive.org/release-group/{release_group_id}/front-500"
        elif release_id:
            return f"https://coverartarchive.org/release/{release_id}/front-500"
        return None
