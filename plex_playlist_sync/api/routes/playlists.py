"""Playlist management routes with SSRF protection and targeting."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import (
    get_current_user,
    get_db,
    get_deezer_client,
    get_spotify_client,
)
from plex_playlist_sync.clients.deezer import DeezerClient
from plex_playlist_sync.clients.spotify import SpotifyClient
from plex_playlist_sync.security import (
    extract_deezer_id,
    extract_spotify_id,
    sanitize_text,
)
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class PlaylistCreateRequest(BaseModel):
    url_or_id: str = Field(..., description="Spotify/Deezer URL, URI, or alphanumeric/numeric ID")
    service: Optional[str] = Field(default=None, description="Optional service hint: 'spotify' or 'deezer'")
    targets: Optional[list[str]] = Field(default=None, description="Optional list of target user IDs")


class PlaylistTargetsRequest(BaseModel):
    user_ids: list[str] = Field(..., description="List of target user IDs for this playlist")


@router.get("")
def list_playlists(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Lists playlists. Admins see all; regular users only see playlists targeted to them."""
    if current_user.get("is_admin"):
        playlists = db.list_playlists()
    else:
        playlists = db.list_playlists(user_id=str(current_user["id"]))

    for p in playlists:
        p["targets"] = db.get_playlist_targets(p["id"])

    return playlists


@router.post("", status_code=status.HTTP_201_CREATED)
def create_playlist(
    req: PlaylistCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    spotify_client: Optional[SpotifyClient] = Depends(get_spotify_client),
    deezer_client: Optional[DeezerClient] = Depends(get_deezer_client),
) -> dict[str, Any]:
    """Adds playlist via Spotify/Deezer URL or ID. Validates SSRF with extract_spotify_id / extract_deezer_id.

    Extracts metadata and sets initial targets.
    """
    service_hint = req.service.lower().strip() if req.service else None
    pl_id: Optional[str] = None
    service: Optional[str] = None

    if service_hint == "spotify":
        pl_id = extract_spotify_id(req.url_or_id)
        service = "spotify"
    elif service_hint == "deezer":
        pl_id = extract_deezer_id(req.url_or_id)
        service = "deezer"
    else:
        sp_id = extract_spotify_id(req.url_or_id)
        dz_id = extract_deezer_id(req.url_or_id)
        if sp_id:
            pl_id = sp_id
            service = "spotify"
        elif dz_id:
            pl_id = dz_id
            service = "deezer"

    if not pl_id or not service:
        logger.warning("Rejected invalid or malicious playlist input: '%s'", req.url_or_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Spotify or Deezer playlist URL or ID (SSRF validation failed)",
        )

    # Extract metadata using verified client
    title = f"{service.title()} Playlist {pl_id}"
    description = ""
    poster_url = ""

    if service == "spotify" and spotify_client:
        try:
            meta = spotify_client.get_playlist_by_id(pl_id)
            if meta:
                title = meta.name
                description = meta.description
                poster_url = meta.poster
        except Exception as e:
            logger.warning("Could not fetch Spotify metadata for %s: %s", pl_id, e)
    elif service == "deezer" and deezer_client:
        try:
            meta = deezer_client.get_playlist_by_id(pl_id)
            if meta:
                title = meta.name
                description = meta.description
                poster_url = meta.poster
        except Exception as e:
            logger.warning("Could not fetch Deezer metadata for %s: %s", pl_id, e)

    clean_title = sanitize_text(title) or f"{service.title()} Playlist {pl_id}"
    clean_desc = sanitize_text(description)

    # Upsert playlist into DB with creator_id
    creator_id = str(current_user["id"])
    playlist = db.upsert_playlist(
        playlist_id=pl_id,
        name=clean_title,
        service=service,
        description=clean_desc,
        poster_url=poster_url,
        creator_id=creator_id,
    )

    # Initial targets
    if current_user.get("is_admin"):
        initial_targets = req.targets if req.targets is not None else [creator_id]
    else:
        initial_targets = [creator_id]

    db.set_playlist_targets(pl_id, initial_targets)
    playlist["targets"] = db.get_playlist_targets(pl_id)

    return playlist


@router.put("/{playlist_id}/targets")
def update_playlist_targets(
    playlist_id: str,
    req: PlaylistTargetsRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Updates target user list for playlist. Regular users can only toggle themselves."""
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    if current_user.get("is_admin"):
        new_targets = req.user_ids
    else:
        # Regular users can only toggle themselves
        uid = str(current_user["id"])
        existing_targets = set(db.get_playlist_targets(playlist_id))
        if uid in req.user_ids:
            existing_targets.add(uid)
        else:
            existing_targets.discard(uid)
        new_targets = list(existing_targets)

    db.set_playlist_targets(playlist_id, new_targets)
    return {
        "id": playlist_id,
        "targets": db.get_playlist_targets(playlist_id),
    }


@router.delete("/{playlist_id}")
def delete_playlist(
    playlist_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Deletes playlist (admin or creator only)."""
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found",
        )

    is_admin = bool(current_user.get("is_admin"))
    is_creator = playlist.get("creator_id") == str(current_user["id"])

    if not (is_admin or is_creator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only administrators or the playlist creator can delete this playlist",
        )

    db.delete_playlist(playlist_id)
    return {"status": "deleted", "id": playlist_id}
