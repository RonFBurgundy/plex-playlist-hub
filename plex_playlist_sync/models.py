from dataclasses import dataclass, field
from enum import Enum, IntFlag, StrEnum
from typing import Any, List, Optional, Union

from plex_playlist_sync.security import mask_channel_config


class UserPermission(IntFlag):
    ADMIN = 1
    REQUEST = 2
    AUTO_APPROVE = 4
    AUTO_APPROVE_ALBUM = 8
    MANAGE_REQUESTS = 16
    REPORT_ISSUE = 32
    DEFAULT = 34  # REQUEST | REPORT_ISSUE


class IssueType(StrEnum):
    AUDIO_QUALITY = "audio_quality"
    CORRUPTED_FILE = "corrupted_file"
    WRONG_RELEASE = "wrong_release"
    MISSING_TRACKS = "missing_tracks"
    INCORRECT_TAGS = "incorrect_tags"
    OTHER = "other"


class IssueStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


@dataclass
class MediaIssue:
    id: str
    user_id: str
    media_title: str
    artist: str
    issue_type: str
    problem_details: str
    request_id: Optional[str] = None
    status: Union[IssueStatus, str] = IssueStatus.OPEN
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    username: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "media_title": self.media_title,
            "artist": self.artist,
            "issue_type": self.issue_type.value if hasattr(self.issue_type, "value") else str(self.issue_type),
            "problem_details": self.problem_details,
            "request_id": self.request_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "username": self.username,
        }


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
    quality_profile_id: Optional[str] = None
    current_quality: Optional[str] = None
    cutoff_met: int = 1
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
            "quality_profile_id": self.quality_profile_id,
            "current_quality": self.current_quality,
            "cutoff_met": self.cutoff_met,
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
    track_id: Optional[str] = None
    album_id: Optional[str] = None

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
            "track_id": self.track_id,
            "album_id": self.album_id,
        }


@dataclass
class BlocklistItem:
    id: str
    source_title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    release_guid: Optional[str] = None
    info_hash: Optional[str] = None
    protocol: Optional[str] = None
    indexer: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_title": self.source_title,
            "artist": self.artist,
            "album": self.album,
            "release_guid": self.release_guid,
            "info_hash": self.info_hash,
            "protocol": self.protocol,
            "indexer": self.indexer,
            "reason": self.reason,
            "created_at": self.created_at,
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
    custom_formats: list[dict[str, Any]] = field(default_factory=list)
    min_score: Optional[int] = None
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
            "custom_formats": list(self.custom_formats),
            "min_score": self.min_score,
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


class NotificationChannelType(str, Enum):
    DISCORD = "discord"
    TELEGRAM = "telegram"
    PUSHOVER = "pushover"
    WEBHOOK = "webhook"
    EMAIL = "email"


class NotificationEvent(str, Enum):
    REQUEST_CREATED = "request_created"
    REQUEST_APPROVED = "request_approved"
    REQUEST_REJECTED = "request_rejected"
    DOWNLOAD_STARTED = "download_started"
    ITEM_AVAILABLE = "item_available"
    DOWNLOAD_FAILED = "download_failed"
    ISSUE_REPORTED = "issue_reported"


