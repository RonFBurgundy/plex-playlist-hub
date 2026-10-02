"""Discovery REST API endpoints for trending charts, new releases, and unified multi-source search."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from plex_playlist_sync.api.dependencies import (
    get_db,
    get_discovery_client,
    get_plex_client,
    require_user,
)
from plex_playlist_sync.clients.discovery import DiscoveryClient
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.library_availability import get_item_availability
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


def annotate_item_statuses(
    items: list[dict[str, Any]],
    db: Database,
    plex_client: Optional[PlexClient] = None,
) -> list[dict[str, Any]]:
    """Cross-references discovery items with music_requests and native library or Plex."""
    try:
        media_settings = db.get_media_management_settings()
        library_mode = media_settings.get("library_mode", "native")
    except Exception as e:
        logger.warning("Error loading media management settings for status annotation: %s", e)
        library_mode = "native"

    try:
        all_requests = db.list_requests()
        req_by_foreign_id = {r["foreign_id"]: r for r in all_requests if r.get("foreign_id")}
        req_by_artist_title = {
            ((r.get("artist") or "").lower().strip(), (r.get("title") or "").lower().strip()): r
            for r in all_requests
        }
    except Exception as e:
        logger.warning("Error loading requests for status annotation: %s", e)
        req_by_foreign_id = {}
        req_by_artist_title = {}

    annotated: list[dict[str, Any]] = []
    for item in items:
        it = dict(item)
        foreign_id = it.get("id")
        artist = (it.get("artist") or "").lower().strip()
        title = (it.get("title") or "").lower().strip()

        matched_req = req_by_foreign_id.get(foreign_id) or req_by_artist_title.get((artist, title))

        if library_mode == "native":
            is_album = (it.get("type") == "album") or (it.get("item_type") == "album")
            avail = get_item_availability(
                db,
                artist_name=it.get("artist"),
                album_title=it.get("title") if is_album else None,
                track_title=it.get("title") if not is_album else None,
                foreign_id=foreign_id,
            )
            if avail.get("in_library"):
                it["status"] = avail["status"]
                it["quality"] = avail.get("quality")
                if matched_req:
                    it["request_id"] = matched_req.get("id")
                annotated.append(it)
                continue

        if matched_req:
            req_status = matched_req.get("status")
            if req_status in ("available", "completed"):
                it["status"] = "available"
            elif req_status in ("processing", "approved"):
                it["status"] = "processing"
            elif req_status == "rejected":
                it["status"] = "rejected"
            else:
                it["status"] = "requested"
            it["request_id"] = matched_req.get("id")
        else:
            in_plex = False
            if plex_client is not None and title:
                try:
                    plex_matches = plex_client.search_library_tracks(query=title, limit=5)
                    for pm in plex_matches:
                        pm_artist = (pm.get("artist") or "").lower().strip()
                        pm_title = (pm.get("title") or "").lower().strip()
                        if (pm_artist and (artist in pm_artist or pm_artist in artist)) and (pm_title == title):
                            in_plex = True
                            break
                except Exception as e:
                    logger.debug("Plex library check error for '%s': %s", title, e)

            it["status"] = "in_library" if in_plex else "none"

        annotated.append(it)
    return annotated


@router.get("/trending")
def get_trending(
    limit: int = Query(default=25, ge=1, le=50),
    discovery: DiscoveryClient = Depends(get_discovery_client),
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves trending music tracks and albums annotated with library & request status."""
    raw_items = discovery.get_trending(limit=limit)
    annotated = annotate_item_statuses(raw_items, db=db, plex_client=plex_client)
    return {"items": annotated, "count": len(annotated)}


@router.get("/new-releases")
def get_new_releases(
    limit: int = Query(default=25, ge=1, le=50),
    discovery: DiscoveryClient = Depends(get_discovery_client),
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves latest album releases annotated with library & request status."""
    raw_items = discovery.get_new_releases(limit=limit)
    annotated = annotate_item_statuses(raw_items, db=db, plex_client=plex_client)
    return {"items": annotated, "count": len(annotated)}


@router.get("/search")
def search_discovery(
    q: str = Query(..., min_length=1),
    type: str = Query(default="all"),
    limit: int = Query(default=25, ge=1, le=50),
    discovery: DiscoveryClient = Depends(get_discovery_client),
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Performs unified multi-source search across iTunes and Deezer public APIs."""
    raw_items = discovery.search(query=q, item_type=type, limit=limit)
    annotated = annotate_item_statuses(raw_items, db=db, plex_client=plex_client)
    return {"items": annotated, "query": q, "type": type, "count": len(annotated)}


@router.get("/album/{album_id}")
def get_album(
    album_id: str,
    discovery: DiscoveryClient = Depends(get_discovery_client),
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves deep album details including tracklist and previews annotated with status."""
    album_data = discovery.get_album_details(album_id)
    if not album_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Album '{album_id}' not found",
        )

    album_dict = dict(album_data)
    album_dict.setdefault("item_type", "album")

    raw_tracks = album_dict.get("tracks", [])
    for t in raw_tracks:
        t.setdefault("item_type", "track")

    annotated_tracks = annotate_item_statuses(raw_tracks, db=db, plex_client=plex_client)
    annotated_album = annotate_item_statuses([album_dict], db=db, plex_client=plex_client)[0]
    annotated_album["tracks"] = annotated_tracks
    return annotated_album


@router.get("/artist/{artist_id}")
def get_artist(
    artist_id: str,
    discovery: DiscoveryClient = Depends(get_discovery_client),
    db: Database = Depends(get_db),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves artist details and discography grouped into albums, singles_eps, and compilations."""
    artist_data = discovery.get_artist_details(artist_id)
    if not artist_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artist '{artist_id}' not found",
        )

    artist_dict = dict(artist_data)
    for group_key in ("albums", "singles_eps", "compilations"):
        items = artist_dict.get(group_key, [])
        for it in items:
            it.setdefault("item_type", "album")
        artist_dict[group_key] = annotate_item_statuses(items, db=db, plex_client=plex_client)

    return artist_dict
