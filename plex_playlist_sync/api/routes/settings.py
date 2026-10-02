"""Media Management Settings and Token Preview API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import get_db, require_admin, require_user
from plex_playlist_sync.naming import PRESETS, build_track_path
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
    root_folder_path: str = Field("/music", description="Base music library folder")
    colon_replacement_format: str = Field(" - ", description="String to replace colons with")
    clean_artist_names: bool = Field(True, description="Whether to strip leading articles from artist names")
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


class PreviewRequestModel(BaseModel):
    artist_folder_format: str | None = None
    album_folder_format: str | None = None
    standard_track_format: str | None = None
    compilation_track_format: str | None = None
    multi_disc_folder_format: str | None = None
    root_folder_path: str | None = None
    colon_replacement_format: str | None = None
    clean_artist_names: bool | None = None


class PreviewItemModel(BaseModel):
    id: str
    name: str
    description: str
    metadata: dict[str, Any]
    output_path: str


class PreviewResponseModel(BaseModel):
    previews: list[PreviewItemModel]


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
    current_user: dict[str, Any] = Depends(require_user),
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
