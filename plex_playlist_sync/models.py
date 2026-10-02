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
    protocol: str = ""

    def __post_init__(self) -> None:
        if not self.protocol:
            src = (self.source or "").lower()
            if src in ("torznab", "torrent") or bool(self.magnet_url):
                self.protocol = "torrent"
            elif src in ("newznab", "usenet"):
                self.protocol = "usenet"
            elif src in ("slskd", "soulseek"):
                self.protocol = "slskd"
            else:
                self.protocol = "torrent"

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
            "protocol": self.protocol,
        }


class AudioQuality(str, Enum):
    FLAC_24BIT = "FLAC 24bit"
    FLAC_16BIT = "FLAC 16bit"
    MP3_320 = "MP3 320"
    MP3_V0 = "MP3 V0"
    AAC_256 = "AAC 256"
    MP3_192 = "MP3 192"
    MP3_V2 = "MP3 V2"
    UNKNOWN = "Unknown"


@dataclass
class QualityProfileItem:
    quality: str
    allowed: bool = True
    weight: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "allowed": bool(self.allowed),
            "weight": int(self.weight),
        }


@dataclass
class QualityProfile:
    id: str
    name: str
    cutoff: str
    items: list[QualityProfileItem]
    preferred_tags: list[str] = field(default_factory=list)
    ignored_tags: list[str] = field(default_factory=list)
    min_size_mb: Optional[float] = None
    max_size_mb: Optional[float] = None
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cutoff": self.cutoff,
            "items": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.items
            ],
            "preferred_tags": list(self.preferred_tags),
            "ignored_tags": list(self.ignored_tags),
            "min_size_mb": self.min_size_mb,
            "max_size_mb": self.max_size_mb,
            "is_default": bool(self.is_default),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ParsedRelease:
    raw_title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    quality: str = "Unknown"
    source: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    bitrate_kbps: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_title": self.raw_title,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "year": self.year,
            "quality": self.quality,
            "source": self.source,
            "tags": list(self.tags),
            "bitrate_kbps": self.bitrate_kbps,
        }


@dataclass
class EvaluationResult:
    is_acceptable: bool
    score: int
    rejection_reasons: list[str]
    parsed_quality: str
    meets_cutoff: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_acceptable": bool(self.is_acceptable),
            "score": int(self.score),
            "rejection_reasons": list(self.rejection_reasons),
            "parsed_quality": self.parsed_quality,
            "meets_cutoff": bool(self.meets_cutoff),
        }



