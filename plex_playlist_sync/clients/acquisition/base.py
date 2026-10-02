"""Base acquisition driver interface for native download clients."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from plex_playlist_sync.models import AcquisitionSearchResult


class AcquisitionDriver(ABC):
    """Abstract base class for all acquisition drivers."""

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Test connectivity and authentication with download client or indexer.

        Returns:
            tuple[bool, str]: (success, status_or_error_message)
        """
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        artist: str,
        title: Optional[str] = None,
        album: Optional[str] = None,
    ) -> list[AcquisitionSearchResult]:
        """Search client/indexer for music tracks or albums matching the query.

        Returns:
            list[AcquisitionSearchResult]: Formatted search results with metadata.
        """
        raise NotImplementedError

    def fetch_recent(self, limit: int = 100) -> list[AcquisitionSearchResult]:
        """Poll recent releases from indexer feed. Default empty implementation."""
        return []

    @abstractmethod
    def download(self, result: AcquisitionSearchResult) -> str:
        """Submit a download request to the download client.

        Args:
            result: The chosen AcquisitionSearchResult.

        Returns:
            str: Unique download ID or hash assigned by the client.
        """
        raise NotImplementedError

    @abstractmethod
    def get_status(self, download_id: str) -> dict[str, Any]:
        """Query download status, progress, speed, and file location from the client.

        Args:
            download_id: Unique download ID or hash.

        Returns:
            dict[str, Any]: Standardized status dictionary containing:
                - status: str ("queued", "downloading", "completed", "failed")
                - progress: float (0.0 - 100.0)
                - size_bytes: int
                - speed_bps: int
                - eta_seconds: int
                - source_path: Optional[str]
                - error_message: Optional[str]
        """
        raise NotImplementedError

    @abstractmethod
    def cancel(self, download_id: str) -> bool:
        """Cancel and remove a download from the client.

        Args:
            download_id: Unique download ID or hash.

        Returns:
            bool: True if successfully cancelled/removed, False otherwise.
        """
        raise NotImplementedError
