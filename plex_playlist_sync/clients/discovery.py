"""Zero-key music discovery client wrapping iTunes and Deezer public APIs with TTL caching."""

import logging
import threading
import time
import urllib.parse
from typing import Any, Optional

import requests

from plex_playlist_sync.models import DiscoveryItem

logger = logging.getLogger(__name__)


class DiscoveryClient:
    """Thread-safe zero-key client for querying public trending, new release, and search APIs."""

    def __init__(self, ttl_seconds: float = 900.0, timeout: float = 5.0) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.timeout = float(timeout)
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "TrackSeerr/1.0 (ZeroKey Music Discovery; https://github.com/trackseerr)",
                "Accept": "application/json",
            }
        )

    def _get_cached(self, key: str) -> Optional[list[dict[str, Any]]]:
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                timestamp, data = entry
                if time.time() - timestamp < self.ttl_seconds:
                    return [dict(d) for d in data]
                del self._cache[key]
        return None

    def _set_cached(self, key: str, data: list[dict[str, Any]]) -> None:
        with self._lock:
            self._cache[key] = (time.time(), [dict(d) for d in data])

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # -------------------------------------------------------------------------
    # Public Methods
    # -------------------------------------------------------------------------

    def get_trending(self, limit: int = 25) -> list[dict[str, Any]]:
        """Retrieves top trending tracks and albums from Deezer charts with iTunes fallback."""
        cache_key = f"trending:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        items: list[dict[str, Any]] = []

        # 1. Attempt Deezer Charts
        try:
            # Query trending tracks
            track_url = f"https://api.deezer.com/chart/0/tracks?limit={max(10, limit)}"
            resp = self.session.get(track_url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                for t in data.get("data", []):
                    art = t.get("artist", {}) if isinstance(t.get("artist"), dict) else {}
                    alb = t.get("album", {}) if isinstance(t.get("album"), dict) else {}
                    cover = alb.get("cover_big") or alb.get("cover_medium") or ""
                    items.append(
                        DiscoveryItem(
                            id=f"deezer:track:{t.get('id')}",
                            item_type="track",
                            title=str(t.get("title", "")).strip(),
                            artist=str(art.get("name", "")).strip() or "Unknown Artist",
                            album=str(alb.get("title", "")).strip() or None,
                            cover_url=cover or None,
                            preview_url=t.get("preview") or None,
                            release_date=t.get("release_date") or None,
                        ).to_dict()
                    )

            # Query trending albums
            album_url = f"https://api.deezer.com/chart/0/albums?limit={max(10, limit)}"
            resp_alb = self.session.get(album_url, timeout=self.timeout)
            if resp_alb.status_code == 200:
                data_alb = resp_alb.json()
                for a in data_alb.get("data", []):
                    art = a.get("artist", {}) if isinstance(a.get("artist"), dict) else {}
                    cover = a.get("cover_big") or a.get("cover_medium") or ""
                    items.append(
                        DiscoveryItem(
                            id=f"deezer:album:{a.get('id')}",
                            item_type="album",
                            title=str(a.get("title", "")).strip(),
                            artist=str(art.get("name", "")).strip() or "Unknown Artist",
                            album=str(a.get("title", "")).strip(),
                            cover_url=cover or None,
                            preview_url=None,
                            release_date=a.get("release_date") or None,
                        ).to_dict()
                    )
        except Exception as e:
            logger.warning("Deezer trending charts query failed: %s; falling back to iTunes RSS", e)

        # 2. Fallback to iTunes Top Albums RSS if Deezer returned empty
        if not items:
            items = self._fetch_itunes_top_albums(limit=limit)

        deduped = self._deduplicate_items(items, limit=limit)
        self._set_cached(cache_key, deduped)
        return deduped

    def get_new_releases(self, limit: int = 25) -> list[dict[str, Any]]:
        """Retrieves new release albums from iTunes RSS feed with Deezer fallback."""
        cache_key = f"new_releases:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # 1. Primary: iTunes Top Albums / New Releases RSS
        items = self._fetch_itunes_top_albums(limit=limit)

        # 2. Fallback: Deezer Chart Albums
        if not items:
            try:
                album_url = f"https://api.deezer.com/chart/0/albums?limit={limit}"
                resp = self.session.get(album_url, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    for a in data.get("data", []):
                        art = a.get("artist", {}) if isinstance(a.get("artist"), dict) else {}
                        cover = a.get("cover_big") or a.get("cover_medium") or ""
                        items.append(
                            DiscoveryItem(
                                id=f"deezer:album:{a.get('id')}",
                                item_type="album",
                                title=str(a.get("title", "")).strip(),
                                artist=str(art.get("name", "")).strip() or "Unknown Artist",
                                album=str(a.get("title", "")).strip(),
                                cover_url=cover or None,
                                preview_url=None,
                                release_date=a.get("release_date") or None,
                            ).to_dict()
                        )
            except Exception as e:
                logger.warning("Deezer fallback albums query failed: %s", e)

        deduped = self._deduplicate_items(items, limit=limit)
        self._set_cached(cache_key, deduped)
        return deduped

    def search(self, query: str, item_type: str = "all", limit: int = 25) -> list[dict[str, Any]]:
        """Performs multi-source search across iTunes and Deezer public APIs."""
        clean_q = (query or "").strip()
        if not clean_q:
            return []

        clean_type = (item_type or "all").lower().strip()
        cache_key = f"search:{clean_q}:{clean_type}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        items: list[dict[str, Any]] = []

        # 1. Search Deezer
        deezer_items = self._search_deezer(clean_q, clean_type, limit=limit)
        items.extend(deezer_items)

        # 2. Search iTunes
        itunes_items = self._search_itunes(clean_q, clean_type, limit=limit)
        items.extend(itunes_items)

        deduped = self._deduplicate_items(items, limit=limit)
        self._set_cached(cache_key, deduped)
        return deduped

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _fetch_itunes_top_albums(self, limit: int = 25) -> list[dict[str, Any]]:
        """Fetches top albums from iTunes RSS JSON feed."""
        url = f"https://itunes.apple.com/us/rss/topalbums/limit={limit}/json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning("iTunes RSS returned status %d", resp.status_code)
                return []

            data = resp.json()
            feed = data.get("feed", {})
            entries = feed.get("entry", [])
            if not isinstance(entries, list):
                entries = [entries] if entries else []

            results: list[dict[str, Any]] = []
            for entry in entries:
                title = entry.get("im:name", {}).get("label", "")
                artist = entry.get("im:artist", {}).get("label", "")
                images = entry.get("im:image", [])
                cover = ""
                if isinstance(images, list) and images:
                    # Pick largest image available
                    cover = images[-1].get("label", "")
                    if cover:
                        cover = cover.replace("170x170bb", "600x600bb")

                item_id = ""
                id_obj = entry.get("id", {})
                if isinstance(id_obj, dict):
                    attrs = id_obj.get("attributes", {})
                    if isinstance(attrs, dict):
                        item_id = attrs.get("im:id", "")

                rel_date = entry.get("im:releaseDate", {}).get("label", "")

                if title and artist:
                    results.append(
                        DiscoveryItem(
                            id=f"itunes:album:{item_id}" if item_id else f"itunes:album:{hash(title + artist)}",
                            item_type="album",
                            title=str(title).strip(),
                            artist=str(artist).strip(),
                            album=str(title).strip(),
                            cover_url=cover or None,
                            preview_url=None,
                            release_date=rel_date or None,
                        ).to_dict()
                    )
            return results
        except Exception as e:
            logger.warning("iTunes RSS query error: %s", e)
            return []

    def _search_deezer(self, query: str, item_type: str, limit: int = 25) -> list[dict[str, Any]]:
        """Queries Deezer public search API."""
        encoded_q = urllib.parse.quote(query)
        results: list[dict[str, Any]] = []

        try:
            if item_type in ("track", "all"):
                url = f"https://api.deezer.com/search/track?q={encoded_q}&limit={limit}"
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    for t in resp.json().get("data", []):
                        art = t.get("artist", {}) if isinstance(t.get("artist"), dict) else {}
                        alb = t.get("album", {}) if isinstance(t.get("album"), dict) else {}
                        cover = alb.get("cover_big") or alb.get("cover_medium") or ""
                        results.append(
                            DiscoveryItem(
                                id=f"deezer:track:{t.get('id')}",
                                item_type="track",
                                title=str(t.get("title", "")).strip(),
                                artist=str(art.get("name", "")).strip() or "Unknown Artist",
                                album=str(alb.get("title", "")).strip() or None,
                                cover_url=cover or None,
                                preview_url=t.get("preview") or None,
                                release_date=t.get("release_date") or None,
                            ).to_dict()
                        )

            if item_type in ("album", "all"):
                url = f"https://api.deezer.com/search/album?q={encoded_q}&limit={limit}"
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    for a in resp.json().get("data", []):
                        art = a.get("artist", {}) if isinstance(a.get("artist"), dict) else {}
                        cover = a.get("cover_big") or a.get("cover_medium") or ""
                        results.append(
                            DiscoveryItem(
                                id=f"deezer:album:{a.get('id')}",
                                item_type="album",
                                title=str(a.get("title", "")).strip(),
                                artist=str(art.get("name", "")).strip() or "Unknown Artist",
                                album=str(a.get("title", "")).strip(),
                                cover_url=cover or None,
                                preview_url=None,
                                release_date=a.get("release_date") or None,
                            ).to_dict()
                        )
        except Exception as e:
            logger.warning("Deezer search error: %s", e)

        return results

    def _search_itunes(self, query: str, item_type: str, limit: int = 25) -> list[dict[str, Any]]:
        """Queries iTunes search API."""
        encoded_q = urllib.parse.quote(query)
        results: list[dict[str, Any]] = []

        entities = []
        if item_type in ("album", "all"):
            entities.append(("album", "album"))
        if item_type in ("track", "all"):
            entities.append(("song", "track"))

        for entity_param, mapped_type in entities:
            try:
                url = f"https://itunes.apple.com/search?term={encoded_q}&entity={entity_param}&limit={limit}"
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("results", []):
                        title = r.get("trackName") if mapped_type == "track" else r.get("collectionName")
                        artist = r.get("artistName", "")
                        album = r.get("collectionName")
                        cover = r.get("artworkUrl100", "")
                        if cover:
                            cover = cover.replace("100x100bb", "600x600bb")
                        preview = r.get("previewUrl") if mapped_type == "track" else None
                        item_id = r.get("trackId") if mapped_type == "track" else r.get("collectionId")

                        if title and artist:
                            results.append(
                                DiscoveryItem(
                                    id=f"itunes:{mapped_type}:{item_id}",
                                    item_type=mapped_type,
                                    title=str(title).strip(),
                                    artist=str(artist).strip(),
                                    album=str(album).strip() if album else None,
                                    cover_url=cover or None,
                                    preview_url=preview or None,
                                    release_date=r.get("releaseDate") or None,
                                ).to_dict()
                            )
            except Exception as e:
                logger.warning("iTunes search error for entity %s: %s", entity_param, e)

        return results

    def _deduplicate_items(self, items: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
        """Deduplicates items prioritizing entries with preview URLs."""
        seen: dict[tuple[str, str, str], dict[str, Any]] = {}
        for it in items:
            item_type = it.get("item_type", "")
            artist = (it.get("artist") or "").lower().strip()
            title = (it.get("title") or "").lower().strip()
            key = (item_type, artist, title)

            if key not in seen:
                seen[key] = it
            else:
                # If existing has no preview_url but new one has one, replace
                if not seen[key].get("preview_url") and it.get("preview_url"):
                    seen[key] = it

        out = list(seen.values())
        return out[:limit]
