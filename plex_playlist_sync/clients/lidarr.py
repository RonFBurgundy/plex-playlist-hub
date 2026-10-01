"""Lidarr REST API Client for automated music discovery and library queuing."""

import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class LidarrClient:
    """Client for interacting with Lidarr's REST API (v1)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        verify_ssl: bool = True,
        auto_search: bool = True,
        root_folder: Optional[str] = None,
        quality_profile_id: Optional[int] = None,
        metadata_profile_id: Optional[int] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.verify_ssl = verify_ssl
        self.auto_search = auto_search
        self.root_folder = root_folder
        self.quality_profile_id = quality_profile_id
        self.metadata_profile_id = metadata_profile_id
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def test_connection(self) -> dict[str, Any]:
        """Validates connectivity and authentication against Lidarr."""
        url = f"{self.base_url}/api/v1/system/status"
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as client:
                resp = client.get(url, headers=self._get_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "online": True,
                        "version": data.get("version", "unknown"),
                        "app_name": data.get("appName", "Lidarr"),
                    }
                return {
                    "online": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:100]}",
                }
        except Exception as e:
            return {"online": False, "error": str(e)}

    def get_root_folder(self, client: Optional[httpx.Client] = None) -> str:
        """Retrieves configured or default Lidarr root folder path."""
        if self.root_folder:
            return self.root_folder
        url = f"{self.base_url}/api/v1/rootfolder"
        headers = self._get_headers()
        try:
            if client:
                resp = client.get(url, headers=headers)
            else:
                with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as c:
                    resp = c.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return str(data[0].get("path", "/music"))
        except Exception as e:
            logger.warning("Could not discover Lidarr root folder: %s", e)
        return "/music"

    def get_quality_profile_id(self, client: Optional[httpx.Client] = None) -> int:
        """Retrieves configured or default Lidarr quality profile ID."""
        if self.quality_profile_id is not None:
            return self.quality_profile_id
        url = f"{self.base_url}/api/v1/qualityprofile"
        headers = self._get_headers()
        try:
            if client:
                resp = client.get(url, headers=headers)
            else:
                with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as c:
                    resp = c.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return int(data[0].get("id", 1))
        except Exception as e:
            logger.warning("Could not discover Lidarr quality profile: %s", e)
        return 1

    def get_metadata_profile_id(self, client: Optional[httpx.Client] = None) -> int:
        """Retrieves configured or default Lidarr metadata profile ID."""
        if self.metadata_profile_id is not None:
            return self.metadata_profile_id
        url = f"{self.base_url}/api/v1/metadataprofile"
        headers = self._get_headers()
        try:
            if client:
                resp = client.get(url, headers=headers)
            else:
                with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as c:
                    resp = c.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return int(data[0].get("id", 1))
        except Exception as e:
            logger.warning("Could not discover Lidarr metadata profile: %s", e)
        return 1

    def add_artist_and_albums(
        self,
        artist_name: str,
        album_names: Optional[list[str]] = None,
        auto_search: Optional[bool] = None,
        monitor_mode: str = "specific",
    ) -> dict[str, Any]:
        """Looks up an artist, ensures the artist and requested albums are monitored in Lidarr.

        Optimized for bulk onboarding:
        - 1 artist lookup per artist (drastically reduces MusicBrainz network calls)
        - Supports monitor_mode="specific" to prevent downloading full artist discographies
        - Batches album search commands into a single AlbumSearch call
        - Gracefully handles HTTP 429 / 503 rate limits with retry-after guidance
        """
        clean_artist = artist_name.strip()
        if not clean_artist:
            return {"status": "error", "message": "Empty artist name"}

        clean_albums = [a.strip() for a in (album_names or []) if a and a.strip()]
        should_search = self.auto_search if auto_search is None else auto_search
        headers = self._get_headers()

        try:
            with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as client:
                # 1. Look up artist in Lidarr / MusicBrainz
                lookup_url = f"{self.base_url}/api/v1/artist/lookup?term={quote(clean_artist)}"
                resp = client.get(lookup_url, headers=headers)

                if resp.status_code in (429, 503):
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    return {
                        "status": "rate_limited",
                        "artist": clean_artist,
                        "retry_after": retry_after,
                        "message": f"Rate limited by Lidarr/MusicBrainz (HTTP {resp.status_code}). Backing off for {retry_after}s.",
                    }

                if resp.status_code != 200:
                    return {
                        "status": "error",
                        "artist": clean_artist,
                        "message": f"Lookup failed: HTTP {resp.status_code}",
                    }

                results = resp.json()
                if not results or not isinstance(results, list):
                    return {
                        "status": "not_found",
                        "artist": clean_artist,
                        "message": "Artist not found in Lidarr lookup",
                    }

                candidate = results[0]
                artist_id = candidate.get("id", 0)
                artist_title = candidate.get("artistName", clean_artist)
                was_new = False

                # 2. If artist is not yet in library
                if not artist_id:
                    root_folder = self.get_root_folder(client)
                    quality_id = self.get_quality_profile_id(client)
                    metadata_id = self.get_metadata_profile_id(client)

                    payload = {
                        **candidate,
                        "monitored": True,
                        "rootFolderPath": root_folder,
                        "qualityProfileId": quality_id,
                        "metadataProfileId": metadata_id,
                        "addOptions": {
                            "monitor": "none" if monitor_mode == "specific" else "all",
                            "searchForMissingAlbums": False,
                        },
                    }

                    add_url = f"{self.base_url}/api/v1/artist"
                    add_resp = client.post(add_url, headers=headers, json=payload)
                    if add_resp.status_code in (429, 503):
                        retry_after = int(add_resp.headers.get("Retry-After", 60))
                        return {
                            "status": "rate_limited",
                            "artist": artist_title,
                            "retry_after": retry_after,
                            "message": f"Rate limited during artist add (HTTP {add_resp.status_code}).",
                        }

                    if add_resp.status_code in (200, 201):
                        added_data = add_resp.json()
                        artist_id = added_data.get("id", 0)
                        was_new = True
                        logger.info("Added artist '%s' (ID %s) to Lidarr", artist_title, artist_id)
                    else:
                        return {
                            "status": "error",
                            "artist": artist_title,
                            "message": f"Failed to add artist: HTTP {add_resp.status_code}",
                        }

                # 3. Locate requested albums and ensure they are monitored
                matched_album_ids: list[int] = []
                if artist_id and clean_albums:
                    try:
                        alb_url = f"{self.base_url}/api/v1/album?artistId={artist_id}"
                        alb_resp = client.get(alb_url, headers=headers)
                        if alb_resp.status_code in (429, 503):
                            return {
                                "status": "rate_limited",
                                "artist": artist_title,
                                "retry_after": int(alb_resp.headers.get("Retry-After", 60)),
                                "message": "Rate limited while fetching albums.",
                            }
                        if alb_resp.status_code == 200:
                            albums = alb_resp.json()
                            for req_alb in clean_albums:
                                req_lower = req_alb.lower()
                                for alb in albums:
                                    alb_title = (alb.get("title") or "").lower()
                                    if req_lower in alb_title or alb_title in req_lower:
                                        a_id = alb.get("id")
                                        if a_id and a_id not in matched_album_ids:
                                            matched_album_ids.append(a_id)
                                            if not alb.get("monitored"):
                                                alb["monitored"] = True
                                                client.put(f"{self.base_url}/api/v1/album/{a_id}", headers=headers, json=alb)
                                        break
                    except Exception as e:
                        logger.warning("Error inspecting Lidarr albums for artist %s: %s", artist_id, e)

                # 4. Trigger decoupled search command if requested
                searched = False
                if should_search:
                    cmd_url = f"{self.base_url}/api/v1/command"
                    if matched_album_ids:
                        cmd_payload = {"name": "AlbumSearch", "albumIds": matched_album_ids}
                        cmd_resp = client.post(cmd_url, headers=headers, json=cmd_payload)
                        searched = cmd_resp.status_code in (200, 201)
                    elif was_new and monitor_mode != "specific":
                        cmd_payload = {"name": "ArtistSearch", "artistId": artist_id}
                        cmd_resp = client.post(cmd_url, headers=headers, json=cmd_payload)
                        searched = cmd_resp.status_code in (200, 201)

                return {
                    "status": "success",
                    "artist": artist_title,
                    "artist_id": artist_id,
                    "added": was_new,
                    "matched_album_ids": matched_album_ids,
                    "searched": searched,
                    "message": f"{'Added and monitored' if was_new else 'Monitored'} in Lidarr ({len(matched_album_ids)} album(s))",
                }

        except Exception as e:
            logger.error("Exception in Lidarr add_artist_and_albums: %s", e)
            return {"status": "error", "artist": clean_artist, "message": str(e)}

    def search_and_add_track(
        self,
        artist_name: str,
        album_name: str = "",
        title: str = "",
        auto_search: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Finds artist/album in Lidarr, ensures it is monitored, and triggers search."""
        res = self.add_artist_and_albums(
            artist_name=artist_name,
            album_names=[album_name] if album_name else [],
            auto_search=auto_search,
            monitor_mode="specific",
        )
        if res.get("status") == "success":
            return {
                "status": "added" if res.get("added") else "already_monitored",
                "artist": res.get("artist", artist_name),
                "album": album_name,
                "lidarr_id": res.get("artist_id", 0),
                "searched": res.get("searched", False),
                "message": res.get("message", ""),
            }
        return res
