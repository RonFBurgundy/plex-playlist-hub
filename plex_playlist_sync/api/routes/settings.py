"""Media Management Settings and Token Preview API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import get_db, require_admin, require_user
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.naming import PRESETS, build_track_path
from plex_playlist_sync.security import is_safe_service_url, mask_secret
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()

# Default preview sample items representing real-world library scenarios
SAMPLE_PREVIEW_ITEMS: list[dict[str, Any]] = [
    {
        "id": "standard",
        "name": "Standard Single-Disc Track",
        "description": "Standard studio album track",
        "metadata": {
            "artist": "Pink Floyd",
            "album": "The Dark Side of the Moon",
            "title": "Speak to Me",
            "release_year": 1973,
            "year": 1973,
            "track_number": 1,
            "disc_number": 1,
            "total_discs": 1,
            "codec": "FLAC",
            "bit_depth": 24,
            "bits_per_sample": 24,
            "sample_rate": 96000,
            "extension": ".flac",
            "quality_full": "FLAC 24bit 96kHz",
        },
    },
    {
        "id": "multi_disc",
        "name": "Multi-Disc Track (Disc 2)",
        "description": "Track on second disc of a multi-disc set",
        "metadata": {
            "artist": "The Beatles",
            "album": "The Beatles (White Album)",
            "title": "Revolution 1",
            "release_year": 1968,
            "year": 1968,
            "track_number": 1,
            "disc_number": 2,
            "total_discs": 2,
            "medium_format": "CD",
            "codec": "FLAC",
            "bit_depth": 16,
            "bits_per_sample": 16,
            "sample_rate": 44100,
            "extension": ".flac",
            "quality_full": "FLAC 16bit 44.1kHz",
        },
    },
    {
        "id": "compilation",
        "name": "Compilation / Various Artists Track",
        "description": "Track with distinct artist on a Various Artists compilation",
        "metadata": {
            "artist": "Queen",
            "album_artist": "Various Artists",
            "album": "Wayne's World: Music from the Motion Picture",
            "title": "Bohemian Rhapsody",
            "release_year": 1992,
            "year": 1992,
            "album_type": "Soundtrack",
            "track_number": 1,
            "disc_number": 1,
            "total_discs": 1,
            "is_compilation": True,
            "codec": "MP3",
            "bitrate": "320kbps",
            "extension": ".mp3",
            "quality_full": "MP3 320kbps",
        },
    },
]


class MediaManagementSettingsModel(BaseModel):
    artist_folder_format: str = Field(..., description="Format for artist directory")
    album_folder_format: str = Field(..., description="Format for album directory")
    standard_track_format: str = Field(..., description="Format for standard track filenames")
    compilation_track_format: str = Field(..., description="Format for compilation track filenames")
    multi_disc_folder_format: str = Field(..., description="Format for multi-disc subdirectories")
    root_folder_path: str = Field("/data/media/music", description="Base music library folder")
    colon_replacement_format: str = Field(" - ", description="String to replace colons with")
    clean_artist_names: bool = Field(True, description="Whether to strip leading articles from artist names")
    staging_folder_path: str = Field("/data/downloads", description="Path for staging/downloads folder")
    import_mode: str = Field("move", description="Import mode: move or hardlink")
    write_audio_tags: bool = Field(True, description="Whether to normalize audio tags on import")
    embed_artwork: bool = Field(True, description="Whether to embed cover artwork in audio files")
    save_cover_art_file: bool = Field(True, description="Whether to save cover.jpg in album directory")
    updated_at: str | None = None


class MediaManagementUpdateModel(BaseModel):
    artist_folder_format: str | None = None
    album_folder_format: str | None = None
    standard_track_format: str | None = None
    compilation_track_format: str | None = None
    multi_disc_folder_format: str | None = None
    root_folder_path: str | None = None
    colon_replacement_format: str | None = None
    clean_artist_names: bool | None = None
    staging_folder_path: str | None = None
    import_mode: str | None = None
    write_audio_tags: bool | None = None
    embed_artwork: bool | None = None
    save_cover_art_file: bool | None = None


class PreviewRequestModel(BaseModel):
    artist_folder_format: str | None = None
    album_folder_format: str | None = None
    standard_track_format: str | None = None
    compilation_track_format: str | None = None
    multi_disc_folder_format: str | None = None
    root_folder_path: str | None = None
    colon_replacement_format: str | None = None
    clean_artist_names: bool | None = None
    staging_folder_path: str | None = None
    import_mode: str | None = None


class PreviewItemModel(BaseModel):
    id: str
    name: str
    description: str
    metadata: dict[str, Any]
    output_path: str


class PreviewResponseModel(BaseModel):
    previews: list[PreviewItemModel]


class LidarrSettingsModel(BaseModel):
    url: str | None = None
    api_key: str | None = None
    auto_search: bool = True
    root_folder: str | None = None
    quality_profile_id: int | None = None
    metadata_profile_id: int | None = None
    trickle_rate_seconds: float = 3.0
    trickle_batch_size: int = 25
    auto_trickle: bool = False
    auto_trickle_interval_minutes: int = 30
    updated_at: str | None = None


class LidarrSettingsUpdateModel(BaseModel):
    url: str | None = None
    api_key: str | None = None
    auto_search: bool | None = None
    root_folder: str | None = None
    quality_profile_id: int | None = None
    metadata_profile_id: int | None = None
    trickle_rate_seconds: float | None = None
    trickle_batch_size: int | None = None
    auto_trickle: bool | None = None
    auto_trickle_interval_minutes: int | None = None


class LidarrTestConnectionPayload(BaseModel):
    url: str
    api_key: str


class LidarrTestConnectionResponse(BaseModel):
    online: bool
    version: str | None = None
    error: str | None = None


class MediaManagementGetResponse(BaseModel):
    settings: MediaManagementSettingsModel
    presets: dict[str, dict[str, Any]]


def _render_previews_for_settings(settings: dict[str, Any]) -> list[PreviewItemModel]:
    """Generates preview items in-memory without any filesystem operations."""
    items: list[PreviewItemModel] = []
    for sample in SAMPLE_PREVIEW_ITEMS:
        out_path = build_track_path(sample["metadata"], settings)
        items.append(
            PreviewItemModel(
                id=sample["id"],
                name=sample["name"],
                description=sample["description"],
                metadata=sample["metadata"],
                output_path=out_path,
            )
        )
    return items


@router.get(
    "/media-management",
    response_model=MediaManagementGetResponse,
    summary="Get Media Management Settings & Presets",
)
def get_media_management_settings(
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> MediaManagementGetResponse:
    """Retrieves current media management settings and preset templates."""
    settings_dict = db.get_media_management_settings()
    return MediaManagementGetResponse(
        settings=MediaManagementSettingsModel(**settings_dict),
        presets=PRESETS,
    )


@router.post(
    "/media-management",
    response_model=MediaManagementSettingsModel,
    summary="Update Media Management Settings (Admin Only)",
)
def update_media_management_settings(
    payload: MediaManagementUpdateModel,
    db: Database = Depends(get_db),
    admin_user: dict[str, Any] = Depends(require_admin),
) -> MediaManagementSettingsModel:
    """Admin-only: updates media management naming templates and options."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        current = db.get_media_management_settings()
        return MediaManagementSettingsModel(**current)

    try:
        updated = db.update_media_management_settings(updates)
        return MediaManagementSettingsModel(**updated)
    except Exception as e:
        logger.error("Failed to update media management settings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database update failed: {e}",
        ) from e


