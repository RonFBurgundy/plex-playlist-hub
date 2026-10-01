"""Playlist management routes with SSRF protection, targeting, and direct track imports."""

import hashlib
import json
import logging
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_deezer_client,
    get_plex_client,
    get_spotify_client,
)
from plex_playlist_sync.clients.deezer import DeezerClient
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.clients.spotify import SpotifyClient
from plex_playlist_sync.clients.spotify_scraper import SpotifyWebScraper
from plex_playlist_sync.config import Config
from plex_playlist_sync.models import Playlist, Track
from plex_playlist_sync.security import (
    extract_deezer_id,
    extract_spotify_id,
    is_safe_image_url,
    sanitize_text,
)
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class PlaylistCreateRequest(BaseModel):
    url_or_id: str = Field(..., description="Spotify/Deezer URL, URI, or alphanumeric/numeric ID")
    service: Optional[str] = Field(default=None, description="Optional service hint: 'spotify' or 'deezer'")
    targets: Optional[list[str]] = Field(default=None, description="Optional list of target user IDs")


class TrackImportItem(BaseModel):
    title: str = Field(..., description="Track title")
    artist: Optional[str] = Field(default="", description="Artist name")
    album: Optional[str] = Field(default="", description="Album name")
    uri: Optional[str] = Field(default="", description="Optional Spotify/Deezer URI or URL")


class PlaylistDirectImportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Playlist name")
    service: Optional[str] = Field(default="spotify", description="Service tag: spotify, deezer, or custom")
    description: Optional[str] = Field(default="", max_length=1000, description="Playlist description")
    poster_url: Optional[str] = Field(default="", description="Cover artwork URL")
    tracks: list[TrackImportItem] = Field(..., min_length=1, max_length=2000, description="List of tracks to import")
    targets: Optional[list[str]] = Field(default=None, description="Optional target user IDs")


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
    spotify_client: Optional[Union[SpotifyClient, SpotifyWebScraper]] = Depends(get_spotify_client),
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

    existing_targets = set(db.get_playlist_targets(playlist_id))
    uid = str(current_user["id"])
    is_admin = bool(current_user.get("is_admin"))
    is_creator = playlist.get("creator_id") == uid
    is_already_targeted = uid in existing_targets

    # Access control:
    # 1. Admins and the creator can always modify targets.
    # 2. For private playlists owned by another regular user, outside regular users cannot opt in (IDOR).
    # 3. For public/server playlists (creator is None or admin), any user can opt themselves in or out.
    if not is_admin and not is_creator:
        creator_id = playlist.get("creator_id")
        if creator_id:
            creator_user = db.get_user(creator_id)
            is_creator_admin = bool(creator_user and creator_user.get("is_admin"))
            if not is_creator_admin and not is_already_targeted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access or modify targets for this private playlist",
                )

    if is_admin:
        new_targets = req.user_ids
    else:
        # Regular users can only toggle themselves
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


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_playlist_tracks(
    req: PlaylistDirectImportRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
) -> dict[str, Any]:
    """Imports playlist and tracks directly from browser helpers, clipboard, or bookmarklet."""
    clean_name = sanitize_text(req.name)
    clean_desc = sanitize_text(req.description or "")
    poster_url = req.poster_url.strip() if req.poster_url else ""
    if poster_url and not is_safe_image_url(poster_url):
        logger.warning("Rejected unsafe or SSRF-prone poster URL: %s", poster_url)
        poster_url = ""

    # Generate stable unique ID based on creator and name hash
    hash_seed = f"{current_user['id']}_{clean_name}_{len(req.tracks)}"
    import_id = f"imp_{hashlib.sha256(hash_seed.encode()).hexdigest()[:12]}"

    tracks_data = [
        {"title": t.title, "artist": t.artist or "", "album": t.album or ""}
        for t in req.tracks
        if t.title.strip()
    ]
    tracks_json_str = json.dumps(tracks_data)

    db.upsert_playlist(
        playlist_id=import_id,
        name=clean_name,
        service=req.service.lower() if req.service else "spotify",
        description=clean_desc,
        poster_url=poster_url,
        creator_id=str(current_user["id"]),
        tracks_json=tracks_json_str,
    )

    # Determine targets: Admins can target anyone, regular users strictly target themselves
    if current_user.get("is_admin") and req.targets is not None:
        targets = req.targets
    else:
        targets = [str(current_user["id"])]

    db.set_playlist_targets(import_id, targets)

    # Convert to Track models
    model_tracks = [
        Track(
            title=sanitize_text(t.title),
            artist=sanitize_text(t.artist or ""),
            album=sanitize_text(t.album or ""),
        )
        for t in req.tracks
        if t.title.strip()
    ]

    matched_count = 0
    missing_count = 0
    if plex_client and model_tracks:
        target_usernames = []
        for uid in targets:
            user_row = db.get_user(uid)
            if user_row:
                target_usernames.append(user_row["username"])

        if target_usernames:
            model_playlist = Playlist(
                id=import_id,
                name=clean_name,
                tracks=model_tracks,
                description=clean_desc,
                poster=poster_url,
            )
            try:
                results = plex_client.sync_playlist_to_users(
                    playlist=model_playlist,
                    target_usernames=target_usernames,
                    append=config.append_instead_of_sync,
                    add_description=config.add_playlist_description,
                    add_poster=config.add_playlist_poster,
                    write_missing_as_csv=config.write_missing_as_csv,
                    data_dir=config.data_dir,
                    threshold=config.search_similarity_threshold,
                )
                matched, missing = plex_client.match_playlist_tracks(
                    model_tracks, threshold=config.search_similarity_threshold
                )
                matched_count = len(matched)
                missing_count = len(missing)
                success = any(r.success for r in results) if results else False
                db.record_sync_result(
                    import_id,
                    status="success" if (success and not missing) else ("partial" if success else "error"),
                    missing_tracks=missing,
                )
            except Exception as e:
                logger.error("Error during direct import sync to Plex: %s", e)
                db.record_sync_result(import_id, status="error")

    return {
        "id": import_id,
        "name": clean_name,
        "service": req.service,
        "track_count": len(model_tracks),
        "matched_count": matched_count,
        "missing_count": missing_count,
        "targets": targets,
        "status": "imported",
    }
