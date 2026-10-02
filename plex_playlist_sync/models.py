from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PROCESSING = "processing"
    AVAILABLE = "available"
    REJECTED = "rejected"


@dataclass
class MusicRequest:
    id: str
    user_id: str
    item_type: str  # "album" or "track"
    title: str
    artist: str
    album: Optional[str] = None
    cover_url: Optional[str] = None
    status: RequestStatus = RequestStatus.PENDING
    release_date: Optional[str] = None
    foreign_id: Optional[str] = None
    preview_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    username: Optional[str] = None  # Joined for display

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "item_type": self.item_type,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "cover_url": self.cover_url,
            "status": self.status.value if isinstance(self.status, RequestStatus) else str(self.status),
            "release_date": self.release_date,
            "foreign_id": self.foreign_id,
            "preview_url": self.preview_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "username": self.username,
        }


@dataclass
class DiscoveryItem:
    id: str
    item_type: str  # "album" or "track"
    title: str
    artist: str
    album: Optional[str] = None
    cover_url: Optional[str] = None
    preview_url: Optional[str] = None
    release_date: Optional[str] = None
    status: str = "none"  # "none", "requested", "processing", "available", "in_library"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_type": self.item_type,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "cover_url": self.cover_url,
            "preview_url": self.preview_url,
            "release_date": self.release_date,
            "status": self.status,
        }


@dataclass
class Track:
    title: str
    artist: str
    album: str
    url: str = ""

    def __repr__(self) -> str:
        return f"<Track: {self.artist} - {self.title}>"


@dataclass
class Playlist:
    id: str
    name: str
    description: str = ""
    poster: str = ""
    tracks: List[Track] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"<Playlist: {self.name} (ID: {self.id})>"


@dataclass
class SyncResult:
    playlist_name: str
    total_tracks: int
    matched_tracks: int
    missing_tracks: int
    success: bool
    error: str = ""


class DownloadDriverType(str, Enum):
    SLSKD = "slskd"
    SABNZBD = "sabnzbd"
    QBITTORRENT = "qbittorrent"
    LIDARR = "lidarr"


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    IMPORTING = "importing"
    IMPORTED = "imported"


@dataclass
class DownloadClientConfig:
    id: str
    name: str
    driver_type: str  # DownloadDriverType or string value
    host_url: str
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: bool = True
    priority: int = 1
    extra_settings_json: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "driver_type": self.driver_type.value if isinstance(self.driver_type, DownloadDriverType) else str(self.driver_type),
            "host_url": self.host_url,
            "api_key": self.api_key,
            "username": self.username,
            "password": self.password,
            "enabled": bool(self.enabled),
            "priority": int(self.priority),
            "extra_settings_json": self.extra_settings_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class IndexerConfig:
    id: str
    name: str
    indexer_type: str  # "torznab" or "newznab"
    host_url: str
    api_key: Optional[str] = None
    categories: str = "3000,3010,3020,3030,3040"
    enabled: bool = True
    priority: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "indexer_type": self.indexer_type,
            "host_url": self.host_url,
            "api_key": self.api_key,
            "categories": self.categories,
            "enabled": bool(self.enabled),
            "priority": int(self.priority),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ActiveDownload:
    id: str
    client_id: str
    title: str
    artist: str
    request_id: Optional[str] = None
    download_hash: Optional[str] = None
    item_type: str = "track"
    status: str = DownloadStatus.QUEUED.value
    progress: float = 0.0
    size_bytes: int = 0
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    client_name: Optional[str] = None
    speed_bps: Optional[int] = None
    eta_seconds: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "client_id": self.client_id,
            "download_hash": self.download_hash,
            "title": self.title,
            "artist": self.artist,
            "item_type": self.item_type,
            "status": self.status.value if isinstance(self.status, DownloadStatus) else str(self.status),
            "progress": float(self.progress),
            "size_bytes": int(self.size_bytes),
            "source_path": self.source_path,
            "target_path": self.target_path,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "client_name": self.client_name,
            "speed_bps": self.speed_bps,
            "eta_seconds": self.eta_seconds,
        }


@dataclass
class AcquisitionSearchResult:
    download_id: str
    title: str
    artist: str
    album: Optional[str] = None
    item_type: str = "track"
    size_bytes: int = 0
    bit_rate: Optional[int] = None
    format: Optional[str] = None
    quality_str: Optional[str] = None
    seeders: Optional[int] = None
    leechers: Optional[int] = None
    download_url: Optional[str] = None
    magnet_url: Optional[str] = None
    source: str = ""
    extra: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "download_id": self.download_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "item_type": self.item_type,
            "size_bytes": self.size_bytes,
            "bit_rate": self.bit_rate,
            "format": self.format,
            "quality_str": self.quality_str,
            "seeders": self.seeders,
            "leechers": self.leechers,
            "download_url": self.download_url,
            "magnet_url": self.magnet_url,
            "source": self.source,
            "extra": self.extra,
        }


