"""HTTP client for Gateway-to-Core internal communication."""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class CoreClient:
    """Internal HTTP client used by the Gateway tier to proxy requests to TrackSeerr Core."""

    def __init__(
        self,
        core_url: str,
        secret: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.core_url = str(core_url).rstrip("/")
        self.secret = secret
        self.timeout = timeout

    def _headers(self, user_info: Optional[dict[str, Any]] = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.secret:
            headers["X-Internal-Token"] = self.secret
            headers["X-Api-Key"] = self.secret
        if user_info:
            if user_info.get("id"):
                headers["X-User-Id"] = str(user_info["id"])
            if user_info.get("username"):
                headers["X-User-Name"] = str(user_info["username"])
        return headers

    def get_availability(
        self,
        artist_name: Optional[str] = None,
        album_title: Optional[str] = None,
        track_title: Optional[str] = None,
        foreign_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Queries Core for availability of an artist, album, or track."""
        params: dict[str, str] = {}
        if artist_name:
            params["artist_name"] = artist_name
        if album_title:
            params["album_title"] = album_title
        if track_title:
            params["track_title"] = track_title
        if foreign_id:
            params["foreign_id"] = foreign_id

        url = f"{self.core_url}/api/library/availability"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    def forward_request(
        self,
        payload: dict[str, Any],
        user_info: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Forwards single music request creation to TrackSeerr Core."""
        url = f"{self.core_url}/api/requests"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=self._headers(user_info))
            resp.raise_for_status()
            return resp.json()

    def forward_batch_requests(
        self,
        payload: dict[str, Any],
        user_info: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Forwards batch music request creation to TrackSeerr Core."""
        url = f"{self.core_url}/api/requests/batch"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=self._headers(user_info))
            resp.raise_for_status()
            return resp.json()

    def forward_delete_request(self, request_id: str) -> bool:
        """Forwards deletion of a request to TrackSeerr Core."""
        url = f"{self.core_url}/api/requests/{request_id}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.delete(url, headers=self._headers())
            return resp.is_success