@router.post(
    "/media-management/preview",
    response_model=PreviewResponseModel,
    summary="Live Preview Token Templates (In-Memory)",
)
def preview_media_management_templates(
    payload: PreviewRequestModel | None = None,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> PreviewResponseModel:
    """Renders real-time example paths purely in-memory using provided or stored settings."""
    stored_settings = db.get_media_management_settings()

    effective_settings = dict(stored_settings)
    if payload:
        overrides = payload.model_dump(exclude_unset=True)
        effective_settings.update(overrides)

    previews = _render_previews_for_settings(effective_settings)
    return PreviewResponseModel(previews=previews)


# -----------------------------------------------------------------------------
# Lidarr Automation Settings Endpoints
# -----------------------------------------------------------------------------


def _mask_lidarr_settings(settings: dict[str, Any]) -> dict[str, Any]:
    res = dict(settings)
    if res.get("api_key"):
        res["api_key"] = mask_secret(res["api_key"])
    return res


@router.get(
    "/lidarr",
    response_model=LidarrSettingsModel,
    summary="Get Lidarr Automation Settings",
)
def get_lidarr_settings(
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> LidarrSettingsModel:
    """Retrieves Lidarr automation settings with masked API key."""
    settings = db.get_lidarr_settings()
    masked = _mask_lidarr_settings(settings)
    return LidarrSettingsModel(**masked)


@router.post(
    "/lidarr",
    response_model=LidarrSettingsModel,
    summary="Update Lidarr Automation Settings (Admin Only)",
)
def update_lidarr_settings(
    payload: LidarrSettingsUpdateModel,
    db: Database = Depends(get_db),
    admin_user: dict[str, Any] = Depends(require_admin),
) -> LidarrSettingsModel:
    """Admin-only: updates Lidarr automation settings in database.

    Preserves existing API key if masked or empty.
    """
    existing = db.get_lidarr_settings()
    updates = payload.model_dump(exclude_unset=True)

    if "url" in updates and updates["url"]:
        clean_url = str(updates["url"]).strip().rstrip("/")
        if not is_safe_service_url(clean_url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prohibited or invalid host URL (SSRF defense)",
            )
        updates["url"] = clean_url

    if "api_key" in updates:
        k = updates["api_key"]
        # If masked (contains * or •) or empty, keep existing
        if k and ("*" in k or "•" in k):
            updates["api_key"] = existing.get("api_key")
        elif not k:
            updates["api_key"] = existing.get("api_key")
        else:
            updates["api_key"] = k.strip()

    try:
        updated = db.update_lidarr_settings(updates)
        masked = _mask_lidarr_settings(updated)
        return LidarrSettingsModel(**masked)
    except Exception as e:
        logger.error("Failed to update Lidarr settings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database update failed: {e}",
        ) from e


@router.post(
    "/lidarr/test",
    response_model=LidarrTestConnectionResponse,
    summary="Test Lidarr Connection (Admin Only)",
)
def test_lidarr_connection(
    payload: LidarrTestConnectionPayload,
    db: Database = Depends(get_db),
    admin_user: dict[str, Any] = Depends(require_admin),
) -> LidarrTestConnectionResponse:
    """Admin-only: tests connectivity and credentials for Lidarr instance."""
    clean_url = str(payload.url).strip().rstrip("/")
    if not is_safe_service_url(clean_url):
        return LidarrTestConnectionResponse(
            online=False,
            version=None,
            error="Prohibited or invalid host URL (SSRF defense)",
        )

    api_key = payload.api_key.strip()
    if not api_key or "*" in api_key or "•" in api_key:
        existing = db.get_lidarr_settings()
        api_key = str(existing.get("api_key") or "")

    try:
        client = LidarrClient(base_url=clean_url, api_key=api_key)
        result = client.test_connection()
        return LidarrTestConnectionResponse(
            online=bool(result.get("online", False)),
            version=result.get("version"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.warning("Lidarr connection test failed with exception: %s", e)
        return LidarrTestConnectionResponse(
            online=False,
            version=None,
            error=str(e),
        )