@dataclass
class NotificationChannel:
    id: str
    name: str
    channel_type: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    events: list[str] = field(
        default_factory=lambda: [
            "request_created",
            "request_approved",
            "request_rejected",
            "download_started",
            "item_available",
            "download_failed",
            "issue_reported",
        ]
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self, mask_secrets: bool = False) -> dict[str, Any]:
        cfg = dict(self.config) if isinstance(self.config, dict) else {}
        ctype = (
            self.channel_type.value
            if isinstance(self.channel_type, NotificationChannelType)
            else str(self.channel_type)
        )
        if mask_secrets:
            cfg = mask_channel_config(ctype, cfg)
        return {
            "id": self.id,
            "name": self.name,
            "channel_type": ctype,
            "enabled": bool(self.enabled),
            "config": cfg,
            "events": [
                e.value if isinstance(e, NotificationEvent) else str(e)
                for e in self.events
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class LibraryMode(StrEnum):
    NATIVE = "native"
    LIDARR = "lidarr"


@dataclass
class LibraryArtist:
    id: str
    name: str
    clean_name: str = ""
    foreign_artist_id: Optional[str] = None
    path: Optional[str] = None
    monitored: bool = True
    quality_profile_id: Optional[str] = None
    metadata_json: Optional[str] = None
    mbid: Optional[str] = None
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    bio: Optional[str] = None
    genres: Optional[str] = None
    country: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "clean_name": self.clean_name,
            "foreign_artist_id": self.foreign_artist_id,
            "path": self.path,
            "monitored": bool(self.monitored),
            "quality_profile_id": self.quality_profile_id,
            "metadata_json": self.metadata_json,
            "mbid": self.mbid,
            "image_url": self.image_url,
            "banner_url": self.banner_url,
            "bio": self.bio,
            "genres": self.genres,
            "country": self.country,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class LibraryAlbum:
    id: str
    artist_id: str
    title: str
    clean_title: str = ""
    foreign_album_id: Optional[str] = None
    release_date: Optional[str] = None
    year: Optional[int] = None
    album_type: str = "album"
    monitored: bool = True
    path: Optional[str] = None
    cover_url: Optional[str] = None
    total_tracks: Optional[int] = None
    mb_release_group_id: Optional[str] = None
    mb_release_id: Optional[str] = None
    genres: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "artist_id": self.artist_id,
            "title": self.title,
            "clean_title": self.clean_title,
            "foreign_album_id": self.foreign_album_id,
            "release_date": self.release_date,
            "year": int(self.year) if self.year is not None else None,
            "album_type": self.album_type,
            "monitored": bool(self.monitored),
            "path": self.path,
            "cover_url": self.cover_url,
            "total_tracks": int(self.total_tracks) if self.total_tracks is not None else None,
            "mb_release_group_id": self.mb_release_group_id,
            "mb_release_id": self.mb_release_id,
            "genres": self.genres,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class LibraryTrack:
    id: str
    album_id: str
    artist_id: str
    title: str
    clean_title: str = ""
    track_number: int = 1
    disc_number: int = 1
    duration_seconds: Optional[float] = None
    monitored: bool = True
    foreign_track_id: Optional[str] = None
    mb_recording_id: Optional[str] = None
    isrc: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "album_id": self.album_id,
            "artist_id": self.artist_id,
            "title": self.title,
            "clean_title": self.clean_title,
            "track_number": int(self.track_number),
            "disc_number": int(self.disc_number),
            "duration_seconds": float(self.duration_seconds) if self.duration_seconds is not None else None,
            "monitored": bool(self.monitored),
            "foreign_track_id": self.foreign_track_id,
            "mb_recording_id": self.mb_recording_id,
            "isrc": self.isrc,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class LibraryFile:
    id: str
    track_id: str
    file_path: str
    relative_path: str
    codec: str
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    bits_per_sample: Optional[int] = None
    quality_name: str = "Unknown"
    size_bytes: int = 0
    cutoff_met: bool = True
    date_added: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "track_id": self.track_id,
            "file_path": self.file_path,
            "relative_path": self.relative_path,
            "codec": self.codec,
            "bitrate": int(self.bitrate) if self.bitrate is not None else None,
            "sample_rate": int(self.sample_rate) if self.sample_rate is not None else None,
            "bits_per_sample": int(self.bits_per_sample) if self.bits_per_sample is not None else None,
            "quality_name": self.quality_name,
            "size_bytes": int(self.size_bytes),
            "cutoff_met": bool(self.cutoff_met),
            "date_added": self.date_added,
            "updated_at": self.updated_at,
        }


@dataclass
class LibraryCollection:
    id: str
    name: str
    clean_name: str = ""
    summary: Optional[str] = None
    poster_url: Optional[str] = None
    monitored: bool = True
    foreign_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "clean_name": self.clean_name,
            "summary": self.summary,
            "poster_url": self.poster_url,
            "monitored": bool(self.monitored),
            "foreign_id": self.foreign_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class MediaManagementSettings:
    id: int = 1
    root_folder_path: str = "/data/music"
    staging_folder_path: str = "/data/downloads"
    artist_folder_format: str = "{Artist Name}"
    album_folder_format: str = "{Artist Name} - {Album Title} ({Release Year})"
    track_file_format: str = "{Track:02d} - {Track Title}"
    import_mode: str = "move"
    delete_empty_folders: bool = True
    write_audio_tags: bool = True
    embed_artwork: bool = True
    save_cover_art_file: bool = True
    delete_completed_transfers: bool = False
    enable_quality_upgrades: bool = True
    library_mode: str = "native"
    seed_ratio_limit: Optional[float] = None
    seed_time_limit_minutes: Optional[int] = None
    enrich_mbids: bool = True
    acoustid_api_key: Optional[str] = None
    mb_mirror_url: str = "https://api.brainzmash.org"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "root_folder_path": self.root_folder_path,
            "staging_folder_path": self.staging_folder_path,
            "artist_folder_format": self.artist_folder_format,
            "album_folder_format": self.album_folder_format,
            "track_file_format": self.track_file_format,
            "import_mode": self.import_mode,
            "delete_empty_folders": bool(self.delete_empty_folders),
            "write_audio_tags": bool(self.write_audio_tags),
            "embed_artwork": bool(self.embed_artwork),
            "save_cover_art_file": bool(self.save_cover_art_file),
            "delete_completed_transfers": bool(self.delete_completed_transfers),
            "enable_quality_upgrades": bool(self.enable_quality_upgrades),
            "library_mode": self.library_mode,
            "seed_ratio_limit": float(self.seed_ratio_limit) if self.seed_ratio_limit is not None else None,
            "seed_time_limit_minutes": int(self.seed_time_limit_minutes) if self.seed_time_limit_minutes is not None else None,
            "enrich_mbids": bool(self.enrich_mbids),
            "acoustid_api_key": self.acoustid_api_key,
            "mb_mirror_url": self.mb_mirror_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
